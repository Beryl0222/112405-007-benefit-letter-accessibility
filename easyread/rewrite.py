"""易读版改写。

改写不是自由生成，而是**受控模板**：每一句易读说明都由已抽取的事实
渲染，且必须携带至少一个正式文本引用位置（``record[start:end]``）。

关键保真规则：

* 「可在十日内补交」必须与「资格尚未核定」同屏出现，避免被误读为已获批；
* 申诉期限必须显式写明**起算锚点**（送达日而非打印日）；
* 家庭成员、核算周期、可补交材料等条件性内容按原文条件渲染，
  条件词（仅当、在……后、但……）一律保留，不把条件改写成无条件承诺；
* 被更正的事实同时标注原依据与更正依据位置。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .model import (
    AmountFact,
    ConclusionFact,
    CONCLUSION_APPROVED,
    CONCLUSION_PENDING,
    CONCLUSION_REJECTED,
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
from .textmodel import Span

_CONCLUSION_TEXT = {
    CONCLUSION_APPROVED: "经审核，您的补助申请已获批准。",
    CONCLUSION_REJECTED: "经审核，您的补助申请未获批准。",
    CONCLUSION_PENDING: "您的补助资格目前还没有最终核定，现在还不能视为已经获批。",
}

# 锚点的申请人友好说法
_ANCHOR_HINT = {
    "送达": "自您收到（送达）本决定书的当天起算，不是按决定书上的打印日期起算。",
    "收到": "自您收到本决定书的当天起算，不是按决定书上的打印日期起算。",
    "打印": "注意：原文写的是自打印之日起算，请先与经办人确认实际送达日期后再计算期限。",
    "签发": "自决定书签发之日起算；如与实际送达日期不一致，请向经办人确认。",
    "决定": "自决定作出之日起算；如与实际送达日期不一致，请向经办人确认。",
    "其他": "原文未写明起算日，请向经办人确认后再计算期限，不要自行推算。",
}


@dataclass(frozen=True)
class RewrittenSentence:
    """一句易读说明及其正式依据。"""

    section: str          # 所属栏目
    text: str             # 易读正文
    citations: list[Span] # 正式依据片段（至少一个）
    note: str = ""        # 必要的风险提示（如起算口径、条件提醒）

    def to_dict(self) -> dict:
        return {
            "section": self.section,
            "text": self.text,
            "note": self.note,
            "citations": [s.to_dict() for s in self.citations],
        }


@dataclass
class EasyReadDocument:
    """一份易读说明的完整内容。"""

    title: str
    sentences: list[RewrittenSentence] = field(default_factory=list)
    reading_guide: str = (
        "阅读提示：本说明只是对正式决定书的通俗解释，所有内容以正式决定书为准；"
        "每句话后面的编号（如 R1[0:12]）是该句在正式文本中的依据位置，可凭此核对。"
    )

    def plain_text(self) -> str:
        """渲染为申请人可读的纯文本。"""
        lines = [self.title, "", self.reading_guide, ""]
        current_section = ""
        for sentence in self.sentences:
            if sentence.section != current_section:
                current_section = sentence.section
                lines.append(f"【{current_section}】")
            locators = "、".join(c.locator for c in sentence.citations)
            lines.append(f"· {sentence.text}（依据：{locators}）")
            if sentence.note:
                lines.append(f"  提示：{sentence.note}")
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "reading_guide": self.reading_guide,
            "sentences": [s.to_dict() for s in self.sentences],
        }


def rewrite_easyread(sheet: FactSheet, title: str = "补助决定书易读说明") -> EasyReadDocument:
    """根据有效事实清单生成易读说明。

    调用前应先通过 :func:`easyread.contradictions.resolve` 完成更正应用
    与矛盾检测；存在未消解矛盾时不应调用本函数。
    """
    doc = EasyReadDocument(title=title)
    doc.sentences.extend(_section_conclusion(sheet))
    doc.sentences.extend(_section_amount(sheet))
    doc.sentences.extend(_section_family(sheet))
    doc.sentences.extend(_section_period(sheet))
    doc.sentences.extend(_section_supplement(sheet))
    doc.sentences.extend(_section_remedy(sheet))
    doc.sentences.extend(_section_exceptions(sheet))
    return doc


# ---------------------------------------------------------------- 各栏目


def _section_conclusion(sheet: FactSheet) -> list[RewrittenSentence]:
    out: list[RewrittenSentence] = []
    for fact in sheet.by_type(ConclusionFact):
        text = _CONCLUSION_TEXT.get(fact.conclusion, f"决定结果：{fact.conclusion_raw}。")
        note = ""
        if fact.conclusion == CONCLUSION_PENDING:
            note = "补交材料只是补正手续，不代表资格已经获批；最终结果以核定通知为准。"
        citations = [fact.span]
        if fact.correction_span:
            citations.append(fact.correction_span)
            note = (note + " " if note else "") + "该结论已经更正记录修改，请同时查看更正依据。"
        out.append(
            RewrittenSentence(section="一、资格结论", text=text, citations=citations, note=note)
        )
    return out


def _section_amount(sheet: FactSheet) -> list[RewrittenSentence]:
    out: list[RewrittenSentence] = []
    for fact in sheet.by_type(AmountFact):
        if fact.action == "grant":
            text = f"本次批准发放的补助金额为人民币 {fact.amount_yuan} 元（{fact.amount_raw}）。"
        else:
            text = f"相关款项处理：{fact.amount_raw}，具体以正式决定书表述为准。"
        citations = [fact.span]
        note = ""
        if fact.correction_span:
            citations.append(fact.correction_span)
            note = "金额已经更正记录修改，请同时查看更正依据。"
        out.append(RewrittenSentence(section="二、补助金额", text=text, citations=citations, note=note))
    return out


def _section_family(sheet: FactSheet) -> list[RewrittenSentence]:
    members = sheet.by_type(FamilyMemberFact)
    if not members:
        return []
    listing = "、".join(_member_label(m) for m in members)
    citations = [m.span for m in members]
    return [
        RewrittenSentence(
            section="三、家庭成员",
            text=f"本决定涉及的家庭成员为：{listing}。仅以上述列明对象为准，未列明人员不随本决定享受相应待遇。",
            citations=citations,
            note="家庭成员范围按正式文本列明内容转述，没有新增或省略对象。",
        )
    ]


def _member_label(member: FamilyMemberFact) -> str:
    # 角色保留称谓原文（如「女儿」），不压缩成单字，避免申请人误读
    if member.role and member.name:
        if member.member_raw.endswith(member.name):
            prefix = member.member_raw[: -len(member.name)]
            if prefix:
                return f"{prefix}{member.name}"
        return f"{member.role}{member.name}"
    return member.member_raw


def _section_period(sheet: FactSheet) -> list[RewrittenSentence]:
    out: list[RewrittenSentence] = []
    for fact in sheet.by_type(PeriodFact):
        out.append(
            RewrittenSentence(
                section="四、核算周期",
                text=f"本次补助的核算周期为 {fact.start_raw} 至 {fact.end_raw}，周期外的情形不在本次核定范围内。",
                citations=[fact.span],
            )
        )
    return out


def _section_supplement(sheet: FactSheet) -> list[RewrittenSentence]:
    out: list[RewrittenSentence] = []
    deadlines = [d for d in sheet.by_type(DeadlineFact) if d.purpose == DEADLINE_SUPPLEMENT]
    materials = sheet.by_type(SupplementMaterialFact)

    for fact in materials:
        if fact.condition_raw:
            condition = fact.condition_raw.lstrip("在")
            text = (
                f"在满足「{condition}」的前提下，您可以补交的材料是：{fact.material_raw}。"
                "这是一项附条件安排，条件未成就时不能直接补交。"
            )
            note = "条件原文已保留，未改写成无条件承诺。"
        else:
            text = f"您可以补交的材料是：{fact.material_raw}。"
            note = ""
        out.append(
            RewrittenSentence(
                section="五、补交材料",
                text=text,
                citations=[fact.span],
                note=note,
            )
        )

    for deadline in deadlines:
        if deadline.correction_span is not None:
            text = (
                f"补交材料的期限已更正为 {deadline.amount}{deadline.unit}内；"
                f"原期限表述见 {deadline.span.locator}，更正依据见 {deadline.correction_span.locator}。"
            )
        else:
            text = (
                f"补交材料的期限是 {deadline.amount}{deadline.unit}内"
                f"（原文：{deadline.span.text}）。"
            )
        note_parts = [_ANCHOR_HINT.get(deadline.anchor, _ANCHOR_HINT["其他"])]
        # 与待核定结论联动，防止误读为已获批
        pending = any(c.conclusion == CONCLUSION_PENDING for c in sheet.by_type(ConclusionFact))
        if pending:
            note_parts.append("允许补交不等于资格已经获批，逾期未补交可能按现有材料处理。")
        citations = [deadline.span]
        if deadline.correction_span:
            citations.append(deadline.correction_span)
            note_parts.append("该期限已经更正记录修改，本句反映的是更正后的新期限。")
        out.append(
            RewrittenSentence(
                section="五、补交材料",
                text=text,
                citations=citations,
                note=" ".join(note_parts),
            )
        )
    return out


def _section_remedy(sheet: FactSheet) -> list[RewrittenSentence]:
    out: list[RewrittenSentence] = []
    appeal_deadlines = [d for d in sheet.by_type(DeadlineFact) if d.purpose == DEADLINE_APPEAL]
    seen_channels: set[str] = set()
    for remedy in sheet.by_type(RemedyFact):
        if remedy.channel in seen_channels:
            continue
        seen_channels.add(remedy.channel)
        channel_text = {
            "review": "申请复核",
            "行政复议": "申请行政复议",
            "行政诉讼": "提起行政诉讼",
            "申诉": "提出申诉",
        }.get(remedy.channel, remedy.channel_raw)
        if appeal_deadlines:
            deadline = appeal_deadlines[0]
            if deadline.correction_span is not None:
                text = (
                    f"如果您对本决定有异议，可以{channel_text}；"
                    f"申请期限已更正为 {deadline.amount}{deadline.unit}内"
                    f"（原表述见 {deadline.span.locator}，更正依据见 {deadline.correction_span.locator}）。"
                )
            else:
                text = (
                    f"如果您对本决定有异议，可以{channel_text}；"
                    f"申请期限为 {deadline.amount}{deadline.unit}内（原文：{deadline.span.text}）。"
                )
            note = _ANCHOR_HINT.get(deadline.anchor, _ANCHOR_HINT["其他"])
            citations = [remedy.span, deadline.span]
            if deadline.correction_span:
                citations.append(deadline.correction_span)
                note += " 该期限已经更正记录修改。"
        else:
            text = f"如果您对本决定有异议，可以{channel_text}，具体期限以正式决定书载明为准。"
            note = "原文未在同条写明期限，请核对正式决定书后告知申请人。"
            citations = [remedy.span]
        out.append(
            RewrittenSentence(
                section="六、异议与救济",
                text=text,
                citations=citations,
                note=note,
            )
        )
    return out


def _section_exceptions(sheet: FactSheet) -> list[RewrittenSentence]:
    out: list[RewrittenSentence] = []
    for fact in sheet.by_type(ExceptionFact):
        out.append(
            RewrittenSentence(
                section="七、例外与限制",
                text=f"请注意正式决定中的例外规定：{fact.clause_raw}。该限制持续有效，不因本说明的通俗表述而改变。",
                citations=[fact.span],
                note="但书条款按原文保留，未作弱化处理。",
            )
        )
    return out
