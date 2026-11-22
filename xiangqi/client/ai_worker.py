"""AI 后台线程。

主线程把不可变棋盘快照、执子方、难度与取消标记交给 QThread；搜索完成后
通过信号把结果排队回主线程。悔棋/重开/关窗时调用 :meth:`AIWorker.cancel`
让搜索尽快退出，会话层再用 request_id 丢弃过期结果。
"""

from __future__ import annotations

from threading import Event
from typing import Optional

from PySide6.QtCore import QThread, Signal

from xiangqi.client.ai_engine import (
    AIDifficulty,
    search_best_move,
)
from xiangqi.shared.rules import Board, Side


class AIWorker(QThread):
    """一次性 AI 搜索线程。"""

    #: request_id, from_row, from_col, to_row, to_col
    move_ready = Signal(int, int, int, int, int)
    #: request_id, 错误信息
    search_failed = Signal(int, str)

    def __init__(
        self,
        request_id: int,
        board_snapshot: Board,
        side: Side,
        difficulty: AIDifficulty,
        cancel_event: Optional[Event] = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.request_id = request_id
        self._board = board_snapshot
        self._side = side
        self._difficulty = difficulty
        self._cancel_event = cancel_event or Event()

    def cancel(self) -> None:
        """请求搜索尽快停止。"""
        self._cancel_event.set()

    def run(self) -> None:  # noqa: N802 - Qt 接口
        try:
            result = search_best_move(
                self._board,
                self._side,
                self._difficulty,
                self._cancel_event,
            )
        except Exception as exc:  # 搜索失败不应让线程崩溃
            if not self._cancel_event.is_set():
                self.search_failed.emit(
                    self.request_id,
                    f"{type(exc).__name__}: {exc}",
                )
            return

        if self._cancel_event.is_set():
            return
        move = result.move
        if move is None:
            self.search_failed.emit(self.request_id, "没有可用的合法着法")
            return
        self.move_ready.emit(
            self.request_id,
            move.from_row,
            move.from_col,
            move.to_row,
            move.to_col,
        )


__all__ = ["AIWorker"]
