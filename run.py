#!/usr/bin/env python3
"""隔离模式（python3 -I）下的命令行启动器。

``-I`` 会忽略当前目录与 PYTHONPATH，因此这里显式把仓库根目录加入
``sys.path`` 后再调用包内 CLI。用法与 ``python -m easyread.cli`` 相同：

    python3 -I run.py rewrite data/decision_sample.json
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from easyread.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
