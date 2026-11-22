"""WebSocket 端点：首帧协议校验与房间消息分发。"""

from __future__ import annotations

import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from server.app.users import AuthManager
from server.app.ws.rooms import Connection, RoomManager
from xiangqi.shared.errors import ProtocolError
from xiangqi.shared.protocol import (
    CLIENT_AUTH,
    SERVER_AUTH_OK,
    SERVER_ERROR,
    make_message,
    parse_message,
)

logger = logging.getLogger(__name__)


def create_router(
    manager: RoomManager,
    auth_manager: AuthManager,
) -> APIRouter:
    """创建绑定到指定 RoomManager/AuthManager 的路由。"""
    router = APIRouter()

    @router.websocket("/api/v1/ws")
    async def websocket_endpoint(websocket: WebSocket) -> None:
        await websocket.accept()
        conn = Connection(websocket)
        try:
            while True:
                try:
                    data = await websocket.receive_json()
                except WebSocketDisconnect:
                    break
                except Exception:
                    logger.warning("收到无法解析的 WebSocket 消息")
                    break

                try:
                    message_type, payload, request_id = parse_message(data)
                except ProtocolError as exc:
                    await _safe_send(
                        websocket,
                        make_message(
                            SERVER_ERROR, {"message": str(exc)}
                        ),
                    )
                    continue

                if message_type == CLIENT_AUTH:
                    if conn.user_id is not None:
                        await _safe_send(
                            websocket,
                            make_message(
                                SERVER_ERROR,
                                {"message": "当前连接已经登录"},
                            ),
                        )
                        continue
                    user = auth_manager.resolve(payload.get("token"))
                    if user is None:
                        await _safe_send(
                            websocket,
                            make_message(
                                SERVER_ERROR,
                                {"message": "登录已失效，请重新登录"},
                            ),
                        )
                        continue
                    conn.user_id = user.id
                    conn.name = user.nickname
                    conn.rating = user.rating
                    manager.register(conn)
                    await _safe_send(
                        websocket,
                        make_message(
                            SERVER_AUTH_OK,
                            {
                                "user_id": user.id,
                                "nickname": user.nickname,
                                "rating": user.rating,
                            },
                        ),
                    )
                    continue

                if conn.user_id is None:
                    await _safe_send(
                        websocket,
                        make_message(
                            SERVER_ERROR, {"message": "请先登录"}
                        ),
                    )
                    continue

                await manager.handle(
                    conn, message_type, payload, request_id
                )
        finally:
            await manager.disconnect(conn)
            manager.unregister(conn)

    return router


async def _safe_send(
    websocket: WebSocket,
    message: object,
) -> None:
    try:
        await websocket.send_json(message)  # type: ignore[arg-type]
    except Exception:
        logger.warning("WebSocket 发送失败", exc_info=True)


__all__ = ["create_router"]
