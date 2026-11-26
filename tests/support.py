"""测试辅助：在 ``python3 -I`` 隔离模式下把仓库根目录加入模块搜索路径。

各测试模块以 ``from support import ...`` 或直接 ``import support`` 开头即可；
``unittest discover -s tests`` 会把 tests 目录本身放入 ``sys.path``。
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
