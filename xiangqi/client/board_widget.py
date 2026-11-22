"""中国象棋棋盘自绘控件。

绘制分两层：
    * 静态层：外框、木纹棋盘面、10×9 网格、九宫斜线、楚河汉界、炮/兵位
      记号与印章，按控件尺寸和 DPR 缓存为 QPixmap；
    * 动态层：上一手标记、被将军提示、棋子、选中环、合法目标点与悬停环。

控件只消费不可变 BoardView，不校验规则、不弹窗；点击交叉点后发出
``cell_clicked(row, col)``，由 MainWindow/会话层决定如何处理。
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import Optional

from PySide6.QtCore import (
    QEvent,
    QPointF,
    QRectF,
    QSize,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QFont,
    QLinearGradient,
    QMouseEvent,
    QPaintEvent,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QRadialGradient,
    QResizeEvent,
)
from PySide6.QtWidgets import QSizePolicy, QWidget

from xiangqi.client.board_geometry import BoardGeometry
from xiangqi.client.board_view import BoardView
from xiangqi.client.constants import (
    BOARD_CORNER_RADIUS_RATIO,
    BOARD_FRAME_GOLD,
    BOARD_GRAIN_LINE_COUNT,
    BOARD_LACQUER_BOTTOM,
    BOARD_LACQUER_TOP,
    BOARD_MIN_SIZE,
    BOARD_SUGGESTED_SIZE,
    BOARD_SURFACE_CORNER_RATIO,
    CHECK_COLOR,
    EFFECT_CAPTURE_SECONDS,
    EFFECT_CHECK_SECONDS,
    EFFECT_CHECKMATE_SECONDS,
    FRAME_INTERVAL_MS,
    GRID_COLOR,
    LAST_MOVE_COLOR,
    LEGAL_TARGET_COLOR,
    MOVE_ANIMATION_SECONDS,
    MOVE_LIFT_SPACING_RATIO,
    PIECE_GLYPH_SIZE_RATIO,
    PIECE_RADIUS_RATIO,
    PIECE_SHADOW_COLOR,
    RIVER_TEXT_COLOR,
    RIVER_TEXT_SIZE_RATIO,
    SELECTION_COLOR,
    WOOD_BORDER_COLOR,
    WOOD_BOTTOM_COLOR,
    WOOD_GRAIN_COLOR,
    WOOD_MIDDLE_COLOR,
    WOOD_TOP_COLOR,
)
from xiangqi.client.theme_palette import (
    CINNABAR,
    CINNABAR_DARK,
    GOLD,
    INK,
    PAPER_LIGHT,
    PIECE_BLACK_INK,
    PIECE_IVORY,
    PIECE_IVORY_DEEP,
    PIECE_RED_INK,
)
from xiangqi.client.ui_theme import make_piece_font
from xiangqi.shared.rules import (
    BOARD_COLS,
    BOARD_ROWS,
    Move,
    Piece,
    Side,
)

# 炮位与兵/卒位的 L 形记号（0 起始行列）。
CANNON_POINTS: tuple[tuple[int, int], ...] = (
    (2, 1),
    (2, 7),
    (7, 1),
    (7, 7),
)
PAWN_POINTS: tuple[tuple[int, int], ...] = (
    (3, 0),
    (3, 2),
    (3, 4),
    (3, 6),
    (3, 8),
    (6, 0),
    (6, 2),
    (6, 4),
    (6, 6),
    (6, 8),
)
PALACE_DIAGONALS: tuple[tuple[int, int, int, int], ...] = (
    (0, 3, 2, 5),
    (0, 5, 2, 3),
    (7, 3, 9, 5),
    (7, 5, 9, 3),
)


def _color(name: str, alpha: int = 255) -> QColor:
    """创建带透明度的颜色（PySide6 不支持 QColor(hex, alpha)）。"""
    color = QColor(name)
    color.setAlpha(max(0, min(255, int(alpha))))
    return color


@dataclass
class _MoveAnimation:
    """一手的落子动画状态。"""

    move: Move
    piece: Piece
    captured: Optional[Piece]
    move_count: int
    start_time: float
    duration: float


@dataclass
class _BoardEffect:
    """棋盘中央的短暂文字特效。"""

    kind: str
    text: str
    start_time: float
    duration: float


_EFFECT_SPECS: dict[str, tuple[str, float, float, str]] = {
    "capture": ("吃", EFFECT_CAPTURE_SECONDS, 1.35, INK),
    "check": ("将 军", EFFECT_CHECK_SECONDS, 0.95, CINNABAR),
    "checkmate": ("绝 杀", EFFECT_CHECKMATE_SECONDS, 1.15, CINNABAR_DARK),
}


class BoardWidget(QWidget):
    """9 列 × 10 行交叉点的中国象棋棋盘。"""

    cell_clicked = Signal(int, int)

    def __init__(
        self,
        view: BoardView,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._view = view
        self._geometry = BoardGeometry.for_widget_size(1.0, 1.0)
        self._hover_cell: Optional[tuple[int, int]] = None
        self._interaction_enabled = False
        # 执黑视角：棋盘行列整体颠倒，但棋子文字保持正向。
        self._flipped = False
        self._static_cache: Optional[QPixmap] = None
        self._static_cache_key: Optional[tuple[int, int, float]] = None

        self._animation: Optional[_MoveAnimation] = None
        self._effects: list[_BoardEffect] = []
        self._frame_timer = QTimer(self)
        self._frame_timer.setInterval(FRAME_INTERVAL_MS)
        self._frame_timer.timeout.connect(self._on_frame_tick)

        self.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )
        self.setMinimumSize(BOARD_MIN_SIZE, BOARD_MIN_SIZE)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.ArrowCursor)

    # ------------------------------------------------------------------
    # 对外接口
    # ------------------------------------------------------------------
    def sizeHint(self) -> QSize:  # noqa: N802 - Qt 接口
        return QSize(BOARD_SUGGESTED_SIZE, int(BOARD_SUGGESTED_SIZE * 1.1))

    @property
    def view(self) -> BoardView:
        """当前只读视图（测试与调试用）。"""
        return self._view

    @property
    def flipped(self) -> bool:
        """是否以执黑视角颠倒棋盘（棋子文字仍正向绘制）。"""
        return self._flipped

    @property
    def is_animating(self) -> bool:
        return self._animation is not None

    @property
    def has_effect(self) -> bool:
        return bool(self._effects)

    @property
    def effect_text(self) -> str:
        return self._effects[0].text if self._effects else ""

    @property
    def effect_kind(self) -> str:
        return self._effects[0].kind if self._effects else ""

    def animation_progress(self) -> float:
        animation = self._animation
        if animation is None:
            return 1.0
        elapsed = time.monotonic() - animation.start_time
        return max(0.0, min(1.0, elapsed / animation.duration))

    def animation_remaining_ms(self) -> int:
        if self._animation is None:
            return 0
        return max(
            0,
            int(
                (self._animation.duration - (
                    time.monotonic() - self._animation.start_time
                ))
                * 1000
            ),
        )

    def effect_remaining_ms(self) -> int:
        if not self._effects:
            return 0
        now = time.monotonic()
        first = self._effects[0]
        start = first.start_time if first.start_time > 0 else now
        remaining = max(0.0, first.duration - (now - start))
        remaining += sum(effect.duration for effect in self._effects[1:])
        return int(remaining * 1000)

    def transient_remaining_ms(self) -> int:
        """当前动画/特效剩余时间，用于延后终局弹窗。"""
        return max(self.animation_remaining_ms(), self.effect_remaining_ms())

    def show_effect(self, kind: str) -> None:
        """在棋盘中央排队播放一个短暂文字特效。"""
        spec = _EFFECT_SPECS.get(kind)
        if spec is None:
            return
        text, duration, _size_ratio, _color = spec
        start = time.monotonic() if not self._effects else 0.0
        self._effects.append(
            _BoardEffect(kind, text, start, duration)
        )
        self._ensure_frame_timer()
        self.update()

    def set_view(self, view: BoardView) -> None:
        """更新只读视图；若出现新的一手则启动落子动画。"""
        previous_count = self._view.move_count
        previous_last = self._view.last_move
        self._view = view

        if view.move_count > previous_count and view.last_move is not None:
            self._start_move_animation(view.last_move, view.move_count)
        elif view.move_count < previous_count or view.last_move is None:
            self._cancel_animation()
            if view.move_count < previous_count or view.move_count == 0:
                self._clear_effects()
        elif self._animation is not None:
            animation = self._animation
            if (
                view.move_count != animation.move_count
                or view.last_move != animation.move
            ):
                self._cancel_animation()
                self._clear_effects()
        elif previous_last is not None and view.last_move != previous_last:
            self._clear_effects()

        self.update()

    def set_interaction_enabled(self, enabled: bool) -> None:
        """启用/禁用点击与悬停。"""
        enabled = bool(enabled)
        if enabled == self._interaction_enabled:
            return
        self._interaction_enabled = enabled
        if not enabled:
            self._hover_cell = None
            self.unsetCursor()
        self.update()

    def set_flipped(self, flipped: bool) -> None:
        """设置是否以执黑视角显示（行列颠倒，棋子文字不旋转）。"""
        flipped = bool(flipped)
        if flipped == self._flipped:
            return
        self._flipped = flipped
        self._hover_cell = None
        self.update()

    def refresh(self) -> None:
        """强制重绘（静态缓存保留）。"""
        self.update()

    def _sync_geometry(self) -> None:
        """按当前控件尺寸刷新几何（尺寸变化不一定立即触发 paint）。"""
        self._geometry = BoardGeometry.for_widget_size(
            float(self.width()), float(self.height())
        )

    def _display_square(self, row: int, col: int) -> tuple[int, int]:
        """把逻辑坐标映射到显示坐标；颠倒操作是对合变换。"""
        if self._flipped:
            return (
                BOARD_ROWS - 1 - row,
                BOARD_COLS - 1 - col,
            )
        return row, col

    def _point_for(self, row: int, col: int) -> QPointF:
        """逻辑交叉点在控件中的显示中心。"""
        return self._geometry.point_for(
            *self._display_square(row, col)
        )

    def board_rect(self) -> QRectF:
        """返回棋盘外框矩形（逻辑像素）。"""
        self._sync_geometry()
        return QRectF(self._geometry.panel_rect)

    def cell_center(self, row: int, col: int) -> QPointF:
        """返回交叉点在当前视角下的中心。"""
        self._sync_geometry()
        return self._point_for(row, col)

    def cell_at(self, point: QPointF) -> Optional[tuple[int, int]]:
        """把控件坐标映射为逻辑交叉点。"""
        self._sync_geometry()
        cell = self._geometry.cell_at(point)
        if cell is None:
            return None
        return self._display_square(*cell)

    # ------------------------------------------------------------------
    # Qt 事件
    # ------------------------------------------------------------------
    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802 - Qt 接口
        self._sync_geometry()
        self._invalidate_static_cache()
        super().resizeEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt 接口
        if (
            event.button() is Qt.MouseButton.LeftButton
            and self._interaction_enabled
            and self._animation is None
        ):
            cell = self.cell_at(event.position())
            if cell is not None:
                self.cell_clicked.emit(cell[0], cell[1])
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt 接口
        if not self._interaction_enabled or self._animation is not None:
            return super().mouseMoveEvent(event)
        cell = self.cell_at(event.position())
        if cell != self._hover_cell:
            self._hover_cell = cell
            self.update()
        self._update_cursor(cell)
        super().mouseMoveEvent(event)

    def leaveEvent(self, event: QEvent) -> None:  # noqa: N802 - Qt 接口
        if self._hover_cell is not None:
            self._hover_cell = None
            self.update()
        self.unsetCursor()
        super().leaveEvent(event)

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802 - Qt 接口
        del event
        self._geometry = BoardGeometry.for_widget_size(
            float(self.width()), float(self.height())
        )
        if self._geometry.spacing <= 0.0:
            self._invalidate_static_cache()
            return

        self._ensure_static_cache()

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

        if self._static_cache is not None:
            painter.drawPixmap(
                QRectF(0.0, 0.0, float(self.width()), float(self.height())),
                self._static_cache,
                QRectF(self._static_cache.rect()),
            )

        self._draw_last_move_markers(painter)
        self._draw_check_marker(painter)
        self._draw_pieces(painter)
        self._draw_captured_ghost(painter)
        self._draw_moving_piece(painter)
        self._draw_selection(painter)
        self._draw_legal_targets(painter)
        self._draw_hover(painter)
        self._draw_effect(painter)
        painter.end()

    # ------------------------------------------------------------------
    # 静态层
    # ------------------------------------------------------------------
    def _invalidate_static_cache(self) -> None:
        self._static_cache = None
        self._static_cache_key = None

    def _ensure_static_cache(self) -> None:
        key = (
            self.width(),
            self.height(),
            round(float(self.devicePixelRatioF()), 3),
        )
        if self._static_cache is not None and key == self._static_cache_key:
            return
        if self.width() <= 0 or self.height() <= 0:
            return

        dpr = float(self.devicePixelRatioF())
        pixmap = QPixmap(
            max(1, int(self.width() * dpr)),
            max(1, int(self.height() * dpr)),
        )
        pixmap.setDevicePixelRatio(dpr)
        pixmap.fill(Qt.GlobalColor.transparent)

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        self._draw_board_surface(painter)
        painter.end()

        self._static_cache = pixmap
        self._static_cache_key = key

    def _draw_board_surface(self, painter: QPainter) -> None:
        panel = self._geometry.panel_rect
        surface = self._geometry.surface_rect
        spacing = self._geometry.spacing
        panel_radius = panel.width() * BOARD_CORNER_RADIUS_RATIO
        surface_radius = surface.width() * BOARD_SURFACE_CORNER_RATIO

        # 外框投影
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, 42))
        painter.drawRoundedRect(
            panel.translated(0.0, spacing * 0.10),
            panel_radius,
            panel_radius,
        )

        # 深漆外框 + 金线
        lacquer = QLinearGradient(panel.topLeft(), panel.bottomLeft())
        lacquer.setColorAt(0.0, QColor(BOARD_LACQUER_TOP))
        lacquer.setColorAt(1.0, QColor(BOARD_LACQUER_BOTTOM))
        painter.setBrush(lacquer)
        painter.setPen(QPen(QColor(BOARD_FRAME_GOLD), max(1.0, spacing * 0.028)))
        painter.drawRoundedRect(panel, panel_radius, panel_radius)

        inner = panel.adjusted(
            spacing * 0.075,
            spacing * 0.075,
            -spacing * 0.075,
            -spacing * 0.075,
        )
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(BOARD_FRAME_GOLD), max(0.8, spacing * 0.012)))
        painter.drawRoundedRect(
            inner,
            panel_radius * 0.82,
            panel_radius * 0.82,
        )

        # 暖木棋盘面
        wood = QLinearGradient(surface.topLeft(), surface.bottomLeft())
        wood.setColorAt(0.0, QColor(WOOD_TOP_COLOR))
        wood.setColorAt(0.52, QColor(WOOD_MIDDLE_COLOR))
        wood.setColorAt(1.0, QColor(WOOD_BOTTOM_COLOR))
        painter.setBrush(wood)
        painter.setPen(QPen(QColor(WOOD_BORDER_COLOR), max(1.0, spacing * 0.022)))
        painter.drawRoundedRect(surface, surface_radius, surface_radius)

        self._draw_wood_grain(painter, surface, spacing)
        self._draw_grid(painter)
        self._draw_river_text(painter)
        self._draw_frame_seal(painter, panel, spacing)

    def _draw_wood_grain(
        self,
        painter: QPainter,
        surface: QRectF,
        spacing: float,
    ) -> None:
        clip = QPainterPath()
        clip.addRoundedRect(
            surface,
            surface.width() * BOARD_SURFACE_CORNER_RATIO,
            surface.width() * BOARD_SURFACE_CORNER_RATIO,
        )
        painter.save()
        painter.setClipPath(clip)
        pen = QPen(_color(WOOD_GRAIN_COLOR, 18), max(0.6, spacing * 0.012))
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        step = max(18.0, spacing * 0.5)
        amplitude = spacing * 0.06
        for index in range(BOARD_GRAIN_LINE_COUNT):
            base_y = surface.top() + surface.height() * (index + 0.5) / BOARD_GRAIN_LINE_COUNT
            path = QPainterPath(QPointF(surface.left(), base_y))
            x = surface.left()
            while x <= surface.right():
                y = base_y + math.sin((x + index * 37.0) / step) * amplitude
                path.lineTo(x, y)
                x += step
            painter.drawPath(path)
        painter.restore()

    def _draw_grid(self, painter: QPainter) -> None:
        spacing = self._geometry.spacing
        grid_pen = QPen(QColor(GRID_COLOR), max(1.0, spacing * 0.022))
        grid_pen.setCapStyle(Qt.PenCapStyle.FlatCap)
        painter.setPen(grid_pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)

        for row in range(BOARD_ROWS):
            painter.drawLine(
                self._geometry.point_for(row, 0),
                self._geometry.point_for(row, BOARD_COLS - 1),
            )

        last_col = BOARD_COLS - 1
        for col in range(BOARD_COLS):
            top = self._geometry.point_for(0, col)
            bottom = self._geometry.point_for(BOARD_ROWS - 1, col)
            if col in (0, last_col):
                painter.drawLine(top, bottom)
            else:
                painter.drawLine(top, self._geometry.point_for(4, col))
                painter.drawLine(
                    self._geometry.point_for(5, col),
                    bottom,
                )

        for row_a, col_a, row_b, col_b in PALACE_DIAGONALS:
            painter.drawLine(
                self._geometry.point_for(row_a, col_a),
                self._geometry.point_for(row_b, col_b),
            )

        marker_pen = QPen(QColor(GRID_COLOR), max(1.0, spacing * 0.020))
        marker_pen.setCapStyle(Qt.PenCapStyle.FlatCap)
        painter.setPen(marker_pen)
        for row, col in CANNON_POINTS + PAWN_POINTS:
            self._draw_position_marker(painter, row, col)

    def _draw_position_marker(
        self,
        painter: QPainter,
        row: int,
        col: int,
    ) -> None:
        spacing = self._geometry.spacing
        center = self._geometry.point_for(row, col)
        gap = spacing * 0.12
        length = spacing * 0.15
        for sx in (-1, 1):
            for sy in (-1, 1):
                if sx < 0 and col == 0:
                    continue
                if sx > 0 and col == BOARD_COLS - 1:
                    continue
                if sy < 0 and row == 0:
                    continue
                if sy > 0 and row == BOARD_ROWS - 1:
                    continue
                corner = QPointF(
                    center.x() + sx * gap,
                    center.y() + sy * gap,
                )
                painter.drawLine(
                    corner,
                    QPointF(corner.x() + sx * length, corner.y()),
                )
                painter.drawLine(
                    corner,
                    QPointF(corner.x(), corner.y() + sy * length),
                )

    def _draw_river_text(self, painter: QPainter) -> None:
        spacing = self._geometry.spacing
        grid = self._geometry.grid_rect
        font = QFont()
        font.setFamilies(["Ma Shan Zheng", "KaiTi", "FangSong"])
        font.setPixelSize(max(1, int(spacing * RIVER_TEXT_SIZE_RATIO)))
        painter.setFont(font)
        painter.setPen(_color(RIVER_TEXT_COLOR, 160))
        middle_y = (
            self._geometry.point_for(4, 0).y()
            + self._geometry.point_for(5, 0).y()
        ) / 2.0
        for text, center_x in (
            ("楚 河", grid.left() + grid.width() * 0.25),
            ("汉 界", grid.left() + grid.width() * 0.75),
        ):
            rect = QRectF(
                center_x - grid.width() * 0.18,
                middle_y - spacing * 0.30,
                grid.width() * 0.36,
                spacing * 0.60,
            )
            painter.drawText(rect, int(Qt.AlignmentFlag.AlignCenter), text)

    def _draw_frame_seal(
        self,
        painter: QPainter,
        panel: QRectF,
        spacing: float,
    ) -> None:
        size = spacing * 0.30
        seal = QRectF(
            panel.right() - size - spacing * 0.09,
            panel.top() + spacing * 0.09,
            size,
            size,
        )
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(_color(CINNABAR, 205))
        painter.drawRoundedRect(seal, size * 0.16, size * 0.16)

        font = QFont()
        font.setFamilies(["Ma Shan Zheng", "KaiTi", "FangSong"])
        font.setPixelSize(max(1, int(size * 0.62)))
        painter.setFont(font)
        painter.setPen(QColor(PAPER_LIGHT))
        painter.drawText(seal, int(Qt.AlignmentFlag.AlignCenter), "棋")

    # ------------------------------------------------------------------
    # 动态层
    # ------------------------------------------------------------------
    def _piece_radius(self) -> float:
        return self._geometry.spacing * PIECE_RADIUS_RATIO

    def _draw_corner_brackets(
        self,
        painter: QPainter,
        center: QPointF,
        radius: float,
        color: QColor,
        width: float,
    ) -> None:
        pen = QPen(color, width)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        arm = radius * 0.42
        for sx in (-1, 1):
            for sy in (-1, 1):
                corner = QPointF(
                    center.x() + sx * radius,
                    center.y() + sy * radius,
                )
                painter.drawLine(corner, QPointF(corner.x() - sx * arm, corner.y()))
                painter.drawLine(corner, QPointF(corner.x(), corner.y() - sy * arm))

    def _draw_last_move_markers(self, painter: QPainter) -> None:
        move = self._view.last_move
        if move is None:
            return
        spacing = self._geometry.spacing
        for square, strong in ((move.origin, False), (move.target, True)):
            center = self._point_for(*square)
            radius = spacing * (0.49 if strong else 0.40)
            color = _color(LAST_MOVE_COLOR, 210 if strong else 105)
            self._draw_corner_brackets(
                painter,
                center,
                radius,
                color,
                max(1.0, spacing * 0.034),
            )

    def _draw_check_marker(self, painter: QPainter) -> None:
        if not self._view.is_check:
            return
        from xiangqi.shared.rules import find_king

        square = find_king(self._view.board, self._view.side_to_move)
        if square is None:
            return
        center = self._point_for(*square)
        radius = self._piece_radius() * 1.12
        spacing = self._geometry.spacing
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(_color(CHECK_COLOR, 70), max(2.0, spacing * 0.09)))
        painter.drawEllipse(center, radius, radius)
        painter.setPen(QPen(QColor(CHECK_COLOR), max(1.0, spacing * 0.035)))
        painter.drawEllipse(center, radius, radius)

    def _paint_piece(
        self,
        painter: QPainter,
        center: QPointF,
        piece: Piece,
        *,
        radius_scale: float = 1.0,
        alpha: float = 1.0,
    ) -> None:
        """在任意中心绘制一枚棋子，供静态/动画/残影复用。"""
        if alpha <= 0.0:
            return
        spacing = self._geometry.spacing
        radius = self._piece_radius() * radius_scale
        painter.save()
        painter.setOpacity(max(0.0, min(1.0, alpha)))

        shadow = QRectF(
            center.x() - radius,
            center.y() - radius + radius * 0.12,
            radius * 2.0,
            radius * 2.0,
        )
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(_color(PIECE_SHADOW_COLOR, 70))
        painter.drawEllipse(shadow)

        gradient = QRadialGradient(
            QPointF(
                center.x() - radius * 0.30,
                center.y() - radius * 0.36,
            ),
            radius * 1.30,
        )
        gradient.setColorAt(0.0, QColor(PIECE_IVORY))
        gradient.setColorAt(0.72, QColor(PIECE_IVORY))
        gradient.setColorAt(1.0, QColor(PIECE_IVORY_DEEP))
        painter.setBrush(gradient)
        painter.setPen(
            QPen(QColor(WOOD_BORDER_COLOR), max(1.0, spacing * 0.018))
        )
        painter.drawEllipse(center, radius, radius)

        ink = (
            PIECE_RED_INK
            if piece.side is Side.RED
            else PIECE_BLACK_INK
        )
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(ink), max(0.8, spacing * 0.015)))
        painter.drawEllipse(center, radius * 0.78, radius * 0.78)

        painter.setFont(
            make_piece_font(int(radius * PIECE_GLYPH_SIZE_RATIO))
        )
        painter.setPen(QColor(ink))
        text_rect = QRectF(
            center.x() - radius,
            center.y() - radius,
            radius * 2.0,
            radius * 2.0,
        )
        painter.drawText(
            text_rect,
            int(Qt.AlignmentFlag.AlignCenter),
            piece.glyph,
        )
        painter.restore()

    def _draw_pieces(self, painter: QPainter) -> None:
        skip = (
            self._animation.move.target
            if self._animation is not None
            else None
        )
        for row in range(BOARD_ROWS):
            for col in range(BOARD_COLS):
                if skip is not None and (row, col) == skip:
                    continue
                piece = self._view.board[row][col]
                if piece is None:
                    continue
                self._paint_piece(
                    painter,
                    self._point_for(row, col),
                    piece,
                )

    def _draw_captured_ghost(self, painter: QPainter) -> None:
        animation = self._animation
        if animation is None or animation.captured is None:
            return
        progress = self.animation_progress()
        alpha = max(0.0, 1.0 - progress * 1.25)
        if alpha <= 0.0:
            return
        self._paint_piece(
            painter,
            self._point_for(*animation.move.target),
            animation.captured,
            radius_scale=1.0 - progress * 0.08,
            alpha=alpha,
        )

    def _draw_moving_piece(self, painter: QPainter) -> None:
        animation = self._animation
        if animation is None:
            return
        progress = self.animation_progress()
        eased = progress * progress * (3.0 - 2.0 * progress)
        origin = self._point_for(*animation.move.origin)
        target = self._point_for(*animation.move.target)
        lift = (
            math.sin(math.pi * eased)
            * self._geometry.spacing
            * MOVE_LIFT_SPACING_RATIO
        )
        center = QPointF(
            origin.x() + (target.x() - origin.x()) * eased,
            origin.y() + (target.y() - origin.y()) * eased - lift,
        )
        scale = 1.0 + math.sin(math.pi * eased) * 0.06
        self._paint_piece(
            painter,
            center,
            animation.piece,
            radius_scale=scale,
        )

    def _draw_effect(self, painter: QPainter) -> None:
        if not self._effects:
            return
        effect = self._effects[0]
        now = time.monotonic()
        start = effect.start_time if effect.start_time > 0.0 else now
        progress = max(
            0.0, min(1.0, (now - start) / effect.duration)
        )
        if progress <= 0.0:
            return
        spec = _EFFECT_SPECS.get(effect.kind)
        if spec is None:
            return
        _text, _duration, size_ratio, color = spec
        spacing = self._geometry.spacing
        center = self._geometry.grid_rect.center()

        alpha_in = min(1.0, progress / 0.15)
        alpha_out = (
            1.0 if progress < 0.70 else max(0.0, (1.0 - progress) / 0.30)
        )
        alpha = alpha_in * alpha_out
        pop = min(1.0, progress / 0.22)
        scale = 0.55 + 0.55 * (1.0 - (1.0 - pop) ** 3)

        painter.save()
        painter.setOpacity(alpha)

        radius = spacing * (0.85 + 0.75 * progress)
        glow = QRadialGradient(center, radius)
        glow.setColorAt(0.0, _color(PAPER_LIGHT, 238))
        glow.setColorAt(0.62, _color(PAPER_LIGHT, 185))
        glow.setColorAt(1.0, _color(PAPER_LIGHT, 0))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(glow)
        painter.drawEllipse(center, radius, radius)

        if effect.kind == "capture":
            length = spacing * 1.15 * scale
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(
                QPen(
                    _color(CINNABAR, 185),
                    max(2.0, spacing * 0.07),
                    Qt.PenStyle.SolidLine,
                    Qt.PenCapStyle.RoundCap,
                )
            )
            painter.drawLine(
                QPointF(center.x() - length, center.y() + length * 0.55),
                QPointF(center.x() + length, center.y() - length * 0.55),
            )
        elif effect.kind == "check":
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(
                QPen(_color(CINNABAR, 135), max(1.5, spacing * 0.045))
            )
            painter.drawEllipse(
                center, radius * 0.72, radius * 0.72
            )
            painter.setPen(
                QPen(_color(CINNABAR, 70), max(0.8, spacing * 0.02))
            )
            painter.drawEllipse(
                center, radius * 0.82, radius * 0.82
            )
        else:  # checkmate
            painter.setBrush(Qt.BrushStyle.NoBrush)
            for index in range(3):
                ring_radius = spacing * (
                    0.55 + index * 0.32 + progress * 0.95
                )
                ring_color = GOLD if index % 2 else CINNABAR
                painter.setPen(
                    QPen(
                        _color(ring_color, int(155 * (1.0 - progress))),
                        max(1.5, spacing * 0.035),
                    )
                )
                painter.drawEllipse(
                    center, ring_radius, ring_radius
                )
            painter.setPen(
                QPen(_color(GOLD, 190), max(1.5, spacing * 0.04))
            )
            line_y = center.y() + spacing * 0.72
            painter.drawLine(
                QPointF(center.x() - spacing * 1.0, line_y),
                QPointF(center.x() + spacing * 1.0, line_y),
            )

        font = QFont()
        font.setFamilies(["Ma Shan Zheng", "KaiTi", "FangSong"])
        font.setPixelSize(
            max(1, int(spacing * size_ratio * scale))
        )
        font.setWeight(QFont.Weight.Bold)
        painter.setFont(font)
        text_rect = QRectF(
            center.x() - spacing * 2.2,
            center.y() - spacing * 1.1,
            spacing * 4.4,
            spacing * 2.2,
        )
        painter.setPen(_color(INK, 95))
        painter.drawText(
            text_rect.translated(0.0, max(1.0, spacing * 0.045)),
            int(Qt.AlignmentFlag.AlignCenter),
            effect.text,
        )
        painter.setPen(QColor(color))
        painter.drawText(
            text_rect,
            int(Qt.AlignmentFlag.AlignCenter),
            effect.text,
        )
        painter.restore()

    def _draw_selection(self, painter: QPainter) -> None:
        selected = self._view.selected
        if selected is None:
            return
        center = self._point_for(*selected)
        radius = self._piece_radius() * 1.10
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(
            QPen(QColor(SELECTION_COLOR), max(1.2, self._geometry.spacing * 0.040))
        )
        painter.drawEllipse(center, radius, radius)
        painter.setPen(
            QPen(_color(SELECTION_COLOR, 110), max(0.8, self._geometry.spacing * 0.014))
        )
        painter.drawEllipse(center, radius * 1.08, radius * 1.08)

    def _draw_legal_targets(self, painter: QPainter) -> None:
        spacing = self._geometry.spacing
        for target in self._view.legal_targets:
            row, col = target
            center = self._point_for(row, col)
            if self._view.board[row][col] is None:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(_color(LEGAL_TARGET_COLOR, 185))
                dot = spacing * 0.105
                painter.drawEllipse(center, dot, dot)
            else:
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.setPen(
                    QPen(_color(LEGAL_TARGET_COLOR, 210), max(1.2, spacing * 0.042))
                )
                ring = spacing * 0.37
                painter.drawEllipse(center, ring, ring)

    def _draw_hover(self, painter: QPainter) -> None:
        if (
            not self._interaction_enabled
            or self._hover_cell is None
            or self._animation is not None
        ):
            return
        center = self._point_for(*self._hover_cell)
        radius = self._piece_radius() * 1.04
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(
            QPen(_color(SELECTION_COLOR, 85), max(1.0, self._geometry.spacing * 0.028))
        )
        painter.drawEllipse(center, radius, radius)

    # ------------------------------------------------------------------
    # 动效时序
    # ------------------------------------------------------------------
    def _start_move_animation(
        self,
        move: Move,
        move_count: int,
    ) -> None:
        piece = self._view.board[move.to_row][move.to_col]
        if piece is None:
            self._cancel_animation()
            return
        self._clear_effects()
        self._animation = _MoveAnimation(
            move=move,
            piece=piece,
            captured=move.captured,
            move_count=move_count,
            start_time=time.monotonic(),
            duration=MOVE_ANIMATION_SECONDS,
        )
        self._ensure_frame_timer()

    def _cancel_animation(self) -> None:
        self._animation = None

    def _clear_effects(self) -> None:
        self._effects.clear()

    def _ensure_frame_timer(self) -> None:
        if not self._frame_timer.isActive():
            self._frame_timer.start()

    def _on_frame_tick(self) -> None:
        now = time.monotonic()
        if self._animation is not None:
            if (
                now - self._animation.start_time
                >= self._animation.duration
            ):
                self._animation = None

        while self._effects:
            first = self._effects[0]
            if first.start_time <= 0.0:
                first.start_time = now
            if now - first.start_time < first.duration:
                break
            self._effects.pop(0)
            if self._effects:
                self._effects[0].start_time = now

        if self._animation is None and not self._effects:
            self._frame_timer.stop()
        self.update()

    def _update_cursor(self, cell: Optional[tuple[int, int]]) -> None:
        if cell is None:
            self.unsetCursor()
            return
        row, col = cell
        piece = self._view.board[row][col]
        if (piece is not None and piece.side is self._view.side_to_move) or (
            cell in self._view.legal_targets
        ):
            self.setCursor(Qt.CursorShape.PointingHandCursor)
        else:
            self.unsetCursor()


__all__ = ["BoardWidget", "CANNON_POINTS", "PAWN_POINTS", "PALACE_DIAGONALS"]
