import support  # noqa: F401  隔离模式路径引导
import unittest
from pathlib import Path

from easyread.model import DeadlineFact, DEADLINE_APPEAL, DEADLINE_SUPPLEMENT
from easyread.pipeline import load_case_file, run
from easyread.contradictions import resolve
from easyread.extract import extract_facts
from easyread.verify import verify
from easyread.rewrite import rewrite_easyread

CASE_PATH = Path(__file__).parents[1] / "data" / "case.json"


class ExistingCaseMaterialTest(unittest.TestCase):
    """仓库自带 data/case.json（BL-3/BL-4/BL-5）的端到端核对。"""

    def test_blue_case_pipeline_with_correction(self):
        case_id, records = load_case_file(CASE_PATH)
        self.assertEqual(case_id, "benefit-3")

        result = run(records, case_id=case_id)
        self.assertTrue(result.ok, [str(i) for i in (result.issues or [])])

        # BL-5 把 BL-3 的补交期限从十个工作日更正为十五个工作日
        deadlines = result.sheet.by_type(DeadlineFact)
        supplement = next(d for d in deadlines if d.purpose == DEADLINE_SUPPLEMENT)
        self.assertEqual(supplement.amount, 15)
        self.assertEqual(supplement.unit, "工作日")
        self.assertIsNotNone(supplement.correction_span)
        self.assertEqual(supplement.correction_span.record_id, "BL-5")

        # BL-4 的申诉期限仍为三十日，且起算锚点为「收到」
        appeal = next(d for d in deadlines if d.purpose == DEADLINE_APPEAL)
        self.assertEqual(appeal.amount, 30)
        self.assertEqual(appeal.anchor, "收到")

        plain = result.document.plain_text()
        self.assertIn("15工作日", plain)
        self.assertIn("打印日期", plain)  # 起算日提示必须出现
        self.assertTrue(result.report.passed)

    def test_blue_case_citation_locators_resolve(self):
        _, records = load_case_file(CASE_PATH)
        sheet = resolve(extract_facts(records))
        doc = rewrite_easyread(sheet)
        report = verify(sheet, doc)
        self.assertTrue(report.passed, report.plain_text())
        record_text = {r.record_id: r.text for r in records}
        for sentence in doc.sentences:
            for citation in sentence.citations:
                self.assertEqual(
                    record_text[citation.record_id][citation.start:citation.end],
                    citation.text,
                )


if __name__ == "__main__":
    unittest.main()
