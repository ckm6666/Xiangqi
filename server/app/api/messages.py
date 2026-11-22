"""好友私聊历史、发送与已读接口。

私聊只允许好友之间进行；消息持久化在 SQLite，对方在线时通过
WebSocket 实时推送，离线时等下次打开聊天窗补收。
"""

from __future__ import annotations

import threading
import time

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel

from server.app.api.deps import make_current_user
from server.app.users import (
    AuthManager,
    DirectMessage,
    User,
    UserStore,
)
from xiangqi.shared.protocol import (
    SERVER_DIRECT_MESSAGE,
    make_message,
)
from xiangqi.shared.social import (
    SocialError,
    normalize_direct_message,
)

#: 单进程内的私聊限流：每账号 10 秒最多 10 条。
_DM_WINDOW_SECONDS = 10.0
_DM_MAX_PER_WINDOW = 10
_send_times: dict[int, list[float]] = {}
_send_lock = threading.Lock()


class SendMessageRequest(BaseModel):
    content: str


class MarkMessagesReadRequest(BaseModel):
    message_ids: list[str] = []


def _check_send_rate(user_id: int) -> None:
    now = time.monotonic()
    with _send_lock:
        recent = [
            stamp
            for stamp in _send_times.get(user_id, [])
            if now - stamp < _DM_WINDOW_SECONDS
        ]
        if len(recent) >= _DM_MAX_PER_WINDOW:
            raise HTTPException(
                status_code=429,
                detail="发送过于频繁，请稍后再试",
            )
        recent.append(now)
        _send_times[user_id] = recent
        if len(_send_times) > 4096:
            stale = [
                key
                for key, stamps in _send_times.items()
                if not stamps
                or now - stamps[-1] >= _DM_WINDOW_SECONDS
            ]
            for key in stale:
                _send_times.pop(key, None)


def _message_payload(
    message: DirectMessage,
    sender: User,
) -> dict[str, object]:
    """一条私聊的线格式；收发双方看到的字段一致。"""
    return {
        "id": str(message.id),
        "sender_id": str(message.sender_id),
        "sender_name": sender.nickname,
        "recipient_id": str(message.recipient_id),
        "content": message.content,
        "sent_at_ms": message.sent_at_ms,
    }


def create_router(
    users: UserStore,
    auth: AuthManager,
) -> APIRouter:
    router = APIRouter(
        prefix="/api/v1/messages", tags=["messages"]
    )
    current_user = make_current_user(auth)

    def _require_friend(
        user: User, nickname: str
    ) -> User:
        target = users.find_by_nickname(nickname)
        if target is None:
            raise HTTPException(status_code=404, detail="玩家不存在")
        if users.relationship(user.id, target.id) != "friend":
            raise HTTPException(
                status_code=403, detail="只能和好友私聊"
            )
        return target

    @router.get("")
    async def message_history(
        nickname: str = Query(...),
        limit: int = Query(default=50, ge=1, le=200),
        user: User = Depends(current_user),
    ) -> dict[str, object]:
        """读取与某位好友的最近私聊，并把本次返回的来信标为已读。"""
        target = _require_friend(user, nickname)
        rows = users.list_direct_messages(
            user.id, target.id, limit
        )
        read_ids = [
            message.id
            for message in rows
            if message.sender_id == target.id
        ]
        if read_ids:
            users.mark_direct_messages_read(
                user.id, target.id, read_ids
            )
        return {
            "nickname": target.nickname,
            "messages": [
                _message_payload(
                    message,
                    user if message.sender_id == user.id else target,
                )
                for message in rows
            ],
        }

    @router.post("")
    async def send_message(
        payload: SendMessageRequest,
        request: Request,
        nickname: str = Query(...),
        user: User = Depends(current_user),
    ) -> dict[str, object]:
        """向好友发送私聊；对方在线时实时推送。"""
        target = _require_friend(user, nickname)
        try:
            content = normalize_direct_message(payload.content)
        except SocialError as exc:
            raise HTTPException(
                status_code=400, detail=str(exc)
            ) from exc
        _check_send_rate(user.id)

        message = users.create_direct_message(
            user.id,
            target.id,
            content,
            int(time.time() * 1000),
        )
        entry = _message_payload(message, user)
        manager = getattr(
            request.app.state, "room_manager", None
        )
        if manager is not None:
            await manager.send_to_user(
                target.id,
                make_message(SERVER_DIRECT_MESSAGE, entry),
            )
        return entry

    @router.post("/read")
    async def mark_messages_read(
        payload: MarkMessagesReadRequest,
        nickname: str = Query(...),
        user: User = Depends(current_user),
    ) -> dict[str, object]:
        """把已经显示在聊天窗里的来信标为已读。"""
        target = _require_friend(user, nickname)
        ids: list[int] = []
        for item in payload.message_ids[:200]:
            try:
                value = int(item)
            except (TypeError, ValueError):
                continue
            if value > 0:
                ids.append(value)
        count = users.mark_direct_messages_read(
            user.id, target.id, ids
        )
        return {"read_count": count}

    return router


__all__ = ["create_router"]
