"""残局挑战会话占位。

后续版本在 GameModel.from_setup 之上加载残局摆子、限制步数、接入防守方
AI，并在成功/失败时发出独立信号。
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QObject

from xiangqi.client.board_view import BoardView
from xiangqi.client.sessions.base import GameSession
from xiangqi.shared.game_model import GameModel
from xiangqi.shared.puzzle import Puzzle


class PuzzleSession(GameSession):
    """残局会话占位；只展示初始棋盘。"""

    def __init__(
        self,
        puzzle: Optional[Puzzle] = None,
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self.puzzle = puzzle
        self._model = GameModel.initial()

    @property
    def view(self) -> BoardView:
        return BoardView.from_model(self._model)

    @property
    def model(self) -> GameModel:
        return self._model

    @property
    def accepts_human_input(self) -> bool:
        return False

    @property
    def can_undo(self) -> bool:
        return False

    def shutdown(self) -> None:
        return None


__all__ = ["PuzzleSession"]
