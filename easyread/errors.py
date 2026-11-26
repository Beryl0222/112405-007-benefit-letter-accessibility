"""工具包统一的异常类型。"""

from __future__ import annotations


class EasyReadError(Exception):
    """easyread 所有自定义异常的基类。"""


class ContradictionError(EasyReadError):
    """正式文本之间存在无法自动消解的矛盾，必须交还经办人处理。

    异常会携带 :class:`~easyread.model.ContradictionIssue` 列表；
    工具链在该异常抛出时不得生成或送达易读版，以免靠语言流畅度猜定事实。
    """

    def __init__(self, issues, message: str | None = None) -> None:
        self.issues = list(issues)
        detail = "；".join(str(issue) for issue in self.issues)
        super().__init__(message or f"正式文本存在 {len(self.issues)} 处矛盾，需人工处理：{detail}")
