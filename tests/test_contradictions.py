import support  # noqa: F401  隔离模式路径引导
import unittest

from easyread.contradictions import detect_contradictions, resolve
from easyread.errors import ContradictionError
from easyread.extract import extract_facts
from easyread.model import (
    CONFLICT_DATE,
    CONFLICT_DEADLINE,
    CONFLICT_OBJECT,
    DeadlineFact,
    DEADLINE_SUPPLEMENT,
)
from easyread.textmodel import SourceRecord


class CorrectionApplicationTest(unittest.TestCase):
    def test_correction_replaces_deadline_and_keeps_trace(self):
        records = [
            SourceRecord("BL-3", "申请人可自送达之日起十个工作日内补充材料；补交不表示资格已核定。", "decision"),
            SourceRecord("BL-5", "更正：BL-3 的期限为十五个工作日，其他内容不变。", "correction"),
        ]
        sheet = resolve(extract_facts(records))
        deadlines = sheet.by_type(DeadlineFact)
        self.assertEqual(len(deadlines), 1)
        fact = deadlines[0]
        self.assertEqual(fact.amount, 15)
        self.assertEqual(fact.unit, "工作日")
        # 原依据位置保留，更正指令位置可追溯
        self.assertEqual(fact.span.record_id, "BL-3")
        self.assertIsNotNone(fact.correction_span)
        self.assertEqual(fact.correction_span.record_id, "BL-5")

    def test_correction_missing_target_is_reported(self):
        records = [
            SourceRecord("X9", "更正：BL-99 的期限为十五个工作日，其他内容不变。", "correction"),
        ]
        with self.assertRaises(ContradictionError) as ctx:
            resolve(extract_facts(records))
        self.assertTrue(ctx.exception.issues)
        self.assertIn("BL-99", ctx.exception.issues[0].message)

    def test_delivery_and_receipt_anchors_are_equivalent(self):
        records = [
            SourceRecord("A1", "申请人可自送达之日起十个工作日内补充材料。", "decision"),
            SourceRecord("A2", "如对本决定有异议，可自收到之日起三十日内申请复核。", "appeal-clause"),
        ]
        sheet = resolve(extract_facts(records))
        self.assertEqual(detect_contradictions(sheet), [])


class ContradictionDetectionTest(unittest.TestCase):
    def test_anchor_conflict_delivery_vs_print(self):
        records = [
            SourceRecord("C4", "申请人可自送达之日起十个工作日内补充材料。", "decision"),
            SourceRecord("C5", "如对本决定有异议，可自打印之日起十五日内申请复核。", "appeal-clause"),
        ]
        sheet = extract_facts(records)
        issues = detect_contradictions(sheet)
        kinds = {i.kind for i in issues}
        self.assertIn(CONFLICT_DEADLINE, kinds)
        self.assertTrue(any("起算口径" in i.message for i in issues))
        # 所有问题都必须带至少两个正式文本位置
        for issue in issues:
            self.assertGreaterEqual(len(issue.spans), 2)

    def test_same_role_date_conflict(self):
        records = [
            SourceRecord(
                "C6",
                "本决定书打印日期为2026年11月3日；本决定书打印日期为2026年11月8日。",
                "decision",
            ),
        ]
        sheet = extract_facts(records)
        issues = detect_contradictions(sheet)
        self.assertTrue(any(i.kind == CONFLICT_DATE for i in issues))

    def test_different_role_dates_are_not_conflict(self):
        records = [
            SourceRecord(
                "D1",
                "本决定书打印日期为2026年11月3日，送达日期为2026年11月6日。",
                "decision",
            ),
        ]
        sheet = extract_facts(records)
        self.assertEqual(detect_contradictions(sheet), [])

    def test_object_conflict_same_role_different_name(self):
        records = [
            SourceRecord("C2", "家庭成员包括配偶李萍、女儿吴蕊。", "decision"),
            SourceRecord("C3", "另经核对，申请人配偶为王梅，应同步登记。", "decision"),
        ]
        sheet = extract_facts(records)
        issues = detect_contradictions(sheet)
        self.assertTrue(any(i.kind == CONFLICT_OBJECT for i in issues))
        message = " ".join(i.message for i in issues if i.kind == CONFLICT_OBJECT)
        self.assertIn("李萍", message)
        self.assertIn("王梅", message)

    def test_conflicting_case_never_produces_easyread(self):
        # 端到端：存在矛盾时流水线必须阻断，而不是输出流畅但失真的文本
        from easyread.pipeline import run

        records = [
            SourceRecord("E1", "家庭成员包括配偶李萍。", "decision"),
            SourceRecord("E2", "经核对，申请人配偶为王梅。", "decision"),
        ]
        result = run(records, case_id="blocked-case")
        self.assertFalse(result.ok)
        self.assertTrue(result.issues)
        self.assertIsNone(result.document)

    def test_same_purpose_deadline_length_conflict(self):
        records = [
            SourceRecord("F1", "申请人可自送达之日起十个工作日内补充材料。", "decision"),
            SourceRecord("F2", "申请人亦可自送达之日起五个工作日内补充材料。", "decision"),
        ]
        sheet = extract_facts(records)
        issues = detect_contradictions(sheet)
        self.assertTrue(
            any(i.kind == CONFLICT_DEADLINE and "长度不一致" in i.message for i in issues)
        )


if __name__ == "__main__":
    unittest.main()
