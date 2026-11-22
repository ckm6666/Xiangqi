"""本地双人对局会话。"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QObject

from xiangqi.client.board_view import BoardView
from xiangqi.client.sessions.base import GameSession
from xiangqi.shared.game_model import GameModel
from xiangqi.shared.rules import Move


class LocalGameSession(GameSession):
    """两名玩家共用一块棋盘的本地会话。

    规则裁决全部交给 :class:`~xiangqi.shared.game_model.GameModel`；本类
    只负责人类输入能力、暂停状态与信号派发。
    """

    def __init__(
        self,
        model: Optional[GameModel] = None,
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self._model = model if model is not None else GameModel.initial()
        self._paused = False

    # ------------------------------------------------------------------
    # 只读状态
    # ------------------------------------------------------------------
    @property
    def view(self) -> BoardView:
        return BoardView.from_model(self._model)

    @property
    def model(self) -> GameModel:
        return self._model

    @property
    def accepts_human_input(self) -> bool:
        return not self._paused and not self._model.is_game_over

    @property
    def can_undo(self) -> bool:
        return self._model.move_count > 0

    @property
    def move_history(self) -> tuple[Move, ...]:
        return self._model.moves

    # ------------------------------------------------------------------
    # 意图
    # ------------------------------------------------------------------
    def legal_moves_from(self, row: int, col: int) -> tuple[Move, ...]:
        if not self.accepts_human_input:
            return ()
        board = self._model.board
        if not (0 <= row < len(board) and 0 <= col < len(board[row])):
            return ()
        piece = board[row][col]
        if piece is None or piece.side is not self._model.side_to_move:
            return ()
        return self._model.legal_moves_from(row, col)

    def request_move(
        self,
        from_row: int,
        from_col: int,
        to_row: int,
        to_col: int,
    ) -> bool:
        if not self.accepts_human_input:
            return False
        move = self._model.apply_move(from_row, from_col, to_row, to_col)
        if move is None:
            return False

        self.state_changed.emit()
        self.move_made.emit()
        if self._model.is_game_over:
            self.game_over.emit()
        return True

    def request_undo(self) -> bool:
        if self._paused:
            return False
        if not self._model.undo():
            return False
        self.state_changed.emit()
        return True

    def request_restart(self) -> bool:
        self._model.reset()
        self._paused = False
        self.state_changed.emit()
        return True

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------
    def pause(self) -> None:
        if not self._paused:
            self._paused = True
            self.state_changed.emit()

    def resume(self) -> None:
        if self._paused:
            self._paused = False
            self.state_changed.emit()

    def shutdown(self) -> None:
        return None


__all__ = ["LocalGameSession"]
