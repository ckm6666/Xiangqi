"""联机对局的表情 / 评论相关控件。

包含三部分：

* :class:`ChatLogPanel` —— 只读的对话日志面板，只展示双方发过的评论与表情；
* :class:`EmojiPickerButton` —— 点击后弹出表情网格的按钮；
* :class:`PresetCommentButton` —— 点击后弹出预设评论的按钮。
"""

from __future__ import annotations

import html
from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction, QFont, QFontDatabase
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QLabel,
    QMenu,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
    QWidgetAction,
)

from xiangqi.shared.chat import (
    CHAT_KIND_EMOJI,
    COMMENT_PRESETS,
    EMOJI_PRESETS,
    ChatMessage,
)

#: 对话日志最多保留的条数，超出后丢弃最早的记录。
MAX_LOG_ENTRIES = 200

_EMOJI_FONT_FAMILIES = (
    "Segoe UI Emoji",
    "Apple Color Emoji",
    "Noto Color Emoji",
    "Segoe UI Symbol",
)


def resolve_emoji_font_family() -> Optional[str]:
    """返回系统可用的彩色表情字体名；没有时返回 None。"""
    families = set(QFontDatabase.families())
    for name in _EMOJI_FONT_FAMILIES:
        if name in families:
            return name
    return None


def resolve_emoji_font(pixel_size: int) -> QFont:
    """创建用于表情按钮/文本的字体。"""
    font = QFont()
    family = resolve_emoji_font_family()
    if family is not None:
        font.setFamily(family)
    font.setPixelSize(max(1, int(pixel_size)))
    return font


class ChatLogPanel(QFrame):
    """只读对话日志面板：显示自己与对手发送的评论和表情。"""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("chatLogPanel")
        self.setFrameShape(QFrame.Shape.NoFrame)

        self._entries: list[str] = []
        self._labels: list[QLabel] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)

        self._title = QLabel("对话日志", self)
        self._title.setObjectName("chatLogTitle")
        layout.addWidget(self._title)

        self._scroll = QScrollArea(self)
        self._scroll.setObjectName("chatLogScroll")
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        layout.addWidget(self._scroll, 1)

        self._body = QWidget(self._scroll)
        self._body.setObjectName("chatLogBody")
        self._body_layout = QVBoxLayout(self._body)
        self._body_layout.setContentsMargins(2, 2, 2, 2)
        self._body_layout.setSpacing(4)
        self._body_layout.addStretch(1)
        self._scroll.setWidget(self._body)

    # ------------------------------------------------------------------
    # 对外接口
    # ------------------------------------------------------------------
    def append_message(self, message: ChatMessage, is_self: bool) -> None:
        """追加一条日志；自己的消息右对齐暖色，对手的左对齐冷色。"""
        name = "你" if is_self else (message.sender_name or "对手")
        plain = f"{name}：{message.content}"

        label = QLabel(self._body)
        label.setObjectName("chatLogEntry")
        label.setProperty("side", "self" if is_self else "opponent")
        label.setWordWrap(True)
        label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )

        if message.kind == CHAT_KIND_EMOJI:
            self._apply_emoji_text(label, plain, message.content)
        else:
            label.setTextFormat(Qt.TextFormat.PlainText)
            label.setText(plain)

        if is_self:
            label.setAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop
            )
        else:
            label.setAlignment(
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop
            )

        self._body_layout.insertWidget(
            self._body_layout.count() - 1, label
        )
        self._entries.append(plain)
        self._labels.append(label)

        label.style().unpolish(label)
        label.style().polish(label)

        self._trim_entries()
        self._scroll_to_bottom()

    def append_notice(self, text: str) -> None:
        """追加一条系统提示（例如“发言太快”）。"""
        label = QLabel(self._body)
        label.setObjectName("chatLogNotice")
        label.setWordWrap(True)
        label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        label.setText(text or "")
        label.setAlignment(
            Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignTop
        )
        self._body_layout.insertWidget(
            self._body_layout.count() - 1, label
        )
        self._entries.append(text or "")
        self._labels.append(label)
        self._trim_entries()
        self._scroll_to_bottom()

    def clear_log(self) -> None:
        """清空全部日志。"""
        for label in self._labels:
            self._body_layout.removeWidget(label)
            label.setParent(None)
            label.deleteLater()
        self._labels.clear()
        self._entries.clear()

    def entry_texts(self) -> list[str]:
        """按顺序返回每条日志的纯文本（供测试断言）。"""
        return list(self._entries)

    def entry_count(self) -> int:
        """当前保留的日志条数。"""
        return len(self._entries)

    # ------------------------------------------------------------------
    # 内部辅助
    # ------------------------------------------------------------------
    def _apply_emoji_text(
        self, label: QLabel, plain: str, emoji: str
    ) -> None:
        """用富文本渲染表情，让表情字形使用解析出的彩色字体。"""
        prefix = plain[: len(plain) - len(emoji)] if emoji else plain
        family = resolve_emoji_font_family()
        if family is None:
            label.setTextFormat(Qt.TextFormat.PlainText)
            label.setText(plain)
            label.setFont(resolve_emoji_font(16))
            return

        style = f"font-family:'{family}'; font-size:16px;"
        label.setTextFormat(Qt.TextFormat.RichText)
        label.setText(
            f"{html.escape(prefix)}"
            f'<span style="{style}">{html.escape(emoji)}</span>'
        )

    def _trim_entries(self) -> None:
        while len(self._entries) > MAX_LOG_ENTRIES:
            label = self._labels.pop(0)
            self._entries.pop(0)
            self._body_layout.removeWidget(label)
            label.setParent(None)
            label.deleteLater()

    def _scroll_to_bottom(self) -> None:
        bar = self._scroll.verticalScrollBar()
        bar.setValue(bar.maximum())


class EmojiPickerButton(QPushButton):
    """表情按钮：点击后弹出表情网格菜单。"""

    emoji_picked = Signal(str)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("emojiPickerButton")
        self.setText("表情")

        self._menu = QMenu(self)
        self._menu.setObjectName("chatMenu")
        self._grid_host = QWidget(self._menu)
        self._grid = QGridLayout(self._grid_host)
        self._grid.setContentsMargins(6, 6, 6, 6)
        self._grid.setSpacing(4)

        emoji_font = resolve_emoji_font(19)
        for index, emoji in enumerate(EMOJI_PRESETS):
            button = QPushButton(emoji, self._grid_host)
            button.setObjectName("emojiGridButton")
            button.setFixedSize(36, 36)
            button.setFont(emoji_font)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setToolTip("发送这个表情")
            button.clicked.connect(
                lambda _checked=False, item=emoji: (
                    self.emoji_picked.emit(item)
                )
            )
            self._grid.addWidget(button, index // 4, index % 4)

        action = QWidgetAction(self._menu)
        action.setDefaultWidget(self._grid_host)
        self._menu.addAction(action)
        self.setMenu(self._menu)

    def set_emoji_enabled(self, enabled: bool) -> None:
        self.setEnabled(bool(enabled))


class PresetCommentButton(QPushButton):
    """快捷评论按钮：点击后弹出预设评论菜单。"""

    comment_picked = Signal(str)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("presetCommentButton")
        self.setText("快捷评论")

        self._menu = QMenu(self)
        self._menu.setObjectName("chatMenu")
        for text in COMMENT_PRESETS:
            action = QAction(text, self._menu)
            action.triggered.connect(
                lambda _checked=False, item=text: (
                    self.comment_picked.emit(item)
                )
            )
            self._menu.addAction(action)
        self.setMenu(self._menu)


__all__ = [
    "MAX_LOG_ENTRIES",
    "ChatLogPanel",
    "EmojiPickerButton",
    "PresetCommentButton",
    "resolve_emoji_font",
    "resolve_emoji_font_family",
]
