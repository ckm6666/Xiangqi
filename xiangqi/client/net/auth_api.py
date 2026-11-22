"""REST 注册/登录客户端（QtNetwork 异步）。"""

from __future__ import annotations

import json
import logging
from typing import Optional

from PySide6.QtCore import QObject, QUrl, Signal
from PySide6.QtNetwork import (
    QNetworkAccessManager,
    QNetworkReply,
    QNetworkRequest,
)

logger = logging.getLogger(__name__)


class AuthApi(QObject):
    """调用服务端 /api/v1/auth/register 与 /login。"""

    #: token, nickname, rating
    authenticated = Signal(str, str, int)
    #: 登录后即可知的头像标识（default:N 或 custom）
    avatar_known = Signal(str)
    failed = Signal(str)

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._manager = QNetworkAccessManager(self)

    def register(
        self,
        base_url: str,
        nickname: str,
        password: str,
    ) -> None:
        self._post(base_url, "register", nickname, password)

    def login(
        self,
        base_url: str,
        nickname: str,
        password: str,
    ) -> None:
        self._post(base_url, "login", nickname, password)

    def _post(
        self,
        base_url: str,
        action: str,
        nickname: str,
        password: str,
    ) -> None:
        url = QUrl(
            f"{base_url.rstrip('/')}/api/v1/auth/{action}"
        )
        request = QNetworkRequest(url)
        request.setHeader(
            QNetworkRequest.KnownHeaders.ContentTypeHeader,
            "application/json",
        )
        body = json.dumps(
            {"nickname": nickname, "password": password},
            ensure_ascii=False,
        ).encode("utf-8")
        reply = self._manager.post(request, body)
        reply.finished.connect(
            lambda current=reply: self._on_reply(current)
        )

    def _on_reply(self, reply: QNetworkReply) -> None:
        status = reply.attribute(
            QNetworkRequest.Attribute.HttpStatusCodeAttribute
        )
        raw = bytes(reply.readAll()).decode("utf-8", errors="replace")
        reply.deleteLater()

        try:
            data = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            data = {}
        if not isinstance(data, dict):
            data = {}

        if status == 200:
            token = data.get("token")
            nickname = data.get("nickname")
            rating = data.get("rating")
            if isinstance(token, str) and token and isinstance(
                nickname, str
            ):
                self.authenticated.emit(
                    token,
                    nickname,
                    int(rating) if isinstance(rating, int) else 1200,
                )
                avatar = data.get("avatar")
                if isinstance(avatar, str) and avatar:
                    self.avatar_known.emit(avatar)
                return

        detail = data.get("detail")
        if isinstance(detail, str) and detail:
            message = detail
        elif reply.error() != QNetworkReply.NetworkError.NoError:
            message = reply.errorString()
        else:
            message = f"登录请求失败（HTTP {status}）"
        logger.warning("认证失败：%s", message)
        self.failed.emit(message)


__all__ = ["AuthApi"]
