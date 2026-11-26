"""事实抽取：把决定书正式文本解析为带字符位置的结构化事实。

采用「规则优先、位置保留」的中文 NLP 策略：

* 所有模式均基于正则与中文数量词解析（:mod:`easyread.numerals`），
  离线可用、结果可解释，不依赖模型猜测；
* 每个事实都记录其在来源记录全文中的字符区间，供改写引用与核对；
* 更正记录（``kind == "correction"``）解析为
  :class:`~easyread.model.CorrectionDirective`，由
  :mod:`easyread.contradictions` 负责应用与矛盾判定，本模块不擅自改写事实。
"""

from __future__ import annotations

import re

from .model import (
    AmountFact,
    ConclusionFact,
    CONCLUSION_APPROVED,
    CONCLUSION_PENDING,
    CONCLUSION_REJECTED,
    CorrectionDirective,
    DateFact,
    DeadlineFact,
    DEADLINE_APPEAL,
    DEADLINE_OTHER,
    DEADLINE_SUPPLEMENT,
    ExceptionFact,
    Fact,
    FactSheet,
    FamilyMemberFact,
    PeriodFact,
    RemedyFact,
    SupplementMaterialFact,
)
from .numerals import parse_chinese_number
from .textmodel import SourceRecord, Span, make_span, split_sentences

# ---------------------------------------------------------------- 基础模式

# 中文或阿拉伯数字串（长度上限防止误吞整句）
_NUM = r"[0-9]+|[零一二两三四五六七八九十百千万亿壹贰叁肆伍陆柒捌玖拾佰仟]{1,8}"
# 期限单位
_UNIT = r"个工作日|工作日|日|天"
# 起算锚点
_ANCHOR = r"(送达之日|收到之日|签收之日|打印之日|签发之日|决定之日|作出之日|送达|收到|签收|打印|签发)"
# 明确日期
_DATE_RE = re.compile(r"(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日")
# 期限：锚点 + 数字 + 单位
_DEADLINE_RE = re.compile(
    rf"(?:自)?{_ANCHOR}?[^。；;！!？?\n]{{0,12}}?({_NUM})\s*({_UNIT})"
)
# 金额：人民币/币种 + 数字（阿拉伯或中文大写）+ 元
_AMOUNT_RE = re.compile(
    r"(?:人民币)?\s*((?:[0-9][0-9,，]*\.?\d*)|(?:[零壹贰叁肆伍陆柒捌玖拾佰仟亿]{1,12}))\s*元"
)
# 核算周期
_PERIOD_RE = re.compile(
    r"核算周期[^。；;！!？?\n]{0,6}?"
    r"(\d{4}\s*年\s*\d{1,2}\s*月)\s*(?:至|到|—|-|~|～)\s*"
    r"(\d{4}\s*年\s*\d{1,2}\s*月)"
)
# 家庭成员枚举（枚举内容在逗号/句号处结束，避免吞掉后续分句）
_FAMILY_ENUM_RE = re.compile(r"家庭成员(?:包括|有|为)([^。；;！!？?\n，,]+)")
# 角色+姓名：长称谓必须排在短称谓之前，否则「女儿」会被「女」抢先匹配
_FAMILY_PAIR_RE = re.compile(
    r"(配偶|父亲|母亲|外祖父|外祖母|祖父|祖母|孙子|孙女|儿子|女儿|兄|弟|姐|妹|子|女)([一-龥]{2,4})"
)
# 可补交材料：要求出现「材料」清单提示，避免「补交不表示资格已核定」误匹配
_SUPPLEMENT_RE = re.compile(
    r"可?补交(?:的)?材料(?:包括|为|是|有)?[：:]?\s*([^。；;！!？?\n，,]{2,40})"
)
# 救济渠道：要求真实的救济句式，排除「申诉期限自…起算」这类提醒句
_REMEDY_RE = re.compile(
    r"(?:可)?(申请复核|申请行政复议|提起行政诉讼|提出申诉|行政复议|行政诉讼|申请复核|复核|复议|申诉)(?!期限)"
)
# 例外/但书
_EXCEPTION_RE = re.compile(r"(?:但|但是|然而|惟|不过)([^。；;！!？?\n]+)")
# 更正指令
_CORRECTION_RE = re.compile(
    r"更正[：:]\s*([A-Za-z0-9一-龥\-_]+)\s*的\s*([^为]+?)\s*为\s*([^，,。；;]+)"
)

# 结论关键词（按优先级排列，先具体后宽泛）
_CONCLUSION_RULES = [
    (re.compile(r"不予(?:补助|批准|受理|发放|核定)"), CONCLUSION_REJECTED),
    (re.compile(r"(?:补助|申请|资格)未?获?批准|驳回"), CONCLUSION_REJECTED),
    (re.compile(r"予以(?:补助|批准|发放|核定)|同意(?:补助|发放|批准)|批准享受"), CONCLUSION_APPROVED),
    (re.compile(r"资格尚未?核定|待核定|补交不表示资格已核定|未完成核定"), CONCLUSION_PENDING),
]

# 锚点归一化
_ANCHOR_NORMALIZE = {
    "送达": "送达",
    "送达之日": "送达",
    "签收": "送达",
    "签收之日": "送达",
    "收到": "收到",
    "收到之日": "收到",
    "打印": "打印",
    "打印之日": "打印",
    "签发": "签发",
    "签发之日": "签发",
    "决定": "决定",
    "决定之日": "决定",
    "作出": "决定",
    "作出之日": "决定",
}

_ROLE_NORMALIZE = {
    "儿子": "子",
    "女儿": "女",
    "祖父": "祖父",
    "祖母": "祖母",
    "外祖父": "外祖父",
    "外祖母": "外祖母",
    "孙子": "孙",
    "孙女": "孙",
}

_REMEDY_CHANNEL = {
    "申请复核": "review",
    "复核": "review",
    "行政复议": "行政复议",
    "复议": "行政复议",
    "行政诉讼": "行政诉讼",
    "提起诉讼": "行政诉讼",
    "申诉": "申诉",
}


# ---------------------------------------------------------------- 公开入口


def extract_facts(records: list[SourceRecord]) -> FactSheet:
    """对全部来源记录执行抽取，返回 :class:`FactSheet`。

    更正记录只解析指令，不抽取普通事实；普通记录逐句抽取，
    同一句中的期限与救济渠道会建立关联，便于核对申诉期限。
    """
    sheet = FactSheet(records={r.record_id: r for r in records})
    for record in records:
        if record.kind == "correction":
            sheet.corrections.extend(_extract_corrections(record))
            continue
        for sentence in split_sentences(record):
            _extract_sentence(record, sentence.text, sentence.start, sheet)
    return sheet


# ---------------------------------------------------------------- 逐句抽取


def _extract_sentence(record: SourceRecord, text: str, base_offset: int, sheet: FactSheet) -> None:
    _extract_deadlines(record, text, base_offset, sheet)
    _extract_amounts(record, text, base_offset, sheet)
    _extract_conclusions(record, text, base_offset, sheet)
    _extract_family(record, text, base_offset, sheet)
    _extract_periods(record, text, base_offset, sheet)
    _extract_supplement(record, text, base_offset, sheet)
    _extract_remedies(record, text, base_offset, sheet)
    _extract_exceptions(record, text, base_offset, sheet)
    _extract_dates(record, text, base_offset, sheet)


def _shift_span(record: SourceRecord, match: re.Match, base: int, group=0) -> Span:
    span = make_span(record, match, group)
    return Span(span.record_id, span.start + base, span.end + base, span.text)


def _extract_deadlines(record: SourceRecord, text: str, base: int, sheet: FactSheet) -> None:
    # 先定位「数字+单位」，再向前回看一个窗口找起算锚点；
    # 这样即使锚点写作「自送达之日起……十个工作日」也不会因可选分组而丢失。
    # 负向后顾排除「2026年11月3日」这类明确日期中的「3日」。
    core = re.compile(rf"(?<!\d)(?<!年)(?<!月)({_NUM})\s*({_UNIT})")
    for match in core.finditer(text):
        number = parse_chinese_number(match.group(1))
        if number is None:
            continue
        window = text[max(0, match.start() - 12):match.start()]
        anchor_match = None
        for candidate in re.finditer(_ANCHOR, window):
            anchor_match = candidate  # 取离期限最近的锚点
        if anchor_match:
            anchor_raw = anchor_match.group(0)
            span_start = max(0, match.start() - 12) + anchor_match.start()
        else:
            anchor_raw = ""
            span_start = match.start()
        anchor = _ANCHOR_NORMALIZE.get(anchor_raw, "其他")
        unit = match.group(2)
        unit_norm = "工作日" if "工作日" in unit else "日"
        # 用途按期限前后窗口内的邻近关键词判定，避免同句其他词串扰
        purpose_window = text[max(0, match.start() - 8):min(len(text), match.end() + 8)]
        purpose = DEADLINE_OTHER
        if re.search(r"补交|补充(?:材料|证明)", purpose_window):
            purpose = DEADLINE_SUPPLEMENT
        elif re.search(r"复核|复议|诉讼|申诉|异议", purpose_window):
            purpose = DEADLINE_APPEAL
        span = Span(
            record.record_id,
            base + span_start,
            base + match.end(),
            text[span_start:match.end()],
        )
        sheet.add(
            DeadlineFact(
                span=span,
                amount=number,
                unit=unit_norm,
                anchor=anchor,
                anchor_raw=anchor_raw or "（原文未写明起算日）",
                purpose=purpose,
            )
        )


def _extract_amounts(record: SourceRecord, text: str, base: int, sheet: FactSheet) -> None:
    for match in _AMOUNT_RE.finditer(text):
        raw = match.group(1)
        normalized = raw.replace(",", "").replace("，", "")
        amount: int | None
        if normalized.isdigit():
            amount = int(normalized)
        else:
            amount = parse_chinese_number(normalized)
        if amount is None:
            continue
        action = "reject" if re.search(r"不予|停止|取消|追回", text) else "grant"
        sheet.add(
            AmountFact(
                span=_shift_span(record, match, base),
                amount_yuan=amount,
                amount_raw=match.group(0).strip(),
                action=action,
            )
        )


def _extract_conclusions(record: SourceRecord, text: str, base: int, sheet: FactSheet) -> None:
    for pattern, label in _CONCLUSION_RULES:
        match = pattern.search(text)
        if match:
            sheet.add(
                ConclusionFact(
                    span=_shift_span(record, match, base),
                    conclusion=label,
                    conclusion_raw=match.group(0),
                )
            )
            return  # 一句话只取一个结论（最具体的规则优先）


def _extract_family(record: SourceRecord, text: str, base: int, sheet: FactSheet) -> None:
    enum_match = _FAMILY_ENUM_RE.search(text)
    if enum_match:
        enum_span = _shift_span(record, enum_match, base, group=1)
        for item in re.split(r"[、,，；;和及\s]+", enum_match.group(1)):
            item = item.strip()
            if not item:
                continue
            role, name = _split_role_name(item)
            if not role:
                # 枚举尾巴上的非成员表述（如「仅上述列明对象……」）不视作家庭成员
                continue
            item_start = record.text.find(item, enum_span.start)
            span = Span(
                record.record_id,
                item_start if item_start >= 0 else enum_span.start,
                (item_start + len(item)) if item_start >= 0 else enum_span.end,
                item,
            )
            sheet.add(FamilyMemberFact(span=span, member_raw=item, role=role, name=name))
        return
    # 非枚举句中的角色+姓名（如「配偶李萍符合连带申报条件」）
    for match in _FAMILY_PAIR_RE.finditer(text):
        role_raw = match.group(1)
        name = match.group(2)
        sheet.add(
            FamilyMemberFact(
                span=_shift_span(record, match, base),
                member_raw=match.group(0),
                role=_ROLE_NORMALIZE.get(role_raw, role_raw),
                name=name,
            )
        )


def _split_role_name(item: str) -> tuple[str, str]:
    match = _FAMILY_PAIR_RE.match(item)
    if match:
        role_raw = match.group(1)
        return _ROLE_NORMALIZE.get(role_raw, role_raw), match.group(2)
    # 纯姓名等情况：角色留空，保留原文
    return "", item


def _extract_periods(record: SourceRecord, text: str, base: int, sheet: FactSheet) -> None:
    for match in _PERIOD_RE.finditer(text):
        sheet.add(
            PeriodFact(
                span=_shift_span(record, match, base),
                period_raw=match.group(0),
                start_raw=match.group(1).replace(" ", ""),
                end_raw=match.group(2).replace(" ", ""),
            )
        )


def _extract_supplement(record: SourceRecord, text: str, base: int, sheet: FactSheet) -> None:
    for match in _SUPPLEMENT_RE.finditer(text):
        material = match.group(1).strip()
        # 识别前缀条件，如「在公示无异议后可补交…」
        condition = ""
        cond_match = re.search(r"(在[^，,。；;]{2,20}?(?:后|之内|之内时))[，,]?\s*可?补交", text)
        if cond_match:
            condition = cond_match.group(1)
        sheet.add(
            SupplementMaterialFact(
                span=_shift_span(record, match, base),
                material_raw=material,
                condition_raw=condition,
            )
        )


def _extract_remedies(record: SourceRecord, text: str, base: int, sheet: FactSheet) -> None:
    seen_records: set[str] = set()
    for match in _REMEDY_RE.finditer(text):
        channel_raw = match.group(1)
        # 排除但书/说明语境中的词，如「但复核期间不停止执行」里的「复核」并非救济渠道
        following = text[match.end():match.end() + 2]
        if following.startswith(("期间", "的", "期", "程序")):
            continue
        # 同一句中「申请复核」已包含「复核」，按归一化渠道去重，保留更长的原表述
        channel = _REMEDY_CHANNEL.get(channel_raw, "other")
        if channel in seen_records:
            continue
        seen_records.add(channel)
        # 同句中的期限片段与救济渠道关联
        deadline_span: Span | None = None
        dl_match = _DEADLINE_RE.search(text)
        if dl_match:
            deadline_span = _shift_span(record, dl_match, base)
        sheet.add(
            RemedyFact(
                span=_shift_span(record, match, base),
                channel=channel,
                channel_raw=channel_raw,
                deadline_span=deadline_span,
            )
        )


def _extract_exceptions(record: SourceRecord, text: str, base: int, sheet: FactSheet) -> None:
    for match in _EXCEPTION_RE.finditer(text):
        sheet.add(
            ExceptionFact(
                span=_shift_span(record, match, base),
                clause_raw=match.group(0),
            )
        )


def _extract_dates(record: SourceRecord, text: str, base: int, sheet: FactSheet) -> None:
    for match in _DATE_RE.finditer(text):
        year, month, day = (int(part) for part in match.groups())
        normalized = f"{year:04d}-{month:02d}-{day:02d}"
        # 向前回看 10 个字符，识别日期的语义角色（打印日/送达日/决定日）
        lookbehind = text[max(0, match.start() - 10):match.start()]
        role = "未注明"
        for keyword, label in (
            ("打印", "打印"),
            ("送达", "送达"),
            ("签收", "送达"),
            ("收到", "送达"),
            ("决定", "决定"),
            ("作出", "决定"),
            ("签发", "签发"),
        ):
            if keyword in lookbehind:
                role = label
                break
        sheet.add(
            DateFact(
                span=_shift_span(record, match, base),
                date_raw=match.group(0).replace(" ", ""),
                normalized=normalized,
                role=role,
            )
        )


# ---------------------------------------------------------------- 更正指令


def _extract_corrections(record: SourceRecord) -> list[CorrectionDirective]:
    directives: list[CorrectionDirective] = []
    for match in _CORRECTION_RE.finditer(record.text):
        field_raw = match.group(2).strip()
        if "期限" in field_raw or "工作日" in field_raw or "日" in field_raw:
            field = "deadline"
        elif "金额" in field_raw or "补助" in field_raw:
            field = "amount"
        elif "结论" in field_raw or "资格" in field_raw:
            field = "conclusion"
        else:
            field = "other"
        directives.append(
            CorrectionDirective(
                source_record_id=record.record_id,
                target_record_id=match.group(1).strip(),
                field=field,
                new_value_raw=match.group(3).strip(),
                directive_span=Span(record.record_id, match.start(), match.end(), match.group(0)),
                target_span=Span(
                    record.record_id,
                    match.start(1),
                    match.end(1),
                    match.group(1),
                ),
            )
        )
    return directives


def extract_deadline_from_text(value_raw: str) -> tuple[int, str] | None:
    """从更正新值（如 ``十五个工作日``）中解析期限长度与归一化单位。"""
    match = re.search(rf"({_NUM})\s*({_UNIT})", value_raw)
    if not match:
        return None
    number = parse_chinese_number(match.group(1))
    if number is None:
        return None
    unit = "工作日" if "工作日" in match.group(2) else "日"
    return number, unit
