"""REST 路由共享依赖：从 Bearer 令牌解析当前用户。"""

from __future__ import annotations

from typing import Callable, Optional

from fastapi import Header, HTTPException

from server.app.users import AuthManager, User


def make_current_user(
    auth: AuthManager,
) -> Callable[..., User]:
    """返回一个 FastAPI 依赖函数，要求请求携带有效登录令牌。"""

    def current_user(
        authorization: Optional[str] = Header(default=None),
    ) -> User:
        token = ""
        if isinstance(authorization, str):
            parts = authorization.split(None, 1)
            if len(parts) == 2 and parts[0].lower() == "bearer":
                token = parts[1].strip()
        user = auth.resolve(token)
        if user is None:
            raise HTTPException(
                status_code=401, detail="登录已失效，请重新登录"
            )
        return user

    return current_user


__all__ = ["make_current_user"]
