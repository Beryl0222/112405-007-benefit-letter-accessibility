"""领域事实模型。

抽取阶段把正式文本解析为一组带 :class:`~easyread.textmodel.Span` 的
不可变事实对象；改写与核对都基于这些对象，而不是重新解析字符串，
从而保证「同一份事实」贯穿全流程。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .textmodel import SourceRecord, Span


@dataclass(frozen=True)
class Fact:
    """所有事实的基类，至少包含来源片段。"""

    span: Span

    @property
    def record_id(self) -> str:
        return self.span.record_id

    def to_dict(self) -> dict[str, Any]:
        raise NotImplementedError


# ---------------------------------------------------------------- 期限

# 期限用途（归一化标签）
DEADLINE_SUPPLEMENT = "supplement"   # 补交材料期限
DEADLINE_APPEAL = "appeal"           # 救济/复核期限
DEADLINE_OTHER = "other"


@dataclass(frozen=True)
class DeadlineFact(Fact):
    """期限事实，如「自送达之日起十个工作日内补充材料」。

    :param amount: 期限长度（整数）。
    :param unit: 归一化单位，``工作日`` 或 ``日``。
    :param anchor: 起算锚点归一化值，``送达`` / ``收到`` / ``打印`` / ``决定`` / ``其他``。
    :param anchor_raw: 锚点原文，如 ``送达之日``。
    :param purpose: 用途标签，见本模块顶部的常量。
    :param correction_span: 若该事实已被更正记录修改，指向更正指令的位置。
    """

    amount: int
    unit: str
    anchor: str
    anchor_raw: str
    purpose: str = DEADLINE_OTHER
    correction_span: Span | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": "deadline",
            "amount": self.amount,
            "unit": self.unit,
            "anchor": self.anchor,
            "anchor_raw": self.anchor_raw,
            "purpose": self.purpose,
            "correction_span": self.correction_span.to_dict() if self.correction_span else None,
            "span": self.span.to_dict(),
        }


# ---------------------------------------------------------------- 金额

@dataclass(frozen=True)
class AmountFact(Fact):
    """补助金额事实，单位统一为人民币元。"""

    amount_yuan: int
    amount_raw: str
    action: str = "grant"  # grant=批准发放，reject=不予发放等
    correction_span: Span | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": "amount",
            "amount_yuan": self.amount_yuan,
            "amount_raw": self.amount_raw,
            "action": self.action,
            "correction_span": self.correction_span.to_dict() if self.correction_span else None,
            "span": self.span.to_dict(),
        }


# ---------------------------------------------------------------- 资格结论

CONCLUSION_APPROVED = "approved"
CONCLUSION_REJECTED = "rejected"
CONCLUSION_PENDING = "pending"       # 尚待核定（如补交材料情形）
CONCLUSION_OTHER = "other"


@dataclass(frozen=True)
class ConclusionFact(Fact):
    """资格结论事实。"""

    conclusion: str
    conclusion_raw: str
    correction_span: Span | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": "conclusion",
            "conclusion": self.conclusion,
            "conclusion_raw": self.conclusion_raw,
            "correction_span": self.correction_span.to_dict() if self.correction_span else None,
            "span": self.span.to_dict(),
        }


# ---------------------------------------------------------------- 家庭成员

@dataclass(frozen=True)
class FamilyMemberFact(Fact):
    """家庭成员/对象事实。

    :param member_raw: 成员原文，如 ``配偶李萍``。
    :param role: 归一化称谓，如 ``配偶``；无法识别时为空串。
    :param name: 姓名；无法识别时为空串。
    """

    member_raw: str
    role: str = ""
    name: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": "family_member",
            "member_raw": self.member_raw,
            "role": self.role,
            "name": self.name,
            "span": self.span.to_dict(),
        }


# ---------------------------------------------------------------- 核算周期

@dataclass(frozen=True)
class PeriodFact(Fact):
    """核算周期事实，如「核算周期为2026年7月至2026年12月」。"""

    period_raw: str
    start_raw: str
    end_raw: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": "period",
            "period_raw": self.period_raw,
            "start_raw": self.start_raw,
            "end_raw": self.end_raw,
            "span": self.span.to_dict(),
        }


# ---------------------------------------------------------------- 可补交材料

@dataclass(frozen=True)
class SupplementMaterialFact(Fact):
    """可补交材料事实，条件性内容必须原样保留条件。"""

    material_raw: str
    condition_raw: str = ""  # 条件原文，如「在公示无异议后」，无条件则为空

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": "supplement_material",
            "material_raw": self.material_raw,
            "condition_raw": self.condition_raw,
            "span": self.span.to_dict(),
        }


# ---------------------------------------------------------------- 救济方式

@dataclass(frozen=True)
class RemedyFact(Fact):
    """救济方式事实（申请复核、行政复议、行政诉讼等）。"""

    channel: str          # 归一化：review/复议/诉讼/other
    channel_raw: str
    deadline_span: Span | None = None  # 关联期限片段（同句时）

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": "remedy",
            "channel": self.channel,
            "channel_raw": self.channel_raw,
            "deadline_span": self.deadline_span.to_dict() if self.deadline_span else None,
            "span": self.span.to_dict(),
        }


# ---------------------------------------------------------------- 例外条款

@dataclass(frozen=True)
class ExceptionFact(Fact):
    """例外/但书条款，如「但复核期间不停止执行」。"""

    clause_raw: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": "exception",
            "clause_raw": self.clause_raw,
            "span": self.span.to_dict(),
        }


# ---------------------------------------------------------------- 明确日期

@dataclass(frozen=True)
class DateFact(Fact):
    """明确写在文本中的日期，用于日期矛盾检测。

    :param role: 语义角色，如 ``打印`` / ``送达`` / ``决定`` / ``未注明``。
    :param date_raw: 日期原文。
    :param normalized: ISO 格式 YYYY-MM-DD，无法完整解析时保留原文。
    """

    date_raw: str
    normalized: str
    role: str = "未注明"  # ISO 格式 YYYY-MM-DD，无法完整解析时保留原文

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": "date",
            "date_raw": self.date_raw,
            "normalized": self.normalized,
            "role": self.role,
            "span": self.span.to_dict(),
        }


# ---------------------------------------------------------------- 更正指令

@dataclass(frozen=True)
class CorrectionDirective:
    """更正记录中解析出的结构化指令。

    例：「更正：BL-3 的期限为十五个工作日，其他内容不变。」
    解析为目标记录 ``BL-3``、字段 ``deadline``、新值原文 ``十五个工作日``。
    """

    source_record_id: str
    target_record_id: str
    field: str                 # deadline / amount / conclusion / other
    new_value_raw: str
    directive_span: Span       # 整条更正指令在更正记录中的位置
    target_span: Span          # 目标编号的引用位置


# ---------------------------------------------------------------- 事实清单


@dataclass
class FactSheet:
    """一次抽取的全部事实，按记录编号与类型组织。"""

    facts: list[Fact] = field(default_factory=list)
    corrections: list[CorrectionDirective] = field(default_factory=list)
    records: dict[str, SourceRecord] = field(default_factory=dict)

    def add(self, fact: Fact) -> None:
        self.facts.append(fact)

    def by_type(self, fact_type: type) -> list[Fact]:
        return [f for f in self.facts if isinstance(f, fact_type)]

    def by_record(self, record_id: str) -> list[Fact]:
        return [f for f in self.facts if f.record_id == record_id]

    def replace_facts(self, record_id: str, predicate, new_facts: list[Fact]) -> None:
        """应用更正：删除满足 ``predicate`` 的旧事实，插入新事实。"""
        kept = [
            f
            for f in self.facts
            if not (f.record_id == record_id and predicate(f))
        ]
        self.facts = kept + list(new_facts)

    def to_dict(self) -> dict[str, Any]:
        return {
            "facts": [f.to_dict() for f in self.facts],
            "corrections": [
                {
                    "source_record_id": c.source_record_id,
                    "target_record_id": c.target_record_id,
                    "field": c.field,
                    "new_value_raw": c.new_value_raw,
                    "directive_span": c.directive_span.to_dict(),
                    "target_span": c.target_span.to_dict(),
                }
                for c in self.corrections
            ],
        }


# ---------------------------------------------------------------- 矛盾条目

CONFLICT_DEADLINE = "deadline_conflict"
CONFLICT_DATE = "date_conflict"
CONFLICT_OBJECT = "object_conflict"
CONFLICT_AMOUNT = "amount_conflict"
CONFLICT_CONCLUSION = "conclusion_conflict"


@dataclass(frozen=True)
class ContradictionIssue:
    """一处无法自动消解的矛盾。

    :param kind: 矛盾类型常量。
    :param message: 面向经办人的中文说明。
    :param spans: 涉及的正式文本片段（至少两个）。
    """

    kind: str
    message: str
    spans: list[Span]

    def __str__(self) -> str:
        locators = "、".join(s.locator for s in self.spans)
        return f"[{self.kind}] {self.message}（依据位置：{locators}）"

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "message": self.message,
            "spans": [s.to_dict() for s in self.spans],
        }
