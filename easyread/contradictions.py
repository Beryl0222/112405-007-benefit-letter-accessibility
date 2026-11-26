"""更正应用与矛盾检测。

设计原则（对应业务要求）：

1. **更正优先、可追溯**：``correction`` 类型的记录是明确的「以新替旧」
   指令，应用后旧事实被替换，但新事实同时保留原依据位置与更正指令
   位置（``correction_span``），送达快照也留存当时全文。
2. **矛盾不靠流畅度猜定**：凡没有明确更正关系、却在同一维度互相冲突
   的事实（期限长度/单位/起算锚点、明确日期、对象、金额、结论），
   一律生成 :class:`~easyread.model.ContradictionIssue` 并抛出
   :class:`~easyread.errors.ContradictionError`，由经办人处理。
"""

from __future__ import annotations

from dataclasses import replace

from .errors import ContradictionError
from .extract import extract_deadline_from_text
from .model import (
    AmountFact,
    ConclusionFact,
    CONFLICT_AMOUNT,
    CONFLICT_CONCLUSION,
    CONFLICT_DATE,
    CONFLICT_DEADLINE,
    CONFLICT_OBJECT,
    ContradictionIssue,
    CorrectionDirective,
    DateFact,
    DeadlineFact,
    FactSheet,
)

# 行政文书中「送达」与「收到」对申请人而言是同一类实际知悉口径，
# 归为同一锚点组；「打印」是文书制作口径，与前两者冲突时必须上报。
_ANCHOR_ALIASES = {"送达": "送达", "签收": "送达", "收到": "送达"}


def build_effective_sheet(sheet: FactSheet) -> FactSheet:
    """应用全部更正指令，得到「当前有效」事实清单。

    更正指令找不到目标记录、或新值无法解析时，也作为矛盾/问题上报，
    不静默忽略。返回的清单可继续用于矛盾检测与改写。
    """
    issues: list[ContradictionIssue] = []
    for directive in sheet.corrections:
        if directive.target_record_id not in sheet.records:
            issues.append(
                ContradictionIssue(
                    kind=CONFLICT_OBJECT,
                    message=(
                        f"更正记录 {directive.source_record_id} 指向的 "
                        f"{directive.target_record_id} 不存在，无法确定更正对象"
                    ),
                    spans=[directive.target_span, directive.directive_span],
                )
            )
            continue
        if directive.field == "deadline":
            _apply_deadline_correction(sheet, directive, issues)
        elif directive.field == "amount":
            _apply_amount_correction(sheet, directive, issues)
        elif directive.field == "conclusion":
            _apply_conclusion_correction(sheet, directive, issues)
        else:
            issues.append(
                ContradictionIssue(
                    kind=CONFLICT_CONCLUSION,
                    message=(
                        f"更正记录 {directive.source_record_id} 的字段「{directive.field}」"
                        "暂不支持自动应用，需经办人人工改写"
                    ),
                    spans=[directive.directive_span],
                )
            )
    if issues:
        raise ContradictionError(issues)
    return sheet


def detect_contradictions(sheet: FactSheet) -> list[ContradictionIssue]:
    """在（已应用更正的）事实清单上检测互相矛盾的事实。

    检测维度：期限（同用途的长度/单位/锚点）、明确日期、对象、金额、结论。
    已被更正替换的旧事实不再参与比较。
    """
    issues: list[ContradictionIssue] = []
    issues.extend(_detect_deadline_conflicts(sheet))
    issues.extend(_detect_date_conflicts(sheet))
    issues.extend(_detect_object_conflicts(sheet))
    issues.extend(_detect_amount_conflicts(sheet))
    issues.extend(_detect_conclusion_conflicts(sheet))
    return issues


def resolve(sheet: FactSheet) -> FactSheet:
    """便捷入口：应用更正并执行矛盾检测，无矛盾时返回有效清单。

    检测到矛盾时抛出 :class:`ContradictionError`，调用方应把问题交还经办人，
    不得继续生成易读版。
    """
    build_effective_sheet(sheet)
    issues = detect_contradictions(sheet)
    if issues:
        raise ContradictionError(issues)
    return sheet


# ---------------------------------------------------------------- 更正应用


def _apply_deadline_correction(
    sheet: FactSheet, directive: CorrectionDirective, issues: list
) -> None:
    parsed = extract_deadline_from_text(directive.new_value_raw)
    if parsed is None:
        issues.append(
            ContradictionIssue(
                kind=CONFLICT_DEADLINE,
                message=(
                    f"更正记录 {directive.source_record_id} 的新期限「"
                    f"{directive.new_value_raw}」无法解析，需经办人确认"
                ),
                spans=[directive.directive_span],
            )
        )
        return
    new_amount, new_unit = parsed
    old_facts = [
        f
        for f in sheet.by_record(directive.target_record_id)
        if isinstance(f, DeadlineFact)
    ]
    if not old_facts:
        issues.append(
            ContradictionIssue(
                kind=CONFLICT_DEADLINE,
                message=(
                    f"目标记录 {directive.target_record_id} 中没有可更正的期限事实"
                ),
                spans=[directive.directive_span],
            )
        )
        return
    new_facts = [
        replace(
            old,
            amount=new_amount,
            unit=new_unit,
            correction_span=directive.directive_span,
        )
        for old in old_facts
    ]
    sheet.replace_facts(
        directive.target_record_id,
        lambda f: isinstance(f, DeadlineFact),
        new_facts,
    )


def _apply_amount_correction(
    sheet: FactSheet, directive: CorrectionDirective, issues: list
) -> None:
    from .numerals import parse_chinese_number

    match = directive.new_value_raw
    digits = match.replace("人民币", "").replace("元", "").replace(",", "").replace("，", "").strip()
    value = parse_chinese_number(digits) if digits else None
    if value is None:
        issues.append(
            ContradictionIssue(
                kind=CONFLICT_AMOUNT,
                message=f"更正后的金额「{directive.new_value_raw}」无法解析，需经办人确认",
                spans=[directive.directive_span],
            )
        )
        return
    old_facts = [
        f
        for f in sheet.by_record(directive.target_record_id)
        if isinstance(f, AmountFact)
    ]
    if not old_facts:
        issues.append(
            ContradictionIssue(
                kind=CONFLICT_AMOUNT,
                message=f"目标记录 {directive.target_record_id} 中没有可更正的金额事实",
                spans=[directive.directive_span],
            )
        )
        return
    new_facts = [
        replace(
            old,
            amount_yuan=value,
            amount_raw=directive.new_value_raw,
            correction_span=directive.directive_span,
        )
        for old in old_facts
    ]
    sheet.replace_facts(
        directive.target_record_id,
        lambda f: isinstance(f, AmountFact),
        new_facts,
    )


def _apply_conclusion_correction(
    sheet: FactSheet, directive: CorrectionDirective, issues: list
) -> None:
    from .extract import _CONCLUSION_RULES  # 复用结论规则表

    label = None
    for pattern, candidate in _CONCLUSION_RULES:
        if pattern.search(directive.new_value_raw):
            label = candidate
            break
    if label is None:
        issues.append(
            ContradictionIssue(
                kind=CONFLICT_CONCLUSION,
                message=f"更正后的结论「{directive.new_value_raw}」无法识别，需经办人确认",
                spans=[directive.directive_span],
            )
        )
        return
    old_facts = [
        f
        for f in sheet.by_record(directive.target_record_id)
        if isinstance(f, ConclusionFact)
    ]
    if not old_facts:
        issues.append(
            ContradictionIssue(
                kind=CONFLICT_CONCLUSION,
                message=f"目标记录 {directive.target_record_id} 中没有可更正的结论事实",
                spans=[directive.directive_span],
            )
        )
        return
    new_facts = [
        replace(
            old,
            conclusion=label,
            conclusion_raw=directive.new_value_raw,
            correction_span=directive.directive_span,
        )
        for old in old_facts
    ]
    sheet.replace_facts(
        directive.target_record_id,
        lambda f: isinstance(f, ConclusionFact),
        new_facts,
    )


# ---------------------------------------------------------------- 矛盾检测


def _anchor_key(anchor: str) -> str:
    return _ANCHOR_ALIASES.get(anchor, anchor)


def _detect_deadline_conflicts(sheet: FactSheet) -> list[ContradictionIssue]:
    issues: list[ContradictionIssue] = []
    deadlines = sheet.by_type(DeadlineFact)
    # 同用途（补交 / 救济）的期限长度与单位必须一致
    for purpose in ("supplement", "appeal"):
        group = [d for d in deadlines if d.purpose == purpose]
        for i in range(len(group)):
            for j in range(i + 1, len(group)):
                left, right = group[i], group[j]
                if (left.amount, left.unit) != (right.amount, right.unit):
                    issues.append(
                        ContradictionIssue(
                            kind=CONFLICT_DEADLINE,
                            message=(
                                f"同一事项的期限长度不一致："
                                f"「{left.span.text}」与「{right.span.text}」"
                            ),
                            spans=[left.span, right.span],
                        )
                    )
    # 起算锚点口径冲突跨用途检测：决定书若同时出现「送达起算」与「打印起算」，
    # 经办人必须明确申诉/补交期限到底从哪一天起算，工具不得自行选择。
    anchored = [d for d in deadlines if d.anchor not in ("其他",)]
    for i in range(len(anchored)):
        for j in range(i + 1, len(anchored)):
            left, right = anchored[i], anchored[j]
            if _anchor_key(left.anchor) != _anchor_key(right.anchor):
                issues.append(
                    ContradictionIssue(
                        kind=CONFLICT_DEADLINE,
                        message=(
                            "期限起算口径不一致："
                            f"「{left.anchor_raw}」（{left.span.locator}）与"
                            f"「{right.anchor_raw}」（{right.span.locator}），"
                            "不能凭行文习惯选择，需经办人确认统一的起算日"
                        ),
                        spans=[left.span, right.span],
                    )
                )
    return issues


def _detect_date_conflicts(sheet: FactSheet) -> list[ContradictionIssue]:
    """同一语义角色（如两个「打印日期」）出现不同日期即矛盾。

    不同角色（打印日 vs 送达日）各自独立，不算矛盾；未注明角色的日期
    若出现两个以上不同值，也上报请经办人注明含义。
    """
    issues: list[ContradictionIssue] = []
    dates = [d for d in sheet.by_type(DateFact) if d.normalized]
    by_role: dict[str, list] = {}
    for fact in dates:
        by_role.setdefault(fact.role, []).append(fact)
    for role, group in by_role.items():
        distinct = {d.normalized: d for d in group}
        if len(distinct) >= 2:
            ordered = sorted(distinct.values(), key=lambda d: d.normalized)
            role_label = role if role != "未注明" else "未注明含义"
            issues.append(
                ContradictionIssue(
                    kind=CONFLICT_DATE,
                    message=(
                        f"同一语义角色「{role_label}」出现多个不同日期："
                        + "、".join(d.date_raw for d in ordered)
                        + "，不能凭语言流畅度任选其一，需经办人确认正式日期"
                    ),
                    spans=[d.span for d in ordered],
                )
            )
    return issues


def _detect_object_conflicts(sheet: FactSheet) -> list[ContradictionIssue]:
    """对象矛盾：同一角色称谓对应两个不同姓名。

    例如 R4「配偶李萍」与 R6「配偶王梅」没有更正关系，即对象冲突。
    """
    issues: list[ContradictionIssue] = []
    from .model import FamilyMemberFact

    by_role: dict[str, list] = {}
    for member in sheet.by_type(FamilyMemberFact):
        if member.role and member.name:
            by_role.setdefault(member.role, []).append(member)
    for role, members in by_role.items():
        names = {m.name: m for m in members}
        if len(names) >= 2:
            conflicting = list(names.values())
            issues.append(
                ContradictionIssue(
                    kind=CONFLICT_OBJECT,
                    message=(
                        f"同一称谓「{role}」对应不同对象："
                        + "、".join(m.member_raw for m in conflicting)
                        + "，缺少明确更正关系，需经办人确认适格对象"
                    ),
                    spans=[m.span for m in conflicting],
                )
            )
    return issues


def _detect_amount_conflicts(sheet: FactSheet) -> list[ContradictionIssue]:
    issues: list[ContradictionIssue] = []
    amounts = [a for a in sheet.by_type(AmountFact) if a.action == "grant"]
    values = {a.amount_yuan: a for a in amounts}
    if len(values) >= 2:
        conflicting = list(values.values())
        issues.append(
            ContradictionIssue(
                kind=CONFLICT_AMOUNT,
                message=(
                    "批准发放的补助金额出现多个数值："
                    + "、".join(a.amount_raw for a in conflicting)
                    + "，无更正关系，需经办人核定"
                ),
                spans=[a.span for a in conflicting],
            )
        )
    return issues


def _detect_conclusion_conflicts(sheet: FactSheet) -> list[ContradictionIssue]:
    issues: list[ContradictionIssue] = []
    conclusions = sheet.by_type(ConclusionFact)
    labels = {c.conclusion: c for c in conclusions}
    # 批准与拒绝直接对立；待核定与批准/拒绝并存也需人工确认口径
    if "approved" in labels and "rejected" in labels:
        involved = [labels["approved"], labels["rejected"]]
        issues.append(
            ContradictionIssue(
                kind=CONFLICT_CONCLUSION,
                message="资格结论同时出现批准与不予批准，需经办人确认正式结论",
                spans=[c.span for c in involved],
            )
        )
    return issues
