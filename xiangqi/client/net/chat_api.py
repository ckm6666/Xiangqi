"""好友私聊 REST 客户端（QtNetwork 异步）。"""

from __future__ import annotations

import json
import logging
from typing import Callable, Optional
from urllib.parse import quote

from PySide6.QtCore import QObject, QUrl, Signal
from PySide6.QtNetwork import (
    QNetworkAccessManager,
    QNetworkReply,
    QNetworkRequest,
)

logger = logging.getLogger(__name__)


class ChatApi(QObject):
    """读取历史、发送消息与标记已读。"""

    #: 昵称, ``{"messages": [...]}``
    messages_loaded = Signal(str, object)
    #: 昵称, 新消息条目
    message_sent = Signal(str, object)
    #: 昵称, ``{"read_count": N}``
    messages_read = Signal(str, object)
    #: 昵称, 中文错误
    failed = Signal(str, str)

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._manager = QNetworkAccessManager(self)

    # ------------------------------------------------------------------
    # 公开接口
    # ------------------------------------------------------------------
    def fetch_messages(
        self,
        base_url: str,
        token: str,
        nickname: str,
        limit: int = 50,
    ) -> None:
        count = max(1, min(200, int(limit)))
        self._request(
            "GET",
            self._url(
                base_url,
                "/api/v1/messages"
                f"?nickname={quote(nickname, safe='')}"
                f"&limit={count}",
            ),
            token,
            None,
            lambda data, name=nickname: self.messages_loaded.emit(
                name, data
            ),
            lambda message, name=nickname: self.failed.emit(
                name, message
            ),
        )

    def send_message(
        self,
        base_url: str,
        token: str,
        nickname: str,
        content: str,
    ) -> None:
        body = json.dumps(
            {"content": content}, ensure_ascii=False
        ).encode("utf-8")
        self._request(
            "POST",
            self._url(
                base_url,
                "/api/v1/messages"
                f"?nickname={quote(nickname, safe='')}",
            ),
            token,
            body,
            lambda data, name=nickname: self.message_sent.emit(
                name, data
            ),
            lambda message, name=nickname: self.failed.emit(
                name, message
            ),
        )

    def mark_messages_read(
        self,
        base_url: str,
        token: str,
        nickname: str,
        message_ids: list[str],
    ) -> None:
        ids = [
            str(item)
            for item in message_ids
            if isinstance(item, str) and item
        ][:200]
        if not ids:
            return
        body = json.dumps(
            {"message_ids": ids}, ensure_ascii=False
        ).encode("utf-8")
        self._request(
            "POST",
            self._url(
                base_url,
                "/api/v1/messages/read"
                f"?nickname={quote(nickname, safe='')}",
            ),
            token,
            body,
            lambda data, name=nickname: self.messages_read.emit(
                name, data
            ),
            lambda message, name=nickname: self.failed.emit(
                name, message
            ),
        )

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------
    @staticmethod
    def _url(base_url: str, path: str) -> str:
        return f"{base_url.rstrip('/')}{path}"

    def _request(
        self,
        method: str,
        url: str,
        token: str,
        body: Optional[bytes],
        on_success: Callable[[dict], None],
        on_error: Callable[[str], None],
    ) -> None:
        request = QNetworkRequest(QUrl(url))
        request.setRawHeader(
            b"Authorization", f"Bearer {token}".encode("utf-8")
        )
        if body is not None:
            request.setHeader(
                QNetworkRequest.KnownHeaders.ContentTypeHeader,
                "application/json",
            )
        if method == "POST":
            reply = self._manager.post(request, body or b"")
        else:
            reply = self._manager.get(request)
        reply.finished.connect(
            lambda current=reply: self._finish(
                current, on_success, on_error
            )
        )

    def _finish(
        self,
        reply: QNetworkReply,
        on_success: Callable[[dict], None],
        on_error: Callable[[str], None],
    ) -> None:
        status = reply.attribute(
            QNetworkRequest.Attribute.HttpStatusCodeAttribute
        )
        raw = bytes(reply.readAll())
        has_error = (
            reply.error() != QNetworkReply.NetworkError.NoError
        )
        error_string = reply.errorString()
        reply.deleteLater()

        data: dict = {}
        if raw:
            try:
                parsed = json.loads(
                    raw.decode("utf-8", errors="replace")
                )
                if isinstance(parsed, dict):
                    data = parsed
            except json.JSONDecodeError:
                data = {}

        if status == 200:
            on_success(data)
            return

        detail = data.get("detail")
        if isinstance(detail, str) and detail:
            message = detail
        elif has_error:
            message = error_string
        else:
            body_text = raw.decode(
                "utf-8", errors="replace"
            ).strip()
            message = body_text or f"请求失败（HTTP {status}）"
        logger.warning("私聊请求失败：%s", message)
        on_error(message)


__all__ = ["ChatApi"]
