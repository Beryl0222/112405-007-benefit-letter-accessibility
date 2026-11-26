"""文本模型：字符位置片段、来源记录与切句。

所有抽取结果都保留在**原记录全文**中的字符区间（``start``/``end``），
使改写后的每一句话都能回指到正式文本的具体位置，例如
``R3[12:25]``，满足「追查每个改写句子对应的正式依据」的要求。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# 中文文书常见句末标点（含全角分号、句号等）
_SENTENCE_DELIMITERS = "。；;！!？?\n"
# 分句时保留标点的切分模式
_SENT_PATTERN = re.compile(rf"([^{_SENTENCE_DELIMITERS}]+[{_SENTENCE_DELIMITERS}]?)")


@dataclass(frozen=True)
class SourceRecord:
    """一条正式文本记录（决定书原文、申诉条款、更正书等）。

    :param record_id: 稳定编号，如 ``R1``、``BL-3``。
    :param text: 记录全文。
    :param kind: 记录类型，如 ``decision`` / ``appeal-clause`` / ``correction``。
    """

    record_id: str
    text: str
    kind: str = "decision"

    @classmethod
    def from_dict(cls, data: dict) -> "SourceRecord":
        return cls(
            record_id=str(data["id"]),
            text=str(data["text"]),
            kind=str(data.get("kind") or data.get("source") or "decision"),
        )

    def to_dict(self) -> dict:
        return {"id": self.record_id, "text": self.text, "kind": self.kind}


@dataclass(frozen=True)
class Span:
    """一段文字及其在所属 :class:`SourceRecord` 全文中的字符位置。"""

    record_id: str
    start: int
    end: int
    text: str

    @property
    def locator(self) -> str:
        """可在报告中展示的引用位置，如 ``R3[12:25]``。"""
        return f"{self.record_id}[{self.start}:{self.end}]"

    def to_dict(self) -> dict:
        return {
            "record_id": self.record_id,
            "start": self.start,
            "end": self.end,
            "text": self.text,
            "locator": self.locator,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Span":
        return cls(
            record_id=data["record_id"],
            start=int(data["start"]),
            end=int(data["end"]),
            text=data["text"],
        )


@dataclass(frozen=True)
class Sentence:
    """切句结果，同样带字符位置。"""

    record_id: str
    start: int
    end: int
    text: str

    @property
    def span(self) -> Span:
        return Span(self.record_id, self.start, self.end, self.text)


def split_sentences(record: SourceRecord) -> list[Sentence]:
    """把一条记录按中文句末标点切成若干句子，位置相对记录全文。

    切分只在标点处发生，不改变原文用字；空白片段会被丢弃。
    """
    sentences: list[Sentence] = []
    for match in _SENT_PATTERN.finditer(record.text):
        piece = match.group(0).strip()
        if not piece:
            continue
        # strip 后位置需要重新定位：在原匹配区间内查找子串
        offset = match.group(0).index(piece[0])
        start = match.start() + offset
        end = start + len(piece)
        sentences.append(Sentence(record.record_id, start, end, piece))
    return sentences


def find_span(record: SourceRecord, snippet: str, start_at: int = 0) -> Span | None:
    """在记录全文中查找 ``snippet``，返回带位置的片段；找不到返回 ``None``。"""
    index = record.text.find(snippet, start_at)
    if index < 0:
        return None
    return Span(record.record_id, index, index + len(snippet), snippet)


def make_span(record: SourceRecord, match: re.Match, group: int | str = 0) -> Span:
    """把正则匹配结果包装成 :class:`Span`。"""
    text = match.group(group)
    start = match.start(group)
    return Span(record.record_id, start, start + len(text), text)
