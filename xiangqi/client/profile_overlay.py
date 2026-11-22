"""玩家资料窗口（窗口内模态遮罩）。

查看自己时展示头像、昵称、称号、积分、战绩、胜率与成就，并可在内置
默认头像之间切换或上传自定义头像；查看他人时只读展示资料，并根据好
友关系显示「申请加好友 / 同意好友申请 / 已是好友」按钮。好友列表与
申请统一放在独立的「好友」窗口中。
"""

from __future__ import annotations

import logging
from typing import Optional

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from xiangqi.client.avatars import (
    encode_png_bytes,
    load_avatar_image,
    pixmap_from_png_bytes,
    render_default_avatar,
)
from xiangqi.client.modal_overlay import ModalOverlay
from xiangqi.client.net.profile_api import ProfileApi
from xiangqi.client.ui_theme import render_result_backdrop
from xiangqi.shared.profile import DEFAULT_AVATAR_IDS

logger = logging.getLogger(__name__)

AVATAR_DISPLAY_SIZE = 92


class ProfileOverlay(ModalOverlay):
    """个人资料窗口；``nickname`` 为空表示查看自己。"""

    def __init__(
        self,
        api: Optional[ProfileApi],
        base_url: str,
        token: str,
        nickname: Optional[str] = None,
        *,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent, object_name="profileDialog")
        self._api = api if api is not None else ProfileApi(self)
        if self._api.parent() is None:
            self._api.setParent(self)
        self._base_url = base_url
        self._token = token
        self._nickname = nickname
        self._is_self = nickname is None
        self._profile: Optional[dict] = None
        self._relationship = "self" if self._is_self else "none"
        self._avatar_pixmap = render_default_avatar(
            DEFAULT_AVATAR_IDS[0],
            AVATAR_DISPLAY_SIZE,
            dpr=self._dpr(),
        )
        self._custom_avatar_requested = False
        self._profile_changed = False
        self._avatar_buttons: dict[str, QPushButton] = {}

        self._api.profile_loaded.connect(self._on_profile_loaded)
        self._api.profile_updated.connect(self._on_profile_updated)
        self._api.player_loaded.connect(self._on_player_loaded)
        self._api.friend_request_sent.connect(
            self._on_friend_request_sent
        )
        self._api.friend_request_resolved.connect(
            self._on_friend_resolved
        )
        self._api.avatar_loaded.connect(self._on_avatar_loaded)
        self._api.failed.connect(self._on_failed)

        self._build_ui()
        if self._is_self:
            self._api.fetch_profile(self._base_url, self._token)
        else:
            self._api.fetch_player_profile(
                self._base_url, self._token, str(nickname)
            )

    # ------------------------------------------------------------------
    # 对外结果
    # ------------------------------------------------------------------
    @property
    def profile(self) -> Optional[dict]:
        """关闭时最新的资料（未成功加载时为 None）。"""
        return self._profile

    @property
    def avatar_pixmap(self) -> QPixmap:
        """当前头像位图，供大厅预览复用。"""
        return self._avatar_pixmap

    @property
    def profile_changed(self) -> bool:
        return self._profile_changed

    @property
    def is_self(self) -> bool:
        return self._is_self

    # ------------------------------------------------------------------
    # 界面
    # ------------------------------------------------------------------
    def _dpr(self) -> float:
        return max(1.0, self.devicePixelRatioF())

    def _build_ui(self) -> None:
        card = self.card
        card.setObjectName("profileCard")
        card.setFixedSize(660, 600)
        card.set_renderer(
            lambda size, dpr: render_result_backdrop(size, dpr, "draw")
        )

        layout = QVBoxLayout(card)
        layout.setContentsMargins(30, 20, 30, 18)
        layout.setSpacing(8)

        header = QHBoxLayout()
        header.setSpacing(16)
        self.avatar_label = QLabel(card)
        self.avatar_label.setObjectName("profileAvatar")
        self.avatar_label.setFixedSize(
            AVATAR_DISPLAY_SIZE, AVATAR_DISPLAY_SIZE
        )
        self.avatar_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.avatar_label.setPixmap(self._avatar_pixmap)

        identity = QVBoxLayout()
        identity.setContentsMargins(0, 4, 0, 0)
        identity.setSpacing(2)
        self.name_label = QLabel("加载中…", card)
        self.name_label.setObjectName("profileName")
        self.identity_label = QLabel("正在读取玩家资料", card)
        self.identity_label.setObjectName("profileIdentity")
        self.record_label = QLabel("", card)
        self.record_label.setObjectName("profileRecord")
        self.progress_label = QLabel("", card)
        self.progress_label.setObjectName("profileProgress")
        self.progress_label.setWordWrap(True)
        identity.addWidget(self.name_label)
        identity.addWidget(self.identity_label)
        identity.addWidget(self.record_label)
        identity.addWidget(self.progress_label)

        header.addWidget(
            self.avatar_label, 0, Qt.AlignmentFlag.AlignTop
        )
        header.addLayout(identity, 1)

        self.refresh_button = QPushButton("刷新资料", card)
        self.refresh_button.setObjectName("smallButton")
        self.refresh_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.refresh_button.clicked.connect(self._refresh)
        header.addWidget(
            self.refresh_button, 0, Qt.AlignmentFlag.AlignTop
        )
        layout.addLayout(header)

        self.status_label = QLabel("", card)
        self.status_label.setObjectName("profileStatus")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_label.setWordWrap(True)
        self.status_label.setMinimumHeight(18)
        self.status_label.setProperty("error", "false")
        layout.addWidget(self.status_label)

        self._stat_labels: dict[str, QLabel] = {}
        stats_row = QHBoxLayout()
        stats_row.setSpacing(8)
        for key, caption in (
            ("rating", "积分"),
            ("record", "战绩"),
            ("win_rate", "胜率"),
            ("streak", "最高连胜"),
        ):
            tile = QFrame(card)
            tile.setObjectName("profileStatTile")
            tile_layout = QVBoxLayout(tile)
            tile_layout.setContentsMargins(10, 7, 10, 7)
            tile_layout.setSpacing(1)
            value = QLabel("—", tile)
            value.setObjectName("profileStatValue")
            value.setAlignment(Qt.AlignmentFlag.AlignCenter)
            name = QLabel(caption, tile)
            name.setObjectName("profileStatCaption")
            name.setAlignment(Qt.AlignmentFlag.AlignCenter)
            tile_layout.addWidget(value)
            tile_layout.addWidget(name)
            self._stat_labels[key] = value
            stats_row.addWidget(tile, 1)
        layout.addLayout(stats_row)

        scroll = QScrollArea(card)
        scroll.setObjectName("profileScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        body = QWidget(scroll)
        body.setObjectName("profileScrollBody")
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(2, 2, 8, 2)
        body_layout.setSpacing(8)

        self.avatar_section = QWidget(body)
        avatar_section_layout = QVBoxLayout(self.avatar_section)
        avatar_section_layout.setContentsMargins(0, 0, 0, 0)
        avatar_section_layout.setSpacing(6)

        avatar_title = QLabel("头像", self.avatar_section)
        avatar_title.setObjectName("sectionTitle")
        avatar_section_layout.addWidget(avatar_title)

        avatar_row = QHBoxLayout()
        avatar_row.setSpacing(6)
        for index, avatar_id in enumerate(DEFAULT_AVATAR_IDS, start=1):
            button = QPushButton(self.avatar_section)
            button.setObjectName("avatarChoice")
            button.setProperty("selected", "false")
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setFixedSize(48, 48)
            button.setIcon(
                QIcon(
                    render_default_avatar(
                        avatar_id, 36, dpr=self._dpr()
                    )
                )
            )
            button.setIconSize(QSize(36, 36))
            button.setToolTip(f"默认头像 {index}")
            button.setAccessibleName(f"默认头像 {index}")
            button.clicked.connect(
                lambda _checked=False, value=avatar_id: self._choose_avatar(
                    value
                )
            )
            self._avatar_buttons[avatar_id] = button
            avatar_row.addWidget(button)

        self.upload_button = QPushButton("上传头像", self.avatar_section)
        self.upload_button.setObjectName("smallButton")
        self.upload_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.upload_button.setMinimumHeight(36)
        self.upload_button.setToolTip(
            "选择本地图片，裁剪为正方形后上传（PNG，最大 512 KB）"
        )
        self.upload_button.clicked.connect(self._upload_avatar)
        avatar_row.addSpacing(6)
        avatar_row.addWidget(self.upload_button)
        avatar_row.addStretch(1)
        avatar_section_layout.addLayout(avatar_row)
        body_layout.addWidget(self.avatar_section)
        self.avatar_section.setVisible(self._is_self)

        self.achievement_title = QLabel("成就", body)
        self.achievement_title.setObjectName("sectionTitle")
        body_layout.addWidget(self.achievement_title)
        self.achievement_container = QWidget(body)
        self.achievement_grid = QGridLayout(self.achievement_container)
        self.achievement_grid.setContentsMargins(0, 0, 0, 0)
        self.achievement_grid.setHorizontalSpacing(6)
        self.achievement_grid.setVerticalSpacing(6)
        body_layout.addWidget(self.achievement_container)
        body_layout.addStretch(1)

        scroll.setWidget(body)
        layout.addWidget(scroll, 1)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.friend_button = QPushButton("申请加好友", card)
        self.friend_button.setObjectName("profileFriendButton")
        self.friend_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.friend_button.setMinimumWidth(128)
        self.friend_button.setMinimumHeight(38)
        self.friend_button.clicked.connect(
            self._on_friend_button_clicked
        )
        self.friend_button.setVisible(False)
        buttons.addWidget(self.friend_button)

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
        """按宿主尺寸调整卡片，避免在小窗口下溢出。"""
        host = self.parentWidget()
        if host is not None:
            width = min(660, max(520, host.width() - 36))
            height = min(600, max(480, host.height() - 36))
            self.card.setFixedSize(width, height)
        super().show_overlay()

    # ------------------------------------------------------------------
    # 数据填充
    # ------------------------------------------------------------------
    def _refresh(self) -> None:
        self._set_status("正在刷新…")
        if self._is_self:
            self._api.fetch_profile(self._base_url, self._token)
        else:
            self._api.fetch_player_profile(
                self._base_url, self._token, str(self._nickname)
            )

    def _on_profile_loaded(self, data: object) -> None:
        if self._is_self and isinstance(data, dict):
            self._custom_avatar_requested = False
            self._apply_profile(data)
            self._set_status("")

    def _on_profile_updated(self, data: object) -> None:
        if self._is_self and isinstance(data, dict):
            # 重新上传自定义头像后必须重新拉取图片，不能复用旧缓存标记。
            self._custom_avatar_requested = False
            self._apply_profile(data)
            self._profile_changed = True
            self._set_status("头像已更新")

    def _on_player_loaded(self, data: object) -> None:
        if not self._is_self and isinstance(data, dict):
            self._custom_avatar_requested = False
            self._apply_profile(data)
            self._set_status("")

    def _apply_profile(self, data: dict) -> None:
        self._profile = dict(data)
        nickname = str(data.get("nickname", "棋友"))
        title = str(data.get("title", "棋童"))
        rating = int(data.get("rating", 1200))
        self.name_label.setText(nickname)
        self.identity_label.setText(f"{title} · 排位 {rating} 分")
        self._stat_labels["rating"].setText(str(rating))
        self._stat_labels["record"].setText(
            str(data.get("record_text", "0胜 0和 0负"))
        )
        win_rate = data.get("win_rate", 0.0)
        try:
            win_rate_text = f"{float(win_rate):.1f}%"
        except (TypeError, ValueError):
            win_rate_text = "0.0%"
        self._stat_labels["win_rate"].setText(win_rate_text)
        try:
            best_streak = int(data.get("best_streak", 0))
        except (TypeError, ValueError):
            best_streak = 0
        self._stat_labels["streak"].setText(str(best_streak))
        next_info = data.get("next_title")
        if isinstance(next_info, dict):
            name = str(next_info.get("name", ""))
            try:
                minimum = int(next_info.get("min_rating", 0))
            except (TypeError, ValueError):
                minimum = 0
            gap = max(0, minimum - rating)
            self.progress_label.setText(
                f"再得 {gap} 分晋升「{name}」"
            )
        else:
            self.progress_label.setText("已达到最高称号")

        avatar_id = str(data.get("avatar", DEFAULT_AVATAR_IDS[0]))
        if self._is_self:
            self._update_avatar_choice(avatar_id)
        if avatar_id.startswith("default:"):
            self._set_avatar_pixmap(
                render_default_avatar(
                    avatar_id,
                    AVATAR_DISPLAY_SIZE,
                    dpr=self._dpr(),
                )
            )
            self._custom_avatar_requested = False
        else:
            if not self._custom_avatar_requested:
                self._custom_avatar_requested = True
                self._api.fetch_avatar(self._base_url, nickname)

        self._populate_achievements(data.get("achievements", []))
        if not self._is_self:
            relationship = data.get("relationship")
            if isinstance(relationship, str):
                self._relationship = relationship
            self._update_friend_button()

    def _update_avatar_choice(self, avatar_id: str) -> None:
        for key, button in self._avatar_buttons.items():
            selected = "true" if key == avatar_id else "false"
            if button.property("selected") != selected:
                button.setProperty("selected", selected)
                button.style().unpolish(button)
                button.style().polish(button)

    def _set_avatar_pixmap(self, pixmap: QPixmap) -> None:
        self._avatar_pixmap = pixmap
        self.avatar_label.setPixmap(pixmap)

    def _update_friend_button(self) -> None:
        if self._is_self:
            self.friend_button.setVisible(False)
            return
        self.friend_button.setVisible(True)
        self.friend_button.setEnabled(True)
        if self._relationship == "friend":
            self.friend_button.setText("已是好友")
            self.friend_button.setEnabled(False)
        elif self._relationship == "pending_out":
            self.friend_button.setText("已发送申请")
            self.friend_button.setEnabled(False)
        elif self._relationship == "pending_in":
            self.friend_button.setText("同意好友申请")
        elif self._relationship == "self":
            self.friend_button.setVisible(False)
        else:
            self.friend_button.setText("申请加好友")

    def _populate_achievements(self, items: object) -> None:
        while self.achievement_grid.count():
            child = self.achievement_grid.takeAt(0)
            widget = child.widget()
            if widget is not None:
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()
        if not isinstance(items, list):
            items = []
        earned = 0
        for index, item in enumerate(items):
            if not isinstance(item, dict):
                continue
            is_earned = bool(item.get("earned"))
            if is_earned:
                earned += 1
            chip = QLabel(self.achievement_container)
            chip.setObjectName("achievementChip")
            chip.setProperty("earned", "true" if is_earned else "false")
            chip.setText(
                ("★ " if is_earned else "☆ ")
                + str(item.get("name", "成就"))
            )
            chip.setToolTip(str(item.get("description", "")))
            chip.setAlignment(Qt.AlignmentFlag.AlignCenter)
            chip.setMinimumHeight(28)
            self.achievement_grid.addWidget(
                chip, index // 3, index % 3
            )
        self.achievement_title.setText(
            f"成就 {earned}/{len(items)}"
        )

    # ------------------------------------------------------------------
    # 操作
    # ------------------------------------------------------------------
    def _choose_avatar(self, avatar_id: str) -> None:
        if not self._is_self:
            return
        self._set_status("正在保存头像…")
        self._api.choose_default_avatar(
            self._base_url, self._token, avatar_id
        )

    def _upload_avatar(self) -> None:
        if not self._is_self:
            return
        path, _selected = QFileDialog.getOpenFileName(
            self,
            "选择头像图片",
            "",
            "图片 (*.png *.jpg *.jpeg *.bmp *.webp)",
        )
        if not path:
            return
        try:
            image = load_avatar_image(path)
            data = encode_png_bytes(image, 256)
        except ValueError as exc:
            self._set_status(f"读取图片失败：{exc}", error=True)
            return
        if len(data) > 512 * 1024:
            self._set_status("头像文件过大，请选择更小的图片", True)
            return
        self._set_status("正在上传头像…")
        self._api.upload_avatar(self._base_url, self._token, data)

    def _on_friend_button_clicked(self) -> None:
        if self._is_self or not self._nickname:
            return
        if self._relationship == "pending_in":
            self.friend_button.setEnabled(False)
            self._set_status("正在同意好友申请…")
            self._api.accept_friend(
                self._base_url, self._token, str(self._nickname)
            )
            return
        if self._relationship not in ("none", "pending_in"):
            return
        self.friend_button.setEnabled(False)
        self._set_status("正在发送好友申请…")
        self._api.request_friend(
            self._base_url, self._token, str(self._nickname)
        )

    def _on_friend_request_sent(self, data: object) -> None:
        if not isinstance(data, dict) or self._is_self:
            return
        relationship = data.get("relationship")
        if isinstance(relationship, str):
            self._relationship = relationship
        self._update_friend_button()
        if self._relationship == "friend":
            self._set_status("已添加好友")
        else:
            self._set_status("好友申请已发送，等待对方同意")

    def _on_friend_resolved(self, data: object) -> None:
        if not isinstance(data, dict) or self._is_self:
            return
        relationship = data.get("relationship", "friend")
        if isinstance(relationship, str):
            self._relationship = relationship
        self._update_friend_button()
        self._set_status("已添加好友")

    def _on_avatar_loaded(self, data: bytes) -> None:
        pixmap = pixmap_from_png_bytes(
            data, AVATAR_DISPLAY_SIZE, dpr=self._dpr()
        )
        if pixmap is not None:
            self._set_avatar_pixmap(pixmap)

    def _on_failed(self, message: str) -> None:
        if not self._is_self:
            self._update_friend_button()
        self._set_status(f"操作失败：{message}", True)

    def _set_status(self, text: str, error: bool = False) -> None:
        self.status_label.setText(text)
        value = "true" if error else "false"
        if self.status_label.property("error") != value:
            self.status_label.setProperty("error", value)
            self.status_label.style().unpolish(self.status_label)
            self.status_label.style().polish(self.status_label)
            self.status_label.update()


__all__ = ["AVATAR_DISPLAY_SIZE", "ProfileOverlay"]
