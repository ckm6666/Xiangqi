"""中国象棋棋盘的像素几何与命中测试。

棋盘网格为 8×9 个等距格（9 列、10 行交叉点），外框与边距均以格距
``spacing`` 为基准缩放。棋盘整体（含外框）宽高比为 10:11，在任意窗口
尺寸下居中显示，不拉伸变形。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

from PySide6.QtCore import QPointF, QRectF

from xiangqi.client.constants import (
    BOARD_FRAME_SPACING_RATIO,
    BOARD_GRID_MARGIN_SPACING_RATIO,
    BOARD_OUTER_PADDING,
    CLICK_TOLERANCE_RATIO,
)
from xiangqi.shared.rules import BOARD_COLS, BOARD_ROWS

GRID_SPAN_X = BOARD_COLS - 1
GRID_SPAN_Y = BOARD_ROWS - 1


@dataclass(frozen=True)
class BoardGeometry:
    """一次布局计算的结果，全部使用逻辑像素。"""

    panel_rect: QRectF
    surface_rect: QRectF
    grid_rect: QRectF
    spacing: float

    @classmethod
    def for_widget_size(cls, width: float, height: float) -> "BoardGeometry":
        """按控件尺寸计算最大且居中的棋盘几何。"""
        unit = BOARD_FRAME_SPACING_RATIO + BOARD_GRID_MARGIN_SPACING_RATIO
        units_x = GRID_SPAN_X + 2.0 * unit
        units_y = GRID_SPAN_Y + 2.0 * unit

        available_w = max(0.0, float(width) - 2.0 * BOARD_OUTER_PADDING)
        available_h = max(0.0, float(height) - 2.0 * BOARD_OUTER_PADDING)
        spacing = min(available_w / units_x, available_h / units_y)
        spacing = max(0.0, spacing)

        panel_w = spacing * units_x
        panel_h = spacing * units_y
        left = (float(width) - panel_w) / 2.0
        top = (float(height) - panel_h) / 2.0
        panel_rect = QRectF(left, top, panel_w, panel_h)

        frame = spacing * BOARD_FRAME_SPACING_RATIO
        surface_rect = panel_rect.adjusted(frame, frame, -frame, -frame)
        margin = spacing * BOARD_GRID_MARGIN_SPACING_RATIO
        grid_rect = surface_rect.adjusted(margin, margin, -margin, -margin)
        return cls(
            panel_rect=panel_rect,
            surface_rect=surface_rect,
            grid_rect=grid_rect,
            spacing=spacing,
        )

    def point_for(self, row: int, col: int) -> QPointF:
        """返回交叉点的逻辑坐标。"""
        return QPointF(
            self.grid_rect.left() + col * self.spacing,
            self.grid_rect.top() + row * self.spacing,
        )

    def cell_at(
        self,
        point: QPointF,
        tolerance_ratio: float = CLICK_TOLERANCE_RATIO,
    ) -> Optional[tuple[int, int]]:
        """把控件坐标映射到最近的交叉点；超出容差返回 None。"""
        if self.spacing <= 0.0:
            return None
        col_f = (point.x() - self.grid_rect.left()) / self.spacing
        row_f = (point.y() - self.grid_rect.top()) / self.spacing
        row = round(row_f)
        col = round(col_f)
        if not (0 <= row < BOARD_ROWS and 0 <= col < BOARD_COLS):
            return None
        center = self.point_for(row, col)
        distance = math.hypot(point.x() - center.x(), point.y() - center.y())
        if distance > self.spacing * tolerance_ratio:
            return None
        return (row, col)


__all__ = ["BoardGeometry", "GRID_SPAN_X", "GRID_SPAN_Y"]
