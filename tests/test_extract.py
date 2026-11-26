import support  # noqa: F401  隔离模式路径引导
import unittest

from easyread.extract import extract_facts
from easyread.model import (
    AmountFact,
    ConclusionFact,
    CONCLUSION_APPROVED,
    CONCLUSION_PENDING,
    DateFact,
    DeadlineFact,
    DEADLINE_APPEAL,
    DEADLINE_SUPPLEMENT,
    ExceptionFact,
    FamilyMemberFact,
    PeriodFact,
    RemedyFact,
    SupplementMaterialFact,
)
from easyread.textmodel import SourceRecord

RECORDS = [
    SourceRecord("R1", "决定予以补助；家庭成员包括配偶李萍、女儿周玥。", "decision"),
    SourceRecord("R2", "核算周期为2026年7月至2026年12月。", "decision"),
    SourceRecord(
        "R3",
        "批准发放补助人民币壹仟贰佰元；申请人可自送达之日起十个工作日内补充材料，补交不表示资格已核定。",
        "decision",
    ),
    SourceRecord(
        "R4",
        "在公示无异议后，可补交的材料为收入证明、医疗票据。",
        "decision",
    ),
    SourceRecord(
        "R5",
        "如对本决定有异议，可自收到之日起三十日内申请复核；但复核期间不停止执行。",
        "appeal-clause",
    ),
    SourceRecord("R6", "本决定书打印日期为2026年11月3日，送达日期为2026年11月6日。", "decision"),
]


class ExtractionTest(unittest.TestCase):
    def setUp(self):
        self.sheet = extract_facts(RECORDS)

    def test_deadlines_with_anchor_and_purpose(self):
        deadlines = self.sheet.by_type(DeadlineFact)
        self.assertEqual(len(deadlines), 2)
        supplement = next(d for d in deadlines if d.purpose == DEADLINE_SUPPLEMENT)
        appeal = next(d for d in deadlines if d.purpose == DEADLINE_APPEAL)
        self.assertEqual((supplement.amount, supplement.unit), (10, "工作日"))
        self.assertEqual(supplement.anchor, "送达")
        self.assertIn("送达之日", supplement.anchor_raw)
        self.assertEqual((appeal.amount, appeal.unit), (30, "日"))
        self.assertEqual(appeal.anchor, "收到")

    def test_date_day_component_is_not_misread_as_deadline(self):
        # 「2026年11月3日」中的「3日」不得被识别成期限
        self.assertEqual(
            [d.amount for d in self.sheet.by_type(DeadlineFact)],
            [10, 30],
        )
        dates = self.sheet.by_type(DateFact)
        roles = {d.normalized: d.role for d in dates}
        self.assertEqual(roles["2026-11-03"], "打印")
        self.assertEqual(roles["2026-11-06"], "送达")

    def test_amount_financial_uppercase(self):
        amounts = self.sheet.by_type(AmountFact)
        self.assertEqual(len(amounts), 1)
        self.assertEqual(amounts[0].amount_yuan, 1200)
        self.assertIn("壹仟贰佰", amounts[0].amount_raw)

    def test_conclusions_include_pending_guard(self):
        conclusions = self.sheet.by_type(ConclusionFact)
        labels = {c.conclusion for c in conclusions}
        self.assertIn(CONCLUSION_APPROVED, labels)
        self.assertIn(CONCLUSION_PENDING, labels)

    def test_family_members_keep_full_role(self):
        members = self.sheet.by_type(FamilyMemberFact)
        pairs = {(m.role, m.name) for m in members}
        # 「女儿」必须整体识别，不能被「女」拆成「女 + 儿周玥」
        self.assertIn(("配偶", "李萍"), pairs)
        self.assertIn(("女", "周玥"), pairs)
        self.assertTrue(any(m.member_raw == "女儿周玥" for m in members))
        # 枚举尾巴上的非成员表述不得混入
        self.assertFalse(any("列明对象" in m.member_raw for m in members))

    def test_period_fact(self):
        periods = self.sheet.by_type(PeriodFact)
        self.assertEqual(len(periods), 1)
        self.assertEqual(periods[0].start_raw, "2026年7月")
        self.assertEqual(periods[0].end_raw, "2026年12月")

    def test_supplement_keeps_condition(self):
        materials = self.sheet.by_type(SupplementMaterialFact)
        self.assertEqual(len(materials), 1)
        self.assertIn("收入证明", materials[0].material_raw)
        self.assertIn("公示无异议", materials[0].condition_raw)

    def test_remedy_and_exception(self):
        remedies = self.sheet.by_type(RemedyFact)
        self.assertEqual(len(remedies), 1)  # 同句重复渠道已去重
        self.assertEqual(remedies[0].channel, "review")
        exceptions = self.sheet.by_type(ExceptionFact)
        self.assertEqual(len(exceptions), 1)
        self.assertIn("不停止执行", exceptions[0].clause_raw)

    def test_all_spans_round_trip_in_source_text(self):
        for fact in self.sheet.facts:
            record = next(r for r in RECORDS if r.record_id == fact.record_id)
            self.assertEqual(
                record.text[fact.span.start:fact.span.end],
                fact.span.text,
                f"片段 {fact.span.locator} 无法在原文还原",
            )

    def test_correction_directive_parsed(self):
        records = RECORDS + [
            SourceRecord("R7", "更正：R3 的期限为十五个工作日，其他内容不变。", "correction")
        ]
        sheet = extract_facts(records)
        self.assertEqual(len(sheet.corrections), 1)
        directive = sheet.corrections[0]
        self.assertEqual(directive.target_record_id, "R3")
        self.assertEqual(directive.field, "deadline")
        self.assertEqual(directive.new_value_raw, "十五个工作日")
        # 更正记录本身不抽取普通事实
        self.assertFalse(any(f.record_id == "R7" for f in sheet.facts))


if __name__ == "__main__":
    unittest.main()
