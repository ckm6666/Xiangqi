"""AIWorker 线程包装测试。"""

from __future__ import annotations

import unittest
from threading import Event

from tests.qt_helpers import ensure_qt_app

ensure_qt_app()

from xiangqi.client.ai_engine import AIDifficulty  # noqa: E402
from xiangqi.client.ai_worker import AIWorker  # noqa: E402
from xiangqi.shared.game_model import GameModel  # noqa: E402
from xiangqi.shared.rules import Side, is_legal_move  # noqa: E402


class AIWorkerTests(unittest.TestCase):
    """直接调用 run()，验证信号载荷与取消。"""

    def test_emits_legal_move(self) -> None:
        worker = AIWorker(
            7,
            GameModel.initial().board,
            Side.RED,
            AIDifficulty.EASY,
        )
        events: list[tuple[int, int, int, int, int]] = []
        failures: list[tuple[int, str]] = []
        worker.move_ready.connect(lambda *args: events.append(args))
        worker.search_failed.connect(
            lambda request_id, message: failures.append(
                (request_id, message)
            )
        )

        worker.run()
        self.assertEqual(failures, [])
        self.assertEqual(len(events), 1)
        request_id, from_row, from_col, to_row, to_col = events[0]
        self.assertEqual(request_id, 7)
        self.assertTrue(
            is_legal_move(
                GameModel.initial().board,
                Side.RED,
                from_row,
                from_col,
                to_row,
                to_col,
            )
        )

    def test_cancelled_search_emits_nothing(self) -> None:
        cancel_event = Event()
        cancel_event.set()
        worker = AIWorker(
            8,
            GameModel.initial().board,
            Side.RED,
            AIDifficulty.EASY,
            cancel_event,
        )
        events: list[object] = []
        worker.move_ready.connect(lambda *args: events.append(args))
        worker.run()
        self.assertEqual(events, [])


if __name__ == "__main__":
    unittest.main()
