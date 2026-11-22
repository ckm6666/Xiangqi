"""联机协议基础。

协议采用 JSON 信封::

    {"protocol": 1, "type": "move_intent", "request_id": "...", "payload": {...}}

服务端权威：客户端只发送意图，收到 game_state 快照后才更新棋盘。房间、
认证与时钟的完整流程见 server/README.md。

坐标与棋盘编码与 :mod:`xiangqi.shared.rules` 完全一致：
``row 0`` 为黑方底线，空格为 0，红方棋子为 ``+PieceKind``，黑方为
``-PieceKind``。
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Mapping, Optional

from xiangqi.shared.errors import ProtocolError
from xiangqi.shared.rules import (
    BOARD_COLS,
    BOARD_ROWS,
    Board,
    BoardLike,
    Move,
    Piece,
    Square,
)

PROTOCOL_VERSION = 1

# 客户端 → 服务端
CLIENT_AUTH = "auth"
CLIENT_CREATE_ROOM = "create_room"
CLIENT_JOIN_ROOM = "join_room"
CLIENT_JOIN_QUEUE = "join_queue"
CLIENT_MOVE_INTENT = "move_intent"
CLIENT_UNDO_REQUEST = "undo_request"
CLIENT_UNDO_RESPONSE = "undo_response"
CLIENT_RESIGN = "resign"
CLIENT_REMATCH = "rematch"
CLIENT_LEAVE = "leave"
CLIENT_INVITE_FRIEND = "invite_friend"
CLIENT_CHALLENGE_RESPONSE = "challenge_response"
CLIENT_CHAT = "chat"
CLIENT_SPECTATE = "spectate"

# 服务端 → 客户端
SERVER_AUTH_OK = "auth_ok"
SERVER_GAME_STATE = "game_state"
SERVER_QUEUE_STATUS = "queue_status"
SERVER_MOVE_REJECTED = "move_rejected"
SERVER_UNDO_REQUESTED = "undo_requested"
SERVER_UNDO_RESULT = "undo_result"
SERVER_REMATCH_REQUESTED = "rematch_requested"
SERVER_ERROR = "error"
SERVER_INVITE_RESULT = "invite_result"
SERVER_CHALLENGE = "challenge"
SERVER_CHALLENGE_CANCELLED = "challenge_cancelled"
SERVER_CHAT = "chat_message"
SERVER_DIRECT_MESSAGE = "direct_message"
SERVER_SPECTATE_ENDED = "spectate_ended"

MESSAGE_TYPES = frozenset(
    {
        CLIENT_AUTH,
        CLIENT_CREATE_ROOM,
        CLIENT_JOIN_ROOM,
        CLIENT_JOIN_QUEUE,
        CLIENT_MOVE_INTENT,
        CLIENT_UNDO_REQUEST,
        CLIENT_UNDO_RESPONSE,
        CLIENT_RESIGN,
        CLIENT_REMATCH,
        CLIENT_LEAVE,
        CLIENT_INVITE_FRIEND,
        CLIENT_CHALLENGE_RESPONSE,
        CLIENT_CHAT,
        CLIENT_SPECTATE,
        SERVER_AUTH_OK,
        SERVER_GAME_STATE,
        SERVER_QUEUE_STATUS,
        SERVER_MOVE_REJECTED,
        SERVER_UNDO_REQUESTED,
        SERVER_UNDO_RESULT,
        SERVER_REMATCH_REQUESTED,
        SERVER_ERROR,
        SERVER_INVITE_RESULT,
        SERVER_CHALLENGE,
        SERVER_CHALLENGE_CANCELLED,
        SERVER_CHAT,
        SERVER_DIRECT_MESSAGE,
        SERVER_SPECTATE_ENDED,
    }
)


def make_message(
    message_type: str,
    payload: Optional[Mapping[str, object]] = None,
    request_id: Optional[str] = None,
) -> dict[str, object]:
    """构造协议信封。"""
    if message_type not in MESSAGE_TYPES:
        raise ProtocolError(f"未知消息类型：{message_type!r}")
    if payload is not None and not isinstance(payload, Mapping):
        raise ProtocolError("payload 必须是映射")
    message: dict[str, object] = {
        "protocol": PROTOCOL_VERSION,
        "type": message_type,
        "payload": dict(payload or {}),
    }
    if request_id:
        message["request_id"] = str(request_id)
    return message


def parse_message(
    data: object,
) -> tuple[str, dict[str, object], Optional[str]]:
    """校验并拆解协议信封，返回 ``(type, payload, request_id)``。"""
    if not isinstance(data, Mapping):
        raise ProtocolError("消息必须是 JSON 对象")
    if data.get("protocol") != PROTOCOL_VERSION:
        raise ProtocolError("协议版本不匹配")
    message_type = data.get("type")
    if not isinstance(message_type, str) or message_type not in MESSAGE_TYPES:
        raise ProtocolError(f"未知消息类型：{message_type!r}")
    payload = data.get("payload", {})
    if not isinstance(payload, Mapping):
        raise ProtocolError("payload 必须是映射")
    request_id = data.get("request_id")
    if request_id is not None and not isinstance(request_id, str):
        raise ProtocolError("request_id 必须是字符串")
    return message_type, dict(payload), request_id


# ---------------------------------------------------------------------------
# 棋盘/着法序列化
# ---------------------------------------------------------------------------
def serialize_board(board: BoardLike) -> list[list[int]]:
    """把棋盘转换为 10×9 的整数编码二维数组。"""
    return [
        [board[row][col].code if board[row][col] else 0 for col in range(BOARD_COLS)]
        for row in range(BOARD_ROWS)
    ]


def deserialize_board(data: object) -> Board:
    """从整数编码还原不可变棋盘；非法数据抛出 ProtocolError。"""
    if not isinstance(data, (list, tuple)) or len(data) != BOARD_ROWS:
        raise ProtocolError("棋盘必须是 10 行数组")
    rows: list[tuple[Optional[Piece], ...]] = []
    for row_data in data:
        if not isinstance(row_data, (list, tuple)) or len(row_data) != BOARD_COLS:
            raise ProtocolError("棋盘每行必须是 9 列数组")
        row: list[Optional[Piece]] = []
        for code in row_data:
            if not isinstance(code, int) or isinstance(code, bool):
                raise ProtocolError("棋盘格必须是整数编码")
            if code == 0:
                row.append(None)
                continue
            try:
                row.append(Piece.from_code(code))
            except ValueError as exc:
                raise ProtocolError(str(exc)) from exc
        rows.append(tuple(row))
    return tuple(rows)


def serialize_move(move: Optional[Move]) -> Optional[dict[str, object]]:
    """序列化一手棋；用于 last_move 展示。"""
    if move is None:
        return None
    payload: dict[str, object] = {
        "from_row": move.from_row,
        "from_col": move.from_col,
        "to_row": move.to_row,
        "to_col": move.to_col,
    }
    if move.captured is not None:
        payload["captured"] = move.captured.code
    return payload


def deserialize_move(data: object) -> Optional[Move]:
    """反序列化 last_move；None 表示无。"""
    if data is None:
        return None
    if not isinstance(data, Mapping):
        raise ProtocolError("last_move 必须是对象或 null")
    try:
        from_row = int(data["from_row"])
        from_col = int(data["from_col"])
        to_row = int(data["to_row"])
        to_col = int(data["to_col"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ProtocolError("last_move 字段不完整") from exc
    if not (
        0 <= from_row < BOARD_ROWS
        and 0 <= from_col < BOARD_COLS
        and 0 <= to_row < BOARD_ROWS
        and 0 <= to_col < BOARD_COLS
    ):
        raise ProtocolError("last_move 坐标越界")
    captured_code = data.get("captured")
    captured: Optional[Piece] = None
    if captured_code is not None:
        if not isinstance(captured_code, int) or isinstance(captured_code, bool):
            raise ProtocolError("captured 必须是整数编码")
        try:
            captured = Piece.from_code(captured_code)
        except ValueError as exc:
            raise ProtocolError(str(exc)) from exc
    return Move(from_row, from_col, to_row, to_col, captured)


def serialize_moves(moves: Iterable[Move]) -> list[dict[str, object]]:
    """序列化完整着法序列；空序列返回空数组。"""
    return [serialize_move(move) for move in moves]  # type: ignore[misc]


def deserialize_moves(data: object) -> tuple[Move, ...]:
    """还原完整着法序列；非数组或含空着法时抛出 ProtocolError。"""
    if data is None:
        return ()
    if not isinstance(data, (list, tuple)):
        raise ProtocolError("moves 必须是数组")
    moves: list[Move] = []
    for item in data:
        move = deserialize_move(item)
        if move is None:
            raise ProtocolError("moves 不能包含空着法")
        moves.append(move)
    return tuple(moves)


def square_from_payload(data: object) -> Square:
    """解析 move_intent 的四个整数字段。"""
    if not isinstance(data, Mapping):
        raise ProtocolError("payload 必须是映射")
    try:
        from_row = int(data["from_row"])
        from_col = int(data["from_col"])
        to_row = int(data["to_row"])
        to_col = int(data["to_col"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ProtocolError("着法字段不完整") from exc
    if not (
        0 <= from_row < BOARD_ROWS
        and 0 <= from_col < BOARD_COLS
        and 0 <= to_row < BOARD_ROWS
        and 0 <= to_col < BOARD_COLS
    ):
        raise ProtocolError("着法坐标越界")
    return (from_row, from_col, to_row, to_col)


__all__ = [
    "PROTOCOL_VERSION",
    "MESSAGE_TYPES",
    "CLIENT_AUTH",
    "CLIENT_CREATE_ROOM",
    "CLIENT_JOIN_ROOM",
    "CLIENT_JOIN_QUEUE",
    "CLIENT_MOVE_INTENT",
    "CLIENT_UNDO_REQUEST",
    "CLIENT_UNDO_RESPONSE",
    "CLIENT_RESIGN",
    "CLIENT_REMATCH",
    "CLIENT_LEAVE",
    "CLIENT_INVITE_FRIEND",
    "CLIENT_CHALLENGE_RESPONSE",
    "CLIENT_CHAT",
    "CLIENT_SPECTATE",
    "SERVER_AUTH_OK",
    "SERVER_GAME_STATE",
    "SERVER_QUEUE_STATUS",
    "SERVER_MOVE_REJECTED",
    "SERVER_UNDO_REQUESTED",
    "SERVER_UNDO_RESULT",
    "SERVER_REMATCH_REQUESTED",
    "SERVER_ERROR",
    "SERVER_INVITE_RESULT",
    "SERVER_CHALLENGE",
    "SERVER_CHALLENGE_CANCELLED",
    "SERVER_CHAT",
    "SERVER_DIRECT_MESSAGE",
    "SERVER_SPECTATE_ENDED",
    "make_message",
    "parse_message",
    "serialize_board",
    "deserialize_board",
    "serialize_move",
    "deserialize_move",
    "serialize_moves",
    "deserialize_moves",
    "square_from_payload",
]
