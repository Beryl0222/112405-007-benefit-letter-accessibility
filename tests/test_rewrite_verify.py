import support  # noqa: F401  隔离模式路径引导
import unittest

from easyread.contradictions import resolve
from easyread.extract import extract_facts
from easyread.rewrite import rewrite_easyread
from easyread.textmodel import SourceRecord
from easyread.verify import verify

RECORDS = [
    SourceRecord("R1", "经审查决定予以补助；家庭成员包括配偶李萍、女儿周玥，仅上述列明对象随本决定申报。", "decision"),
    SourceRecord("R2", "本次补助的核算周期为2026年7月至2026年12月。", "decision"),
    SourceRecord("R3", "批准发放补助人民币壹仟贰佰元；申请人可自送达之日起十个工作日内补充材料，补交不表示资格已核定。", "decision"),
    SourceRecord("R4", "在公示无异议后，可补交的材料为收入证明、医疗票据及租房合同。", "decision"),
    SourceRecord("R5", "如对本决定有异议，可自收到之日起三十日内申请复核；但复核期间不停止本决定的执行。", "appeal-clause"),
    SourceRecord("R7", "更正：R3 的期限为十五个工作日，其他内容不变。", "correction"),
]


class RewriteTest(unittest.TestCase):
    def setUp(self):
        self.sheet = resolve(extract_facts(RECORDS))
        self.doc = rewrite_easyread(self.sheet)
        self.full_text = self.doc.plain_text()

    def test_every_sentence_has_real_citation(self):
        self.assertTrue(self.doc.sentences)
        for sentence in self.doc.sentences:
            self.assertTrue(sentence.citations, f"栏目 {sentence.section} 存在无引用句子")
            records = {r.record_id: r for r in RECORDS}
            for citation in sentence.citations:
                record = records[citation.record_id]
                self.assertEqual(
                    record.text[citation.start:citation.end],
                    citation.text,
                )

    def test_pending_qualification_is_not_presented_as_approved(self):
        self.assertIn("还没有最终核定", self.full_text)
        self.assertIn("不代表资格已经获批", self.full_text)

    def test_appeal_deadline_mentions_anchor_not_print_date(self):
        self.assertIn("收到", self.full_text)
        self.assertIn("不是按决定书上的打印日期起算", self.full_text)
        self.assertIn("30日", self.full_text)

    def test_corrected_deadline_shows_new_value_and_both_locators(self):
        supplement_section = [s for s in self.doc.sentences if s.section == "五、补交材料"]
        joined = "\n".join(s.text for s in supplement_section)
        self.assertIn("15工作日", joined)
        self.assertIn("R7[0:16]", joined)
        self.assertIn("R3", joined)

    def test_conditional_material_keeps_condition(self):
        supplement_section = [s for s in self.doc.sentences if s.section == "五、补交材料"]
        joined = "\n".join(s.text + s.note for s in supplement_section)
        self.assertIn("公示无异议", joined)
        self.assertIn("附条件", joined)
        self.assertIn("收入证明", joined)

    def test_family_and_period_preserved(self):
        self.assertIn("配偶李萍", self.full_text)
        self.assertIn("女儿周玥", self.full_text)
        self.assertIn("2026年7月", self.full_text)
        self.assertIn("2026年12月", self.full_text)

    def test_exception_clause_preserved(self):
        self.assertIn("复核期间不停止本决定的执行", self.full_text)


class VerifyTest(unittest.TestCase):
    def setUp(self):
        self.sheet = resolve(extract_facts(RECORDS))
        self.doc = rewrite_easyread(self.sheet)

    def test_report_passes_for_faithful_rewrite(self):
        report = verify(self.sheet, self.doc)
        self.assertTrue(report.passed, report.plain_text())
        dimensions = {r.dimension for r in report.results}
        self.assertEqual(
            dimensions,
            {"资格结论", "金额", "期限", "例外与条件", "救济方式", "对象与周期", "引用可追溯"},
        )

    def test_report_fails_when_anchor_removed(self):
        from easyread.rewrite import RewrittenSentence

        # 人为删掉救济句中的起算锚点，核对必须发现
        tampered = rewrite_easyread(self.sheet)
        tampered.sentences = [
            RewrittenSentence(
                section=s.section,
                text=s.text.replace("收到", "决定作出").replace("送达", "决定作出"),
                citations=s.citations,
                note=s.note.replace("收到", "决定作出").replace("送达", "决定作出"),
            )
            for s in tampered.sentences
        ]
        report = verify(self.sheet, tampered)
        self.assertFalse(report.passed)
        self.assertTrue(any("锚点" in f.message for f in report.failures))

    def test_report_fails_when_condition_dropped(self):
        # 保留正式事实（含条件），但把易读版中的条件表述删掉，
        # 模拟改写时把附条件安排误写成无条件承诺
        sheet = resolve(extract_facts(RECORDS))
        doc = rewrite_easyread(sheet)
        from easyread.rewrite import RewrittenSentence

        doc.sentences = [
            RewrittenSentence(
                section=s.section,
                text=s.text.replace("公示无异议", "XXXX").replace("附条件", "普通"),
                citations=s.citations,
                note=s.note.replace("条件原文已保留，未改写成无条件承诺。", ""),
            )
            for s in doc.sentences
        ]
        report = verify(sheet, doc)
        self.assertFalse(report.passed)
        self.assertTrue(any(r.dimension == "例外与条件" for r in report.failures))

    def test_report_fails_on_broken_citation(self):
        from easyread.rewrite import RewrittenSentence
        from easyread.textmodel import Span

        doc = rewrite_easyread(self.sheet)
        first = doc.sentences[0]
        broken_citation = Span(first.citations[0].record_id, 0, 3, "被篡改的文字")
        doc.sentences[0] = RewrittenSentence(
            section=first.section,
            text=first.text,
            citations=[broken_citation],
            note=first.note,
        )
        report = verify(self.sheet, doc)
        self.assertFalse(report.passed)
        self.assertTrue(any(r.dimension == "引用可追溯" for r in report.failures))


if __name__ == "__main__":
    unittest.main()
