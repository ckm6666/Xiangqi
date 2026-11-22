"""自建房邀请好友窗口。"""

from __future__ import annotations

import logging
from typing import Optional

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from xiangqi.client.avatars import (
    pixmap_from_png_bytes,
    render_default_avatar,
)
from xiangqi.client.modal_overlay import ModalOverlay
from xiangqi.client.net.profile_api import ProfileApi
from xiangqi.client.ui_theme import render_result_backdrop

logger = logging.getLogger(__name__)

AVATAR_SIZE = 38


class InviteFriendOverlay(ModalOverlay):
    """自建房等待阶段邀请好友。"""

    def __init__(
        self,
        api: Optional[ProfileApi],
        base_url: str,
        token: str,
        session: object,
        *,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent, object_name="inviteDialog")
        self._api = api if api is not None else ProfileApi(self)
        if self._api.parent() is None:
            self._api.setParent(self)
        self._base_url = base_url
        self._token = token
        self._session = session
        self._avatar_buttons: dict[str, QPushButton] = {}
        self._invite_buttons: list[QPushButton] = []

        self._api.friends_loaded.connect(self._on_friends_loaded)
        self._api.avatar_for_loaded.connect(self._on_avatar_loaded)
        self._api.failed.connect(self._on_failed)
        invite_status = getattr(session, "invite_status", None)
        if invite_status is not None:
            invite_status.connect(self._on_invite_status)
        invite_result = getattr(session, "invite_result", None)
        if invite_result is not None:
            invite_result.connect(self._on_invite_result)
        self._build_ui()
        self._api.fetch_friends(self._base_url, self._token)

    @property
    def _dpr(self) -> float:
        return max(1.0, self.devicePixelRatioF())

    # ------------------------------------------------------------------
    # 界面
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        card = self.card
        card.setObjectName("inviteCard")
        card.setFixedSize(560, 520)
        card.set_renderer(
            lambda size, dpr: render_result_backdrop(size, dpr, "draw")
        )
        layout = QVBoxLayout(card)
        layout.setContentsMargins(30, 20, 30, 18)
        layout.setSpacing(8)

        title = QLabel("邀请好友", card)
        title.setObjectName("leaderboardTitle")
        subtitle = QLabel(
            "选择好友发送挑战；对方同意后立即开始对局", card
        )
        subtitle.setObjectName("onlineSubtitle")
        subtitle.setWordWrap(True)
        layout.addWidget(title)
        layout.addWidget(subtitle)

        self.status_label = QLabel("正在读取好友列表…", card)
        self.status_label.setObjectName("profileStatus")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_label.setWordWrap(True)
        self.status_label.setMinimumHeight(18)
        self.status_label.setProperty("error", "false")
        layout.addWidget(self.status_label)

        scroll = QScrollArea(card)
        scroll.setObjectName("profileScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        body = QWidget(scroll)
        body.setObjectName("friendsBody")
        self._rows_layout = QVBoxLayout(body)
        self._rows_layout.setContentsMargins(2, 2, 8, 2)
        self._rows_layout.setSpacing(6)
        self._rows_layout.addStretch(1)
        scroll.setWidget(body)
        layout.addWidget(scroll, 1)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.close_button = QPushButton("取消邀请", card)
        self.close_button.setObjectName("menuBackButton")
        self.close_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.close_button.setMinimumWidth(112)
        self.close_button.setMinimumHeight(38)
        self.close_button.clicked.connect(self.reject)
        buttons.addWidget(self.close_button)
        buttons.addStretch(1)
        layout.addLayout(buttons)
        self.set_default_action(self.reject)
        self.close_button.setFocus()

    def show_overlay(self) -> None:
        host = self.parentWidget()
        if host is not None:
            width = min(560, max(480, host.width() - 36))
            height = min(520, max(400, host.height() - 36))
            self.card.setFixedSize(width, height)
        super().show_overlay()

    # ------------------------------------------------------------------
    # 好友列表
    # ------------------------------------------------------------------
    def _on_friends_loaded(self, data: object) -> None:
        friends = data.get("friends") if isinstance(data, dict) else None
        if not isinstance(friends, list):
            friends = []
        self._clear_rows()
        self._avatar_buttons.clear()
        self._invite_buttons.clear()
        if not friends:
            empty = QLabel(
                "暂无好友，请先在大厅「好友」或排行榜中添加",
                self,
            )
            empty.setObjectName("friendsEmpty")
            empty.setWordWrap(True)
            self._rows_layout.addWidget(empty)
            self._set_status("暂无好友可邀请")
            return
        self._set_status("选择一位好友发送挑战")
        for friend in friends:
            if isinstance(friend, dict):
                self._add_row(friend)
        self._rows_layout.addStretch(1)

    def _clear_rows(self) -> None:
        while self._rows_layout.count():
            item = self._rows_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()

    def _add_row(self, friend: dict) -> None:
        row = QFrame(self)
        row.setObjectName("friendsRow")
        row.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        row.setFixedHeight(56)
        layout = QHBoxLayout(row)
        layout.setContentsMargins(10, 5, 10, 5)
        layout.setSpacing(9)

        nickname = str(friend.get("nickname", "棋友"))
        avatar_id = str(friend.get("avatar", "default:1"))
        avatar_button = QPushButton(row)
        avatar_button.setObjectName("leaderboardAvatar")
        avatar_button.setFixedSize(40, 40)
        avatar_button.setIconSize(QSize(36, 36))
        avatar_button.setEnabled(False)
        if avatar_id.startswith("default:"):
            avatar_button.setIcon(
                QIcon(
                    render_default_avatar(
                        avatar_id, AVATAR_SIZE, dpr=self._dpr
                    )
                )
            )
        else:
            avatar_button.setIcon(
                QIcon(
                    render_default_avatar(
                        "default:1", AVATAR_SIZE, dpr=self._dpr
                    )
                )
            )
            self._api.fetch_avatar(self._base_url, nickname)
        self._avatar_buttons[nickname] = avatar_button

        text_col = QVBoxLayout()
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setSpacing(0)
        name_label = QLabel(nickname, row)
        name_label.setObjectName("leaderboardName")
        info_label = QLabel(
            f"{friend.get('title', '棋童')} · "
            f"{friend.get('rating', 1200)} 分",
            row,
        )
        info_label.setObjectName("leaderboardTitleText")
        text_col.addWidget(name_label)
        text_col.addWidget(info_label)

        invite_button = QPushButton("邀请", row)
        invite_button.setObjectName("friendAcceptButton")
        invite_button.setCursor(Qt.CursorShape.PointingHandCursor)
        invite_button.setMinimumHeight(30)
        invite_button.clicked.connect(
            lambda _checked=False, name=nickname, button=invite_button: (
                self._invite(name, button)
            )
        )
        self._invite_buttons.append(invite_button)

        layout.addWidget(avatar_button)
        layout.addLayout(text_col, 1)
        layout.addWidget(invite_button)
        self._rows_layout.addWidget(row)

    def _on_avatar_loaded(self, nickname: str, data: bytes) -> None:
        button = self._avatar_buttons.get(nickname)
        if button is None:
            return
        pixmap = pixmap_from_png_bytes(
            data, AVATAR_SIZE, dpr=self._dpr
        )
        if pixmap is not None:
            button.setIcon(QIcon(pixmap))

    # ------------------------------------------------------------------
    # 邀请
    # ------------------------------------------------------------------
    def _invite(self, nickname: str, button: QPushButton) -> None:
        inviter = getattr(self._session, "invite_friend", None)
        if not callable(inviter) or not inviter(nickname):
            self._set_status("挑战发送失败，请检查连接", True)
            return
        button.setEnabled(False)
        button.setText("已邀请")
        self._set_status(f"已向 {nickname} 发送挑战，等待回应…")

    def _on_invite_status(self, message: str) -> None:
        self._set_status(message)

    def _on_invite_result(self, accepted: bool, message: str) -> None:
        if accepted:
            self._set_status(message)
            return
        self._set_status(f"邀请失败：{message}", True)
        for button in self._invite_buttons:
            button.setEnabled(True)
            button.setText("邀请")

    def _on_failed(self, message: str) -> None:
        self._set_status(f"加载失败：{message}", True)

    def _set_status(self, text: str, error: bool = False) -> None:
        self.status_label.setText(text)
        value = "true" if error else "false"
        if self.status_label.property("error") != value:
            self.status_label.setProperty("error", value)
            self.status_label.style().unpolish(self.status_label)
            self.status_label.style().polish(self.status_label)
            self.status_label.update()


__all__ = ["AVATAR_SIZE", "InviteFriendOverlay"]
