"""棋盘之上的弹幕 / 表情覆盖层。

控件只负责绘制动画，不参与任何交互：

* 评论以横向弹幕的形式从右边缘飞向左边缘，落在棋盘上方 38% 的三条泳道里，
  避免长时间遮挡棋盘中央；
* 表情在发送方一侧弹出（自己在下、对手在上），随后缓缓上浮并淡出。

覆盖层完全透明且不接收鼠标事件，因此可以和棋盘叠放在同一个布局单元格中，
不会吞掉落子点击。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional

from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QFontDatabase,
    QFontMetricsF,
    QPainter,
    QPen,
)
from PySide6.QtWidgets import QApplication, QWidget

# 彩色表情字体的候选族名，按优先级排列。
EMOJI_FONT_FAMILIES: tuple[str, ...] = (
    "Segoe UI Emoji",
    "Apple Color Emoji",
    "Noto Color Emoji",
    "Segoe UI Symbol",
)

# 表情字体之后的中文回退族，避免标签里的“你：”变成方块。
EMOJI_FALLBACK_FAMILIES: tuple[str, ...] = (
    "Microsoft YaHei UI",
    "Microsoft YaHei",
    "Segoe UI",
    "SimHei",
)


def _available_font_families() -> set[str]:
    """返回当前系统可用的字体族名；查询失败时返回空集合。"""
    try:
        return set(QFontDatabase.families())
    except Exception:  # pragma: no cover - 某些平台插件可能不支持
        return set()


def resolve_emoji_font_family() -> Optional[str]:
    """返回可用的彩色表情字体族名；没有可用字体时返回 None。"""
    families = _available_font_families()
    for name in EMOJI_FONT_FAMILIES:
        if name in families:
            return name
    return None


def _resolve_emoji_font(pixel_size: int) -> QFont:
    """挑选一个可用的表情字体；找不到时回退到应用默认字体。

    测试使用的 ``offscreen`` 平台插件并不会注册 ``Segoe UI Emoji``，
    因此这里必须静默回退，不能抛异常。
    """
    size = max(1, int(pixel_size))
    app = QApplication.instance()
    if app is not None:
        font = QFont(app.font())
    else:
        font = QFont()

    family = resolve_emoji_font_family()
    if family is not None:
        font.setFamilies([family, *EMOJI_FALLBACK_FAMILIES])
    font.setPixelSize(size)
    return font


@dataclass
class _TextItem:
    """一条正在飞行的评论弹幕。"""

    text: str
    from_self: bool
    lane: int = 0
    speed: float = 200.0
    start: float = field(default_factory=time.monotonic)


@dataclass
class _EmojiItem:
    """一个正在弹出的表情。"""

    emoji: str
    from_self: bool
    offset_x: float = 0.0
    start: float = field(default_factory=time.monotonic)


class DanmakuOverlay(QWidget):
    """棋盘之上的弹幕/表情覆盖层：只绘制动画，不接收鼠标事件。"""

    #: 弹幕泳道数量。
    LANE_COUNT = 3
    #: 泳道占据控件高度的比例（位于顶部）。
    LANE_HEIGHT_RATIO = 0.38
    #: 弹幕最小速度（像素/秒）。
    MIN_SPEED = 140.0
    #: 表情总时长（秒）。
    EMOJI_LIFETIME = 2.0
    #: 表情弹出动画时长（秒）。
    EMOJI_POP_TIME = 0.35
    #: 表情字号相对控件高度的比例。
    EMOJI_SIZE_RATIO = 0.13
    #: 表情字号下限（像素）。
    EMOJI_MIN_SIZE = 28

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents, True
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAutoFillBackground(False)

        self._text_items: list[_TextItem] = []
        self._emoji_items: list[_EmojiItem] = []
        self._text_counter = 0
        self._emoji_counter = 0
        # 可选的棋盘控件：弹幕以它绘制出来的正方形棋面为活动范围，
        # 否则动画会落在棋盘四周的留白里。
        self._board_widget: Optional[QWidget] = None

        # 16ms 心跳驱动动画；只在有元素在飞时才运行。
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._on_tick)

    def set_board_widget(self, widget: Optional[QWidget]) -> None:
        """绑定棋盘控件，用它的绘制区域作为弹幕的活动范围。"""
        self._board_widget = widget
        self.update()

    # ------------------------------------------------------------------
    # 对外接口
    # ------------------------------------------------------------------
    def push_text(self, text: str, from_self: bool) -> None:
        """加入一条横向飞过的评论弹幕。"""
        content = "" if text is None else str(text)
        speed = max(self._content_rect().width() / 6.0, self.MIN_SPEED)
        item = _TextItem(
            text=content,
            from_self=bool(from_self),
            lane=self._text_counter % self.LANE_COUNT,
            speed=speed,
        )
        self._text_counter += 1
        self._text_items.append(item)
        self._start_timer()
        self.update()

    def push_emoji(self, emoji: str, from_self: bool) -> None:
        """加入一个在发送方一侧弹出并淡出的表情。"""
        content = "" if emoji is None else str(emoji)
        # 偏移量由计数器推导，保证同一位置的连续表情不会完全重叠，
        # 同时保持可复现（不使用随机数）。
        offset = ((self._emoji_counter * 41) % 13 - 6) * 6.0
        self._emoji_counter += 1
        self._emoji_items.append(
            _EmojiItem(
                emoji=content,
                from_self=bool(from_self),
                offset_x=offset,
            )
        )
        self._start_timer()
        self.update()

    def _start_timer(self) -> None:
        """确保动画心跳正在运行。"""
        if not self._timer.isActive():
            self._timer.start()

    def clear(self) -> None:
        """清空所有在飞的弹幕和表情。"""
        self._text_items.clear()
        self._emoji_items.clear()
        self.update()

    def active_count(self) -> int:
        """当前在飞的元素数量（供测试断言）。"""
        self._purge_expired()
        return len(self._text_items) + len(self._emoji_items)

    # ------------------------------------------------------------------
    # 动画驱动
    # ------------------------------------------------------------------
    def _on_tick(self) -> None:
        """推进动画并请求重绘。"""
        if not self._text_items and not self._emoji_items:
            # 没有元素时停掉心跳，避免空闲时白白占用 60Hz 唤醒。
            self._timer.stop()
            return
        self._purge_expired()
        self.update()

    def _purge_expired(self) -> None:
        """移除已经飞出画面或已经淡出的元素。"""
        now = time.monotonic()
        content = self._content_rect()
        alive_text: list[_TextItem] = []
        for item in self._text_items:
            age = now - item.start
            x = content.right() - age * item.speed
            text_width = self._text_width(item.text)
            if x + text_width > content.left():
                alive_text.append(item)
        self._text_items = alive_text
        self._emoji_items = [
            item
            for item in self._emoji_items
            if now - item.start < self.EMOJI_LIFETIME
        ]

    def _content_rect(self) -> QRectF:
        """返回弹幕的活动范围。

        优先使用棋盘控件绘制出来的正方形棋面；没有绑定棋盘时退化为
        覆盖层自身。这样评论才会横穿棋盘，而不是横穿棋盘旁边的留白。
        """
        board = self._board_widget
        if board is not None:
            getter = getattr(board, "board_rect", None)
            if callable(getter):
                try:
                    rect = getter()
                except Exception:  # pragma: no cover - 防御性
                    rect = None
                if isinstance(rect, QRectF) and rect.width() > 0:
                    return rect
        return QRectF(self.rect())

    # ------------------------------------------------------------------
    # 绘制
    # ------------------------------------------------------------------
    def paintEvent(self, event) -> None:  # noqa: N802 - Qt 接口
        """只绘制在飞的元素，其余区域保持完全透明。"""
        del event
        painter = QPainter(self)
        # 先把自身画布清成透明，避免残留上一帧；必须用透明背景擦除，
        # CompositionMode_Clear 会把区域变成不透明黑块。
        painter.setBackgroundMode(Qt.BGMode.TransparentMode)
        painter.setBackground(QBrush(Qt.GlobalColor.transparent))
        painter.eraseRect(self.rect())
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

        # 只在棋面范围内绘制，弹幕从棋盘右侧进入时不会先露在棋盘外的
        # 留白里，看起来才是"横穿棋盘"。
        content = self._content_rect()
        painter.setClipRect(content)

        for item in list(self._text_items):
            self._paint_text(painter, item)
        for item in list(self._emoji_items):
            self._paint_emoji(painter, item)

        painter.end()

    def _text_font(self) -> QFont:
        """弹幕使用的正文字体。"""
        app = QApplication.instance()
        font = QFont(app.font()) if app is not None else QFont()
        font.setPixelSize(max(13, int(self.height() * 0.05)))
        return font

    def _text_width(self, text: str) -> float:
        """计算一条弹幕的像素宽度。"""
        metrics = QFontMetricsF(self._text_font())
        return float(metrics.horizontalAdvance(text))

    def _fade_alpha(self, ratio: float) -> float:
        """弹幕淡入淡出曲线：前 12% 淡入，后 30% 淡出。"""
        if ratio <= 0.0:
            return 0.0
        if ratio < 0.12:
            return ratio / 0.12
        if ratio > 0.70:
            return max(0.0, (1.0 - ratio) / 0.30)
        return 1.0

    def _paint_text(self, painter: QPainter, item: _TextItem) -> None:
        """绘制一条横向飞行的评论弹幕。"""
        font = self._text_font()
        metrics = QFontMetricsF(font)
        text_width = float(metrics.horizontalAdvance(item.text))
        text_height = float(metrics.height())
        if text_width <= 0.0:
            return

        age = max(0.0, time.monotonic() - item.start)
        content = self._content_rect()
        total = (content.width() + text_width) / max(1.0, item.speed)
        alpha = self._fade_alpha(age / total if total > 0.0 else 1.0)
        if alpha <= 0.01:
            return

        x = content.right() - age * item.speed
        lane_height = (
            content.height() * self.LANE_HEIGHT_RATIO / self.LANE_COUNT
        )
        top = content.top() + item.lane * lane_height
        top += max(0.0, (lane_height - text_height) / 2.0)

        border = QColor(184, 147, 78)
        border.setAlpha(110)
        # 弹幕会从棋盘上方掠过，而最后落子的朱砂点和胜利连线都画在
        # 棋盘这一层。底色太实会把它们盖住，所以这里保持半透明，
        # 让棋盘内容仍然透得出来。
        background = QColor(38, 32, 24, 96)

        painter.save()
        painter.setOpacity(alpha)
        painter.setPen(QPen(border, 1.0))
        painter.setBrush(background)
        painter.drawRoundedRect(
            QRectF(
                x - 7.0,
                top,
                text_width + 14.0,
                text_height + 8.0,
            ),
            7.0,
            7.0,
        )
        painter.setFont(font)
        painter.setPen(QColor(250, 246, 236))
        painter.drawText(
            QRectF(x, top + 4.0, text_width, text_height),
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            item.text,
        )
        painter.restore()

    def _emoji_scale(self, age: float) -> float:
        """表情弹出曲线：0.45 -> 1.15 -> 1.0。"""
        if age <= 0.0:
            return 0.45
        grow_end = self.EMOJI_POP_TIME * 0.45
        if age < grow_end:
            ratio = age / grow_end
            return 0.45 + (1.15 - 0.45) * ratio
        if age < self.EMOJI_POP_TIME:
            span = self.EMOJI_POP_TIME - grow_end
            ratio = (age - grow_end) / span
            return 1.15 + (1.0 - 1.15) * ratio
        return 1.0

    def _emoji_alpha(self, ratio: float) -> float:
        """表情透明度：短暂淡入，随后淡出。"""
        if ratio <= 0.0:
            return 0.0
        if ratio < 0.08:
            return ratio / 0.08
        if ratio > 0.55:
            return max(0.0, (1.0 - ratio) / 0.45)
        return 1.0

    def _paint_emoji(self, painter: QPainter, item: _EmojiItem) -> None:
        """绘制一个弹出并淡出的表情。"""
        age = max(0.0, time.monotonic() - item.start)
        ratio = age / self.EMOJI_LIFETIME
        if ratio >= 1.0:
            return
        alpha = self._emoji_alpha(ratio)
        if alpha <= 0.01:
            return

        size = max(
            self.EMOJI_MIN_SIZE,
            int(self._content_rect().height() * self.EMOJI_SIZE_RATIO),
        )
        font = _resolve_emoji_font(size)

        content = self._content_rect()
        center_x = content.center().x() + item.offset_x
        base_y = content.top() + content.height() * (
            0.74 if item.from_self else 0.18
        )
        drift = -max(0.0, age - self.EMOJI_POP_TIME) * 14.0
        center_y = base_y + drift

        painter.save()
        painter.setOpacity(alpha)
        painter.translate(center_x, center_y)
        scale = self._emoji_scale(age)
        painter.scale(scale, scale)
        painter.setFont(font)
        # 文字必须有一支实心笔：NoPen 会让 drawText 什么都不画，
        # 表情就完全看不见了。彩色字体会忽略这个颜色，
        # 单色回退字体则用墨色保证在棋面上可读。
        painter.setPen(QColor(38, 32, 24))
        painter.drawText(
            QRectF(-size, -size * 0.7, size * 2.0, size * 1.4),
            int(Qt.AlignmentFlag.AlignCenter),
            item.emoji,
        )
        painter.restore()


__all__ = [
    "EMOJI_FALLBACK_FAMILIES",
    "EMOJI_FONT_FAMILIES",
    "DanmakuOverlay",
    "resolve_emoji_font_family",
]
