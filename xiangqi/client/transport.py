"""联机传输抽象（当前版本占位）。

未来 QtWebSocket 实现与测试 FakeTransport 都实现该接口；会话层只依赖
这些信号，不直接接触 QWebSocket。
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QObject, Signal


class Transport(QObject):
    """消息传输抽象。"""

    connected = Signal()
    disconnected = Signal()
    message_received = Signal(object)
    error = Signal(str)

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)

    def open(self, url: str) -> None:
        """建立连接；后续版本实现。"""
        raise NotImplementedError("联机传输将在后续版本实现")

    def send_message(self, message: object) -> None:
        """发送协议消息；后续版本实现。"""
        raise NotImplementedError("联机传输将在后续版本实现")

    def close(self) -> None:
        """关闭连接；后续版本实现。"""
        raise NotImplementedError("联机传输将在后续版本实现")


__all__ = ["Transport"]
