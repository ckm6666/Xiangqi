"""主窗口内的模态遮罩层。

设计原则
--------
应用全局只保留一个原生窗口。终局弹窗、确认框这类原本的模态对话框，
统一改成覆盖在主窗口中央部件之上的控件：一层半透明墨色遮罩 + 居中的
宣纸卡片。它仍然按"模态"方式工作（嵌套事件循环 + 拦截鼠标），但不再
创建第二个原生窗口，任务栏始终只有一个条目。

对外接口与 QDialog 保持一致的部分：

* ``exec()``：进入嵌套事件循环，返回 1（接受）或 0（拒绝）；
* ``accept()`` / ``reject()`` / ``done(code)``；
* ``result()``：最近一次结果码，语义与 ``QDialog.DialogCode`` 一致；
* ``isModal()``：恒为 True。

与 QDialog 的差异：没有 ``setWindowTitle``，不会出现在任务栏或
Alt+Tab 列表里；Esc 键等价于"取消"。
"""

from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtCore import QEvent, QEventLoop, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QKeyEvent, QPainter, QPixmap
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from xiangqi.client.ui_theme import (
    make_seal_pixmap,
    render_result_backdrop,
)

#: 遮罩颜色：半透明墨色，压暗底层棋盘，让卡片成为唯一视觉焦点。
SCRIM_COLOR: QColor = QColor(26, 22, 17, 118)

#: 结果码，与 QDialog.DialogCode 数值一致。
RESULT_ACCEPTED: int = 1
RESULT_REJECTED: int = 0


class PaperCard(QWidget):
    """模态层中央的宣纸卡片：尺寸变化时重绘自绘背景。

    ``renderer`` 接收 ``(QSize, dpr)`` 并返回背景 ``QPixmap``；由具体的
    弹窗决定背景（胜/负/和的色调不同）。
    """

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        *,
        renderer: Optional[Callable[[QSize, float], QPixmap]] = None,
        object_name: str = "modalCard",
    ) -> None:
        super().__init__(parent)
        self._renderer = renderer
        self._pixmap: Optional[QPixmap] = None
        self._key: Optional[tuple[int, int, float]] = None

        self.setObjectName(object_name)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self.setAutoFillBackground(False)

    def set_renderer(
        self, renderer: Callable[[QSize, float], QPixmap]
    ) -> None:
        """替换背景渲染器并立即重绘。"""
        self._renderer = renderer
        self._pixmap = None
        self._key = None
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt 接口
        del event
        width = self.width()
        height = self.height()
        if width <= 0 or height <= 0:
            return
        dpr = max(1.0, self.devicePixelRatioF())
        key = (width, height, round(dpr, 3))
        if self._pixmap is None or self._key != key:
            renderer = self._renderer
            self._pixmap = (
                renderer(QSize(width, height), dpr)
                if renderer is not None
                else QPixmap()
            )
            self._key = key
        painter = QPainter(self)
        painter.drawPixmap(
            QRectF(0, 0, width, height),
            self._pixmap,
            QRectF(self._pixmap.rect()),
        )
        painter.end()


class ModalOverlay(QWidget):
    """覆盖在宿主控件之上的模态层。

    宿主通常是主窗口的中央部件。遮罩层随宿主尺寸变化自动铺满，鼠标
    点击被遮罩拦截，因此底层棋盘不会在弹窗期间被误操作。
    """

    def __init__(
        self,
        host: Optional[QWidget] = None,
        *,
        object_name: str = "modalOverlay",
    ) -> None:
        super().__init__(host)
        self._host = host
        self._loop: Optional[QEventLoop] = None
        self._result: int = RESULT_REJECTED
        self._default_action: Optional[Callable[[], None]] = None

        self.setObjectName(object_name)
        # 遮罩必须自己画满整块区域：不透明绘制事件保证底层像素不会被
        # 背景擦除，半透明墨色叠加后正好把棋盘压暗。
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self.setAutoFillBackground(False)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        if host is not None:
            host.installEventFilter(self)
            self.setGeometry(host.rect())
        self.hide()

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.card = PaperCard(self)
        outer.addStretch(1)
        outer.addWidget(self.card, 0, Qt.AlignmentFlag.AlignCenter)
        outer.addStretch(1)

        # 宿主窗口被关闭时遮罩会随之销毁；此时必须结束嵌套事件循环，
        # 否则 exec() 会一直等下去，进程无法退出。
        self.destroyed.connect(self._on_destroyed)

    def _on_destroyed(self) -> None:
        loop = self._loop
        if loop is not None:
            loop.quit()

    # ------------------------------------------------------------------
    # 宿主联动
    # ------------------------------------------------------------------
    def eventFilter(self, obj, event) -> bool:  # noqa: N802 - Qt 接口
        """宿主尺寸变化时同步遮罩范围。"""
        if obj is self._host and event.type() == QEvent.Type.Resize:
            self.setGeometry(self._host.rect())
        return super().eventFilter(obj, event)

    def set_default_action(self, action: Optional[Callable[[], None]]) -> None:
        """设置回车键的默认动作（与 QDialog 的默认按钮等价）。"""
        self._default_action = action

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------
    def show_overlay(self) -> None:
        """铺满宿主并显示遮罩。"""
        if self._host is not None:
            self.setGeometry(self._host.rect())
            self.raise_()
        self.show()
        self.setFocus(Qt.FocusReason.OtherFocusReason)

    def hide_overlay(self) -> None:
        """隐藏遮罩。"""
        self.hide()

    def exec(self) -> int:
        """进入嵌套事件循环，直到用户接受或拒绝。"""
        self._result = RESULT_REJECTED
        self.show_overlay()
        loop = QEventLoop(self)
        self._loop = loop
        try:
            loop.exec()
        finally:
            self._loop = None
        self.hide_overlay()
        return self._result

    # ------------------------------------------------------------------
    # 语义
    # ------------------------------------------------------------------
    def accept(self) -> None:
        """确认：结果码置为接受。"""
        self.done(RESULT_ACCEPTED)

    def reject(self) -> None:
        """取消：结果码置为拒绝。"""
        self.done(RESULT_REJECTED)

    def done(self, code: int) -> None:
        """结束模态循环并记录结果码。"""
        self._result = int(code)
        if self._loop is not None:
            self._loop.quit()

    def result(self) -> int:
        """返回最近一次结果码（1 接受 / 0 拒绝）。"""
        return self._result

    def isModal(self) -> bool:  # noqa: N802 - Qt 接口
        """模态层始终是模态的（与 QDialog.isModal 语义一致）。"""
        return True

    # ------------------------------------------------------------------
    # 绘制与按键
    # ------------------------------------------------------------------
    def paintEvent(self, event) -> None:  # noqa: N802 - Qt 接口
        del event
        painter = QPainter(self)
        painter.fillRect(self.rect(), SCRIM_COLOR)
        painter.end()

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        """Esc 取消，回车触发默认动作。"""
        key = event.key()
        if key == Qt.Key.Key_Escape:
            self.reject()
            event.accept()
            return
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            action = self._default_action
            if action is not None:
                action()
                event.accept()
                return
        super().keyPressEvent(event)


class NoticeOverlay(ModalOverlay):
    """窗口内的提示遮罩：一条消息 + 一个“知道了”按钮。

    用于取代 ``QMessageBox``——后者是真正的原生窗口，会破坏“全局只保留
    一个窗口”的原则。
    """

    def __init__(
        self,
        title: str,
        message: str,
        *,
        parent: Optional[QWidget] = None,
        seal_text: str = "示",
    ) -> None:
        super().__init__(parent, object_name="noticeDialog")

        card = self.card
        card.setObjectName("noticeCard")
        card.setFixedSize(420, 250)
        card.set_renderer(
            lambda size, dpr: render_result_backdrop(size, dpr, "draw")
        )

        layout = QVBoxLayout(card)
        layout.setContentsMargins(36, 22, 36, 22)
        layout.setSpacing(6)

        dpr = card.devicePixelRatioF()
        self.seal_label = QLabel(card)
        self.seal_label.setObjectName("noticeSeal")
        self.seal_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.seal_label.setPixmap(
            make_seal_pixmap(seal_text, 40, variant="confirm", dpr=dpr)
        )

        self.title_label = QLabel(title, card)
        self.title_label.setObjectName("noticeTitle")
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.message_label = QLabel(message, card)
        self.message_label.setObjectName("noticeMessage")
        self.message_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.message_label.setWordWrap(True)

        layout.addWidget(self.seal_label)
        layout.addWidget(self.title_label)
        layout.addWidget(self.message_label)
        layout.addStretch(1)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.ok_button = QPushButton("知道了", card)
        self.ok_button.setObjectName("resultPrimaryButton")
        self.ok_button.setAutoDefault(False)
        self.ok_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.ok_button.setMinimumWidth(112)
        self.ok_button.setMinimumHeight(38)
        buttons.addWidget(self.ok_button)
        buttons.addStretch(1)
        layout.addLayout(buttons)

        self.ok_button.clicked.connect(self.accept)
        self.set_default_action(self.accept)
        self.ok_button.setFocus()


__all__ = [
    "RESULT_ACCEPTED",
    "RESULT_REJECTED",
    "SCRIM_COLOR",
    "ModalOverlay",
    "NoticeOverlay",
    "PaperCard",
]
