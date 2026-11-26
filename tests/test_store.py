import support  # noqa: F401  隔离模式路径引导
import json
import os
import tempfile
import unittest
from pathlib import Path

from easyread.errors import ContradictionError, EasyReadError
from easyread.store import BlockedBundle, CaseStore, DraftBundle, ServedBundle
from easyread.textmodel import SourceRecord

NORMAL_RECORDS = [
    SourceRecord("R1", "经审查决定予以补助；家庭成员包括配偶李萍。", "decision"),
    SourceRecord(
        "R3",
        "批准发放补助人民币壹仟贰佰元；申请人可自送达之日起十个工作日内补充材料，补交不表示资格已核定。",
        "decision",
    ),
    SourceRecord("R5", "如对本决定有异议，可自收到之日起三十日内申请复核。", "appeal-clause"),
]

CORRECTED_RECORDS = NORMAL_RECORDS + [
    SourceRecord("R7", "更正：R3 的期限为十五个工作日，其他内容不变。", "correction"),
]

CONFLICT_RECORDS = [
    SourceRecord("C2", "家庭成员包括配偶李萍。", "decision"),
    SourceRecord("C3", "经核对，申请人配偶为王梅。", "decision"),
]


class StoreLifecycleTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = CaseStore(self.tmp.name)

    def tearDown(self):
        # 快照是只读的，清理前先恢复权限以便 TemporaryDirectory 删除
        for root, dirs, files in os.walk(self.tmp.name):
            for name in files:
                os.chmod(os.path.join(root, name), 0o644)
            for name in dirs:
                os.chmod(os.path.join(root, name), 0o755)
        self.tmp.cleanup()

    def test_draft_reflects_correction_and_version_increments(self):
        first = self.store.build_draft("CASE-1", NORMAL_RECORDS)
        self.assertIsInstance(first, DraftBundle)
        self.assertEqual(first.version, 1)
        first_text = first.document.plain_text()
        self.assertIn("10工作日", first_text)

        # 决定书更正后重建草稿：未发送，应直接反映新版本
        second = self.store.build_draft("CASE-1", CORRECTED_RECORDS)
        self.assertEqual(second.version, 2)
        second_text = second.document.plain_text()
        self.assertIn("15工作日", second_text)
        self.assertNotIn("10工作日内（原文", second_text)
        # 创建时间保留、更新时间变化
        self.assertEqual(first.created_at, second.created_at)

    def test_served_snapshot_is_immutable_and_keeps_old_wording(self):
        self.store.build_draft("CASE-1", NORMAL_RECORDS)
        snapshot = self.store.serve("CASE-1")
        self.assertIsInstance(snapshot, ServedBundle)
        path = self.store._snapshot_path("CASE-1", snapshot.served_id)

        # 文件权限只读
        self.assertEqual(oct(os.stat(path).st_mode & 0o777), "0o444")

        # 送达后再更正：草稿更新，但已送达快照内容不变
        self.store.build_draft("CASE-1", CORRECTED_RECORDS)
        frozen = json.loads(path.read_text(encoding="utf-8"))
        frozen_plain = "\n".join(s["text"] for s in frozen["document"]["sentences"])
        self.assertIn("10工作日", frozen_plain)
        self.assertNotIn("15工作日", frozen_plain)
        # 快照完整保留当时的正式文本全文
        self.assertTrue(any(r["id"] == "R3" for r in frozen["source_records"]))

    def test_trace_sentence_returns_evidence_locators(self):
        self.store.build_draft("CASE-1", NORMAL_RECORDS)
        snapshot = self.store.serve("CASE-1")
        hits = self.store.trace_sentence("CASE-1", snapshot.served_id, "期限")
        self.assertTrue(hits)
        for hit in hits:
            self.assertTrue(hit["evidence"])
            for evidence in hit["evidence"]:
                self.assertRegex(evidence["locator"], r"^R\d+\[\d+:\d+\]$")
                self.assertTrue(evidence["official_text"])

    def test_serve_without_draft_raises(self):
        with self.assertRaises(EasyReadError):
            self.store.serve("NO-SUCH-CASE")

    def test_blocked_bundle_when_contradiction(self):
        bundle = self.store.try_build("CASE-BAD", CONFLICT_RECORDS)
        self.assertIsInstance(bundle, BlockedBundle)
        self.assertTrue(bundle.issues)
        blocked_path = Path(self.tmp.name) / "CASE-BAD" / "blocked.json"
        self.assertTrue(blocked_path.exists())
        # 阻断时不得生成草稿
        self.assertIsNone(self.store.load_draft("CASE-BAD"))

    def test_build_draft_raises_on_contradiction(self):
        with self.assertRaises(ContradictionError):
            self.store.build_draft("CASE-BAD", CONFLICT_RECORDS)

    def test_draft_round_trip_from_disk(self):
        self.store.build_draft("CASE-1", NORMAL_RECORDS)
        loaded = self.store.load_draft("CASE-1")
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.case_id, "CASE-1")
        self.assertTrue(loaded.report.passed)
        self.assertEqual(
            loaded.document.plain_text(),
            self.store.build_draft("CASE-1", NORMAL_RECORDS).document.plain_text(),
        )


if __name__ == "__main__":
    unittest.main()
