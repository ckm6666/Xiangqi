"""棋盘几何与命中测试。"""

from __future__ import annotations

import unittest

from tests.qt_helpers import ensure_qt_app

ensure_qt_app()

from PySide6.QtCore import QPointF  # noqa: E402

from xiangqi.client.board_geometry import BoardGeometry  # noqa: E402
from xiangqi.shared.rules import BOARD_COLS, BOARD_ROWS  # noqa: E402


class BoardGeometryTests(unittest.TestCase):
    """等距网格、居中与点击容差。"""

    def test_panel_is_centered_and_ratio_is_10_11(self) -> None:
        geometry = BoardGeometry.for_widget_size(720, 860)
        self.assertGreater(geometry.spacing, 0.0)
        self.assertAlmostEqual(geometry.panel_rect.center().x(), 360.0)
        self.assertAlmostEqual(geometry.panel_rect.center().y(), 430.0)
        self.assertAlmostEqual(
            geometry.panel_rect.width() / geometry.panel_rect.height(),
            10.0 / 11.0,
            places=5,
        )

    def test_grid_span_matches_spacing(self) -> None:
        geometry = BoardGeometry.for_widget_size(600, 700)
        self.assertAlmostEqual(
            geometry.grid_rect.width(), 8.0 * geometry.spacing, places=5
        )
        self.assertAlmostEqual(
            geometry.grid_rect.height(), 9.0 * geometry.spacing, places=5
        )
        self.assertAlmostEqual(
            geometry.point_for(0, 0).x(), geometry.grid_rect.left(), places=5
        )
        self.assertAlmostEqual(
            geometry.point_for(0, 0).y(), geometry.grid_rect.top(), places=5
        )
        self.assertAlmostEqual(
            geometry.point_for(9, 8).x(), geometry.grid_rect.right(), places=5
        )
        self.assertAlmostEqual(
            geometry.point_for(9, 8).y(), geometry.grid_rect.bottom(), places=5
        )

    def test_cell_round_trip(self) -> None:
        geometry = BoardGeometry.for_widget_size(640, 820)
        for row, col in (
            (0, 0),
            (0, BOARD_COLS - 1),
            (BOARD_ROWS - 1, 0),
            (BOARD_ROWS - 1, BOARD_COLS - 1),
            (4, 4),
            (9, 8),
        ):
            with self.subTest(row=row, col=col):
                self.assertEqual(
                    geometry.cell_at(geometry.point_for(row, col)),
                    (row, col),
                )

    def test_click_outside_tolerance(self) -> None:
        geometry = BoardGeometry.for_widget_size(640, 820)
        center = geometry.point_for(4, 4)
        point = QPointF(center.x() + geometry.spacing * 0.49, center.y())
        self.assertIsNone(geometry.cell_at(point))

    def test_click_outside_board(self) -> None:
        geometry = BoardGeometry.for_widget_size(640, 820)
        self.assertIsNone(geometry.cell_at(QPointF(0.0, 0.0)))
        self.assertIsNone(
            geometry.cell_at(QPointF(geometry.grid_rect.right() + 200.0, 300.0))
        )

    def test_non_square_widget_keeps_aspect(self) -> None:
        geometry = BoardGeometry.for_widget_size(400, 1000)
        self.assertAlmostEqual(geometry.panel_rect.center().x(), 200.0)
        self.assertAlmostEqual(
            geometry.panel_rect.width() / geometry.panel_rect.height(),
            10.0 / 11.0,
            places=5,
        )

    def test_zero_size_is_safe(self) -> None:
        geometry = BoardGeometry.for_widget_size(0, 0)
        self.assertEqual(geometry.spacing, 0.0)
        self.assertIsNone(geometry.cell_at(QPointF(0.0, 0.0)))
        self.assertEqual(geometry.point_for(0, 0), QPointF(0.0, 0.0))


if __name__ == "__main__":
    unittest.main()
