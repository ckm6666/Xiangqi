"""人机对局会话。

人类与 AI 共用同一个 :class:`GameModel`；AI 搜索在 :class:`AIWorker`
线程中完成，结果通过 request_id 过滤后应用到主线程。悔棋、重开、暂停与
关窗都会使旧搜索结果失效，避免棋盘状态被过期结果污染。
"""

from __future__ import annotations

import logging
from threading import Event
from typing import Callable, Optional

from PySide6.QtCore import QObject, QTimer

from xiangqi.client.ai_engine import AIDifficulty
from xiangqi.client.ai_worker import AIWorker
from xiangqi.client.board_view import BoardView
from xiangqi.client.sessions.base import GameSession
from xiangqi.shared.game_model import GameModel
from xiangqi.shared.rules import Move, Side

logger = logging.getLogger(__name__)

WorkerFactory = Callable[
    [int, object, Side, AIDifficulty, Event],
    object,
]


class AIGameSession(GameSession):
    """玩家 vs 本地 AI。"""

    def __init__(
        self,
        model: Optional[GameModel] = None,
        human_side: Side = Side.RED,
        difficulty: AIDifficulty = AIDifficulty.MEDIUM,
        parent: Optional[QObject] = None,
        *,
        worker_factory: Optional[WorkerFactory] = None,
        ai_start_delay_ms: int = 0,
    ) -> None:
        super().__init__(parent)
        self._model = model if model is not None else GameModel.initial()
        self._human_side = human_side
        self._ai_side = human_side.opponent
        self._difficulty = difficulty
        self._worker_factory = worker_factory or AIWorker
        self._ai_start_delay_ms = max(0, int(ai_start_delay_ms))

        self._ai_thread: Optional[object] = None
        self._cancel_event: Optional[Event] = None
        self._request_id = 0
        self._paused = False
        self._shutdown = False
        self._pending_start = False
        self._pending_ai_move: Optional[tuple[int, int, int, int]] = None

        # 人落子后先播放完棋盘动画再启动搜索，避免搜索线程抢占 GIL
        # 导致落子看起来是瞬移。
        self._ai_start_timer = QTimer(self)
        self._ai_start_timer.setSingleShot(True)
        self._ai_start_timer.timeout.connect(self._maybe_start_ai)

        # AI 先手时等主窗口完成信号连接后再开始思考。
        if (
            not self._model.is_game_over
            and self._model.side_to_move is self._ai_side
        ):
            self._schedule_ai_start(0)

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
    def human_side(self) -> Side:
        return self._human_side

    @property
    def ai_side(self) -> Side:
        return self._ai_side

    @property
    def difficulty(self) -> AIDifficulty:
        return self._difficulty

    @property
    def busy(self) -> bool:
        # AI 回合且搜索已排队/正在执行为“思考中”；落子动画期间也保持
        # 忙碌状态，但真正的搜索线程会等动画结束后才启动。
        thinking = (
            self._ai_thread is not None
            or self._ai_start_timer.isActive()
        )
        return (
            thinking
            and not self._model.is_game_over
            and self._model.side_to_move is self._ai_side
        )

    @property
    def accepts_human_input(self) -> bool:
        return (
            not self._paused
            and not self._shutdown
            and not self._model.is_game_over
            and self._model.side_to_move is self._human_side
            and not self.busy
        )

    @property
    def can_undo(self) -> bool:
        return self._model.move_count > 0

    @property
    def move_history(self) -> tuple[Move, ...]:
        return self._model.moves

    # ------------------------------------------------------------------
    # 人类操作
    # ------------------------------------------------------------------
    def legal_moves_from(self, row: int, col: int) -> tuple[Move, ...]:
        if not self.accepts_human_input:
            return ()
        board = self._model.board
        if not (0 <= row < len(board) and 0 <= col < len(board[row])):
            return ()
        piece = board[row][col]
        if piece is None or piece.side is not self._human_side:
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
        else:
            self._schedule_ai_start()
        return True

    def request_undo(self) -> bool:
        if self._shutdown or self._model.move_count == 0:
            return False

        # 先让任何进行中的搜索失效，再撤到人类回合。
        self._cancel_ai()
        self._pending_ai_move = None
        if not self._model.undo():
            return False
        while (
            self._model.move_count > 0
            and self._model.side_to_move is not self._human_side
        ):
            if not self._model.undo():
                break
        self.state_changed.emit()
        return True

    def request_restart(self) -> bool:
        self._cancel_ai()
        self._pending_ai_move = None
        self._paused = False
        self._model.reset()
        self.state_changed.emit()
        self._schedule_ai_start(0)
        return True

    def set_difficulty(self, difficulty: AIDifficulty) -> None:
        if difficulty is self._difficulty:
            return
        self._difficulty = difficulty
        self.state_changed.emit()

    # ------------------------------------------------------------------
    # 暂停/恢复/关闭
    # ------------------------------------------------------------------
    def pause(self) -> None:
        if self._shutdown or self._paused:
            return
        self._paused = True
        self._ai_start_timer.stop()
        self.state_changed.emit()

    def resume(self) -> None:
        if self._shutdown or not self._paused:
            return
        self._paused = False
        if self._pending_ai_move is not None:
            pending = self._pending_ai_move
            self._pending_ai_move = None
            self._apply_ai_move(*pending)
        else:
            self._schedule_ai_start()
        self.state_changed.emit()

    def shutdown(self) -> None:
        self._shutdown = True
        self._paused = True
        self._pending_ai_move = None
        self._cancel_ai()
        thread = self._ai_thread
        if thread is not None:
            waiter = getattr(thread, "wait", None)
            if callable(waiter):
                try:
                    if not waiter(2000):
                        terminator = getattr(thread, "terminate", None)
                        if callable(terminator):
                            terminator()
                            waiter(500)
                except RuntimeError:
                    pass
            deleter = getattr(thread, "deleteLater", None)
            if callable(deleter):
                try:
                    deleter()
                except RuntimeError:
                    pass
        self._ai_thread = None
        self._cancel_event = None

    # ------------------------------------------------------------------
    # AI 线程调度
    # ------------------------------------------------------------------
    def _schedule_ai_start(self, delay_ms: Optional[int] = None) -> None:
        """排队启动 AI；人落子后默认等待棋盘动画播放完毕。"""
        if (
            self._shutdown
            or self._paused
            or self._model.is_game_over
            or self._model.side_to_move is not self._ai_side
        ):
            return
        delay = (
            self._ai_start_delay_ms
            if delay_ms is None
            else max(0, int(delay_ms))
        )
        self._ai_start_timer.stop()
        self._ai_start_timer.start(delay)
        self.state_changed.emit()

    def _maybe_start_ai(self) -> None:
        self._ai_start_timer.stop()
        if (
            self._shutdown
            or self._paused
            or self._model.is_game_over
            or self._model.side_to_move is not self._ai_side
        ):
            return

        thread = self._ai_thread
        if thread is not None:
            checker = getattr(thread, "isRunning", None)
            if callable(checker) and checker():
                # 旧搜索仍在退出；等 finished 后再启动新一轮。
                self._pending_start = True
                return

        self._pending_start = False
        self._request_id += 1
        request_id = self._request_id
        cancel_event = Event()
        self._cancel_event = cancel_event

        try:
            worker = self._worker_factory(
                request_id,
                self._model.board,
                self._ai_side,
                self._difficulty,
                cancel_event,
            )
        except Exception:
            logger.exception("创建 AI 线程失败")
            self.error.emit("AI 线程创建失败")
            return

        worker.move_ready.connect(self._on_ai_move_ready)
        worker.search_failed.connect(self._on_ai_search_failed)
        worker.finished.connect(
            lambda current=worker: self._on_ai_thread_finished(current)
        )
        self._ai_thread = worker
        self.state_changed.emit()
        worker.start()

    def _cancel_ai(self) -> None:
        self._request_id += 1
        self._ai_start_timer.stop()
        if self._cancel_event is not None:
            self._cancel_event.set()
        self._pending_start = False

    def _on_ai_move_ready(
        self,
        request_id: int,
        from_row: int,
        from_col: int,
        to_row: int,
        to_col: int,
    ) -> None:
        if request_id != self._request_id or self._shutdown:
            return
        if self._model.is_game_over:
            return
        if self._model.side_to_move is not self._ai_side:
            return
        if self._paused:
            self._pending_ai_move = (from_row, from_col, to_row, to_col)
            return
        self._apply_ai_move(from_row, from_col, to_row, to_col)

    def _apply_ai_move(
        self,
        from_row: int,
        from_col: int,
        to_row: int,
        to_col: int,
    ) -> None:
        if self._model.side_to_move is not self._ai_side:
            return
        move = self._model.apply_move(from_row, from_col, to_row, to_col)
        if move is None:
            self.error.emit("AI 返回了非法着法")
            self._apply_fallback_move()
            return

        self.state_changed.emit()
        self.move_made.emit()
        if self._model.is_game_over:
            self.game_over.emit()

    def _on_ai_search_failed(self, request_id: int, message: str) -> None:
        if request_id != self._request_id or self._shutdown:
            return
        logger.warning("AI 搜索失败：%s", message)
        self.error.emit(f"AI 搜索失败：{message}")
        if self._paused:
            fallback = self._fallback_move()
            if fallback is not None:
                self._pending_ai_move = fallback
            return

        if not self._apply_fallback_move():
            self.state_changed.emit()

    def _fallback_move(self) -> Optional[tuple[int, int, int, int]]:
        if self._model.is_game_over or self._model.side_to_move is not self._ai_side:
            return None
        moves = self._model.all_legal_moves()
        if not moves:
            return None
        move = moves[0]
        return (move.from_row, move.from_col, move.to_row, move.to_col)

    def _apply_fallback_move(self) -> bool:
        fallback = self._fallback_move()
        if fallback is None:
            return False
        self._apply_ai_move(*fallback)
        return True

    def _on_ai_thread_finished(self, worker: object) -> None:
        if self._ai_thread is worker:
            self._ai_thread = None
            self._cancel_event = None
            deleter = getattr(worker, "deleteLater", None)
            if callable(deleter):
                try:
                    deleter()
                except RuntimeError:
                    pass

        self.state_changed.emit()
        if self._pending_start and not self._shutdown and not self._paused:
            self._pending_start = False
            self._schedule_ai_start()


__all__ = ["AIGameSession"]
