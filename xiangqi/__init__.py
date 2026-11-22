"""中国象棋（Xiangqi）桌面游戏包。

分层约定：
    xiangqi.shared  纯 Python 规则与数据模型，不依赖 Qt；
    xiangqi.client  PySide6 客户端，只通过会话层访问规则；
    server          FastAPI 联机服务端（账号、排位、资料与好友）。
"""

from __future__ import annotations

__version__ = "0.7.0"

__all__ = ["__version__"]
