"""积分/称号排行榜窗口。"""

from __future__ import annotations

import logging
from typing import Optional

from PySide6.QtCore import QSize, Qt, Signal
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

AVATAR_SIZE = 40


class LeaderboardOverlay(ModalOverlay):
    """按排位积分排序的排行榜；点击头像查看玩家资料。"""

    profile_requested = Signal(str)

    def __init__(
        self,
        api: Optional[ProfileApi],
        base_url: str,
        token: str,
        *,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent, object_name="leaderboardDialog")
        self._api = api if api is not None else ProfileApi(self)
        if self._api.parent() is None:
            self._api.setParent(self)
        self._base_url = base_url
        self._token = token
        self._players: list[dict] = []
        self._avatar_buttons: dict[str, QPushButton] = {}
        self._avatar_requested: set[str] = set()

        self._api.leaderboard_loaded.connect(self._on_loaded)
        self._api.avatar_for_loaded.connect(self._on_avatar_loaded)
        self._api.failed.connect(self._on_failed)
        self._build_ui()
        self._api.fetch_leaderboard(
            self._base_url, self._token, 1000
        )

    # ------------------------------------------------------------------
    # 界面
    # ------------------------------------------------------------------
    def _dpr(self) -> float:
        return max(1.0, self.devicePixelRatioF())

    def _build_ui(self) -> None:
        card = self.card
        card.setObjectName("leaderboardCard")
        card.setFixedSize(680, 650)
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
        title = QLabel("积分排行榜", card)
        title.setObjectName("leaderboardTitle")
        subtitle = QLabel("点击玩家头像查看资料与称号", card)
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

        self.status_label = QLabel("正在读取排行榜…", card)
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
        body.setObjectName("leaderboardBody")
        self._rows_layout = QVBoxLayout(body)
        self._rows_layout.setContentsMargins(2, 2, 8, 2)
        self._rows_layout.setSpacing(6)
        self._rows_layout.addStretch(1)
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
            width = min(680, max(540, host.width() - 36))
            height = min(650, max(480, host.height() - 36))
            self.card.setFixedSize(width, height)
        super().show_overlay()

    def _refresh(self) -> None:
        self._set_status("正在刷新排行榜…")
        self._api.fetch_leaderboard(
            self._base_url, self._token, 1000
        )

    # ------------------------------------------------------------------
    # 数据
    # ------------------------------------------------------------------
    def _on_loaded(self, data: object) -> None:
        if not isinstance(data, dict):
            return
        raw_players = data.get("players", [])
        if not isinstance(raw_players, list):
            raw_players = []
        self._players = [
            item for item in raw_players if isinstance(item, dict)
        ]
        self._clear_rows()
        self._avatar_buttons.clear()
        self._avatar_requested.clear()
        if not self._players:
            self._set_status("排行榜暂无数据")
            return
        self._set_status(
            f"共 {len(self._players)} 位棋手 · 按积分降序"
        )
        for rank, player in enumerate(self._players, start=1):
            self._add_row(rank, player)
        self._rows_layout.addStretch(1)

    def _clear_rows(self) -> None:
        while self._rows_layout.count():
            item = self._rows_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()

    def _add_row(self, rank: int, player: dict) -> None:
        row = QFrame(self)
        row.setObjectName("leaderboardRow")
        row.setProperty(
            "self", "true" if player.get("is_self") else "false"
        )
        row.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(10, 6, 12, 6)
        row_layout.setSpacing(10)

        rank_label = QLabel(str(rank), row)
        rank_label.setObjectName("leaderboardRank")
        rank_label.setProperty("top", "true" if rank <= 3 else "false")
        rank_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        rank_label.setFixedWidth(34)

        nickname = str(player.get("nickname", "棋友"))
        avatar_id = str(player.get("avatar", "default:1"))
        avatar_button = QPushButton(row)
        avatar_button.setObjectName("leaderboardAvatar")
        avatar_button.setCursor(Qt.CursorShape.PointingHandCursor)
        avatar_button.setFixedSize(44, 44)
        avatar_button.setIconSize(QSize(40, 40))
        avatar_button.setToolTip(f"查看 {nickname} 的资料")
        avatar_button.setAccessibleName(f"{nickname} 的头像")
        if avatar_id.startswith("default:"):
            avatar_button.setIcon(
                QIcon(
                    render_default_avatar(
                        avatar_id, AVATAR_SIZE, dpr=self._dpr()
                    )
                )
            )
        else:
            avatar_button.setIcon(
                QIcon(
                    render_default_avatar(
                        "default:1", AVATAR_SIZE, dpr=self._dpr()
                    )
                )
            )
            self._avatar_requested.add(nickname)
            self._api.fetch_avatar(self._base_url, nickname)
        avatar_button.clicked.connect(
            lambda _checked=False, name=nickname: self._request_profile(
                name
            )
        )
        self._avatar_buttons[nickname] = avatar_button

        text_col = QVBoxLayout()
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setSpacing(0)
        name_label = QLabel(nickname, row)
        name_label.setObjectName("leaderboardName")
        title_label = QLabel(
            str(player.get("title", "棋童")), row
        )
        title_label.setObjectName("leaderboardTitleText")
        text_col.addWidget(name_label)
        text_col.addWidget(title_label)

        rating_col = QVBoxLayout()
        rating_col.setContentsMargins(0, 0, 0, 0)
        rating_col.setSpacing(0)
        rating = player.get("rating", 1200)
        rating_label = QLabel(f"{rating} 分", row)
        rating_label.setObjectName("leaderboardRating")
        rating_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        record_label = QLabel(
            str(player.get("record_text", "0胜 0和 0负")), row
        )
        record_label.setObjectName("leaderboardRecord")
        record_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        rating_col.addWidget(rating_label)
        rating_col.addWidget(record_label)

        row_layout.addWidget(rank_label)
        row_layout.addWidget(avatar_button)
        row_layout.addLayout(text_col, 1)
        row_layout.addLayout(rating_col)
        self._rows_layout.addWidget(row)

    def _on_avatar_loaded(self, nickname: str, data: bytes) -> None:
        button = self._avatar_buttons.get(nickname)
        if button is None:
            return
        pixmap = pixmap_from_png_bytes(
            data, AVATAR_SIZE, dpr=self._dpr()
        )
        if pixmap is not None:
            button.setIcon(QIcon(pixmap))

    def _request_profile(self, nickname: str) -> None:
        self.profile_requested.emit(nickname)

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


__all__ = ["AVATAR_SIZE", "LeaderboardOverlay"]
