"""对局会话实现导出。"""

from __future__ import annotations

from xiangqi.client.sessions.ai import AIGameSession
from xiangqi.client.sessions.base import GameSession
from xiangqi.client.sessions.local import LocalGameSession
from xiangqi.client.sessions.online import OnlineGameSession
from xiangqi.client.sessions.puzzle import PuzzleSession

__all__ = [
    "GameSession",
    "LocalGameSession",
    "AIGameSession",
    "OnlineGameSession",
    "PuzzleSession",
]
