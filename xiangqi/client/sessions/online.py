"""联机对局会话（服务器权威）。

客户端不维护可变的 GameModel：所有棋盘状态都来自服务端 game_state 快照。
本地只缓存不可变 BoardView，并通过协议发送 move_intent / undo_request /
resign / rematch。悔棋与再战需要对手同意。
"""

from __future__ import annotations

import logging
from typing import Mapping, Optional

from PySide6.QtCore import QObject, Signal

from xiangqi.client.board_view import BoardView
from xiangqi.client.sessions.base import GameSession
from xiangqi.client.transport import Transport
from xiangqi.shared.errors import ProtocolError
from xiangqi.shared.game_model import GameModel
from xiangqi.shared.protocol import (
    CLIENT_AUTH,
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
    SERVER_AUTH_OK,
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
    deserialize_board,
    deserialize_move,
    deserialize_moves,
    make_message,
    parse_message,
)
from xiangqi.shared.rules import (
    EndReason,
    Move,
    Side,
    legal_moves_from as rules_legal_moves_from,
)

logger = logging.getLogger(__name__)

ACTION_CREATE = "create"
ACTION_JOIN = "join"
ACTION_QUEUE = "queue"
ACTION_LOBBY = "lobby"

STATUS_CONNECTING = "connecting"
STATUS_QUEUED = "queued"
STATUS_WAITING = "waiting"
STATUS_PLAYING = "playing"
STATUS_FINISHED = "finished"
STATUS_DISCONNECTED = "disconnected"


class OnlineGameSession(GameSession):
    """一局联机对战。"""

    room_ready = Signal()
    queue_status = Signal(str)
    undo_requested = Signal(str)
    undo_resolved = Signal(bool, str)
    rematch_requested = Signal(str)
    challenge_received = Signal(str, str)
    challenge_cancelled = Signal(str, str)
    invite_status = Signal(str)
    invite_result = Signal(bool, str)

    def __init__(
        self,
        transport: Transport,
        token: str,
        action: str,
        room_code: Optional[str] = None,
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        if action not in (
            ACTION_CREATE,
            ACTION_JOIN,
            ACTION_QUEUE,
            ACTION_LOBBY,
        ):
            raise ValueError(f"未知联机动作：{action}")
        self._transport = transport
        self._token = token
        self._name = ""
        self._account_rating = 1200
        self._authed = False
        self._action = action
        self._join_code = (room_code or "").strip().upper()

        self._view = BoardView.empty()
        self._status = STATUS_CONNECTING
        self._connected = False
        self._ready = False
        self._paused = False
        self._shutdown = False
        self._your_side: Optional[Side] = None
        self._players: dict[Side, tuple[str, bool]] = {
            Side.RED: ("", False),
            Side.BLACK: ("", False),
        }
        self._undo_requester: Optional[Side] = None
        self._rematch_requests: set[Side] = set()
        self._ranked = False
        self._ratings: dict[Side, int] = {
            Side.RED: 1200,
            Side.BLACK: 1200,
        }
        self._rating_deltas: dict[Side, Optional[int]] = {
            Side.RED: None,
            Side.BLACK: None,
        }
        self._awaiting_move = False
        self._awaiting_undo = False
        self._game_over_emitted = False
        self._request_counter = 0
        self._moves: tuple[Move, ...] = ()

        transport.connected.connect(self._on_connected)
        transport.disconnected.connect(self._on_disconnected)
        transport.message_received.connect(self._on_message)
        transport.error.connect(self._on_transport_error)

    # ------------------------------------------------------------------
    # 连接
    # ------------------------------------------------------------------
    def connect_to(self, url: str) -> None:
        """连接服务器；连接成功后自动创建或加入房间。"""
        self._status = STATUS_CONNECTING
        self.state_changed.emit()
        self._transport.open(url)

    def _on_connected(self) -> None:
        self._connected = True
        self._send(
            CLIENT_AUTH,
            {"token": self._token},
            request_id="auth",
        )

    def _send_action(self) -> None:
        if self._action == ACTION_LOBBY:
            return
        if self._action == ACTION_CREATE:
            self._send(
                CLIENT_CREATE_ROOM,
                request_id="create",
            )
        elif self._action == ACTION_QUEUE:
            self._send(
                CLIENT_JOIN_QUEUE,
                request_id="queue",
            )
        else:
            self._send(
                CLIENT_JOIN_ROOM,
                {"room_code": self._join_code},
                request_id="join",
            )

    def _on_disconnected(self) -> None:
        self._connected = False
        if self._shutdown:
            return
        self._status = STATUS_DISCONNECTED
        self._awaiting_move = False
        self._awaiting_undo = False
        self.state_changed.emit()
        self.error.emit("与服务器的连接已断开")

    def _on_transport_error(self, message: str) -> None:
        if self._shutdown:
            return
        self.error.emit(message)

    # ------------------------------------------------------------------
    # 只读状态
    # ------------------------------------------------------------------
    @property
    def view(self) -> BoardView:
        return self._view

    @property
    def model(self) -> Optional[GameModel]:
        return None

    @property
    def human_side(self) -> Optional[Side]:
        return self._your_side

    @property
    def your_side(self) -> Optional[Side]:
        return self._your_side

    @property
    def account_nickname(self) -> str:
        return self._name

    @property
    def account_rating(self) -> int:
        return self._account_rating

    @property
    def authenticated(self) -> bool:
        return self._authed

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def action(self) -> str:
        return self._action

    @property
    def room_code(self) -> str:
        return self._join_code or ""

    @property
    def status(self) -> str:
        return self._status

    @property
    def players(self) -> dict[Side, tuple[str, bool]]:
        return dict(self._players)

    @property
    def ranked(self) -> bool:
        return self._ranked

    def rating_for(self, side: Side) -> int:
        return self._ratings.get(side, 1200)

    def rating_delta_for(self, side: Side) -> Optional[int]:
        return self._rating_deltas.get(side)

    @property
    def move_history(self) -> tuple[Move, ...]:
        """服务器确认过的完整着法历史（用于棋谱/复盘）。"""
        return self._moves

    @property
    def opponent_name(self) -> str:
        if self._your_side is None:
            return "对手"
        name, _ = self._players[self._your_side.opponent]
        return name or "对手"

    @property
    def undo_requester(self) -> Optional[Side]:
        return self._undo_requester

    @property
    def rematch_requests(self) -> set[Side]:
        return set(self._rematch_requests)

    @property
    def busy(self) -> bool:
        return self._awaiting_move or self._awaiting_undo

    @property
    def waiting_for_opponent(self) -> bool:
        return self._status == STATUS_WAITING

    @property
    def accepts_human_input(self) -> bool:
        return (
            self._ready
            and self._connected
            and not self._shutdown
            and not self._paused
            and self._status == STATUS_PLAYING
            and self._your_side is not None
            and self._your_side is self._view.side_to_move
            and not self._awaiting_move
            and not self._awaiting_undo
            and self._undo_requester is None
            and not self._view.is_game_over
        )

    @property
    def can_undo(self) -> bool:
        return (
            self._ready
            and self._connected
            and self._status == STATUS_PLAYING
            and self._view.move_count > 0
            and not self._awaiting_move
            and not self._awaiting_undo
            and self._undo_requester is None
        )

    # ------------------------------------------------------------------
    # 意图
    # ------------------------------------------------------------------
    def legal_moves_from(self, row: int, col: int) -> tuple[Move, ...]:
        if not self.accepts_human_input:
            return ()
        board = self._view.board
        if not (0 <= row < len(board) and 0 <= col < len(board[row])):
            return ()
        piece = board[row][col]
        if piece is None or piece.side is not self._your_side:
            return ()
        return rules_legal_moves_from(board, row, col)

    def request_move(
        self,
        from_row: int,
        from_col: int,
        to_row: int,
        to_col: int,
    ) -> bool:
        if not self.accepts_human_input:
            return False
        self._request_counter += 1
        sent = self._send(
            CLIENT_MOVE_INTENT,
            {
                "from_row": from_row,
                "from_col": from_col,
                "to_row": to_row,
                "to_col": to_col,
            },
            request_id=f"move-{self._request_counter}",
        )
        if not sent:
            return False
        self._awaiting_move = True
        self.state_changed.emit()
        return True

    def request_undo(self) -> bool:
        if not self.can_undo:
            return False
        if not self._send(CLIENT_UNDO_REQUEST):
            return False
        self._awaiting_undo = True
        self.state_changed.emit()
        return True

    def respond_undo(self, accept: bool) -> bool:
        if not self._connected or self._undo_requester is None:
            return False
        if not self._send(CLIENT_UNDO_RESPONSE, {"accept": bool(accept)}):
            return False
        self._awaiting_undo = True
        self.state_changed.emit()
        return True

    def request_resign(self) -> bool:
        if self._status != STATUS_PLAYING or not self._connected:
            return False
        return self._send(CLIENT_RESIGN)

    def request_restart(self) -> bool:
        if self._status != STATUS_FINISHED or not self._connected:
            return False
        return self._send(CLIENT_REMATCH)

    def invite_friend(self, nickname: str) -> bool:
        """自建房房主邀请好友。"""
        if not self._connected or not isinstance(nickname, str):
            return False
        return self._send(
            CLIENT_INVITE_FRIEND, {"nickname": nickname}
        )

    def respond_challenge(
        self, challenge_id: str, accept: bool
    ) -> bool:
        if not self._connected or not challenge_id:
            return False
        return self._send(
            CLIENT_CHALLENGE_RESPONSE,
            {
                "challenge_id": challenge_id,
                "accept": bool(accept),
            },
        )

    def pause(self) -> None:
        if self._paused:
            return
        self._paused = True
        self.state_changed.emit()

    def resume(self) -> None:
        if not self._paused:
            return
        self._paused = False
        self.state_changed.emit()

    def cancel_queue(self) -> bool:
        """取消排位匹配：通知服务端离开队列并关闭连接。"""
        if self._shutdown:
            return False
        was_queued = self._status in (STATUS_CONNECTING, STATUS_QUEUED)
        if self._connected:
            self._send(CLIENT_LEAVE)
        self._shutdown = True
        self._status = STATUS_DISCONNECTED
        self._connected = False
        self._transport.close()
        return was_queued

    def shutdown(self) -> None:
        if self._shutdown:
            return
        self._shutdown = True
        if self._connected:
            self._send(CLIENT_LEAVE)
        self._transport.close()
        self._connected = False
        self._status = STATUS_DISCONNECTED

    # ------------------------------------------------------------------
    # 消息
    # ------------------------------------------------------------------
    def _on_message(self, data: object) -> None:
        try:
            message_type, payload, _request_id = parse_message(data)
        except ProtocolError as exc:
            self.error.emit(f"服务器消息无效：{exc}")
            return

        if message_type == SERVER_AUTH_OK:
            self._authed = True
            self._name = str(payload.get("nickname", ""))
            self._account_rating = int(
                payload.get("rating", 1200)
            )
            self.state_changed.emit()
            self._send_action()
        elif message_type == SERVER_GAME_STATE:
            self._apply_game_state(payload)
        elif message_type == SERVER_QUEUE_STATUS:
            message = str(payload.get("message", "正在匹配…"))
            self._status = STATUS_QUEUED
            self.queue_status.emit(message)
            self.state_changed.emit()
        elif message_type == SERVER_MOVE_REJECTED:
            self._awaiting_move = False
            self.error.emit(str(payload.get("reason", "落子被拒绝")))
            self.state_changed.emit()
        elif message_type == SERVER_UNDO_REQUESTED:
            name = str(payload.get("name", "对手"))
            side_raw = payload.get("side")
            if side_raw in (Side.RED.value, Side.BLACK.value):
                self._undo_requester = Side(side_raw)
            self.undo_requested.emit(name)
            self.state_changed.emit()
        elif message_type == SERVER_UNDO_RESULT:
            accepted = bool(payload.get("accepted"))
            reason = str(payload.get("reason", ""))
            self._awaiting_undo = False
            self.undo_resolved.emit(accepted, reason)
            self.state_changed.emit()
        elif message_type == SERVER_REMATCH_REQUESTED:
            self.rematch_requested.emit(
                str(payload.get("name", "对手"))
            )
        elif message_type == SERVER_CHALLENGE:
            self.challenge_received.emit(
                str(payload.get("challenge_id", "")),
                str(payload.get("name", "好友")),
            )
            self.state_changed.emit()
        elif message_type == SERVER_CHALLENGE_CANCELLED:
            self.challenge_cancelled.emit(
                str(payload.get("challenge_id", "")),
                str(payload.get("reason", "挑战已取消")),
            )
            self.state_changed.emit()
        elif message_type == SERVER_INVITE_RESULT:
            status = str(payload.get("status", ""))
            name = str(payload.get("name", "好友"))
            reason = str(payload.get("reason", ""))
            if status == "sent":
                self.invite_status.emit(f"已向 {name} 发送挑战")
            elif payload.get("accepted") is True:
                self.invite_result.emit(
                    True, f"{name} 接受了挑战"
                )
            else:
                self.invite_result.emit(
                    False, reason or "好友暂时无法接受挑战"
                )
            self.state_changed.emit()
        elif message_type == SERVER_ERROR:
            self._awaiting_move = False
            self._awaiting_undo = False
            self.error.emit(str(payload.get("message", "联机错误")))
            self.state_changed.emit()

    def _apply_game_state(self, payload: Mapping[str, object]) -> None:
        try:
            board = deserialize_board(payload.get("board"))
            side_to_move = Side(str(payload.get("side_to_move")))
            status = str(payload.get("status", STATUS_WAITING))
            your_raw = payload.get("your_side")
            your_side = (
                Side(your_raw)
                if your_raw in (Side.RED.value, Side.BLACK.value)
                else None
            )
            winner_raw = payload.get("winner")
            winner = (
                Side(winner_raw)
                if winner_raw in (Side.RED.value, Side.BLACK.value)
                else None
            )
            reason_raw = payload.get("end_reason")
            end_reason = (
                EndReason(reason_raw) if reason_raw else None
            )
            last_move = deserialize_move(payload.get("last_move"))
            raw_moves = payload.get("moves")
            if raw_moves is not None:
                moves = deserialize_moves(raw_moves)
            else:
                moves = ()
            is_check = bool(payload.get("is_check"))
            move_count = int(payload.get("move_count", 0))
            room_code = str(payload.get("room_code", ""))
            ranked = bool(payload.get("ranked", False))
            undo_raw = payload.get("undo_requester")
            undo_requester = (
                Side(undo_raw)
                if undo_raw in (Side.RED.value, Side.BLACK.value)
                else None
            )
            rematch_raw = payload.get("rematch_requests", [])
            rematch_requests = {
                Side(value)
                for value in rematch_raw
                if value in (Side.RED.value, Side.BLACK.value)
            }
            players_raw = payload.get("players", {})
            if not isinstance(players_raw, Mapping):
                raise ProtocolError("players 必须是对象")
            players: dict[Side, tuple[str, bool]] = {}
            ratings: dict[Side, int] = {}
            rating_deltas: dict[Side, Optional[int]] = {}
            for side, key in ((Side.RED, "red"), (Side.BLACK, "black")):
                item = players_raw.get(key, {})
                if not isinstance(item, Mapping):
                    raise ProtocolError(f"players.{key} 必须是对象")
                players[side] = (
                    str(item.get("name", "")),
                    bool(item.get("connected")),
                )
                ratings[side] = int(item.get("rating", 1200))
                delta_raw = item.get("rating_delta")
                rating_deltas[side] = (
                    int(delta_raw)
                    if isinstance(delta_raw, int)
                    and not isinstance(delta_raw, bool)
                    else None
                )
        except (ProtocolError, ValueError, TypeError) as exc:
            self.error.emit(f"服务器快照无效：{exc}")
            return

        was_ready = self._ready
        previous_count = self._view.move_count
        previous_finished = self._status == STATUS_FINISHED
        previous_game_over = self._game_over_emitted

        if raw_moves is None:
            moves = self._fallback_moves(
                previous_count, move_count, last_move
            )
        self._moves = moves

        self._view = BoardView(
            board=board,
            side_to_move=side_to_move,
            last_move=last_move,
            is_check=is_check,
            winner=winner,
            end_reason=end_reason,
            is_game_over=status == STATUS_FINISHED,
            move_count=move_count,
        )
        self._status = status
        self._your_side = your_side
        self._players = players
        self._ranked = ranked
        self._ratings = ratings
        self._rating_deltas = rating_deltas
        self._undo_requester = undo_requester
        self._rematch_requests = rematch_requests
        self._awaiting_move = False
        self._awaiting_undo = False
        if status != STATUS_FINISHED:
            self._game_over_emitted = False
        if room_code:
            self._join_code = room_code

        if not was_ready:
            self._ready = True
            self.room_ready.emit()

        self.state_changed.emit()
        if was_ready and move_count > previous_count:
            self.move_made.emit()
        if (
            status == STATUS_FINISHED
            and not previous_finished
            and not previous_game_over
        ):
            self._game_over_emitted = True
            self.game_over.emit()

    def _fallback_moves(
        self,
        previous_count: int,
        move_count: int,
        last_move: Optional[Move],
    ) -> tuple[Move, ...]:
        """兼容旧服务端快照：只带 ``last_move`` 时尽力累积历史。"""
        if move_count <= 0:
            return ()
        if move_count <= previous_count:
            return self._moves[:move_count]
        history = list(self._moves[:previous_count])
        if last_move is not None:
            history.append(last_move)
        return tuple(history[:move_count])

    # ------------------------------------------------------------------
    # 发送
    # ------------------------------------------------------------------
    def _send(
        self,
        message_type: str,
        payload: Optional[Mapping[str, object]] = None,
        request_id: Optional[str] = None,
    ) -> bool:
        try:
            message = make_message(message_type, payload, request_id)
        except ProtocolError as exc:
            self.error.emit(str(exc))
            return False
        try:
            self._transport.send_message(message)
        except Exception as exc:
            logger.exception("发送联机消息失败")
            self.error.emit(f"发送失败：{exc}")
            return False
        return True


__all__ = [
    "OnlineGameSession",
    "ACTION_CREATE",
    "ACTION_JOIN",
    "ACTION_QUEUE",
    "ACTION_LOBBY",
    "STATUS_CONNECTING",
    "STATUS_QUEUED",
    "STATUS_WAITING",
    "STATUS_PLAYING",
    "STATUS_FINISHED",
    "STATUS_DISCONNECTED",
]
