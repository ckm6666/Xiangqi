"""联机会话测试（FakeTransport，不启动真实服务器）。"""

from __future__ import annotations

import unittest

from tests.qt_helpers import ensure_qt_app

ensure_qt_app()

from tests.fakes import FakeTransport  # noqa: E402
from xiangqi.client.sessions.online import (  # noqa: E402
    ACTION_CREATE,
    ACTION_JOIN,
    ACTION_LOBBY,
    ACTION_QUEUE,
    ACTION_SPECTATE,
    OnlineGameSession,
    STATUS_DISCONNECTED,
    STATUS_FINISHED,
    STATUS_PLAYING,
    STATUS_QUEUED,
    STATUS_WAITING,
)
from xiangqi.shared.game_model import GameModel  # noqa: E402
from xiangqi.shared.protocol import (  # noqa: E402
    SERVER_AUTH_OK,
    SERVER_CHALLENGE,
    SERVER_CHALLENGE_CANCELLED,
    SERVER_ERROR,
    SERVER_GAME_STATE,
    SERVER_INVITE_RESULT,
    SERVER_MOVE_REJECTED,
    SERVER_QUEUE_STATUS,
    SERVER_REMATCH_REQUESTED,
    SERVER_SPECTATE_ENDED,
    SERVER_UNDO_REQUESTED,
    SERVER_UNDO_RESULT,
    make_message,
    serialize_board,
)
from xiangqi.shared.rules import Side  # noqa: E402


def snapshot(
    *,
    status: str = STATUS_PLAYING,
    your_side: str | None = "red",
    side_to_move: str = "red",
    move_count: int = 0,
    red: tuple[str, bool] = ("红方", True),
    black: tuple[str, bool] = ("黑方", True),
    winner: str | None = None,
    end_reason: str | None = None,
    undo_requester: str | None = None,
    rematch_requests: tuple[str, ...] = (),
    is_check: bool = False,
    last_move: dict | None = None,
    board=None,
    ranked: bool = False,
    red_rating: int = 1200,
    black_rating: int = 1200,
    red_delta: int | None = None,
    black_delta: int | None = None,
    spectator: bool = False,
) -> dict:
    payload = {
        "room_code": "ABCD",
        "status": status,
        "ranked": ranked,
        "your_side": your_side,
        "spectator": spectator,
        "players": {
            "red": {
                "name": red[0],
                "connected": red[1],
                "rating": red_rating,
                "rating_delta": red_delta,
            },
            "black": {
                "name": black[0],
                "connected": black[1],
                "rating": black_rating,
                "rating_delta": black_delta,
            },
        },
        "board": serialize_board(
            board if board is not None else GameModel.initial().board
        ),
        "side_to_move": side_to_move,
        "last_move": last_move,
        "is_check": is_check,
        "winner": winner,
        "end_reason": end_reason,
        "move_count": move_count,
        "undo_requester": undo_requester,
        "rematch_requests": list(rematch_requests),
        "state_version": 1,
    }
    return payload


class OnlineSessionTests(unittest.TestCase):
    """创建/加入、权威快照、悔棋、认输与再战。"""

    def _make_session(
        self, action=ACTION_CREATE, code=None, target_name=None
    ):
        transport = FakeTransport()
        session = OnlineGameSession(
            transport,
            token="test-token",
            action=action,
            room_code=code,
            target_name=target_name,
        )
        session.connect_to("ws://localhost:8000/api/v1/ws")
        return transport, session

    def _connect(
        self,
        transport: FakeTransport,
        nickname: str = "测试棋友",
        rating: int = 1200,
    ) -> None:
        transport.simulate_connected()
        self.assertEqual(transport.sent[-1]["type"], "auth")
        transport.server_send(
            make_message(
                SERVER_AUTH_OK,
                {
                    "user_id": 1,
                    "nickname": nickname,
                    "rating": rating,
                },
            )
        )

    def _apply(self, transport: FakeTransport, payload: dict) -> None:
        transport.server_send(
            make_message(SERVER_GAME_STATE, payload)
        )

    def test_create_room_flow(self) -> None:
        transport, session = self._make_session()
        ready: list[bool] = []
        session.room_ready.connect(lambda: ready.append(True))

        self.assertEqual(
            transport.opened, ["ws://localhost:8000/api/v1/ws"]
        )
        self._connect(transport)
        self.assertEqual(len(transport.sent), 2)
        self.assertEqual(transport.sent[0]["type"], "auth")
        self.assertEqual(transport.sent[-1]["type"], "create_room")
        self.assertEqual(
            session.account_nickname, "测试棋友"
        )

        self._apply(transport, snapshot(your_side="red"))
        self.assertEqual(ready, [True])
        self.assertEqual(session.status, STATUS_PLAYING)
        self.assertIs(session.human_side, Side.RED)
        self.assertTrue(session.accepts_human_input)
        self.assertEqual(session.room_code, "ABCD")
        targets = {
            move.target for move in session.legal_moves_from(6, 0)
        }
        self.assertIn((5, 0), targets)

    def test_join_room_flow(self) -> None:
        transport, session = self._make_session(
            action=ACTION_JOIN, code="abcd"
        )
        self._connect(transport)
        message = transport.sent[-1]
        self.assertEqual(message["type"], "join_room")
        self.assertEqual(message["payload"]["room_code"], "ABCD")

        self._apply(
            transport,
            snapshot(
                your_side="black",
                side_to_move="red",
                red=("对手", True),
                black=("测试棋友", True),
            ),
        )
        self.assertIs(session.human_side, Side.BLACK)
        self.assertEqual(session.opponent_name, "对手")
        self.assertFalse(session.accepts_human_input)

    def test_auth_handshake_before_action(self) -> None:
        transport, session = self._make_session()
        transport.simulate_connected()
        self.assertEqual(len(transport.sent), 1)
        self.assertEqual(transport.sent[0]["type"], "auth")
        self.assertFalse(session.authenticated)

        transport.server_send(
            make_message(
                SERVER_AUTH_OK,
                {
                    "user_id": 9,
                    "nickname": "账号甲",
                    "rating": 1288,
                },
            )
        )
        self.assertTrue(session.authenticated)
        self.assertEqual(session.account_nickname, "账号甲")
        self.assertEqual(session.account_rating, 1288)
        self.assertEqual(transport.sent[-1]["type"], "create_room")

    def test_move_flow(self) -> None:
        transport, session = self._make_session()
        self._connect(transport)
        self._apply(transport, snapshot(your_side="red"))
        move_events: list[bool] = []
        session.move_made.connect(lambda: move_events.append(True))

        self.assertTrue(session.request_move(6, 0, 5, 0))
        sent = transport.sent[-1]
        self.assertEqual(sent["type"], "move_intent")
        self.assertEqual(sent["payload"]["to_row"], 5)
        self.assertTrue(session.busy)
        self.assertFalse(session.accepts_human_input)

        self._apply(
            transport,
            snapshot(
                your_side="red",
                side_to_move="black",
                move_count=1,
                last_move={
                    "from_row": 6,
                    "from_col": 0,
                    "to_row": 5,
                    "to_col": 0,
                },
            ),
        )
        self.assertFalse(session.busy)
        self.assertFalse(session.accepts_human_input)
        self.assertEqual(session.view.move_count, 1)
        self.assertEqual(move_events, [True])
        self.assertEqual(
            session.view.last_move.target, (5, 0)
        )

        self._apply(
            transport,
            snapshot(
                your_side="red",
                side_to_move="red",
                move_count=2,
            ),
        )
        self.assertTrue(session.accepts_human_input)
        self.assertEqual(move_events, [True, True])

    def test_move_rejected(self) -> None:
        transport, session = self._make_session()
        self._connect(transport)
        self._apply(transport, snapshot(your_side="red"))
        errors: list[str] = []
        session.error.connect(errors.append)

        self.assertTrue(session.request_move(6, 0, 5, 0))
        transport.server_send(
            make_message(
                SERVER_MOVE_REJECTED, {"reason": "落子不合法"}
            )
        )
        self.assertFalse(session.busy)
        self.assertTrue(errors)
        self.assertTrue(session.accepts_human_input)

    def test_opponent_requests_undo(self) -> None:
        transport, session = self._make_session()
        self._connect(transport)
        self._apply(
            transport,
            snapshot(
                your_side="red",
                side_to_move="black",
                move_count=1,
            ),
        )
        requests: list[str] = []
        results: list[tuple[bool, str]] = []
        session.undo_requested.connect(requests.append)
        session.undo_resolved.connect(
            lambda accepted, reason: results.append((accepted, reason))
        )

        transport.server_send(
            make_message(
                SERVER_UNDO_REQUESTED,
                {"name": "黑方", "side": "black"},
            )
        )
        self.assertEqual(requests, ["黑方"])
        self.assertTrue(session.respond_undo(True))
        self.assertEqual(transport.sent[-1]["type"], "undo_response")
        self.assertTrue(transport.sent[-1]["payload"]["accept"])

        transport.server_send(
            make_message(
                SERVER_UNDO_RESULT,
                {"accepted": True, "reason": "已同意悔棋"},
            )
        )
        self.assertEqual(results, [(True, "已同意悔棋")])
        self.assertFalse(session.busy)

    def test_request_undo(self) -> None:
        transport, session = self._make_session()
        self._connect(transport)
        self._apply(
            transport,
            snapshot(
                your_side="red",
                side_to_move="black",
                move_count=1,
            ),
        )
        self.assertTrue(session.can_undo)
        self.assertTrue(session.request_undo())
        self.assertEqual(transport.sent[-1]["type"], "undo_request")
        self.assertTrue(session.busy)
        self.assertFalse(session.can_undo)

        self._apply(
            transport,
            snapshot(
                your_side="red",
                side_to_move="black",
                move_count=1,
                undo_requester="red",
            ),
        )
        self.assertFalse(session.busy)
        self.assertIs(session.undo_requester, Side.RED)
        self.assertFalse(session.accepts_human_input)

    def test_resign_and_rematch(self) -> None:
        transport, session = self._make_session()
        self._connect(transport)
        self._apply(transport, snapshot(your_side="red"))
        over: list[bool] = []
        session.game_over.connect(lambda: over.append(True))

        self.assertTrue(session.request_resign())
        self.assertEqual(transport.sent[-1]["type"], "resign")
        self._apply(
            transport,
            snapshot(
                your_side="red",
                side_to_move="black",
                status=STATUS_FINISHED,
                winner="black",
                end_reason="resign",
                move_count=0,
            ),
        )
        self.assertEqual(over, [True])
        self.assertIs(session.view.winner, Side.BLACK)
        self.assertFalse(session.accepts_human_input)
        self.assertTrue(session.request_restart())
        self.assertEqual(transport.sent[-1]["type"], "rematch")

        self._apply(
            transport,
            snapshot(your_side="red", move_count=0),
        )
        self.assertTrue(session.accepts_human_input)
        self._apply(
            transport,
            snapshot(
                your_side="red",
                status=STATUS_FINISHED,
                winner="red",
                end_reason="checkmate",
                move_count=3,
            ),
        )
        self.assertEqual(over, [True, True])

    def test_waiting_room_and_rematch_request(self) -> None:
        transport, session = self._make_session()
        self._connect(transport)
        self._apply(
            transport,
            snapshot(
                status=STATUS_WAITING,
                your_side="red",
                red=("房主", True),
                black=("", False),
            ),
        )
        self.assertTrue(session.waiting_for_opponent)
        self.assertFalse(session.accepts_human_input)
        self.assertFalse(session.request_restart())

        requests: list[str] = []
        session.rematch_requested.connect(requests.append)
        transport.server_send(
            make_message(
                SERVER_REMATCH_REQUESTED, {"name": "黑方"}
            )
        )
        self.assertEqual(requests, ["黑方"])

    def test_disconnect_and_invalid_snapshot(self) -> None:
        transport, session = self._make_session()
        self._connect(transport)
        self._apply(transport, snapshot(your_side="red"))
        errors: list[str] = []
        session.error.connect(errors.append)

        transport.simulate_disconnected()
        self.assertEqual(session.status, STATUS_DISCONNECTED)
        self.assertFalse(session.accepts_human_input)
        self.assertTrue(errors)

        transport.server_send(
            make_message(SERVER_ERROR, {"message": "测试错误"})
        )
        self.assertIn("测试错误", errors)

        transport.server_send(
            make_message(
                SERVER_GAME_STATE,
                {**snapshot(your_side="red"), "board": []},
            )
        )
        self.assertTrue(
            any("快照" in message for message in errors)
        )

    def test_ranked_queue_and_rating(self) -> None:
        transport, session = self._make_session(action=ACTION_QUEUE)
        self._connect(transport)
        self.assertEqual(transport.sent[-1]["type"], "join_queue")

        statuses: list[str] = []
        session.queue_status.connect(statuses.append)
        transport.server_send(
            make_message(
                SERVER_QUEUE_STATUS,
                {
                    "message": "正在匹配…（第 1 位）",
                    "position": 1,
                    "queued": 1,
                    "rating": 1200,
                },
            )
        )
        self.assertEqual(session.status, STATUS_QUEUED)
        self.assertEqual(statuses, ["正在匹配…（第 1 位）"])

        self._apply(
            transport,
            snapshot(
                ranked=True,
                red_rating=1250,
                black_rating=1230,
            ),
        )
        self.assertTrue(session.ranked)
        self.assertEqual(session.status, STATUS_PLAYING)
        self.assertEqual(session.rating_for(Side.RED), 1250)
        self.assertEqual(session.rating_for(Side.BLACK), 1230)
        self.assertIsNone(session.rating_delta_for(Side.RED))

        self._apply(
            transport,
            snapshot(
                status=STATUS_FINISHED,
                ranked=True,
                winner="red",
                end_reason="resign",
                red_rating=1266,
                black_rating=1214,
                red_delta=16,
                black_delta=-16,
            ),
        )
        self.assertEqual(session.rating_delta_for(Side.RED), 16)
        self.assertEqual(session.rating_delta_for(Side.BLACK), -16)
        self.assertEqual(session.rating_for(Side.RED), 1266)

    def test_lobby_challenge_and_response(self) -> None:
        transport, session = self._make_session(
            action=ACTION_LOBBY
        )
        self._connect(transport)
        self.assertEqual(transport.sent[-1]["type"], "auth")
        received: list[tuple[str, str]] = []
        cancelled: list[tuple[str, str]] = []
        session.challenge_received.connect(
            lambda challenge_id, name: received.append(
                (challenge_id, name)
            )
        )
        session.challenge_cancelled.connect(
            lambda challenge_id, reason: cancelled.append(
                (challenge_id, reason)
            )
        )
        transport.server_send(
            make_message(
                SERVER_CHALLENGE,
                {"challenge_id": "c1", "name": "好友甲"},
            )
        )
        self.assertEqual(received, [("c1", "好友甲")])
        self.assertTrue(session.respond_challenge("c1", True))
        self.assertEqual(
            transport.sent[-1]["type"], "challenge_response"
        )
        self.assertEqual(
            transport.sent[-1]["payload"]["challenge_id"], "c1"
        )
        self.assertTrue(transport.sent[-1]["payload"]["accept"])

        transport.server_send(
            make_message(
                SERVER_CHALLENGE_CANCELLED,
                {"challenge_id": "c1", "reason": "房主已离开"},
            )
        )
        self.assertEqual(cancelled, [("c1", "房主已离开")])

        self._apply(
            transport,
            snapshot(
                your_side="black",
                red=("好友甲", True),
                black=("测试棋友", True),
            ),
        )
        self.assertEqual(session.status, STATUS_PLAYING)
        self.assertIs(session.human_side, Side.BLACK)

    def test_invite_friend_and_result(self) -> None:
        transport, session = self._make_session()
        self._connect(transport)
        self._apply(
            transport,
            snapshot(
                status=STATUS_WAITING,
                your_side="red",
                black=("", False),
            ),
        )
        self.assertTrue(session.invite_friend("好友甲"))
        self.assertEqual(
            transport.sent[-1]["type"], "invite_friend"
        )
        self.assertEqual(
            transport.sent[-1]["payload"]["nickname"], "好友甲"
        )
        statuses: list[str] = []
        results: list[tuple[bool, str]] = []
        session.invite_status.connect(statuses.append)
        session.invite_result.connect(
            lambda accepted, message: results.append(
                (accepted, message)
            )
        )
        transport.server_send(
            make_message(
                SERVER_INVITE_RESULT,
                {"status": "sent", "name": "好友甲"},
            )
        )
        self.assertTrue(statuses)
        transport.server_send(
            make_message(
                SERVER_INVITE_RESULT,
                {
                    "status": "declined",
                    "accepted": False,
                    "name": "好友甲",
                    "reason": "对方拒绝了挑战",
                },
            )
        )
        self.assertEqual(results, [(False, "对方拒绝了挑战")])
        transport.server_send(
            make_message(
                SERVER_INVITE_RESULT,
                {
                    "status": "accepted",
                    "accepted": True,
                    "name": "好友甲",
                },
            )
        )
        self.assertTrue(results[-1][0])

    def test_spectate_flow_is_read_only(self) -> None:
        transport, session = self._make_session(
            action=ACTION_SPECTATE, target_name="好友甲"
        )
        ready: list[bool] = []
        ended: list[str] = []
        session.room_ready.connect(lambda: ready.append(True))
        session.spectate_ended.connect(ended.append)
        self._connect(transport)
        sent = transport.sent[-1]
        self.assertEqual(sent["type"], "spectate")
        self.assertEqual(sent["payload"]["nickname"], "好友甲")
        self.assertTrue(session.spectating)

        self._apply(
            transport,
            snapshot(
                your_side=None,
                red=("好友甲", True),
                black=("对手乙", True),
                spectator=True,
            ),
        )
        self.assertTrue(ready)
        self.assertTrue(session.spectating)
        self.assertIsNone(session.human_side)
        self.assertFalse(session.accepts_human_input)
        self.assertFalse(session.chat_available)
        self.assertFalse(session.can_undo)
        self.assertFalse(session.request_resign())
        self.assertFalse(session.request_restart())

        transport.server_send(
            make_message(
                SERVER_SPECTATE_ENDED, {"reason": "对局已结束"}
            )
        )
        self.assertEqual(ended, ["对局已结束"])

    def test_room_ready_emitted_once(self) -> None:
        transport, session = self._make_session()
        self._connect(transport)
        ready: list[bool] = []
        session.room_ready.connect(lambda: ready.append(True))
        self._apply(transport, snapshot(your_side="red"))
        self._apply(transport, snapshot(your_side="red", move_count=0))
        self.assertEqual(ready, [True])


if __name__ == "__main__":
    unittest.main()
