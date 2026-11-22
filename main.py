"""中国象棋桌面应用入口。

运行：
    python main.py
"""

from __future__ import annotations

import sys

from xiangqi.client.app import main


if __name__ == "__main__":
    sys.exit(main())
