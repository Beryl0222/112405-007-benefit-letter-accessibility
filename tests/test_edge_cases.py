import support  # noqa: F401  隔离模式路径引导
import unittest

from easyread.pipeline import run
from easyread.textmodel import SourceRecord


class EmptyInputTest(unittest.TestCase):
    def test_minimal_record_does_not_fabricate_facts(self):
        records = [SourceRecord("E1", "本决定书写明事项另行通知。", "decision")]
        result = run(records, case_id="edge-1")
        self.assertTrue(result.ok)
        self.assertEqual(result.sheet.facts, [])
        # 没有事实就不生成说明句子，但阅读提示保留，核对全部跳过且通过
        self.assertEqual(result.document.sentences, [])
        self.assertTrue(result.report.passed)
        self.assertIn("阅读提示", result.document.plain_text())

    def test_empty_record_list_is_blocked_safely(self):
        result = run([], case_id="edge-empty")
        self.assertTrue(result.ok)
        self.assertEqual(result.document.sentences, [])


if __name__ == "__main__":
    unittest.main()
