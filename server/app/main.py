"""FastAPI 联机服务端（账号 + 排位模式）。

启动（从项目根目录执行）::

    server\\.venv\\Scripts\\python.exe -m uvicorn server.app.main:app --port 8765

0.7.0 提供 SQLite 账号、排位、战绩、头像、好友、私聊与对局聊天，以及
REST 登录注册、资料与私聊接口。账号、排位分与私聊持久化在
server/data/xiangqi.db；登录令牌保存在内存中。
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI

from server.app.api.auth import create_router as create_auth_router
from server.app.api.messages import create_router as create_messages_router
from server.app.api.players import create_router as create_players_router
from server.app.api.profile import create_router as create_profile_router
from server.app.users import AuthManager, UserStore
from server.app.ws.endpoint import create_router
from server.app.ws.rooms import RoomManager

SERVER_VERSION = "0.7.0"


def create_app(db_path: Optional[Path] = None) -> FastAPI:
    """创建 FastAPI 应用；测试可注入临时 SQLite 路径。"""
    users = UserStore(db_path)
    auth_manager = AuthManager(users)
    manager = RoomManager(users)

    @asynccontextmanager
    async def lifespan(app: FastAPI):  # noqa: ANN202
        del app
        try:
            yield
        finally:
            users.close()

    app = FastAPI(
        title="Xiangqi Online",
        version=SERVER_VERSION,
        lifespan=lifespan,
    )
    app.state.user_store = users
    app.state.auth_manager = auth_manager
    app.state.room_manager = manager

    app.include_router(create_auth_router(users, auth_manager))
    app.include_router(create_profile_router(users, auth_manager))
    app.include_router(create_messages_router(users, auth_manager))
    app.include_router(create_players_router(users, auth_manager))
    app.include_router(create_router(manager, auth_manager))

    @app.get("/api/v1/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "version": SERVER_VERSION}

    return app


app = create_app()


__all__ = ["create_app", "app", "SERVER_VERSION"]
