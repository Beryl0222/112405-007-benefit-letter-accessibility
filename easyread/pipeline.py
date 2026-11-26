"""一站式流水线：加载 → 抽取 → 更正/矛盾 → 改写 → 核对。

适合经办人在脚本或后端服务中直接调用。矛盾不自动消解，
统一以 :class:`~easyread.errors.ContradictionError` 抛出，
或通过 :func:`run` 返回结构化的阻断结果。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .contradictions import detect_contradictions, resolve
from .errors import ContradictionError
from .extract import extract_facts
from .model import FactSheet
from .rewrite import EasyReadDocument, rewrite_easyread
from .textmodel import SourceRecord
from .verify import VerificationReport, verify


@dataclass
class PipelineResult:
    """流水线结果。``ok=False`` 时 ``issues`` 携带矛盾条目。"""

    ok: bool
    case_id: str
    records: list[SourceRecord]
    sheet: FactSheet | None = None
    document: EasyReadDocument | None = None
    report: VerificationReport | None = None
    issues: list | None = None

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "case_id": self.case_id,
            "issues": [i.to_dict() for i in self.issues] if self.issues else [],
            "document": self.document.to_dict() if self.document else None,
            "verification": self.report.to_dict() if self.report else None,
        }


def load_case_file(path: str | Path) -> tuple[str, list[SourceRecord]]:
    """读取案件 JSON（如 ``data/case.json``），返回案件编号与记录列表。"""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    case_id = str(payload.get("case_id", "unknown-case"))
    records = [SourceRecord.from_dict(item) for item in payload["records"]]
    return case_id, records


def run(records: list[SourceRecord], case_id: str = "unknown-case") -> PipelineResult:
    """执行完整流水线；矛盾阻断时返回 ``ok=False`` 的结果而非猜测生成。"""
    sheet = extract_facts(records)
    try:
        resolve(sheet)
    except ContradictionError as exc:
        return PipelineResult(
            ok=False,
            case_id=case_id,
            records=records,
            sheet=sheet,
            issues=exc.issues,
        )
    document = rewrite_easyread(sheet)
    report = verify(sheet, document)
    return PipelineResult(
        ok=True,
        case_id=case_id,
        records=records,
        sheet=sheet,
        document=document,
        report=report,
    )


def inspect_only(records: list[SourceRecord]) -> tuple[FactSheet, list]:
    """只做抽取与矛盾检测，不生成易读版（供经办人排查问题）。"""
    sheet = extract_facts(records)
    return sheet, detect_contradictions(sheet)
