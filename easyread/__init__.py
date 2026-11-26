"""易读改写与权利保真工具包（easyread）。

面向社区服务机构补助决定书的可复用中文 NLP 能力：

* :mod:`easyread.textmodel` —— 切句与带字符位置的文本片段；
* :mod:`easyread.extract`    —— 从正式文本中抽取资格、金额、期限等事实；
* :mod:`easyread.contradictions` —— 更正应用与互相矛盾内容的识别；
* :mod:`easyread.rewrite`    —— 带正式依据引用的易读版改写；
* :mod:`easyread.verify`     —— 五维度一致性核对；
* :mod:`easyread.store`      —— 草稿/送达版本的留存与更正流转。

本包只使用 Python 标准库，可在离线环境运行。所有演练文本均为合成资料。
"""

from .errors import ContradictionError, EasyReadError

__all__ = ["EasyReadError", "ContradictionError", "__version__"]

__version__ = "0.1.0"
