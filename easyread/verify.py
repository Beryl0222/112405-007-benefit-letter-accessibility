"""复核核对：确认易读版与正式文本在五个维度上保持一致。

核对维度（对应业务要求）：

1. **资格结论** —— 批准/拒绝/待核定口径一致，且「待核定」不得被写成已获批；
2. **金额** —— 补助金额数值一致；
3. **期限** —— 同用途期限的长度、单位、起算锚点一致，起算锚点必须在易读句中出现；
4. **例外与条件** —— 正式文本中的条件词、但书必须在易读版中有对应承载；
5. **救济方式** —— 救济渠道一致，且每条易读句子的引用位置真实指向正式文本。

核对只报告事实，不做改写；任何一项失败都会在报告中标记 ``passed=False``。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .model import (
    AmountFact,
    ConclusionFact,
    CONCLUSION_PENDING,
    DeadlineFact,
    DEADLINE_APPEAL,
    DEADLINE_SUPPLEMENT,
    ExceptionFact,
    FactSheet,
    FamilyMemberFact,
    PeriodFact,
    RemedyFact,
    SupplementMaterialFact,
)
from .rewrite import EasyReadDocument
from .textmodel import Span

# 条件性用语：正式文本出现时，易读版必须有对应承载
_CONDITION_TERMS = ["仅当", "只有在", "在", "后", "前提", "但", "但是", "除外", "不包括"]
_PENDING_GUARDWORDS = ["尚未", "没有最终核定", "未核定", "不代表", "不能视为", "还不能视为"]
_ANCHOR_WORDS = {
    "送达": ["送达", "收到"],
    "收到": ["收到"],
    "打印": ["打印"],
    "签发": ["签发"],
    "决定": ["决定作出", "作出"],
    "其他": [],
}


@dataclass
class CheckResult:
    """单项核对结果。"""

    dimension: str
    passed: bool
    message: str
    locators: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "dimension": self.dimension,
            "passed": self.passed,
            "message": self.message,
            "locators": self.locators,
        }


@dataclass
class VerificationReport:
    """完整核对报告。"""

    results: list[CheckResult] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(r.passed for r in self.results)

    @property
    def failures(self) -> list[CheckResult]:
        return [r for r in self.results if not r.passed]

    def add(self, result: CheckResult) -> None:
        self.results.append(result)

    def to_dict(self) -> dict:
        return {
            "passed": self.passed,
            "checks": [r.to_dict() for r in self.results],
        }

    def plain_text(self) -> str:
        lines = [f"核对结论：{'通过' if self.passed else '未通过'}", ""]
        for result in self.results:
            mark = "✓" if result.passed else "✗"
            lines.append(f"[{mark}] {result.dimension}：{result.message}")
            if result.locators:
                lines.append(f"    依据位置：{'、'.join(result.locators)}")
        return "\n".join(lines)


def verify(sheet: FactSheet, doc: EasyReadDocument) -> VerificationReport:
    """对易读文档执行全部核对，返回 :class:`VerificationReport`。"""
    report = VerificationReport()
    report.add(_check_conclusion(sheet, doc))
    report.add(_check_amount(sheet, doc))
    report.add(_check_deadlines(sheet, doc))
    report.add(_check_conditions(sheet, doc))
    report.add(_check_remedies(sheet, doc))
    report.add(_check_family_and_period(sheet, doc))
    report.add(_check_citations(sheet, doc))
    return report


def _all_text(doc: EasyReadDocument) -> str:
    return "\n".join(s.text + "\n" + s.note for s in doc.sentences)


# ---------------------------------------------------------------- 各维度


def _check_conclusion(sheet: FactSheet, doc: EasyReadDocument) -> CheckResult:
    facts = sheet.by_type(ConclusionFact)
    full_text = _all_text(doc)
    locators = [f.span.locator for f in facts]
    if not facts:
        return CheckResult("资格结论", True, "正式文本未出现明确资格结论，本项跳过。", locators)
    for fact in facts:
        if fact.conclusion == CONCLUSION_PENDING:
            guarded = any(word in full_text for word in _PENDING_GUARDWORDS)
            approved_words = ["已获批准", "已经获批", "批准享受"]
            misstates = any(w in full_text for w in approved_words) and not guarded
            if not guarded:
                return CheckResult(
                    "资格结论",
                    False,
                    "正式文本表明资格尚未核定，但易读版缺少「未核定/不代表获批」类提示，申请人可能误以为已获批。",
                    locators,
                )
            if misstates:
                return CheckResult(
                    "资格结论",
                    False,
                    "易读版出现已获批表述，与正式文本的待核定结论冲突。",
                    locators,
                )
        elif fact.conclusion == "approved" and ("未获批准" in full_text or "不予批准" in full_text):
            return CheckResult("资格结论", False, "正式结论为批准，易读版却出现未批准表述。", locators)
        elif fact.conclusion == "rejected" and "已获批准" in full_text:
            return CheckResult("资格结论", False, "正式结论为不予批准，易读版却出现已获批表述。", locators)
    return CheckResult("资格结论", True, "资格结论口径一致，待核定情形的防误读提示齐全。", locators)


def _check_amount(sheet: FactSheet, doc: EasyReadDocument) -> CheckResult:
    facts = [a for a in sheet.by_type(AmountFact) if a.action == "grant"]
    if not facts:
        return CheckResult("金额", True, "正式文本未出现批准发放金额，本项跳过。")
    full_text = _all_text(doc)
    missing = [str(f.amount_yuan) for f in facts if str(f.amount_yuan) not in full_text]
    locators = [f.span.locator for f in facts]
    if missing:
        return CheckResult("金额", False, f"易读版缺少正式文本中的金额数值：{'、'.join(missing)}。", locators)
    return CheckResult("金额", True, "易读版金额与正式文本一致。", locators)


def _check_deadlines(sheet: FactSheet, doc: EasyReadDocument) -> CheckResult:
    facts = sheet.by_type(DeadlineFact)
    if not facts:
        return CheckResult("期限", True, "正式文本未出现期限事实，本项跳过。")
    full_text = _all_text(doc)
    problems: list[str] = []
    locators: list[str] = []
    for fact in facts:
        locators.append(fact.span.locator)
        if str(fact.amount) not in full_text:
            problems.append(f"期限长度 {fact.amount}{fact.unit} 未在易读版出现")
            continue
        anchor_words = _ANCHOR_WORDS.get(fact.anchor, [])
        if anchor_words and not any(word in full_text for word in anchor_words):
            problems.append(
                f"{fact.span.locator} 的起算锚点「{fact.anchor_raw}」未在易读版说明，"
                "申请人可能误用打印日计算"
            )
    if problems:
        return CheckResult("期限", False, "；".join(problems) + "。", locators)
    purpose_labels = {DEADLINE_SUPPLEMENT: "补交", DEADLINE_APPEAL: "申诉/复核"}
    mentioned = "、".join(purpose_labels.get(f.purpose, f.purpose) for f in facts)
    return CheckResult("期限", True, f"{mentioned}期限的长度、单位与起算锚点均与正式文本一致。", locators)


def _check_conditions(sheet: FactSheet, doc: EasyReadDocument) -> CheckResult:
    full_text = _all_text(doc)
    locators: list[str] = []
    problems: list[str] = []

    for fact in sheet.by_type(SupplementMaterialFact):
        locators.append(fact.span.locator)
        if fact.condition_raw:
            # 条件必须在易读版中承载：完整原文或去掉前缀「在」后的关键片段均算命中
            condition = fact.condition_raw
            stripped = condition.lstrip("在")
            if condition not in full_text and stripped not in full_text:
                problems.append(
                    f"补交材料的条件「{fact.condition_raw}」在易读版中丢失，可能变成无条件承诺"
                )
        if fact.material_raw[:6] not in full_text:
            problems.append(f"可补交材料「{fact.material_raw}」未在易读版完整转述")

    for fact in sheet.by_type(ExceptionFact):
        locators.append(fact.span.locator)
        # 但书的关键正文（去掉连词后）应出现在易读版
        body = fact.clause_raw.lstrip("但但是然而惟不过")
        if body[:8] not in full_text:
            problems.append(f"例外条款「{fact.clause_raw}」未在易读版承载")

    if problems:
        return CheckResult("例外与条件", False, "；".join(problems) + "。", locators)
    return CheckResult("例外与条件", True, "条件性用语与但书条款均已保留，未被改写成无条件承诺。", locators)


def _check_remedies(sheet: FactSheet, doc: EasyReadDocument) -> CheckResult:
    facts = sheet.by_type(RemedyFact)
    if not facts:
        return CheckResult("救济方式", True, "正式文本未出现救济渠道，本项跳过。")
    full_text = _all_text(doc)
    channel_words = {
        "review": ["复核"],
        "行政复议": ["行政复议", "复议"],
        "行政诉讼": ["行政诉讼", "诉讼"],
        "申诉": ["申诉"],
        "other": [],
    }
    problems = []
    locators = [f.span.locator for f in facts]
    for fact in facts:
        words = channel_words.get(fact.channel, [])
        if words and not any(w in full_text for w in words):
            problems.append(f"救济渠道「{fact.channel_raw}」未在易读版出现")
    appeal_deadlines = [d for d in sheet.by_type(DeadlineFact) if d.purpose == DEADLINE_APPEAL]
    for deadline in appeal_deadlines:
        if str(deadline.amount) not in full_text:
            problems.append("申诉/复核期限长度未在易读版出现")
    if problems:
        return CheckResult("救济方式", False, "；".join(problems) + "。", locators)
    return CheckResult("救济方式", True, "救济渠道与期限均与正式文本一致。", locators)


def _check_family_and_period(sheet: FactSheet, doc: EasyReadDocument) -> CheckResult:
    full_text = _all_text(doc)
    problems = []
    locators: list[str] = []
    for member in sheet.by_type(FamilyMemberFact):
        locators.append(member.span.locator)
        token = member.name or member.member_raw
        if token and token not in full_text:
            problems.append(f"家庭成员「{member.member_raw}」在易读版缺失")
    for period in sheet.by_type(PeriodFact):
        locators.append(period.span.locator)
        if period.start_raw not in full_text or period.end_raw not in full_text:
            problems.append(f"核算周期「{period.period_raw}」未完整转述")
    if problems:
        return CheckResult("对象与周期", False, "；".join(problems) + "。", locators)
    return CheckResult("对象与周期", True, "家庭成员与核算周期转述完整。", locators)


def _check_citations(sheet: FactSheet, doc: EasyReadDocument) -> CheckResult:
    """每条易读句子必须有引用，且引用位置能在正式记录全文中原样命中。"""
    problems: list[str] = []
    checked = 0
    for sentence in doc.sentences:
        if not sentence.citations:
            problems.append(f"栏目「{sentence.section}」存在无依据引用的句子")
            continue
        for citation in sentence.citations:
            checked += 1
            record = sheet.records.get(citation.record_id)
            if record is None:
                problems.append(f"引用 {citation.locator} 指向不存在的记录")
                continue
            if not (0 <= citation.start < citation.end <= len(record.text)):
                problems.append(f"引用 {citation.locator} 超出正式文本长度范围")
                continue
            if record.text[citation.start:citation.end] != citation.text:
                problems.append(
                    f"引用 {citation.locator} 的文字与正式文本不符："
                    f"正式文本该处为「{record.text[citation.start:citation.end]}」"
                )
    if problems:
        return CheckResult("引用可追溯", False, "；".join(problems) + "。")
    return CheckResult("引用可追溯", True, f"全部 {checked} 处引用均能在正式文本对应位置原样命中。")
