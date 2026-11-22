"""古风确认弹窗：用于返回主菜单、重新开局、更改先手方等操作。

弹窗不再创建独立窗口，而是作为主窗口内的一层模态遮罩（见
:mod:`xiangqi.client.modal_overlay`），因此应用全局始终只有一个窗口。
"""

from __future__ import annotations

from typing import Optional

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

#: 确认卡片尺寸（逻辑像素）。
CARD_WIDTH: int = 460
CARD_HEIGHT: int = 320


class ConfirmDialog(ModalOverlay):
    """水墨宣纸风格的模态确认框。

    确认按钮文字由调用方决定（例如“返回主菜单”/“开始新对局”）；
    取消是默认按钮，Esc/关闭均视为取消，避免误触破坏当前棋局。
    """

    def __init__(
        self,
        title: str,
        message: str,
        *,
        confirm_text: str = "开始新对局",
        cancel_text: str = "取消",
        seal_text: str = "问",
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent, object_name="confirmDialog")

        card = self.card
        card.setObjectName("confirmCard")
        card.setFixedSize(CARD_WIDTH, CARD_HEIGHT)
        card.set_renderer(
            lambda size, dpr: render_result_backdrop(size, dpr, "draw")
        )

        layout = QVBoxLayout(card)
        layout.setContentsMargins(40, 22, 40, 22)
        layout.setSpacing(6)

        dpr = card.devicePixelRatioF()
        self.seal_label = QLabel(card)
        self.seal_label.setObjectName("confirmSeal")
        self.seal_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.seal_label.setPixmap(
            make_seal_pixmap(seal_text, 44, variant="confirm", dpr=dpr)
        )

        self.title_label = QLabel(title, card)
        self.title_label.setObjectName("confirmTitle")
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.message_label = QLabel(message, card)
        self.message_label.setObjectName("confirmMessage")
        self.message_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.message_label.setWordWrap(True)

        self.divider_label = QLabel(card)
        self.divider_label.setObjectName("confirmDivider")
        self.divider_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.divider_label.setPixmap(make_ink_divider(170, 14, dpr=dpr))

        layout.addWidget(self.seal_label)
        layout.addWidget(self.title_label)
        layout.addWidget(self.message_label)
        layout.addWidget(self.divider_label)
        layout.addStretch(1)

        buttons = QHBoxLayout()
        buttons.setSpacing(14)
        buttons.addStretch(1)
        self.confirm_button = QPushButton(confirm_text, card)
        self.confirm_button.setObjectName("resultPrimaryButton")
        self.confirm_button.setAutoDefault(False)
        self.confirm_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.confirm_button.setMinimumWidth(112)
        self.confirm_button.setMinimumHeight(38)
        self.cancel_button = QPushButton(cancel_text, card)
        self.cancel_button.setObjectName("resultSecondaryButton")
        self.cancel_button.setDefault(True)
        self.cancel_button.setAutoDefault(True)
        self.cancel_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.cancel_button.setMinimumWidth(112)
        self.cancel_button.setMinimumHeight(38)
        buttons.addWidget(self.confirm_button)
        buttons.addWidget(self.cancel_button)
        buttons.addStretch(1)
        layout.addLayout(buttons)

        self.confirm_button.clicked.connect(self.accept)
        self.cancel_button.clicked.connect(self.reject)
        self.set_default_action(self.reject)
        self.cancel_button.setFocus()

    @property
    def confirm_requested(self) -> bool:
        """用户是否明确确认。"""
        return self.result() == RESULT_ACCEPTED


__all__ = ["CARD_HEIGHT", "CARD_WIDTH", "ConfirmDialog"]
