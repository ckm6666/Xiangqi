"""基于 QtWebSockets 的联机传输实现。"""

from __future__ import annotations

import json
import logging
from typing import Optional

from PySide6.QtCore import QUrl
from PySide6.QtNetwork import QAbstractSocket
from PySide6.QtWebSockets import QWebSocket

from xiangqi.client.transport import Transport

logger = logging.getLogger(__name__)


class WebSocketTransport(Transport):
    """把 QWebSocket 的文本消息转换为协议字典。"""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._url = ""
        self._socket = QWebSocket(parent=self)
        self._socket.connected.connect(self.connected.emit)
        self._socket.disconnected.connect(self.disconnected.emit)
        self._socket.textMessageReceived.connect(self._on_text)
        self._socket.errorOccurred.connect(self._on_error)

    @property
    def url(self) -> str:
        return self._url

    @property
    def is_connected(self) -> bool:
        return (
            self._socket.state()
            == QAbstractSocket.SocketState.ConnectedState
        )

    def open(self, url: str) -> None:
        parsed = QUrl(url)
        if parsed.scheme() not in ("ws", "wss") or not parsed.host():
            self.error.emit("服务器地址必须是 ws:// 或 wss:// URL")
            return
        self._url = url
        self._socket.open(parsed)

    def send_message(self, message: object) -> None:
        if not self.is_connected:
            self.error.emit("尚未连接服务器")
            return
        try:
            text = json.dumps(message, ensure_ascii=False)
        except (TypeError, ValueError):
            self.error.emit("消息无法序列化")
            return
        self._socket.sendTextMessage(text)

    def close(self) -> None:
        self._socket.close()

    def _on_text(self, text: str) -> None:
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            self.error.emit("服务器返回了非 JSON 消息")
            return
        if not isinstance(data, dict):
            self.error.emit("服务器消息必须是 JSON 对象")
            return
        self.message_received.emit(data)

    def _on_error(
        self,
        error: QAbstractSocket.SocketError,
    ) -> None:
        del error
        message = self._socket.errorString()
        logger.warning("WebSocket 错误：%s", message)
        self.error.emit(message or "WebSocket 连接错误")


__all__ = ["WebSocketTransport"]
