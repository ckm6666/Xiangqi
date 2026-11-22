"""棋盘控件 offscreen 绘制与点击测试。"""

from __future__ import annotations

import unittest

from tests.qt_helpers import ensure_qt_app

APP = ensure_qt_app()

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402

from tests.helpers import model_with, piece  # noqa: E402
from xiangqi.client.board_view import BoardView  # noqa: E402
from xiangqi.client.board_widget import BoardWidget  # noqa: E402
from xiangqi.shared.game_model import GameModel  # noqa: E402
from xiangqi.shared.rules import PieceKind, Side  # noqa: E402


class BoardWidgetTests(unittest.TestCase):
    """棋盘绘制、命中与交互。"""

    def test_initial_view_renders(self) -> None:
        view = BoardView.from_model(GameModel.initial())
        widget = BoardWidget(view)
        widget.resize(620, 682)
        pixmap = widget.grab()
        self.assertFalse(pixmap.isNull())
        self.assertGreater(widget.board_rect().width(), 0.0)
        widget.deleteLater()

    def test_cell_center_round_trip(self) -> None:
        widget = BoardWidget(BoardView.from_model(GameModel.initial()))
        widget.resize(620, 682)
        for row, col in ((0, 0), (4, 4), (9, 8)):
            with self.subTest(row=row, col=col):
                center = widget.cell_center(row, col)
                self.assertEqual(widget.cell_at(center), (row, col))
        widget.deleteLater()

    def test_flipped_board_maps_clicks_and_renders(self) -> None:
        view = BoardView.from_model(GameModel.initial())
        normal = BoardWidget(view)
        normal.resize(620, 682)
        flipped = BoardWidget(view)
        flipped.resize(620, 682)
        flipped.set_flipped(True)

        self.assertTrue(flipped.flipped)
        self.assertEqual(
            flipped.cell_center(0, 0), normal.cell_center(9, 8)
        )
        self.assertEqual(
            flipped.cell_center(9, 8), normal.cell_center(0, 0)
        )
        for row, col in ((0, 0), (4, 4), (6, 0), (9, 8)):
            with self.subTest(row=row, col=col):
                self.assertEqual(
                    flipped.cell_at(
                        flipped.cell_center(row, col)
                    ),
                    (row, col),
                )
        self.assertFalse(flipped.grab().isNull())

        flipped.set_interaction_enabled(True)
        flipped.show()
        APP.processEvents()
        events: list[tuple[int, int]] = []
        flipped.cell_clicked.connect(
            lambda row, col: events.append((row, col))
        )
        QTest.mouseClick(
            flipped,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
            flipped.cell_center(6, 0).toPoint(),
        )
        APP.processEvents()
        self.assertEqual(events, [(6, 0)])

        flipped.set_flipped(False)
        self.assertEqual(
            flipped.cell_center(0, 0), normal.cell_center(0, 0)
        )
        flipped.close()
        normal.deleteLater()
        flipped.deleteLater()

    def test_click_emits_cell(self) -> None:
        view = BoardView.from_model(GameModel.initial())
        widget = BoardWidget(view)
        widget.resize(620, 682)
        widget.set_interaction_enabled(True)
        widget.show()
        APP.processEvents()

        events: list[tuple[int, int]] = []
        widget.cell_clicked.connect(lambda row, col: events.append((row, col)))
        point = widget.cell_center(6, 0).toPoint()
        QTest.mouseClick(
            widget,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
            point,
        )
        APP.processEvents()
        self.assertEqual(events, [(6, 0)])

        widget.set_interaction_enabled(False)
        QTest.mouseClick(
            widget,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
            point,
        )
        APP.processEvents()
        self.assertEqual(events, [(6, 0)])
        widget.close()
        widget.deleteLater()

    def test_selection_and_legal_targets_render(self) -> None:
        view = BoardView.from_model(GameModel.initial())
        view = view.with_selection((6, 0), ((5, 0), (5, 1)))
        widget = BoardWidget(view)
        widget.resize(620, 682)
        self.assertFalse(widget.grab().isNull())
        widget.deleteLater()

    def test_check_view_renders(self) -> None:
        model = model_with(
            {(9, 8): piece(PieceKind.CHARIOT, Side.BLACK)},
            red_king=(9, 3),
            black_king=(0, 5),
        )
        view = BoardView.from_model(model)
        self.assertTrue(view.is_check)
        widget = BoardWidget(view)
        widget.resize(620, 682)
        self.assertFalse(widget.grab().isNull())
        widget.deleteLater()

    def test_game_over_view_renders(self) -> None:
        model = model_with(
            {
                (1, 3): piece(PieceKind.CHARIOT, Side.RED),
                (2, 2): piece(PieceKind.HORSE, Side.RED),
                (4, 4): piece(PieceKind.PAWN, Side.RED),
            },
            red_king=(9, 4),
            black_king=(0, 4),
        )
        self.assertIsNotNone(model.apply_move(1, 3, 0, 3))
        view = BoardView.from_model(model)
        self.assertTrue(view.is_game_over)
        widget = BoardWidget(view)
        widget.resize(620, 682)
        self.assertFalse(widget.grab().isNull())
        widget.deleteLater()

    def test_resize_invalidates_static_cache(self) -> None:
        widget = BoardWidget(BoardView.from_model(GameModel.initial()))
        widget.resize(400, 440)
        self.assertFalse(widget.grab().isNull())
        widget.resize(700, 770)
        self.assertFalse(widget.grab().isNull())
        widget.deleteLater()

    def test_move_animation_progresses_and_finishes(self) -> None:
        model = GameModel.initial()
        widget = BoardWidget(BoardView.from_model(model))
        widget.resize(620, 682)
        widget.show()
        APP.processEvents()

        self.assertIsNotNone(model.apply_move(6, 0, 5, 0))
        widget.set_view(BoardView.from_model(model))
        self.assertTrue(widget.is_animating)
        self.assertFalse(widget.grab().isNull())
        before = widget.animation_progress()

        QTest.qWait(80)
        self.assertGreater(widget.animation_progress(), before)
        self.assertFalse(widget.grab().isNull())

        QTest.qWait(300)
        self.assertFalse(widget.is_animating)
        widget.close()
        widget.deleteLater()

    def test_animation_blocks_board_clicks(self) -> None:
        model = GameModel.initial()
        widget = BoardWidget(BoardView.from_model(model))
        widget.resize(620, 682)
        widget.set_interaction_enabled(True)
        widget.show()
        APP.processEvents()
        events: list[tuple[int, int]] = []
        widget.cell_clicked.connect(
            lambda row, col: events.append((row, col))
        )

        self.assertIsNotNone(model.apply_move(6, 0, 5, 0))
        widget.set_view(BoardView.from_model(model))
        self.assertTrue(widget.is_animating)
        QTest.mouseClick(
            widget,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
            widget.cell_center(5, 0).toPoint(),
        )
        APP.processEvents()
        self.assertEqual(events, [])

        QTest.qWait(320)
        QTest.mouseClick(
            widget,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
            widget.cell_center(5, 0).toPoint(),
        )
        APP.processEvents()
        self.assertEqual(events, [(5, 0)])
        widget.close()
        widget.deleteLater()

    def test_effect_queue_and_remaining_time(self) -> None:
        widget = BoardWidget(BoardView.from_model(GameModel.initial()))
        widget.resize(620, 682)
        widget.show_effect("capture")
        widget.show_effect("check")

        self.assertTrue(widget.has_effect)
        self.assertEqual(widget.effect_kind, "capture")
        self.assertGreater(widget.effect_remaining_ms(), 1000)
        self.assertFalse(widget.grab().isNull())

        QTest.qWait(750)
        self.assertEqual(widget.effect_kind, "check")
        self.assertGreater(widget.effect_remaining_ms(), 300)

        QTest.qWait(1100)
        self.assertFalse(widget.has_effect)
        self.assertEqual(widget.effect_remaining_ms(), 0)
        widget.deleteLater()


if __name__ == "__main__":
    unittest.main()
