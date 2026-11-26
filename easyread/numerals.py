"""中文数量词解析（标准库实现，无第三方依赖）。

决定书里的期限常写作「十个工作日」「三十日」「十五个工作日」，
金额常写作「壹仟贰佰元」「人民币1200元」。本模块把它们统一成
机器可比较的整数，同时保留原文供引用展示。
"""

from __future__ import annotations

# 小写中文数字
_DIGITS = {
    "零": 0,
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
}
# 大写（财务）中文数字
_BIG_DIGITS = {
    "壹": 1,
    "贰": 2,
    "叁": 3,
    "肆": 4,
    "伍": 5,
    "陆": 6,
    "柒": 7,
    "捌": 8,
    "玖": 9,
}
_SMALL_UNITS = {"十": 10, "百": 100, "千": 1000}
_BIG_UNITS = {"拾": 10, "佰": 100, "仟": 1000, "万": 10000, "亿": 100000000}


def parse_chinese_number(text: str) -> int | None:
    """把中文数字字符串解析为整数；无法解析时返回 ``None``。

    支持的写法示例：

    >>> parse_chinese_number("十")
    10
    >>> parse_chinese_number("十五")
    15
    >>> parse_chinese_number("三十")
    30
    >>> parse_chinese_number("壹仟贰佰")
    1200
    >>> parse_chinese_number("12")
    12
    """
    text = text.strip()
    if not text:
        return None
    if text.isdigit():
        return int(text)

    digits = {**_DIGITS, **_BIG_DIGITS}
    units = {**_SMALL_UNITS, **_BIG_UNITS}

    total = 0          # 已累计的部分
    section = 0        # 当前「万/亿」节内的数值
    current = 0        # 当前数字位
    matched = False

    for char in text:
        if char in digits:
            current = digits[char]
            matched = True
        elif char in units:
            unit = units[char]
            if unit >= 10000:
                # 万、亿：先结算当前节，再并入总量
                section += current
                total += (section if section else 1) * unit
                section = 0
            else:
                # 十、百、千（含大写拾佰仟）
                section += (current if current else 1) * unit
            current = 0
            matched = True
        else:
            return None

    return total + section + current if matched else None
