"""好友私聊窗口：历史消息与实时收发。"""

from __future__ import annotations

import html
import logging
from datetime import datetime
from typing import Mapping, Optional, Sequence

from PySide6.QtCore import QEvent, QTimer, Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from xiangqi.client.avatars import render_default_avatar
from xiangqi.client.modal_overlay import ModalOverlay
from xiangqi.client.net.chat_api import ChatApi
from xiangqi.client.ui_theme import render_result_backdrop
from xiangqi.shared.social import MAX_DIRECT_MESSAGE_LENGTH

logger = logging.getLogger(__name__)

READ_FLUSH_DELAY_MS = 120


def _avatar_id(value: object) -> str:
    text = str(value or "default:1")
    if text.startswith("default:"):
        return text
    return "default:1"


class PrivateChatOverlay(ModalOverlay):
    """与一位好友的私聊窗口。"""

    def __init__(
        self,
        api: Optional[ChatApi],
        base_url: str,
        token: str,
        nickname: str,
        self_nickname: str,
        *,
        avatar: str = "default:1",
        online: Optional[bool] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent, object_name="privateChatDialog")
        self._api = api if api is not None else ChatApi(self)
        if self._api.parent() is None:
            self._api.setParent(self)
        self._base_url = base_url
        self._token = token
        self.friend_nickname = nickname
        self.self_nickname = self_nickname
        self._avatar_id = _avatar_id(avatar)

        self._seen_ids: set[str] = set()
        # 对方发来、已经显示、但还没报给服务端销账的消息。
        self._pending_read: list[str] = []
        self._last_sent = ""
        self._placeholder_shown = False

        self._read_timer = QTimer(self)
        self._read_timer.setSingleShot(True)
        self._read_timer.setInterval(READ_FLUSH_DELAY_MS)
        self._read_timer.timeout.connect(self._flush_read)

        self._api.messages_loaded.connect(self._on_loaded)
        self._api.message_sent.connect(self._on_sent)
        self._api.failed.connect(self._on_failed)

        self._build_ui(online)
        self._api.fetch_messages(
            self._base_url, self._token, self.friend_nickname, 100
        )

    @property
    def _dpr(self) -> float:
        return max(1.0, self.devicePixelRatioF())

    # ------------------------------------------------------------------
    # 界面
    # ------------------------------------------------------------------
    def _build_ui(self, online: Optional[bool]) -> None:
        card = self.card
        card.setObjectName("privateChatCard")
        card.setFixedSize(560, 560)
        card.set_renderer(
            lambda size, dpr: render_result_backdrop(size, dpr, "draw")
        )
        layout = QVBoxLayout(card)
        layout.setContentsMargins(26, 18, 26, 16)
        layout.setSpacing(8)

        header = QHBoxLayout()
        header.setSpacing(10)
        avatar_label = QLabel(card)
        avatar_label.setFixedSize(46, 46)
        avatar_label.setPixmap(
            render_default_avatar(
                self._avatar_id, 42, dpr=self._dpr
            )
        )
        header.addWidget(avatar_label)

        identity = QVBoxLayout()
        identity.setContentsMargins(0, 0, 0, 0)
        identity.setSpacing(1)
        self.name_label = QLabel(self.friend_nickname, card)
        self.name_label.setObjectName("leaderboardTitle")
        self.online_label = QLabel(
            "在线" if online else ("离线" if online is False else ""),
            card,
        )
        self.online_label.setObjectName("profileStatus")
        subtitle = QLabel("好友私聊 · 消息会保存", card)
        subtitle.setObjectName("onlineSubtitle")
        identity.addWidget(self.name_label)
        identity.addWidget(self.online_label)
        identity.addWidget(subtitle)
        header.addLayout(identity, 1)
        layout.addLayout(header)

        self.messages_view = QTextBrowser(card)
        self.messages_view.setObjectName("chatMessages")
        self.messages_view.setOpenExternalLinks(False)
        layout.addWidget(self.messages_view, 1)

        input_row = QHBoxLayout()
        input_row.setSpacing(8)
        self.input = QLineEdit(card)
        self.input.setObjectName("chatMessageInput")
        self.input.setPlaceholderText("输入消息，回车发送")
        self.input.setMaxLength(MAX_DIRECT_MESSAGE_LENGTH)
        self.send_button = QPushButton("发送", card)
        self.send_button.setObjectName("chatSendButton")
        self.send_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.send_button.setAutoDefault(False)
        input_row.addWidget(self.input, 1)
        input_row.addWidget(self.send_button)
        layout.addLayout(input_row)

        self.status_label = QLabel(
            "私聊仅限好友 · 单条最多 200 字", card
        )
        self.status_label.setObjectName("profileStatus")
        self.status_label.setWordWrap(True)
        self.status_label.setMinimumHeight(18)

        self.close_button = QPushButton("关闭", card)
        self.close_button.setObjectName("socialSecondaryButton")
        self.close_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.close_button.setAutoDefault(False)
        self.close_button.setToolTip("关闭聊天窗口（Esc）")

        footer = QHBoxLayout()
        footer.setSpacing(10)
        footer.addWidget(self.status_label, 1)
        footer.addWidget(
            self.close_button, 0, Qt.AlignmentFlag.AlignBottom
        )
        layout.addLayout(footer)

        self.send_button.clicked.connect(self._on_send)
        self.input.returnPressed.connect(self._on_send)
        self.close_button.clicked.connect(self.accept)
        # 输入框持有焦点时 Esc 不会冒泡到遮罩层，单独拦一道。
        self.input.installEventFilter(self)

    def show_overlay(self) -> None:
        host = self.parentWidget()
        if host is not None:
            width = min(560, max(480, host.width() - 36))
            height = min(560, max(440, host.height() - 36))
            self.card.setFixedSize(width, height)
        super().show_overlay()
        self.input.setFocus()

    def set_status(self, text: str, error: bool = False) -> None:
        self.status_label.setText(text)
        value = "true" if error else "false"
        if self.status_label.property("error") != value:
            self.status_label.setProperty("error", value)
            self.status_label.style().unpolish(self.status_label)
            self.status_label.style().polish(self.status_label)
            self.status_label.update()

    # ------------------------------------------------------------------
    # 消息
    # ------------------------------------------------------------------
    def append_realtime(self, message: Mapping) -> None:
        """主窗口收到 WebSocket 私聊推送时调用。"""
        if not isinstance(message, Mapping):
            return
        if self._append(message, scroll=True):
            self._scroll_to_bottom()
            if self.isVisible():
                message_id = str(message.get("id", ""))
                if message_id:
                    self._pending_read.append(message_id)
                    self._read_timer.start()

    def set_history(self, messages: Sequence[Mapping]) -> None:
        """把服务端历史并进当前记录，按消息 id 去重。"""
        if not messages and not self._seen_ids:
            self._show_placeholder()
        added = False
        for message in messages:
            if not isinstance(message, Mapping):
                continue
            if self._append(message, scroll=False):
                added = True
            message_id = str(message.get("id", ""))
            if message_id:
                self._pending_read = [
                    pending
                    for pending in self._pending_read
                    if pending != message_id
                ]
        if added:
            self._scroll_to_bottom()

    def pending_read_ids(self) -> list[str]:
        return list(self._pending_read)

    @property
    def last_draft(self) -> str:
        return self._last_sent

    def restore_draft(self) -> None:
        if self._last_sent:
            self.input.setText(self._last_sent)
            self._last_sent = ""

    def _append(
        self,
        message: Mapping,
        *,
        scroll: bool,
    ) -> bool:
        message_id = str(message.get("id", ""))
        if message_id:
            if message_id in self._seen_ids:
                return False
            self._seen_ids.add(message_id)

        sender_name = str(message.get("sender_name", "好友"))
        is_self = sender_name == self.self_nickname

        content = html.escape(str(message.get("content", "")))
        time_text = self._format_time(message)
        align = "right" if is_self else "left"
        bubble = "#E8D5B5" if is_self else "#EFE6D5"
        name_text = "我" if is_self else sender_name
        block = (
            f'<div style="margin:6px 0;text-align:{align};">'
            f'<span style="color:#7A6A55;font-size:11px;">'
            f"{html.escape(name_text)} · {time_text}</span><br/>"
            f'<span style="background:{bubble};padding:4px 8px;'
            f'border-radius:6px;color:#2B2118;">{content}</span>'
            "</div>"
        )
        if self._placeholder_shown:
            self.messages_view.setHtml("")
            self._placeholder_shown = False
        self.messages_view.append(block)
        if scroll:
            self._scroll_to_bottom()
        return True

    @staticmethod
    def _format_time(message: Mapping) -> str:
        sent_at_ms = message.get("sent_at_ms")
        if isinstance(sent_at_ms, int) and sent_at_ms > 0:
            try:
                return datetime.fromtimestamp(
                    sent_at_ms / 1000.0
                ).strftime("%H:%M")
            except (OSError, ValueError):
                pass
        return ""

    def _show_placeholder(self) -> None:
        self._placeholder_shown = True
        self.messages_view.setHtml(
            '<div style="color:#7A6A55;text-align:center;'
            'padding:20px;">还没有聊天记录，打个招呼吧</div>'
        )

    def _scroll_to_bottom(self) -> None:
        bar = self.messages_view.verticalScrollBar()
        bar.setValue(bar.maximum())

    # ------------------------------------------------------------------
    # 发送与已读
    # ------------------------------------------------------------------
    def _on_send(self) -> None:
        text = self.input.text().strip()
        if not text:
            return
        self.input.clear()
        self._last_sent = text
        self.set_status("发送中…")
        self._api.send_message(
            self._base_url,
            self._token,
            self.friend_nickname,
            text,
        )

    def _on_sent(self, nickname: str, data: object) -> None:
        if nickname != self.friend_nickname:
            return
        self._last_sent = ""
        self.set_status("")
        if isinstance(data, Mapping):
            self._append(data, scroll=True)

    def _flush_read(self) -> None:
        ids = [
            message_id
            for message_id in self._pending_read
            if message_id
        ]
        if not ids:
            return
        self._pending_read.clear()
        self._api.mark_messages_read(
            self._base_url,
            self._token,
            self.friend_nickname,
            ids,
        )

    def _on_loaded(self, nickname: str, data: object) -> None:
        if nickname != self.friend_nickname:
            return
        messages = (
            data.get("messages", [])
            if isinstance(data, Mapping)
            else []
        )
        if isinstance(messages, list):
            self.set_history(messages)
        else:
            self.set_history([])
        self.messages_view.verticalScrollBar().setValue(
            self.messages_view.verticalScrollBar().maximum()
        )

    def _on_failed(self, nickname: str, message: str) -> None:
        if nickname != self.friend_nickname:
            return
        self.set_status(message or "发送失败", error=True)
        self.restore_draft()

    # ------------------------------------------------------------------
    # 键盘
    # ------------------------------------------------------------------
    def eventFilter(self, obj, event) -> bool:  # noqa: N802 - Qt 接口
        if (
            obj is self.input
            and event.type() == QEvent.Type.KeyPress
            and event.key() == Qt.Key.Key_Escape
        ):
            self.reject()
            return True
        return super().eventFilter(obj, event)


__all__ = ["PrivateChatOverlay", "READ_FLUSH_DELAY_MS"]
