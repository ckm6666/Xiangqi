"""内存房间管理与服务器权威对局。

0.3.0 采用匿名昵称 + 房间号：
    * 创建房间者为红方，加入者为黑方；
    * 服务器持有 GameModel，客户端只发送 move_intent；
    * 每次状态变化向双方广播完整 game_state 快照；
    * 支持悔棋请求/回应、认输、双方同意的再来一局与断线状态展示。

账号、等级分、持久化与时钟留待后续版本。所有房间只存在于进程内存中。
"""

from __future__ import annotations

import asyncio
import logging
import random
import uuid
from dataclasses import dataclass, field
from typing import Mapping, Optional

from fastapi import WebSocket

from server.app.users import DEFAULT_RATING, UserStore
from xiangqi.shared.game_model import GameModel
from xiangqi.shared.protocol import (
    CLIENT_CHALLENGE_RESPONSE,
    CLIENT_CREATE_ROOM,
    CLIENT_INVITE_FRIEND,
    CLIENT_JOIN_QUEUE,
    CLIENT_JOIN_ROOM,
    CLIENT_LEAVE,
    CLIENT_MOVE_INTENT,
    CLIENT_REMATCH,
    CLIENT_RESIGN,
    CLIENT_UNDO_REQUEST,
    CLIENT_UNDO_RESPONSE,
    SERVER_CHALLENGE,
    SERVER_CHALLENGE_CANCELLED,
    SERVER_ERROR,
    SERVER_GAME_STATE,
    SERVER_INVITE_RESULT,
    SERVER_MOVE_REJECTED,
    SERVER_QUEUE_STATUS,
    SERVER_REMATCH_REQUESTED,
    SERVER_UNDO_REQUESTED,
    SERVER_UNDO_RESULT,
    make_message,
    serialize_board,
    serialize_move,
    serialize_moves,
    square_from_payload,
)
from xiangqi.shared.rules import Side

logger = logging.getLogger(__name__)

ROOM_STATUS_WAITING = "waiting"
ROOM_STATUS_PLAYING = "playing"
ROOM_STATUS_FINISHED = "finished"

_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
_CODE_LENGTH = 4

DEFAULT_RATING = 1200
RATING_K = 32
MATCH_RATING_WINDOW = 300


class RoomError(Exception):
    """可直接返回给客户端的房间错误。"""


@dataclass(eq=False)
class Connection:
    """一条 WebSocket 连接及其绑定的账号/房间/颜色。"""

    websocket: WebSocket
    user_id: Optional[int] = None
    name: str = ""
    rating: int = DEFAULT_RATING
    room_code: Optional[str] = None
    side: Optional[Side] = None


@dataclass
class Challenge:
    """一条待回应的自建房挑战。"""

    challenge_id: str
    room_code: str
    host_user_id: int
    target_user_id: int
    host_name: str
    target_name: str
    host_websocket: WebSocket
    target_websocket: WebSocket


@dataclass
class Room:
    """一个房间的权威状态。"""

    code: str
    game: GameModel = field(default_factory=GameModel.initial)
    status: str = ROOM_STATUS_WAITING
    names: dict[Side, str] = field(default_factory=dict)
    user_ids: dict[Side, Optional[int]] = field(
        default_factory=lambda: {Side.RED: None, Side.BLACK: None}
    )
    ratings: dict[Side, int] = field(
        default_factory=lambda: {
            Side.RED: DEFAULT_RATING,
            Side.BLACK: DEFAULT_RATING,
        }
    )
    websockets: dict[Side, Optional[WebSocket]] = field(
        default_factory=lambda: {Side.RED: None, Side.BLACK: None}
    )
    connected: dict[Side, bool] = field(
        default_factory=lambda: {Side.RED: False, Side.BLACK: False}
    )
    undo_requester: Optional[Side] = None
    rematch_requests: set[Side] = field(default_factory=set)
    ranked: bool = False
    rated: bool = False
    result_recorded: bool = False
    rating_deltas: dict[Side, int] = field(default_factory=dict)
    version: int = 0
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


def other_side(side: Side) -> Side:
    return Side.BLACK if side is Side.RED else Side.RED


class RoomManager:
    """管理所有内存房间与消息分发。"""

    def __init__(self, users: UserStore) -> None:
        self.users = users
        self.rooms: dict[str, Room] = {}
        self.queue: list[Connection] = []
        self._rng = random.Random()
        # 在线连接（同一账号可能同时有大厅监听连接和操作连接）。
        self.connections: dict[int, list[Connection]] = {}
        self.challenges: dict[str, Challenge] = {}
        self.challenges_by_target: dict[int, str] = {}
        self.challenges_by_room: dict[str, str] = {}

    def register(self, conn: Connection) -> None:
        """WebSocket 认证成功后登记在线连接。"""
        if conn.user_id is None:
            return
        conns = self.connections.setdefault(conn.user_id, [])
        if conn not in conns:
            conns.append(conn)

    def unregister(self, conn: Connection) -> None:
        if conn.user_id is None:
            return
        conns = self.connections.get(conn.user_id)
        if not conns:
            return
        try:
            conns.remove(conn)
        except ValueError:
            pass
        if not conns:
            self.connections.pop(conn.user_id, None)

    # ------------------------------------------------------------------
    # 入口
    # ------------------------------------------------------------------
    async def handle(
        self,
        conn: Connection,
        message_type: str,
        payload: Mapping[str, object],
        request_id: Optional[str],
    ) -> None:
        try:
            if message_type == CLIENT_CREATE_ROOM:
                await self.create_room(conn, payload)
            elif message_type == CLIENT_JOIN_ROOM:
                await self.join_room(conn, payload)
            elif message_type == CLIENT_JOIN_QUEUE:
                await self.join_queue(conn, payload)
            elif message_type == CLIENT_LEAVE:
                await self.disconnect(conn)
            elif message_type == CLIENT_INVITE_FRIEND:
                await self.invite_friend(conn, payload)
            elif message_type == CLIENT_CHALLENGE_RESPONSE:
                await self.challenge_response(conn, payload)
            elif conn.room_code is None:
                raise RoomError("请先创建或加入房间")
            elif message_type == CLIENT_MOVE_INTENT:
                await self.move(conn, payload, request_id)
            elif message_type == CLIENT_UNDO_REQUEST:
                await self.undo_request(conn)
            elif message_type == CLIENT_UNDO_RESPONSE:
                await self.undo_response(conn, payload)
            elif message_type == CLIENT_RESIGN:
                await self.resign(conn)
            elif message_type == CLIENT_REMATCH:
                await self.rematch(conn)
            else:
                raise RoomError(f"不支持的消息类型：{message_type}")
        except RoomError as exc:
            await self._send_error(conn, str(exc))
        except Exception:
            logger.exception("处理联机消息失败")
            await self._send_error(conn, "服务器内部错误")

    # ------------------------------------------------------------------
    # 房间生命周期
    # ------------------------------------------------------------------
    async def create_room(
        self,
        conn: Connection,
        payload: Mapping[str, object],
    ) -> None:
        del payload
        user = self._require_user(conn)
        self._remove_from_queue(conn)
        if conn.room_code is not None:
            await self.disconnect(conn)

        code = self._new_code()
        room = Room(code=code)
        room.names[Side.RED] = user.nickname
        room.user_ids[Side.RED] = user.id
        room.ratings[Side.RED] = user.rating
        room.websockets[Side.RED] = conn.websocket
        room.connected[Side.RED] = True
        self.rooms[code] = room

        conn.name = user.nickname
        conn.rating = user.rating
        conn.room_code = code
        conn.side = Side.RED

        await self._send_state(room, Side.RED)

    async def join_room(
        self,
        conn: Connection,
        payload: Mapping[str, object],
    ) -> None:
        user = self._require_user(conn)
        raw_code = payload.get("room_code")
        if not isinstance(raw_code, str):
            raise RoomError("请填写房间号")
        code = raw_code.strip().upper()
        room = self.rooms.get(code)
        if room is None:
            raise RoomError("房间不存在或已解散")

        self._remove_from_queue(conn)
        if conn.room_code is not None:
            await self.disconnect(conn)

        async with room.lock:
            side = self._reconnect_side(room, conn)
            if side is None:
                if room.status != ROOM_STATUS_WAITING:
                    raise RoomError("房间已开始对局")
                if Side.BLACK in room.names:
                    raise RoomError("房间已满")
                side = Side.BLACK
                room.names[side] = user.nickname
                room.user_ids[side] = user.id
                room.ratings[side] = user.rating
                room.status = ROOM_STATUS_PLAYING
                room.game.reset()
                room.rematch_requests.clear()
                room.undo_requester = None
            elif room.connected[side]:
                raise RoomError("你已在房间中")

            room.websockets[side] = conn.websocket
            room.connected[side] = True
            conn.name = user.nickname
            conn.rating = user.rating
            conn.room_code = code
            conn.side = side
            room.version += 1
            await self._broadcast_state(room)

    async def join_queue(
        self,
        conn: Connection,
        payload: Mapping[str, object],
    ) -> None:
        """加入排位匹配队列，优先匹配排位分相近的等待者。"""
        del payload
        user = self._require_user(conn)
        if conn.room_code is not None:
            raise RoomError("请先离开当前房间")
        self._remove_from_queue(conn)
        if any(
            player.user_id == user.id for player in self.queue
        ):
            raise RoomError("该账号正在匹配中")

        rating = user.rating
        candidate: Optional[Connection] = None
        best_diff: Optional[int] = None
        for player in self.queue:
            diff = abs(self._connection_rating(player) - rating)
            if diff <= MATCH_RATING_WINDOW and (
                best_diff is None or diff < best_diff
            ):
                candidate = player
                best_diff = diff

        conn.name = user.nickname
        conn.rating = user.rating
        conn.room_code = None
        conn.side = None
        if candidate is None:
            self.queue.append(conn)
            await self._send_ws(
                conn.websocket,
                make_message(
                    SERVER_QUEUE_STATUS,
                    {
                        "message": (
                            f"正在匹配…（第 {len(self.queue)} 位）"
                        ),
                        "position": len(self.queue),
                        "queued": len(self.queue),
                        "rating": rating,
                    },
                ),
            )
            return

        self.queue.remove(candidate)
        await self._create_ranked_room(candidate, conn)

    async def _create_ranked_room(
        self,
        first: Connection,
        second: Connection,
    ) -> None:
        code = self._new_code()
        room = Room(
            code=code,
            ranked=True,
            status=ROOM_STATUS_PLAYING,
        )
        for side, player in (
            (Side.RED, first),
            (Side.BLACK, second),
        ):
            room.names[side] = player.name
            room.user_ids[side] = player.user_id
            room.ratings[side] = self._connection_rating(player)
            room.websockets[side] = player.websocket
            room.connected[side] = True
            player.room_code = code
            player.side = side
        room.version = 1
        self.rooms[code] = room
        await self._broadcast_state(room)

    def _room_of_user(self, user_id: int) -> Optional[str]:
        for code, room in self.rooms.items():
            for uid in room.user_ids.values():
                if uid == user_id:
                    return code
        return None

    def _connection_for(self, user_id: int) -> Optional[Connection]:
        conns = self.connections.get(user_id, [])
        for candidate in conns:
            if candidate.room_code is None:
                return candidate
        return conns[-1] if conns else None

    def _drop_challenge(self, challenge_id: str) -> Optional[Challenge]:
        challenge = self.challenges.pop(challenge_id, None)
        if challenge is not None:
            self.challenges_by_target.pop(
                challenge.target_user_id, None
            )
            self.challenges_by_room.pop(challenge.room_code, None)
        return challenge

    async def _cancel_challenges(self, conn: Connection) -> None:
        """连接断开时让另一方收到挑战取消/失败。"""
        user_id = conn.user_id
        if user_id is None:
            return
        target_challenge_id = self.challenges_by_target.get(user_id)
        if target_challenge_id:
            challenge = self._drop_challenge(target_challenge_id)
            if challenge is not None:
                await self._send_ws(
                    challenge.host_websocket,
                    make_message(
                        SERVER_INVITE_RESULT,
                        {
                            "status": "declined",
                            "accepted": False,
                            "name": challenge.target_name,
                            "reason": "对方已离线",
                        },
                    ),
                )
        code = conn.room_code
        if code:
            room_challenge_id = self.challenges_by_room.get(code)
            if room_challenge_id:
                challenge = self._drop_challenge(room_challenge_id)
                if challenge is not None:
                    await self._send_ws(
                        challenge.target_websocket,
                        make_message(
                            SERVER_CHALLENGE_CANCELLED,
                            {
                                "challenge_id": challenge.challenge_id,
                                "reason": "房主已离开",
                            },
                        ),
                    )

    async def invite_friend(
        self,
        conn: Connection,
        payload: Mapping[str, object],
    ) -> None:
        """自建房房主邀请好友；好友会收到挑战弹窗。"""
        try:
            host = self._require_user(conn)
            room = self._require_room(conn)
            nickname = payload.get("nickname")
            if not isinstance(nickname, str) or not nickname.strip():
                raise RoomError("请选择要邀请的好友")
            target = self.users.find_by_nickname(nickname)
            if target is None:
                raise RoomError("好友不存在")
            if target.id == host.id:
                raise RoomError("不能邀请自己")
            if self.users.relationship(host.id, target.id) != "friend":
                raise RoomError("只能邀请好友")
            if room.status != ROOM_STATUS_WAITING:
                raise RoomError("对局已经开始")
            if room.names.get(Side.BLACK):
                raise RoomError("房间已满")
            if room.code in self.challenges_by_room:
                raise RoomError("已有待回应的挑战")
            if target.id in self.challenges_by_target:
                raise RoomError("对方已有待处理挑战")
            if self._room_of_user(target.id) is not None:
                raise RoomError("对方正在对局中")
            target_conn = self._connection_for(target.id)
            if target_conn is None:
                raise RoomError("好友不在线")

            challenge_id = uuid.uuid4().hex
            challenge = Challenge(
                challenge_id=challenge_id,
                room_code=room.code,
                host_user_id=host.id,
                target_user_id=target.id,
                host_name=host.nickname,
                target_name=target.nickname,
                host_websocket=conn.websocket,
                target_websocket=target_conn.websocket,
            )
            self.challenges[challenge_id] = challenge
            self.challenges_by_target[target.id] = challenge_id
            self.challenges_by_room[room.code] = challenge_id
            await self._send_ws(
                target_conn.websocket,
                make_message(
                    SERVER_CHALLENGE,
                    {
                        "challenge_id": challenge_id,
                        "name": host.nickname,
                    },
                ),
            )
            await self._send_ws(
                conn.websocket,
                make_message(
                    SERVER_INVITE_RESULT,
                    {
                        "status": "sent",
                        "accepted": None,
                        "name": target.nickname,
                    },
                ),
            )
        except RoomError as exc:
            await self._send_ws(
                conn.websocket,
                make_message(
                    SERVER_INVITE_RESULT,
                    {
                        "status": "error",
                        "accepted": False,
                        "reason": str(exc),
                    },
                ),
            )

    async def challenge_response(
        self,
        conn: Connection,
        payload: Mapping[str, object],
    ) -> None:
        """好友接受/拒绝自建房挑战。"""
        challenge_id = payload.get("challenge_id")
        if not isinstance(challenge_id, str):
            await self._send_ws(
                conn.websocket,
                make_message(
                    SERVER_CHALLENGE_CANCELLED,
                    {"challenge_id": "", "reason": "挑战已失效"},
                ),
            )
            return
        challenge = self.challenges.get(challenge_id)
        if challenge is None or conn.user_id != challenge.target_user_id:
            await self._send_ws(
                conn.websocket,
                make_message(
                    SERVER_CHALLENGE_CANCELLED,
                    {
                        "challenge_id": challenge_id,
                        "reason": "挑战已失效",
                    },
                ),
            )
            return
        accept = payload.get("accept") is True
        room = self.rooms.get(challenge.room_code)
        if (
            room is None
            or room.status != ROOM_STATUS_WAITING
            or not room.connected.get(Side.RED)
        ):
            self._drop_challenge(challenge_id)
            await self._send_ws(
                conn.websocket,
                make_message(
                    SERVER_CHALLENGE_CANCELLED,
                    {
                        "challenge_id": challenge_id,
                        "reason": "挑战已失效",
                    },
                ),
            )
            await self._send_ws(
                challenge.host_websocket,
                    make_message(
                        SERVER_INVITE_RESULT,
                        {
                            "status": "error",
                            "accepted": False,
                            "reason": "房间已失效",
                        },
                    ),
                )
            return

        if not accept:
            self._drop_challenge(challenge_id)
            await self._send_ws(
                challenge.host_websocket,
                    make_message(
                        SERVER_INVITE_RESULT,
                        {
                            "status": "declined",
                            "accepted": False,
                            "name": challenge.target_name,
                            "reason": "对方拒绝了挑战",
                        },
                    ),
                )
            return

        target = self.users.get(challenge.target_user_id)
        if target is None:
            self._drop_challenge(challenge_id)
            await self._send_ws(
                conn.websocket,
                make_message(
                    SERVER_CHALLENGE_CANCELLED,
                    {
                        "challenge_id": challenge_id,
                        "reason": "账号不存在",
                    },
                ),
            )
            return
        existing_room = self._room_of_user(target.id)
        if (
            existing_room is not None
            and existing_room != challenge.room_code
        ):
            self._drop_challenge(challenge_id)
            await self._send_ws(
                challenge.host_websocket,
                make_message(
                    SERVER_INVITE_RESULT,
                    {
                        "status": "declined",
                        "accepted": False,
                        "name": challenge.target_name,
                        "reason": "对方正在对局中",
                    },
                ),
            )
            await self._send_ws(
                conn.websocket,
                make_message(
                    SERVER_CHALLENGE_CANCELLED,
                    {
                        "challenge_id": challenge_id,
                        "reason": "你正在其他对局中",
                    },
                ),
            )
            return

        async with room.lock:
            if (
                room.status != ROOM_STATUS_WAITING
                or room.names.get(Side.BLACK)
                or not room.connected.get(Side.RED)
            ):
                self._drop_challenge(challenge_id)
                await self._send_ws(
                    conn.websocket,
                    make_message(
                        SERVER_CHALLENGE_CANCELLED,
                        {
                            "challenge_id": challenge_id,
                            "reason": "房间已不能加入",
                        },
                    ),
                )
                return
            self._drop_challenge(challenge_id)
            for candidate in self.connections.get(target.id, []):
                self._remove_from_queue(candidate)
            room.names[Side.BLACK] = target.nickname
            room.user_ids[Side.BLACK] = target.id
            room.ratings[Side.BLACK] = target.rating
            room.websockets[Side.BLACK] = conn.websocket
            room.connected[Side.BLACK] = True
            room.status = ROOM_STATUS_PLAYING
            room.game.reset()
            room.rematch_requests.clear()
            room.undo_requester = None
            room.version += 1
            conn.name = target.nickname
            conn.rating = target.rating
            conn.room_code = room.code
            conn.side = Side.BLACK
            await self._send_ws(
                challenge.host_websocket,
                    make_message(
                        SERVER_INVITE_RESULT,
                        {
                            "status": "accepted",
                            "accepted": True,
                            "name": target.nickname,
                        },
                    ),
                )
            await self._broadcast_state(room)

    async def disconnect(self, conn: Connection) -> None:
        """连接断开/主动离开：保留房间以便对手看到断线状态。"""
        await self._cancel_challenges(conn)
        self._remove_from_queue(conn)
        code = conn.room_code
        conn.room_code = None
        if code is None:
            return
        room = self.rooms.get(code)
        if room is None:
            return

        async with room.lock:
            side = conn.side
            conn.side = None
            if side is None:
                return
            if room.websockets[side] is conn.websocket:
                room.websockets[side] = None
                room.connected[side] = False
            room.rematch_requests.discard(side)
            if room.undo_requester is not None:
                room.undo_requester = None

            if room.status == ROOM_STATUS_WAITING:
                self.rooms.pop(code, None)
                return

            room.version += 1
            await self._broadcast_state(room)
            if not any(room.connected.values()):
                self.rooms.pop(code, None)

    # ------------------------------------------------------------------
    # 对局操作
    # ------------------------------------------------------------------
    async def move(
        self,
        conn: Connection,
        payload: Mapping[str, object],
        request_id: Optional[str],
    ) -> None:
        room = self._require_room(conn)
        async with room.lock:
            if room.status != ROOM_STATUS_PLAYING:
                await self._send_move_rejected(
                    conn, request_id, "对局尚未开始或已经结束"
                )
                return
            if room.undo_requester is not None:
                await self._send_move_rejected(
                    conn, request_id, "请先处理悔棋请求"
                )
                return
            if conn.side is None or conn.side is not room.game.side_to_move:
                await self._send_move_rejected(
                    conn, request_id, "还没有轮到你"
                )
                return

            try:
                from_row, from_col, to_row, to_col = square_from_payload(
                    payload
                )
            except Exception as exc:
                await self._send_move_rejected(conn, request_id, str(exc))
                return

            move = room.game.apply_move(
                from_row, from_col, to_row, to_col
            )
            if move is None:
                await self._send_move_rejected(
                    conn, request_id, "落子不合法"
                )
                return

            if room.game.is_game_over:
                room.status = ROOM_STATUS_FINISHED
                self._finish_game(room)
            room.version += 1
            await self._broadcast_state(room)

    async def undo_request(self, conn: Connection) -> None:
        room = self._require_room(conn)
        async with room.lock:
            if room.status != ROOM_STATUS_PLAYING:
                raise RoomError("当前不能悔棋")
            if conn.side is None:
                raise RoomError("你不在对局中")
            if room.undo_requester is not None:
                raise RoomError("已有待处理的悔棋请求")
            if room.game.move_count == 0:
                raise RoomError("还没有可撤销的着法")
            opponent = other_side(conn.side)
            if not room.connected[opponent]:
                raise RoomError("对手不在线")

            room.undo_requester = conn.side
            room.version += 1
            await self._send_ws(
                room.websockets[opponent],
                make_message(
                    SERVER_UNDO_REQUESTED,
                    {"name": conn.name, "side": conn.side.value},
                ),
            )
            await self._broadcast_state(room)

    async def undo_response(
        self,
        conn: Connection,
        payload: Mapping[str, object],
    ) -> None:
        room = self._require_room(conn)
        async with room.lock:
            requester = room.undo_requester
            if requester is None:
                raise RoomError("没有待处理的悔棋请求")
            if conn.side is None or conn.side is requester:
                raise RoomError("不能回应自己的悔棋请求")

            accept = payload.get("accept") is True
            room.undo_requester = None
            accepted = False
            if accept and room.status == ROOM_STATUS_PLAYING:
                accepted = room.game.undo()
                if accepted:
                    room.version += 1

            reason = "已同意悔棋" if accepted else "未悔棋"
            if not accept:
                reason = "对手拒绝悔棋"
            message = make_message(
                SERVER_UNDO_RESULT,
                {"accepted": accepted, "reason": reason},
            )
            await self._send_to_room(room, message)
            await self._broadcast_state(room)

    async def resign(self, conn: Connection) -> None:
        room = self._require_room(conn)
        async with room.lock:
            if room.status != ROOM_STATUS_PLAYING:
                raise RoomError("当前不能认输")
            if conn.side is None:
                raise RoomError("你不在对局中")
            if not room.game.resign(conn.side):
                raise RoomError("对局已经结束")
            room.status = ROOM_STATUS_FINISHED
            room.undo_requester = None
            self._finish_game(room)
            room.version += 1
            await self._broadcast_state(room)

    async def rematch(self, conn: Connection) -> None:
        room = self._require_room(conn)
        async with room.lock:
            if room.status != ROOM_STATUS_FINISHED:
                raise RoomError("对局尚未结束")
            if conn.side is None:
                raise RoomError("你不在对局中")
            opponent = other_side(conn.side)
            if not room.connected[opponent]:
                raise RoomError("对手已离线")

            room.rematch_requests.add(conn.side)
            await self._send_ws(
                room.websockets[opponent],
                make_message(
                    SERVER_REMATCH_REQUESTED,
                    {"name": conn.name},
                ),
            )
            if len(room.rematch_requests) >= 2:
                room.game.reset()
                room.status = ROOM_STATUS_PLAYING
                room.undo_requester = None
                room.rematch_requests.clear()
                room.rated = False
                room.result_recorded = False
                room.rating_deltas.clear()
                room.version += 1
            await self._broadcast_state(room)

    # ------------------------------------------------------------------
    # 快照与发送
    # ------------------------------------------------------------------
    def _snapshot(self, room: Room, side: Side) -> dict[str, object]:
        game = room.game
        return {
            "room_code": room.code,
            "status": room.status,
            "your_side": side.value,
            "ranked": room.ranked,
            "players": {
                "red": {
                    "name": room.names.get(Side.RED, ""),
                    "connected": room.connected[Side.RED],
                    "rating": room.ratings.get(
                        Side.RED, DEFAULT_RATING
                    ),
                    "rating_delta": room.rating_deltas.get(Side.RED),
                },
                "black": {
                    "name": room.names.get(Side.BLACK, ""),
                    "connected": room.connected[Side.BLACK],
                    "rating": room.ratings.get(
                        Side.BLACK, DEFAULT_RATING
                    ),
                    "rating_delta": room.rating_deltas.get(Side.BLACK),
                },
            },
            "board": serialize_board(game.board),
            "moves": serialize_moves(game.moves),
            "side_to_move": game.side_to_move.value,
            "last_move": serialize_move(game.last_move),
            "is_check": game.is_check,
            "winner": game.winner.value if game.winner else None,
            "end_reason": (
                game.end_reason.value if game.end_reason else None
            ),
            "move_count": game.move_count,
            "undo_requester": (
                room.undo_requester.value
                if room.undo_requester is not None
                else None
            ),
            "rematch_requests": sorted(
                side_item.value for side_item in room.rematch_requests
            ),
            "state_version": room.version,
        }

    async def _broadcast_state(self, room: Room) -> None:
        for side in (Side.RED, Side.BLACK):
            await self._send_state(room, side)

    async def _send_state(self, room: Room, side: Side) -> None:
        websocket = room.websockets[side]
        if websocket is None:
            return
        await self._send_ws(
            websocket,
            make_message(SERVER_GAME_STATE, self._snapshot(room, side)),
        )

    async def _send_to_room(
        self,
        room: Room,
        message: Mapping[str, object],
    ) -> None:
        for side in (Side.RED, Side.BLACK):
            await self._send_ws(room.websockets[side], message)

    async def _send_ws(
        self,
        websocket: Optional[WebSocket],
        message: Mapping[str, object],
    ) -> None:
        if websocket is None:
            return
        try:
            await websocket.send_json(message)
        except Exception:
            logger.warning("向客户端发送消息失败", exc_info=True)

    async def _send_error(self, conn: Connection, message: str) -> None:
        await self._send_ws(
            conn.websocket,
            make_message(SERVER_ERROR, {"message": message}),
        )

    async def _send_move_rejected(
        self,
        conn: Connection,
        request_id: Optional[str],
        reason: str,
    ) -> None:
        await self._send_ws(
            conn.websocket,
            make_message(
                SERVER_MOVE_REJECTED,
                {"reason": reason},
                request_id=request_id,
            ),
        )

    # ------------------------------------------------------------------
    # 辅助
    # ------------------------------------------------------------------
    def _require_room(self, conn: Connection) -> Room:
        if conn.room_code is None:
            raise RoomError("请先创建或加入房间")
        room = self.rooms.get(conn.room_code)
        if room is None:
            raise RoomError("房间不存在或已解散")
        return room

    def _new_code(self) -> str:
        while True:
            code = "".join(
                self._rng.choice(_CODE_ALPHABET)
                for _ in range(_CODE_LENGTH)
            )
            if code not in self.rooms:
                return code

    def _require_user(self, conn: Connection):  # type: ignore[no-untyped-def]
        if conn.user_id is None:
            raise RoomError("请先登录")
        user = self.users.get(conn.user_id)
        if user is None:
            raise RoomError("账号不存在")
        conn.name = user.nickname
        conn.rating = user.rating
        return user

    def _connection_rating(self, conn: Connection) -> int:
        if conn.user_id is not None:
            user = self.users.get(conn.user_id)
            if user is not None:
                conn.rating = user.rating
                return user.rating
        return conn.rating

    def _remove_from_queue(self, conn: Connection) -> None:
        try:
            self.queue.remove(conn)
        except ValueError:
            pass

    def _finish_game(self, room: Room) -> None:
        """终局结算：排位赛更新 Elo，所有联机对局累计战绩。"""
        if room.result_recorded:
            return
        room.result_recorded = True
        self._apply_ratings(room)
        self._record_stats(room)

    def _record_stats(self, room: Room) -> None:
        """把胜负写入双方账号的累计战绩（一局只写一次）。"""
        winner = room.game.winner
        if winner is None:
            return
        loser = winner.opponent
        for side, outcome in ((winner, "win"), (loser, "loss")):
            user_id = room.user_ids.get(side)
            if user_id is not None:
                self.users.record_result(user_id, outcome)

    def _apply_ratings(self, room: Room) -> None:
        """按 Elo 更新一场排位赛的双方分数并持久化。"""
        if not room.ranked or room.rated:
            return
        winner = room.game.winner
        if winner is None:
            return
        loser = winner.opponent
        winner_id = room.user_ids.get(winner)
        loser_id = room.user_ids.get(loser)
        if (
            winner_id is None
            or loser_id is None
            or winner_id == loser_id
        ):
            return
        winner_rating = room.ratings.get(winner, DEFAULT_RATING)
        loser_rating = room.ratings.get(loser, DEFAULT_RATING)
        expected = 1.0 / (
            1.0 + 10 ** ((loser_rating - winner_rating) / 400.0)
        )
        delta = max(
            1, int(round(RATING_K * (1.0 - expected)))
        )
        new_winner = max(100, winner_rating + delta)
        new_loser = max(100, loser_rating - delta)
        self.users.set_rating(winner_id, new_winner)
        self.users.set_rating(loser_id, new_loser)
        room.ratings[winner] = new_winner
        room.ratings[loser] = new_loser
        room.rating_deltas = {
            winner: new_winner - winner_rating,
            loser: new_loser - loser_rating,
        }
        room.rated = True

    @staticmethod
    def _reconnect_side(
        room: Room,
        conn: Connection,
    ) -> Optional[Side]:
        for side in (Side.RED, Side.BLACK):
            if room.connected[side]:
                continue
            same_user = (
                conn.user_id is not None
                and room.user_ids.get(side) == conn.user_id
            )
            same_name = (
                bool(conn.name)
                and room.names.get(side) == conn.name
            )
            if same_user or same_name:
                return side
        return None


__all__ = [
    "RoomManager",
    "Room",
    "Connection",
    "RoomError",
    "ROOM_STATUS_WAITING",
    "ROOM_STATUS_PLAYING",
    "ROOM_STATUS_FINISHED",
]
