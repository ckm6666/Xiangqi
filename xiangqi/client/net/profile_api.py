"""玩家资料/排行榜/好友 REST 客户端（QtNetwork 异步）。"""




from __future__ import annotations

import json
import logging
import time
from typing import Callable, Optional
from urllib.parse import quote

from PySide6.QtCore import QObject, QUrl, Signal
from PySide6.QtNetwork import (
    QNetworkAccessManager,
    QNetworkReply,
    QNetworkRequest,
)

logger = logging.getLogger(__name__)


class ProfileApi(QObject):
    """异步个人资料接口。"""

    profile_loaded = Signal(object)
    profile_updated = Signal(object)
    player_loaded = Signal(object)
    leaderboard_loaded = Signal(object)
    friends_loaded = Signal(object)
    search_loaded = Signal(object)
    friend_request_sent = Signal(object)
    friend_request_resolved = Signal(object)
    avatar_loaded = Signal(bytes)
    #: 带昵称的头像加载结果，供排行榜/好友列表定位对应头像。
    avatar_for_loaded = Signal(str, bytes)
    failed = Signal(str)

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._manager = QNetworkAccessManager(self)

    # ------------------------------------------------------------------
    # 公开接口
    # ------------------------------------------------------------------
    def fetch_profile(self, base_url: str, token: str) -> None:
        self._json_request(
            "GET",
            self._url(base_url, "/api/v1/profile"),
            token,
            None,
            self._emit_profile,
        )

    def choose_default_avatar(
        self,
        base_url: str,
        token: str,
        avatar_id: str,
    ) -> None:
        body = json.dumps(
            {"avatar": avatar_id}, ensure_ascii=False
        ).encode("utf-8")
        self._json_request(
            "POST",
            self._url(base_url, "/api/v1/profile/avatar"),
            token,
            body,
            self._emit_updated,
        )

    def upload_avatar(
        self,
        base_url: str,
        token: str,
        png_bytes: bytes,
    ) -> None:
        request = self._request(
            self._url(base_url, "/api/v1/profile/avatar/upload"),
            token,
            "image/png",
        )
        reply = self._manager.post(request, png_bytes)
        reply.finished.connect(
            lambda current=reply: self._finish_json(
                current, self._emit_updated
            )
        )

    def fetch_leaderboard(
        self,
        base_url: str,
        token: str,
        limit: int = 50,
    ) -> None:
        count = max(1, min(1000, int(limit)))
        self._json_request(
            "GET",
            self._url(base_url, f"/api/v1/players?limit={count}"),
            token,
            None,
            self._emit_leaderboard,
        )

    def fetch_player_profile(
        self,
        base_url: str,
        token: str,
        nickname: str,
    ) -> None:
        self._json_request(
            "GET",
            self._url(
                base_url,
                "/api/v1/players/detail"
                f"?nickname={quote(nickname, safe='')}",
            ),
            token,
            None,
            self._emit_player,
        )

    def fetch_friends(self, base_url: str, token: str) -> None:
        self._json_request(
            "GET",
            self._url(base_url, "/api/v1/profile/friends"),
            token,
            None,
            self._emit_friends,
        )

    def search_players(
        self,
        base_url: str,
        token: str,
        query: str,
    ) -> None:
        self._json_request(
            "GET",
            self._url(
                base_url,
                f"/api/v1/players/search?q={quote(query, safe='')}",
            ),
            token,
            None,
            self._emit_search,
        )

    def request_friend(
        self,
        base_url: str,
        token: str,
        nickname: str,
    ) -> None:
        self._friend_post(
            base_url,
            token,
            "/api/v1/profile/friends",
            nickname,
            self._emit_friend_request_sent,
        )

    def accept_friend(
        self,
        base_url: str,
        token: str,
        nickname: str,
    ) -> None:
        self._friend_post(
            base_url,
            token,
            "/api/v1/profile/friends/accept",
            nickname,
            self._emit_friend_resolved,
        )

    def decline_friend(
        self,
        base_url: str,
        token: str,
        nickname: str,
    ) -> None:
        self._friend_post(
            base_url,
            token,
            "/api/v1/profile/friends/decline",
            nickname,
            self._emit_friend_resolved,
        )

    def _friend_post(
        self,
        base_url: str,
        token: str,
        path: str,
        nickname: str,
        on_success: Callable[[dict], None],
    ) -> None:
        body = json.dumps(
            {"nickname": nickname}, ensure_ascii=False
        ).encode("utf-8")
        self._json_request(
            "POST",
            self._url(base_url, path),
            token,
            body,
            on_success,
        )

    def fetch_avatar(
        self,
        base_url: str,
        nickname: str,
    ) -> None:
        # 昵称走查询参数以兼容斜杠等字符；时间戳避免命中旧头像缓存。
        url = self._url(
            base_url,
            f"/api/v1/profile/avatar"
            f"?nickname={quote(nickname, safe='')}"
            f"&v={time.time_ns()}",
        )
        request = QNetworkRequest(QUrl(url))
        reply = self._manager.get(request)
        reply.finished.connect(
            lambda current=reply, name=nickname: self._finish_avatar(
                current, name
            )
        )

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------
    @staticmethod
    def _url(base_url: str, path: str) -> str:
        return f"{base_url.rstrip('/')}{path}"

    def _request(
        self,
        url: str,
        token: str,
        content_type: str = "application/json",
    ) -> QNetworkRequest:
        request = QNetworkRequest(QUrl(url))
        request.setHeader(
            QNetworkRequest.KnownHeaders.ContentTypeHeader,
            content_type,
        )
        request.setRawHeader(
            b"Authorization", f"Bearer {token}".encode("utf-8")
        )
        return request

    def _json_request(
        self,
        method: str,
        url: str,
        token: str,
        body: Optional[bytes],
        on_success: Callable[[dict], None],
    ) -> None:
        request = self._request(url, token)
        if method == "POST":
            reply = self._manager.post(request, body or b"")
        else:
            reply = self._manager.get(request)
        reply.finished.connect(
            lambda current=reply: self._finish_json(current, on_success)
        )

    def _finish_json(
        self,
        reply: QNetworkReply,
        on_success: Callable[[dict], None],
    ) -> None:
        status, data, raw = self._read(reply)
        has_error = (
            reply.error() != QNetworkReply.NetworkError.NoError
        )
        error_string = reply.errorString()
        reply.deleteLater()
        if status == 200:
            on_success(data)
            return
        self._emit_error(status, data, raw, has_error, error_string)

    def _finish_avatar(
        self, reply: QNetworkReply, nickname: str = ""
    ) -> None:
        status, _data, raw = self._read(reply, parse_json=False)
        reply.deleteLater()
        if status == 200 and raw:
            if nickname:
                self.avatar_for_loaded.emit(nickname, raw)
            self.avatar_loaded.emit(raw)
            return
        self.failed.emit("头像加载失败")

    @staticmethod
    def _read(
        reply: QNetworkReply,
        *,
        parse_json: bool = True,
    ) -> tuple[Optional[int], dict, bytes]:
        status = reply.attribute(
            QNetworkRequest.Attribute.HttpStatusCodeAttribute
        )
        raw = bytes(reply.readAll())
        data: dict = {}
        if parse_json and raw:
            try:
                parsed = json.loads(raw.decode("utf-8", errors="replace"))
                if isinstance(parsed, dict):
                    data = parsed
            except json.JSONDecodeError:
                data = {}
        return status, data, raw

    def _emit_error(
        self,
        status: Optional[int],
        data: dict,
        raw: bytes,
        has_error: bool,
        error_string: str,
    ) -> None:
        detail = data.get("detail")
        if isinstance(detail, str) and detail:
            message = detail
        elif has_error:
            message = error_string
        else:
            body = raw.decode("utf-8", errors="replace").strip()
            message = body or f"请求失败（HTTP {status}）"
        if status == 404 and message.strip().lower() == "not found":
            message = "服务端未提供个人资料接口，请重启到 0.7.0 服务端"
        logger.warning("个人资料请求失败：%s", message)
        self.failed.emit(message)

    def _emit_profile(self, data: dict) -> None:
        self.profile_loaded.emit(data)

    def _emit_updated(self, data: dict) -> None:
        self.profile_updated.emit(data)

    def _emit_player(self, data: dict) -> None:
        self.player_loaded.emit(data)

    def _emit_leaderboard(self, data: dict) -> None:
        self.leaderboard_loaded.emit(data)

    def _emit_friends(self, data: dict) -> None:
        self.friends_loaded.emit(data)

    def _emit_search(self, data: dict) -> None:
        self.search_loaded.emit(data)

    def _emit_friend_request_sent(self, data: dict) -> None:
        self.friend_request_sent.emit(data)

    def _emit_friend_resolved(self, data: dict) -> None:
        self.friend_request_resolved.emit(data)


__all__ = ["ProfileApi"]
