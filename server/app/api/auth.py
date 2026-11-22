"""REST 注册/登录接口。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from server.app.users import (
    AuthManager,
    InvalidCredentials,
    NicknameTaken,
    UserStore,
    ValidationError,
)


class AuthRequest(BaseModel):
    nickname: str
    password: str


class AuthResponse(BaseModel):
    token: str
    user_id: int
    nickname: str
    rating: int
    avatar: str


def create_router(
    users: UserStore,
    auth: AuthManager,
) -> APIRouter:
    router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

    def _response(token: str, user) -> AuthResponse:  # type: ignore[no-untyped-def]
        return AuthResponse(
            token=token,
            user_id=user.id,
            nickname=user.nickname,
            rating=user.rating,
            avatar=user.avatar,
        )

    @router.post("/register", response_model=AuthResponse)
    def register(payload: AuthRequest) -> AuthResponse:
        try:
            user = users.register(
                payload.nickname, payload.password
            )
        except ValidationError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except NicknameTaken as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return _response(auth.issue(user), user)

    @router.post("/login", response_model=AuthResponse)
    def login(payload: AuthRequest) -> AuthResponse:
        try:
            user = users.login(payload.nickname, payload.password)
        except InvalidCredentials as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc
        return _response(auth.issue(user), user)

    return router


__all__ = ["create_router", "AuthRequest", "AuthResponse"]
