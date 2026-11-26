"""版本留存与更正流转。

业务规则的落地：

* **未发送的说明是草稿**：决定书更正后，草稿重新生成并反映新版本，
  草稿可反复覆盖，不形成送达事实；
* **已送达的说明是快照**：一经 :meth:`CaseStore.serve` 即写入只读快照，
  完整冻结当时的正式文本全文、易读正文与每句的引用位置。之后即使决定书
  更正，快照内容也不变，便于处理申请人「我当时收到的是这么写的」类追问；
* 快照目录用只读权限位（0444/0555）再加一层防误改保护；
* 所有存储均为 UTF-8 JSON，无第三方依赖。
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .contradictions import resolve
from .errors import ContradictionError, EasyReadError
from .extract import extract_facts
from .model import ContradictionIssue
from .rewrite import EasyReadDocument, rewrite_easyread
from .textmodel import SourceRecord
from .verify import VerificationReport, verify


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass
class DraftBundle:
    """尚未送达的易读说明草稿。"""

    case_id: str
    source_records: list[SourceRecord]
    document: EasyReadDocument
    report: VerificationReport
    source_hash: str
    created_at: str
    updated_at: str
    version: int = 1

    def to_dict(self) -> dict:
        return {
            "case_id": self.case_id,
            "status": "draft",
            "version": self.version,
            "source_hash": self.source_hash,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "source_records": [r.to_dict() for r in self.source_records],
            "document": self.document.to_dict(),
            "verification": self.report.to_dict(),
        }


@dataclass
class ServedBundle:
    """已送达的只读快照。"""

    case_id: str
    served_id: str
    served_at: str
    source_records: list[SourceRecord]
    document: EasyReadDocument
    report: VerificationReport
    source_hash: str
    doc_hash: str

    def to_dict(self) -> dict:
        return {
            "case_id": self.case_id,
            "status": "served",
            "served_id": self.served_id,
            "served_at": self.served_at,
            "source_hash": self.source_hash,
            "doc_hash": self.doc_hash,
            "source_records": [r.to_dict() for r in self.source_records],
            "document": self.document.to_dict(),
            "verification": self.report.to_dict(),
        }


@dataclass
class BlockedBundle:
    """因矛盾被阻断、未能生成的易读说明（问题交还经办人）。"""

    case_id: str
    issues: list[ContradictionIssue]
    source_records: list[SourceRecord]
    created_at: str

    def to_dict(self) -> dict:
        return {
            "case_id": self.case_id,
            "status": "blocked",
            "created_at": self.created_at,
            "issues": [i.to_dict() for i in self.issues],
            "source_records": [r.to_dict() for r in self.source_records],
        }


class CaseStore:
    """按案件目录管理草稿与送达快照的文件存储。"""

    def __init__(self, root: str | os.PathLike) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------ 路径

    def _case_dir(self, case_id: str) -> Path:
        return self.root / case_id

    def _draft_path(self, case_id: str) -> Path:
        return self._case_dir(case_id) / "draft.json"

    def _served_dir(self, case_id: str) -> Path:
        return self._case_dir(case_id) / "served"

    def _snapshot_path(self, case_id: str, served_id: str) -> Path:
        return self._served_dir(case_id) / f"{served_id}.json"

    # ------------------------------------------------------------ 生成

    def build_draft(
        self,
        case_id: str,
        records: list[SourceRecord],
        title: str = "补助决定书易读说明",
    ) -> DraftBundle:
        """从正式记录生成（或重新生成）草稿。

        决定书更正后再次调用本方法，草稿即反映新版本；存在未消解矛盾时
        抛出 :class:`ContradictionError`，不产生易读版。
        """
        sheet = extract_facts(records)
        try:
            resolve(sheet)
        except ContradictionError:
            raise
        document = rewrite_easyread(sheet, title=title)
        report = verify(sheet, document)
        if not report.passed:
            raise EasyReadError(
                "易读版自检未通过，禁止作为草稿留存：\n" + report.plain_text()
            )
        source_hash = _sha256(json.dumps([r.to_dict() for r in records], ensure_ascii=False))
        now = _utc_now()
        existing = self.load_draft(case_id)
        version = existing.version + 1 if existing else 1
        bundle = DraftBundle(
            case_id=case_id,
            source_records=list(records),
            document=document,
            report=report,
            source_hash=source_hash,
            created_at=existing.created_at if existing else now,
            updated_at=now,
            version=version,
        )
        self._write_json(self._draft_path(case_id), bundle.to_dict())
        return bundle

    def try_build(
        self,
        case_id: str,
        records: list[SourceRecord],
        title: str = "补助决定书易读说明",
    ) -> DraftBundle | BlockedBundle:
        """不抛异常的便捷入口：矛盾时返回 :class:`BlockedBundle` 并落盘留痕。"""
        try:
            return self.build_draft(case_id, records, title=title)
        except ContradictionError as exc:
            blocked = BlockedBundle(
                case_id=case_id,
                issues=exc.issues,
                source_records=list(records),
                created_at=_utc_now(),
            )
            self._case_dir(case_id).mkdir(parents=True, exist_ok=True)
            self._write_json(self._case_dir(case_id) / "blocked.json", blocked.to_dict())
            return blocked

    def serve(self, case_id: str) -> ServedBundle:
        """把当前草稿冻结为送达快照；快照此后不可变。"""
        draft = self.load_draft(case_id)
        if draft is None:
            raise EasyReadError(f"案件 {case_id} 没有可送达的草稿")
        stamp = datetime.now(timezone.utc)
        served_id = "S-" + stamp.strftime("%Y%m%d%H%M%S")
        plain = draft.document.plain_text()
        snapshot = ServedBundle(
            case_id=case_id,
            served_id=served_id,
            served_at=stamp.isoformat(timespec="seconds"),
            source_records=draft.source_records,
            document=draft.document,
            report=draft.report,
            source_hash=draft.source_hash,
            doc_hash=_sha256(plain),
        )
        path = self._snapshot_path(case_id, served_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._write_json(path, snapshot.to_dict())
        # 只读保护：文件 0444、目录 0555
        os.chmod(path, 0o444)
        os.chmod(path.parent, 0o555)
        return snapshot

    # ------------------------------------------------------------ 读取

    def load_draft(self, case_id: str) -> DraftBundle | None:
        path = self._draft_path(case_id)
        if not path.exists():
            return None
        return _bundle_from_dict(json.loads(path.read_text(encoding="utf-8")), DraftBundle)

    def list_served(self, case_id: str) -> list[ServedBundle]:
        directory = self._served_dir(case_id)
        if not directory.exists():
            return []
        bundles = [
            _bundle_from_dict(json.loads(p.read_text(encoding="utf-8")), ServedBundle)
            for p in sorted(directory.glob("*.json"))
        ]
        return bundles

    def load_served(self, case_id: str, served_id: str) -> ServedBundle | None:
        path = self._snapshot_path(case_id, served_id)
        if not path.exists():
            return None
        return _bundle_from_dict(json.loads(path.read_text(encoding="utf-8")), ServedBundle)

    def trace_sentence(self, case_id: str, served_id: str, keyword: str) -> list[dict]:
        """申请人追问时，按关键词在送达快照中检索当时的句子及其正式依据。

        返回命中句子的栏目、原文、引用位置，以及引用位置在正式记录全文中的
        实际文字，证明「申请人当时收到的版本」与正式依据的对应关系。
        """
        snapshot = self.load_served(case_id, served_id)
        if snapshot is None:
            return []
        records = {r.record_id: r for r in snapshot.source_records}
        hits: list[dict] = []
        for sentence in snapshot.document.sentences:
            if keyword in sentence.text or keyword in sentence.note:
                evidence = []
                for citation in sentence.citations:
                    record = records.get(citation.record_id)
                    official = (
                        record.text[citation.start:citation.end] if record else "(记录缺失)"
                    )
                    evidence.append(
                        {
                            "locator": citation.locator,
                            "official_text": official,
                        }
                    )
                hits.append(
                    {
                        "section": sentence.section,
                        "text": sentence.text,
                        "note": sentence.note,
                        "evidence": evidence,
                    }
                )
        return hits

    # ------------------------------------------------------------ 工具

    @staticmethod
    def _write_json(path: Path, payload: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


# ---------------------------------------------------------------- 反序列化


def _bundle_from_dict(data: dict, bundle_type: type):
    records = [SourceRecord.from_dict(r) for r in data["source_records"]]
    document = _document_from_dict(data["document"])
    report = _report_from_dict(data["verification"])
    if bundle_type is DraftBundle:
        return DraftBundle(
            case_id=data["case_id"],
            source_records=records,
            document=document,
            report=report,
            source_hash=data["source_hash"],
            created_at=data["created_at"],
            updated_at=data["updated_at"],
            version=data.get("version", 1),
        )
    if bundle_type is ServedBundle:
        return ServedBundle(
            case_id=data["case_id"],
            served_id=data["served_id"],
            served_at=data["served_at"],
            source_records=records,
            document=document,
            report=report,
            source_hash=data["source_hash"],
            doc_hash=data["doc_hash"],
        )
    raise EasyReadError(f"不支持的捆绑类型：{bundle_type}")


def _document_from_dict(data: dict) -> EasyReadDocument:
    from .rewrite import RewrittenSentence
    from .textmodel import Span

    sentences = [
        RewrittenSentence(
            section=item["section"],
            text=item["text"],
            note=item.get("note", ""),
            citations=[Span.from_dict(c) for c in item["citations"]],
        )
        for item in data["sentences"]
    ]
    return EasyReadDocument(
        title=data["title"],
        sentences=sentences,
        reading_guide=data.get("reading_guide", ""),
    )


def _report_from_dict(data: dict) -> VerificationReport:
    from .verify import CheckResult

    return VerificationReport(
        results=[
            CheckResult(
                dimension=item["dimension"],
                passed=item["passed"],
                message=item["message"],
                locators=item.get("locators", []),
            )
            for item in data["checks"]
        ]
    )
