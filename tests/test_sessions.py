"""会话层测试：本地双人 + 占位会话。"""

from __future__ import annotations

import unittest

from tests.helpers import model_with, piece
from tests.qt_helpers import ensure_qt_app

ensure_qt_app()

from PySide6.QtTest import QTest  # noqa: E402

from tests.fakes import FakeAIWorker  # noqa: E402
from xiangqi.client.ai_engine import AIDifficulty  # noqa: E402
from xiangqi.client.board_view import BoardView  # noqa: E402
from xiangqi.client.sessions import (  # noqa: E402
    AIGameSession,
    GameSession,
    LocalGameSession,
    PuzzleSession,
)
from xiangqi.shared.puzzle import Puzzle  # noqa: E402
from xiangqi.shared.rules import (  # noqa: E402
    EndReason,
    PieceKind,
    Side,
)


def fake_factory(move=None, fail=None, delay_ms=0):
    """生成返回确定性 FakeAIWorker 的工厂。"""

    def factory(request_id, board, side, difficulty, cancel_event):
        return FakeAIWorker(
            request_id,
            board,
            side,
            difficulty,
            cancel_event,
            move=move,
            fail=fail,
            delay_ms=delay_ms,
        )

    return factory


class LocalSessionTests(unittest.TestCase):
    """LocalGameSession 的能力、信号与状态。"""

    def test_initial_view_and_capabilities(self) -> None:
        session = LocalGameSession()
        self.assertIsInstance(session, GameSession)
        view = session.view
        self.assertIs(view.side_to_move, Side.RED)
        self.assertEqual(view.move_count, 0)
        self.assertFalse(view.is_game_over)
        self.assertTrue(session.accepts_human_input)
        self.assertFalse(session.can_undo)
        self.assertFalse(session.busy)
        self.assertIsNotNone(session.model)

    def test_legal_moves_from(self) -> None:
        session = LocalGameSession()
        targets = {move.target for move in session.legal_moves_from(6, 0)}
        self.assertIn((5, 0), targets)
        self.assertEqual(session.legal_moves_from(5, 4), ())
        # 黑方棋子不属于当前行棋方。
        self.assertEqual(session.legal_moves_from(3, 0), ())

    def test_request_move_emits_signals(self) -> None:
        session = LocalGameSession()
        events = {"state": 0, "move": 0, "over": 0}
        session.state_changed.connect(lambda: events.__setitem__("state", events["state"] + 1))
        session.move_made.connect(lambda: events.__setitem__("move", events["move"] + 1))
        session.game_over.connect(lambda: events.__setitem__("over", events["over"] + 1))

        self.assertTrue(session.request_move(6, 0, 5, 0))
        self.assertEqual(events["state"], 1)
        self.assertEqual(events["move"], 1)
        self.assertEqual(events["over"], 0)
        self.assertEqual(session.view.move_count, 1)
        self.assertIs(session.view.side_to_move, Side.BLACK)

    def test_illegal_request_is_silent(self) -> None:
        session = LocalGameSession()
        events: list[str] = []
        session.state_changed.connect(lambda: events.append("state"))
        session.move_made.connect(lambda: events.append("move"))

        self.assertFalse(session.request_move(3, 0, 4, 0))
        self.assertFalse(session.request_move(6, 0, 4, 0))
        self.assertEqual(events, [])
        self.assertEqual(session.view.move_count, 0)

    def test_game_over_signal_and_undo(self) -> None:
        model = model_with(
            {
                (1, 3): piece(PieceKind.CHARIOT, Side.RED),
                (2, 2): piece(PieceKind.HORSE, Side.RED),
                (4, 4): piece(PieceKind.PAWN, Side.RED),
            },
            red_king=(9, 4),
            black_king=(0, 4),
        )
        session = LocalGameSession(model)
        over_events: list[bool] = []
        session.game_over.connect(lambda: over_events.append(True))

        self.assertTrue(session.request_move(1, 3, 0, 3))
        self.assertEqual(len(over_events), 1)
        self.assertTrue(session.view.is_game_over)
        self.assertTrue(session.can_undo)

        self.assertTrue(session.request_undo())
        self.assertFalse(session.view.is_game_over)
        self.assertIs(session.view.side_to_move, Side.RED)

    def test_pause_blocks_input(self) -> None:
        session = LocalGameSession()
        session.pause()
        self.assertFalse(session.accepts_human_input)
        self.assertEqual(session.legal_moves_from(6, 0), ())
        self.assertFalse(session.request_move(6, 0, 5, 0))

        session.resume()
        self.assertTrue(session.accepts_human_input)
        self.assertTrue(session.request_move(6, 0, 5, 0))

    def test_restart_resets_model(self) -> None:
        session = LocalGameSession()
        session.request_move(6, 0, 5, 0)
        self.assertTrue(session.request_restart())
        self.assertEqual(session.view.move_count, 0)
        self.assertIs(session.view.side_to_move, Side.RED)

    def test_undo_without_history(self) -> None:
        self.assertFalse(LocalGameSession().request_undo())


class PlaceholderSessionTests(unittest.TestCase):
    """占位会话必须可安全构造与访问。"""

    def _check_safe(self, session: GameSession) -> None:
        self.assertIsInstance(session.view, BoardView)
        self.assertFalse(session.busy)
        self.assertFalse(session.accepts_human_input)
        self.assertFalse(session.can_undo)
        self.assertFalse(session.request_move(6, 0, 5, 0))
        self.assertFalse(session.request_undo())
        self.assertFalse(session.request_restart())
        session.pause()
        session.resume()
        session.shutdown()

    def test_puzzle_session(self) -> None:
        puzzle = Puzzle("p1", "单车擒王")
        session = PuzzleSession(puzzle)
        self._check_safe(session)
        self.assertIs(session.puzzle, puzzle)
        self.assertIsNotNone(session.model)


class AISessionTests(unittest.TestCase):
    """人机会话：后台结果、悔棋、暂停与失败回退。"""

    def test_initial_state_human_red(self) -> None:
        session = AIGameSession(worker_factory=fake_factory())
        self.assertIs(session.human_side, Side.RED)
        self.assertIs(session.ai_side, Side.BLACK)
        self.assertIs(session.difficulty, AIDifficulty.MEDIUM)
        self.assertTrue(session.accepts_human_input)
        self.assertFalse(session.busy)

    def test_ai_moves_first_when_human_is_black(self) -> None:
        session = AIGameSession(
            human_side=Side.BLACK,
            worker_factory=fake_factory(),
        )
        self.assertFalse(session.accepts_human_input)
        QTest.qWait(30)
        self.assertEqual(session.view.move_count, 1)
        self.assertIs(session.view.side_to_move, Side.BLACK)
        self.assertTrue(session.accepts_human_input)
        self.assertFalse(session.busy)

    def test_human_move_triggers_ai_reply(self) -> None:
        session = AIGameSession(worker_factory=fake_factory())
        events = {"state": 0, "move": 0}
        session.state_changed.connect(
            lambda: events.__setitem__("state", events["state"] + 1)
        )
        session.move_made.connect(
            lambda: events.__setitem__("move", events["move"] + 1)
        )

        self.assertTrue(session.request_move(6, 0, 5, 0))
        self.assertTrue(session.busy)
        self.assertFalse(session.accepts_human_input)

        QTest.qWait(30)
        self.assertEqual(session.view.move_count, 2)
        self.assertIs(session.view.side_to_move, Side.RED)
        self.assertTrue(session.accepts_human_input)
        self.assertFalse(session.busy)
        self.assertGreaterEqual(events["state"], 2)
        self.assertEqual(events["move"], 2)

    def test_undo_removes_human_and_ai_moves(self) -> None:
        session = AIGameSession(worker_factory=fake_factory())
        session.request_move(6, 0, 5, 0)
        QTest.qWait(30)
        self.assertEqual(session.view.move_count, 2)

        self.assertTrue(session.request_undo())
        self.assertEqual(session.view.move_count, 0)
        self.assertIs(session.view.side_to_move, Side.RED)
        self.assertTrue(session.accepts_human_input)

    def test_undo_while_ai_thinking_cancels_result(self) -> None:
        session = AIGameSession(
            worker_factory=fake_factory(delay_ms=80)
        )
        session.request_move(6, 0, 5, 0)
        self.assertTrue(session.busy)

        self.assertTrue(session.request_undo())
        self.assertEqual(session.view.move_count, 0)
        QTest.qWait(120)
        self.assertEqual(session.view.move_count, 0)
        self.assertIs(session.view.side_to_move, Side.RED)
        self.assertTrue(session.accepts_human_input)

    def test_pause_keeps_pending_ai_move(self) -> None:
        session = AIGameSession(
            worker_factory=fake_factory(delay_ms=30)
        )
        session.request_move(6, 0, 5, 0)
        session.pause()
        QTest.qWait(60)
        self.assertEqual(session.view.move_count, 1)
        self.assertFalse(session.busy)
        self.assertFalse(session.accepts_human_input)

        session.resume()
        QTest.qWait(60)
        self.assertEqual(session.view.move_count, 2)
        self.assertIs(session.view.side_to_move, Side.RED)
        self.assertTrue(session.accepts_human_input)

    def test_search_failure_falls_back_to_legal_move(self) -> None:
        session = AIGameSession(
            worker_factory=fake_factory(fail="boom")
        )
        errors: list[str] = []
        session.error.connect(errors.append)
        session.request_move(6, 0, 5, 0)
        QTest.qWait(30)

        self.assertEqual(session.view.move_count, 2)
        self.assertIs(session.view.side_to_move, Side.RED)
        self.assertTrue(errors)

    def test_restart_with_ai_first(self) -> None:
        session = AIGameSession(
            human_side=Side.BLACK,
            worker_factory=fake_factory(),
        )
        QTest.qWait(30)
        self.assertEqual(session.view.move_count, 1)

        self.assertTrue(session.request_restart())
        self.assertEqual(session.view.move_count, 0)
        QTest.qWait(30)
        self.assertEqual(session.view.move_count, 1)
        self.assertIs(session.view.side_to_move, Side.BLACK)

    def test_ai_can_mate_and_emit_game_over(self) -> None:
        model = model_with(
            {
                (8, 3): piece(PieceKind.CHARIOT, Side.BLACK),
                (7, 2): piece(PieceKind.HORSE, Side.BLACK),
                (5, 4): piece(PieceKind.PAWN, Side.BLACK),
            },
            red_king=(9, 4),
            black_king=(0, 4),
            side=Side.BLACK,
        )
        session = AIGameSession(
            model=model,
            human_side=Side.RED,
            worker_factory=fake_factory(move=(8, 3, 9, 3)),
        )
        over: list[bool] = []
        session.game_over.connect(lambda: over.append(True))
        QTest.qWait(30)

        self.assertTrue(session.view.is_game_over)
        self.assertIs(session.view.winner, Side.BLACK)
        self.assertIs(session.view.end_reason, EndReason.CHECKMATE)
        self.assertEqual(over, [True])

    def test_human_mate_does_not_start_ai(self) -> None:
        model = model_with(
            {
                (1, 3): piece(PieceKind.CHARIOT, Side.RED),
                (2, 2): piece(PieceKind.HORSE, Side.RED),
                (4, 4): piece(PieceKind.PAWN, Side.RED),
            },
            red_king=(9, 4),
            black_king=(0, 4),
        )

        def unexpected_factory(*args, **kwargs):
            raise AssertionError("将杀后不应再启动 AI")

        session = AIGameSession(
            model=model,
            worker_factory=unexpected_factory,
        )
        over: list[bool] = []
        session.game_over.connect(lambda: over.append(True))
        self.assertTrue(session.request_move(1, 3, 0, 3))
        self.assertTrue(session.view.is_game_over)
        self.assertIs(session.view.end_reason, EndReason.CHECKMATE)
        self.assertEqual(over, [True])
        self.assertFalse(session.accepts_human_input)

    def test_set_difficulty(self) -> None:
        session = AIGameSession(worker_factory=fake_factory())
        events: list[bool] = []
        session.state_changed.connect(lambda: events.append(True))
        session.set_difficulty(AIDifficulty.MASTER)
        self.assertIs(session.difficulty, AIDifficulty.MASTER)
        self.assertTrue(events)

    def test_shutdown_is_safe(self) -> None:
        session = AIGameSession(worker_factory=fake_factory(delay_ms=50))
        session.request_move(6, 0, 5, 0)
        session.shutdown()
        session.shutdown()


if __name__ == "__main__":
    unittest.main()
