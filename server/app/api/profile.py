"""玩家资料与好友 REST 接口。

个人资料、头像与好友申请都需要 ``Authorization: Bearer <token>``；
头像读取接口公开，方便排行榜和他人资料按昵称加载头像。
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from server.app.api.deps import make_current_user
from server.app.users import (
    CUSTOM_AVATAR_ID,
    MAX_AVATAR_BYTES,
    AuthManager,
    FriendAlreadyExists,
    FriendNotFound,
    FriendRequestAlreadySent,
    FriendRequestNotFound,
    User,
    UserStore,
    ValidationError,
)
from xiangqi.shared.achievements import evaluate_achievements
from xiangqi.shared.profile import (
    PlayerStats,
    next_title,
    title_for_rating,
)

_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


class AvatarChoice(BaseModel):
    avatar: str


class FriendRequest(BaseModel):
    nickname: str


def friend_payload(user: User) -> dict[str, object]:
    """好友列表/申请列表中展示的简短玩家信息。"""
    return {
        "nickname": user.nickname,
        "rating": user.rating,
        "title": title_for_rating(user.rating),
        "avatar": user.avatar,
    }


def profile_payload(
    user: User,
    *,
    relationship: Optional[str] = None,
) -> dict[str, object]:
    """完整玩家资料；好友关系状态只在查看他人时附加。"""
    stats = PlayerStats(user.wins, user.losses, user.draws)
    upcoming = next_title(user.rating)
    payload: dict[str, object] = {
        "nickname": user.nickname,
        "rating": user.rating,
        "best_rating": user.best_rating,
        "title": title_for_rating(user.rating),
        "next_title": (
            {"name": upcoming.name, "min_rating": upcoming.min_rating}
            if upcoming is not None
            else None
        ),
        "wins": stats.wins,
        "losses": stats.losses,
        "draws": stats.draws,
        "games": stats.games,
        "win_rate": stats.win_rate,
        "record_text": stats.record_text,
        "current_streak": user.current_streak,
        "best_streak": user.best_streak,
        "avatar": user.avatar,
        "achievements": [
            {
                "key": state.key,
                "name": state.name,
                "description": state.description,
                "earned": state.earned,
            }
            for state in evaluate_achievements(
                wins=user.wins,
                losses=user.losses,
                draws=user.draws,
                best_streak=user.best_streak,
                rating=user.best_rating,
            )
        ],
    }
    if relationship is not None:
        payload["relationship"] = relationship
    return payload


def create_router(
    users: UserStore,
    auth: AuthManager,
) -> APIRouter:
    router = APIRouter(prefix="/api/v1/profile", tags=["profile"])
    current_user = make_current_user(auth)

    @router.get("")
    def get_profile(
        user: User = Depends(current_user),
    ) -> dict[str, object]:
        return profile_payload(user, relationship="self")

    @router.post("/avatar")
    def choose_avatar(
        payload: AvatarChoice,
        user: User = Depends(current_user),
    ) -> dict[str, object]:
        try:
            users.set_avatar(user.id, payload.avatar)
        except ValidationError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        refreshed = users.get(user.id)
        if refreshed is None:
            raise HTTPException(status_code=404, detail="账号不存在")
        return profile_payload(refreshed, relationship="self")

    @router.post("/avatar/upload")
    async def upload_avatar(
        request: Request,
        user: User = Depends(current_user),
    ) -> dict[str, object]:
        body = await request.body()
        if not body:
            raise HTTPException(status_code=400, detail="头像文件为空")
        if len(body) > MAX_AVATAR_BYTES:
            raise HTTPException(
                status_code=400, detail="头像文件不能超过 512 KB"
            )
        if not body.startswith(_PNG_SIGNATURE):
            raise HTTPException(
                status_code=400, detail="头像必须是 PNG 图片"
            )
        try:
            users.set_avatar(user.id, CUSTOM_AVATAR_ID, body)
        except ValidationError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        refreshed = users.get(user.id)
        if refreshed is None:
            raise HTTPException(status_code=404, detail="账号不存在")
        return profile_payload(refreshed, relationship="self")

    def avatar_response(nickname: str) -> Response:
        user = users.find_by_nickname(nickname)
        if user is None:
            raise HTTPException(status_code=404, detail="玩家不存在")
        avatar = users.get_avatar(user.id)
        if avatar is None:
            raise HTTPException(status_code=404, detail="头像不存在")
        avatar_id, blob = avatar
        if avatar_id != CUSTOM_AVATAR_ID or not blob:
            raise HTTPException(
                status_code=404, detail="该玩家使用内置头像"
            )
        return Response(
            content=blob,
            media_type="image/png",
            headers={"Cache-Control": "no-cache"},
        )

    @router.get("/avatar")
    def get_avatar_by_query(nickname: str) -> Response:
        """按查询参数读取头像，昵称可包含斜杠等特殊字符。"""
        return avatar_response(nickname)

    @router.get("/avatar/{nickname}")
    def get_avatar(nickname: str) -> Response:
        return avatar_response(nickname)

    @router.get("/friends")
    def list_friends(
        user: User = Depends(current_user),
    ) -> dict[str, object]:
        incoming, outgoing = users.list_friend_requests(user.id)
        return {
            "friends": [
                friend_payload(friend)
                for friend in users.list_friends(user.id)
            ],
            "incoming": [friend_payload(item) for item in incoming],
            "outgoing": [friend_payload(item) for item in outgoing],
        }

    @router.post("/friends")
    def request_friend(
        payload: FriendRequest,
        user: User = Depends(current_user),
    ) -> dict[str, object]:
        """发送好友申请；若对方已先申请则直接成为好友。"""
        try:
            target = users.send_friend_request(
                user.id, payload.nickname
            )
        except FriendNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (
            FriendAlreadyExists,
            FriendRequestAlreadySent,
        ) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValidationError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        relationship = users.relationship(user.id, target.id)
        return {
            "friend": friend_payload(target),
            "relationship": relationship,
        }

    @router.post("/friends/accept")
    def accept_friend(
        payload: FriendRequest,
        user: User = Depends(current_user),
    ) -> dict[str, object]:
        try:
            friend = users.accept_friend_request(
                user.id, payload.nickname
            )
        except FriendNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except FriendRequestNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValidationError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "friend": friend_payload(friend),
            "relationship": "friend",
        }

    @router.post("/friends/decline")
    def decline_friend(
        payload: FriendRequest,
        user: User = Depends(current_user),
    ) -> dict[str, object]:
        try:
            users.decline_friend_request(user.id, payload.nickname)
        except FriendNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except FriendRequestNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {"ok": True}

    return router


__all__ = [
    "AvatarChoice",
    "FriendRequest",
    "create_router",
    "friend_payload",
    "profile_payload",
]
