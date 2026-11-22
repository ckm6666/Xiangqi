"""声音控制按钮：静音开关与背景音乐/音效音量滑块。

主窗口与联机页各放一个 SoundButton，它们共享同一个应用级 AudioManager，
并通过 ``state_changed`` 信号保持图标与滑块状态一致。
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMenu,
    QSlider,
    QToolButton,
    QVBoxLayout,
    QWidget,
    QWidgetAction,
)

from xiangqi.client.audio import AudioManager, get_audio_manager
from xiangqi.client.ui_theme import make_sound_icon


class SoundButton(QToolButton):
    """一个紧凑的“声音设置”下拉按钮。

    点击后弹出菜单：静音勾选 + 两条音量滑块。图标随静音状态切换，
    所有实例通过 AudioManager 的信号互相同步。
    """

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        *,
        manager: Optional[AudioManager] = None,
    ) -> None:
        super().__init__(parent)
        self._manager = manager or get_audio_manager()
        self._syncing = False

        self.setObjectName("soundButton")
        self.setAutoRaise(True)
        self.setIconSize(QSize(18, 18))
        self.setFixedSize(34, 30)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self.setPopupMode(
            QToolButton.ToolButtonPopupMode.InstantPopup
        )
        self.setAccessibleName("声音设置")

        self._menu = QMenu(self)
        self._menu.setObjectName("soundMenu")

        self._mute_action = QAction("静音", self._menu)
        self._mute_action.setCheckable(True)
        self._mute_action.toggled.connect(self._on_mute_toggled)
        self._menu.addAction(self._mute_action)
        self._menu.addSeparator()

        self._bgm_slider, self._bgm_value = self._add_volume_row(
            "背景音乐音量", self._on_bgm_volume_changed
        )
        self._sfx_slider, self._sfx_value = self._add_volume_row(
            "音效音量", self._on_sfx_volume_changed
        )
        self._sfx_slider.sliderReleased.connect(self._preview_sfx)

        self.setMenu(self._menu)
        self._menu.aboutToShow.connect(self._sync_from_manager)
        self._manager.state_changed.connect(self._sync_from_manager)
        self._sync_from_manager()

    # ------------------------------------------------------------------
    # 构建
    # ------------------------------------------------------------------
    def _add_volume_row(
        self, title: str, handler
    ) -> tuple[QSlider, QLabel]:
        container = QWidget(self._menu)
        container.setObjectName("volumeRow")
        container.setMinimumWidth(238)

        layout = QVBoxLayout(container)
        layout.setContentsMargins(12, 6, 12, 6)
        layout.setSpacing(2)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(6)

        label = QLabel(title, container)
        label.setObjectName("volumeLabel")
        value_label = QLabel(container)
        value_label.setObjectName("volumeValue")
        value_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )

        header.addWidget(label)
        header.addStretch(1)
        header.addWidget(value_label)

        slider = QSlider(Qt.Orientation.Horizontal, container)
        slider.setObjectName("volumeSlider")
        slider.setRange(0, 100)
        slider.setSingleStep(5)
        slider.setPageStep(10)
        slider.setTracking(False)
        slider.valueChanged.connect(handler)

        layout.addLayout(header)
        layout.addWidget(slider)

        action = QWidgetAction(self._menu)
        action.setDefaultWidget(container)
        self._menu.addAction(action)
        return slider, value_label

    # ------------------------------------------------------------------
    # 交互
    # ------------------------------------------------------------------
    def _on_mute_toggled(self, muted: bool) -> None:
        if self._syncing:
            return
        self._manager.set_muted(muted)

    def _on_bgm_volume_changed(self, value: int) -> None:
        if self._syncing:
            return
        self._manager.set_bgm_volume(value)

    def _on_sfx_volume_changed(self, value: int) -> None:
        if self._syncing:
            return
        self._manager.set_sfx_volume(value)

    def _preview_sfx(self) -> None:
        self._manager.play_move()

    # ------------------------------------------------------------------
    # 同步
    # ------------------------------------------------------------------
    def _sync_from_manager(self) -> None:
        if self._syncing:
            return
        self._syncing = True
        try:
            muted = self._manager.muted
            bgm_volume = self._manager.bgm_volume
            sfx_volume = self._manager.sfx_volume

            self._mute_action.setChecked(muted)
            self._bgm_slider.setValue(bgm_volume)
            self._sfx_slider.setValue(sfx_volume)
            self._bgm_value.setText(f"{bgm_volume}%")
            self._sfx_value.setText(f"{sfx_volume}%")

            icon_size = 18
            self.setIcon(
                QIcon(
                    make_sound_icon(
                        muted,
                        icon_size,
                        dpr=max(1.0, self.devicePixelRatioF()),
                    )
                )
            )

            if not self._manager.available:
                self.setEnabled(False)
                self.setToolTip("当前环境不支持声音")
            else:
                self.setEnabled(True)
                self.setToolTip(
                    "声音设置（已静音）" if muted else "声音设置"
                )
        finally:
            self._syncing = False


__all__ = ["SoundButton"]
