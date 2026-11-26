import support  # noqa: F401  隔离模式路径引导
import unittest

from easyread.numerals import parse_chinese_number
from easyread.textmodel import SourceRecord, find_span, split_sentences


class NumeralsTest(unittest.TestCase):
    def test_basic_chinese_numbers(self):
        self.assertEqual(parse_chinese_number("十"), 10)
        self.assertEqual(parse_chinese_number("十五"), 15)
        self.assertEqual(parse_chinese_number("三十"), 30)
        self.assertEqual(parse_chinese_number("一百二十"), 120)

    def test_financial_uppercase(self):
        self.assertEqual(parse_chinese_number("壹仟贰佰"), 1200)
        self.assertEqual(parse_chinese_number("叁佰"), 300)
        self.assertEqual(parse_chinese_number("壹万"), 10000)

    def test_arabic_and_invalid(self):
        self.assertEqual(parse_chinese_number("12"), 12)
        self.assertIsNone(parse_chinese_number("abc"))
        self.assertIsNone(parse_chinese_number(""))


class TextModelTest(unittest.TestCase):
    def setUp(self):
        self.record = SourceRecord(
            record_id="R1",
            text="第一句。第二句；第三句！",
            kind="decision",
        )

    def test_split_sentences_keeps_offsets(self):
        sentences = split_sentences(self.record)
        self.assertEqual([s.text for s in sentences], ["第一句。", "第二句；", "第三句！"])
        # 每个切句片段都能在原全文对应位置还原
        for sentence in sentences:
            self.assertEqual(
                self.record.text[sentence.start:sentence.end],
                sentence.text,
            )

    def test_find_span_locator(self):
        span = find_span(self.record, "第二句")
        self.assertIsNotNone(span)
        self.assertEqual(span.locator, "R1[4:7]")
        self.assertEqual(span.text, "第二句")
        self.assertIsNone(find_span(self.record, "不存在的内容"))

    def test_from_dict_requires_text_and_kind(self):
        record = SourceRecord.from_dict({"id": "X1", "text": "内容", "kind": "decision"})
        self.assertEqual(record.record_id, "X1")
        record_default = SourceRecord.from_dict({"id": "X2", "text": "内容"})
        self.assertEqual(record_default.kind, "decision")


if __name__ == "__main__":
    unittest.main()
