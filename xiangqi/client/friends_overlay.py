"""好友窗口：好友列表、收到的申请与我发出的申请。"""

from __future__ import annotations

import logging
from typing import Optional

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
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


class FriendsOverlay(ModalOverlay):
    """好友与好友申请管理窗口。"""

    profile_requested = Signal(str)
    #: 好友昵称、头像标识、是否在线
    chat_requested = Signal(str, str, bool)

    def __init__(
        self,
        api: Optional[ProfileApi],
        base_url: str,
        token: str,
        *,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent, object_name="friendsDialog")
        self._api = api if api is not None else ProfileApi(self)
        if self._api.parent() is None:
            self._api.setParent(self)
        self._base_url = base_url
        self._token = token
        self._avatar_buttons: dict[str, QPushButton] = {}
        self._friends: list[dict] = []
        self._incoming: list[dict] = []
        self._outgoing: list[dict] = []
        self._search_results: list[dict] = []
        self._search_query = ""

        self._api.friends_loaded.connect(self._on_loaded)
        self._api.search_loaded.connect(self._on_search_loaded)
        self._api.friend_request_resolved.connect(
            self._on_friend_resolved
        )
        self._api.avatar_for_loaded.connect(self._on_avatar_loaded)
        self._api.failed.connect(self._on_failed)
        self._build_ui()
        self._refresh()

    @property
    def _dpr(self) -> float:
        return max(1.0, self.devicePixelRatioF())

    # ------------------------------------------------------------------
    # 界面
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        card = self.card
        card.setObjectName("friendsCard")
        card.setFixedSize(650, 640)
        card.set_renderer(
            lambda size, dpr: render_result_backdrop(size, dpr, "draw")
        )
        layout = QVBoxLayout(card)
        layout.setContentsMargins(30, 20, 30, 18)
        layout.setSpacing(8)

        header = QHBoxLayout()
        titles = QVBoxLayout()
        titles.setContentsMargins(0, 0, 0, 0)
        titles.setSpacing(0)
        title = QLabel("好友", card)
        title.setObjectName("leaderboardTitle")
        subtitle = QLabel(
            "在排行榜点击玩家头像，进入对方资料申请加好友", card
        )
        subtitle.setObjectName("onlineSubtitle")
        titles.addWidget(title)
        titles.addWidget(subtitle)
        header.addLayout(titles, 1)
        self.refresh_button = QPushButton("刷新", card)
        self.refresh_button.setObjectName("smallButton")
        self.refresh_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.refresh_button.clicked.connect(self._refresh)
        header.addWidget(
            self.refresh_button, 0, Qt.AlignmentFlag.AlignTop
        )
        layout.addLayout(header)

        search_row = QHBoxLayout()
        search_row.setSpacing(8)
        self.search_input = QLineEdit(card)
        self.search_input.setObjectName("onlineInput")
        self.search_input.setPlaceholderText("输入昵称搜索玩家")
        self.search_input.setMaxLength(20)
        self.search_input.setMinimumHeight(32)
        self.search_input.returnPressed.connect(self._run_search)
        self.search_button = QPushButton("搜索", card)
        self.search_button.setObjectName("smallButton")
        self.search_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.search_button.setMinimumHeight(32)
        self.search_button.clicked.connect(self._run_search)
        search_row.addWidget(self.search_input, 1)
        search_row.addWidget(self.search_button)
        layout.addLayout(search_row)

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
        self._body_layout = QVBoxLayout(body)
        self._body_layout.setContentsMargins(2, 2, 8, 2)
        self._body_layout.setSpacing(6)
        self._body_layout.addStretch(1)
        scroll.setWidget(body)
        layout.addWidget(scroll, 1)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.close_button = QPushButton("关闭", card)
        self.close_button.setObjectName("resultPrimaryButton")
        self.close_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.close_button.setMinimumWidth(112)
        self.close_button.setMinimumHeight(38)
        self.close_button.clicked.connect(self.accept)
        buttons.addWidget(self.close_button)
        buttons.addStretch(1)
        layout.addLayout(buttons)
        self.set_default_action(self.accept)
        self.close_button.setFocus()

    def show_overlay(self) -> None:
        host = self.parentWidget()
        if host is not None:
            width = min(650, max(520, host.width() - 36))
            height = min(640, max(480, host.height() - 36))
            self.card.setFixedSize(width, height)
        super().show_overlay()

    def refresh(self) -> None:
        """重新读取好友与申请（也供资料窗口关闭后自动刷新）。"""
        self._refresh()
        if self._search_query:
            self._api.search_players(
                self._base_url,
                self._token,
                self._search_query,
            )

    def _refresh(self) -> None:
        self._set_status("正在读取好友列表…")
        self._api.fetch_friends(self._base_url, self._token)

    # ------------------------------------------------------------------
    # 数据
    # ------------------------------------------------------------------
    def _on_loaded(self, data: object) -> None:
        if not isinstance(data, dict):
            return
        self._friends = self._as_players(data.get("friends"))
        self._incoming = self._as_players(data.get("incoming"))
        self._outgoing = self._as_players(data.get("outgoing"))
        self._render()
        self._set_status(
            f"好友 {len(self._friends)} 位 · "
            f"待处理申请 {len(self._incoming)} 条"
        )

    @staticmethod
    def _as_players(value: object) -> list[dict]:
        if not isinstance(value, list):
            return []
        return [item for item in value if isinstance(item, dict)]

    def _run_search(self) -> None:
        query = self.search_input.text().strip()
        if not query:
            self._set_status("请输入要搜索的昵称", True)
            return
        self._search_query = query
        self._search_results = []
        self._set_status(f"正在搜索「{query}」…")
        self._api.search_players(
            self._base_url, self._token, query
        )

    def _on_search_loaded(self, data: object) -> None:
        if not isinstance(data, dict):
            return
        query = str(data.get("query", "")).strip()
        if query:
            self._search_query = query
        self._search_results = self._as_players(
            data.get("players")
        )
        self._render()
        self._set_status(
            f"找到 {len(self._search_results)} 位玩家"
            if self._search_results
            else "没有找到匹配的玩家"
        )

    def _render(self) -> None:
        self._clear_body()
        self._avatar_buttons.clear()
        if self._search_query:
            self._add_search_section()
        self._add_section(
            "收到的申请", self._incoming, incoming=True
        )
        self._add_section(
            "我发出的申请", self._outgoing, outgoing=True
        )
        self._add_section("好友列表", self._friends, friends=True)
        self._body_layout.addStretch(1)

    def _add_search_section(self) -> None:
        section = QLabel(
            f"搜索结果：{self._search_query}", self
        )
        section.setObjectName("sectionTitle")
        self._body_layout.addWidget(section)
        if not self._search_results:
            empty = QLabel("没有找到匹配的玩家", self)
            empty.setObjectName("friendsEmpty")
            self._body_layout.addWidget(empty)
            return
        for player in self._search_results:
            relationship = str(player.get("relationship", "none"))
            status = {
                "pending_out": "已发送申请",
                "pending_in": "待你同意",
            }.get(relationship, "点击头像查看资料")
            self._add_row(
                player,
                incoming=False,
                outgoing=False,
                friends=False,
                status_text=None if relationship == "friend" else status,
                search=True,
            )

    def _clear_body(self) -> None:
        while self._body_layout.count():
            item = self._body_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()

    def _add_section(
        self,
        title: str,
        players: list,
        *,
        incoming: bool = False,
        outgoing: bool = False,
        friends: bool = False,
    ) -> None:
        section = QLabel(title, self)
        section.setObjectName("sectionTitle")
        self._body_layout.addWidget(section)
        valid = [item for item in players if isinstance(item, dict)]
        if not valid:
            empty = QLabel(
                "暂无好友申请"
                if incoming
                else ("暂无发出的申请" if outgoing else "暂无好友"),
                self,
            )
            empty.setObjectName("friendsEmpty")
            self._body_layout.addWidget(empty)
            return
        for player in valid:
            self._add_row(
                player,
                incoming=incoming,
                outgoing=outgoing,
                friends=friends,
            )

    def _add_row(
        self,
        player: dict,
        *,
        incoming: bool,
        outgoing: bool,
        friends: bool,
        status_text: Optional[str] = None,
        search: bool = False,
    ) -> None:
        row = QFrame(self)
        row.setObjectName("friendsRow")
        row.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        layout = QHBoxLayout(row)
        layout.setContentsMargins(10, 5, 10, 5)
        layout.setSpacing(9)

        nickname = str(player.get("nickname", "棋友"))
        avatar_id = str(player.get("avatar", "default:1"))
        online = bool(player.get("online"))
        try:
            unread = int(player.get("unread", 0) or 0)
        except (TypeError, ValueError):
            unread = 0
        relationship = str(player.get("relationship", "none"))
        avatar_button = QPushButton(row)
        avatar_button.setObjectName("leaderboardAvatar")
        avatar_button.setCursor(Qt.CursorShape.PointingHandCursor)
        avatar_button.setFixedSize(40, 40)
        avatar_button.setIconSize(QSize(36, 36))
        avatar_button.setToolTip(f"查看 {nickname} 的资料")
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
        avatar_button.clicked.connect(
            lambda _checked=False, name=nickname: (
                self.profile_requested.emit(name)
            )
        )
        self._avatar_buttons[nickname] = avatar_button

        text_col = QVBoxLayout()
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setSpacing(0)
        name_label = QLabel(nickname, row)
        name_label.setObjectName("leaderboardName")
        info = (
            f"{player.get('title', '棋童')} · "
            f"{player.get('rating', 1200)} 分"
        )
        info_label = QLabel(info, row)
        info_label.setObjectName("leaderboardTitleText")
        text_col.addWidget(name_label)
        text_col.addWidget(info_label)
        if friends or search:
            presence = QLabel(
                "● 在线" if online else "○ 离线", row
            )
            presence.setObjectName("friendPresence")
            presence.setProperty(
                "online", "true" if online else "false"
            )
            text_col.addWidget(presence)

        layout.addWidget(avatar_button)
        layout.addLayout(text_col, 1)
        if friends and unread > 0:
            badge = QLabel(f"{unread} 条未读", row)
            badge.setObjectName("friendUnread")
            layout.addWidget(badge)
        if incoming:
            accept = QPushButton("同意", row)
            accept.setObjectName("friendAcceptButton")
            accept.setCursor(Qt.CursorShape.PointingHandCursor)
            accept.setMinimumHeight(30)
            accept.clicked.connect(
                lambda _checked=False, name=nickname: self._accept(name)
            )
            decline = QPushButton("拒绝", row)
            decline.setObjectName("friendDeclineButton")
            decline.setCursor(Qt.CursorShape.PointingHandCursor)
            decline.setMinimumHeight(30)
            decline.clicked.connect(
                lambda _checked=False, name=nickname: self._decline(name)
            )
            layout.addWidget(accept)
            layout.addWidget(decline)
        elif outgoing:
            waiting = QLabel("等待对方同意", row)
            waiting.setObjectName("friendsEmpty")
            layout.addWidget(waiting)
        elif friends or (
            search and relationship == "friend"
        ):
            chat = QPushButton("聊天", row)
            chat.setObjectName("socialSecondaryButton")
            chat.setCursor(Qt.CursorShape.PointingHandCursor)
            chat.setMinimumHeight(30)
            chat.clicked.connect(
                lambda _checked=False, name=nickname, avatar=avatar_id,
                is_online=online: self.chat_requested.emit(
                    name, avatar, is_online
                )
            )
            layout.addWidget(chat)
        elif status_text:
            status = QLabel(status_text, row)
            status.setObjectName("friendsEmpty")
            layout.addWidget(status)
        self._body_layout.addWidget(row)

    # ------------------------------------------------------------------
    # 操作
    # ------------------------------------------------------------------
    def _accept(self, nickname: str) -> None:
        self._set_status("正在同意好友申请…")
        self._api.accept_friend(
            self._base_url, self._token, nickname
        )

    def _decline(self, nickname: str) -> None:
        self._set_status("正在拒绝好友申请…")
        self._api.decline_friend(
            self._base_url, self._token, nickname
        )

    def _on_friend_resolved(self, data: object) -> None:
        del data
        self._search_query = ""
        self._search_results = []
        self.search_input.clear()
        self._set_status("操作成功")
        self._refresh()

    def _on_avatar_loaded(self, nickname: str, data: bytes) -> None:
        button = self._avatar_buttons.get(nickname)
        if button is None:
            return
        pixmap = pixmap_from_png_bytes(
            data, AVATAR_SIZE, dpr=self._dpr
        )
        if pixmap is not None:
            button.setIcon(QIcon(pixmap))

    def _on_failed(self, message: str) -> None:
        self._set_status(f"操作失败：{message}", True)

    def _set_status(self, text: str, error: bool = False) -> None:
        self.status_label.setText(text)
        value = "true" if error else "false"
        if self.status_label.property("error") != value:
            self.status_label.setProperty("error", value)
            self.status_label.style().unpolish(self.status_label)
            self.status_label.style().polish(self.status_label)
            self.status_label.update()


__all__ = ["AVATAR_SIZE", "FriendsOverlay"]
