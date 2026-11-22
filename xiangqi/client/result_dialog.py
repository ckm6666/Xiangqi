"""古风终局弹窗：胜利 / 惜败 / 和棋。

弹窗不再创建独立窗口，而是作为主窗口内的一层模态遮罩（见
:mod:`xiangqi.client.modal_overlay`），因此应用全局始终只有一个窗口。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from xiangqi.client.modal_overlay import (
    RESULT_ACCEPTED,
    ModalOverlay,
)
from xiangqi.client.ui_theme import (
    make_ink_divider,
    make_seal_pixmap,
    render_result_backdrop,
)

ResultKind = Literal["win", "lose", "draw"]

#: 终局卡片尺寸（逻辑像素）；与旧独立对话框的观感保持一致。
CARD_WIDTH: int = 480
CARD_HEIGHT: int = 400


@dataclass(frozen=True)
class ResultPresentation:
    """终局弹窗的展示内容。"""

    kind: ResultKind
    title: str
    subtitle: str
    detail: str
    seal_text: str
    primary_text: str = "再来一局"
    secondary_text: str = "查看棋盘"


class ResultDialog(ModalOverlay):
    """模态终局弹窗；接受表示再来一局，拒绝表示查看棋盘。"""

    def __init__(
        self,
        presentation: ResultPresentation,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent, object_name="resultDialog")
        self._presentation = presentation

        card = self.card
        card.setObjectName("resultCard")
        card.setFixedSize(CARD_WIDTH, CARD_HEIGHT)
        card.set_renderer(
            lambda size, dpr: render_result_backdrop(
                size, dpr, presentation.kind
            )
        )

        layout = QVBoxLayout(card)
        layout.setContentsMargins(40, 26, 40, 24)
        layout.setSpacing(6)

        dpr = card.devicePixelRatioF()
        self.seal_label = QLabel(card)
        self.seal_label.setObjectName("resultSeal")
        self.seal_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.seal_label.setPixmap(
            make_seal_pixmap(
                presentation.seal_text, 54, variant=presentation.kind, dpr=dpr
            )
        )

        self.title_label = QLabel(presentation.title, card)
        self.title_label.setObjectName("resultTitle")
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.subtitle_label = QLabel(presentation.subtitle, card)
        self.subtitle_label.setObjectName("resultSubtitle")
        self.subtitle_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.subtitle_label.setWordWrap(True)

        self.divider_label = QLabel(card)
        self.divider_label.setObjectName("resultDivider")
        self.divider_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.divider_label.setPixmap(make_ink_divider(190, 16, dpr=dpr))

        self.detail_label = QLabel(presentation.detail, card)
        self.detail_label.setObjectName("resultDetail")
        self.detail_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.detail_label.setWordWrap(True)

        layout.addWidget(self.seal_label)
        layout.addWidget(self.title_label)
        layout.addWidget(self.subtitle_label)
        layout.addWidget(self.divider_label)
        layout.addWidget(self.detail_label)
        layout.addStretch(1)

        buttons = QHBoxLayout()
        buttons.setSpacing(14)
        buttons.addStretch(1)
        self.restart_button = QPushButton(presentation.primary_text, card)
        self.restart_button.setObjectName("resultPrimaryButton")
        self.restart_button.setDefault(True)
        self.restart_button.setAutoDefault(True)
        self.restart_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.restart_button.setMinimumWidth(112)
        self.restart_button.setMinimumHeight(38)
        self.view_button = QPushButton(presentation.secondary_text, card)
        self.view_button.setObjectName("resultSecondaryButton")
        self.view_button.setAutoDefault(False)
        self.view_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.view_button.setMinimumWidth(112)
        self.view_button.setMinimumHeight(38)
        buttons.addWidget(self.restart_button)
        buttons.addWidget(self.view_button)
        buttons.addStretch(1)
        layout.addLayout(buttons)

        self.restart_button.clicked.connect(self.accept)
        self.view_button.clicked.connect(self.reject)
        self.set_default_action(self.accept)
        self.restart_button.setFocus()

    # ------------------------------------------------------------------
    # 语义
    # ------------------------------------------------------------------
    @property
    def restart_requested(self) -> bool:
        """用户是否选择再来一局。"""
        return self.result() == RESULT_ACCEPTED


__all__ = [
    "CARD_HEIGHT",
    "CARD_WIDTH",
    "ResultDialog",
    "ResultKind",
    "ResultPresentation",
]
