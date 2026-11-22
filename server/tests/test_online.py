"""联机服务端测试：账号、房间、走子、悔棋、排位。"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from server.app.main import create_app
from server.app.ws.rooms import Connection, Room, RoomManager
from xiangqi.shared.chat import (
    CHAT_BURST,
    CHAT_KIND_TEXT,
    EMOJI_PRESETS,
    CHAT_KIND_EMOJI,
)
from xiangqi.shared.protocol import (
    CLIENT_AUTH,
    CLIENT_CHALLENGE_RESPONSE,
    CLIENT_CHAT,
    CLIENT_CREATE_ROOM,
    CLIENT_INVITE_FRIEND,
    CLIENT_JOIN_QUEUE,
    CLIENT_JOIN_ROOM,
    CLIENT_MOVE_INTENT,
    CLIENT_REMATCH,
    CLIENT_RESIGN,
    CLIENT_SPECTATE,
    CLIENT_UNDO_REQUEST,
    CLIENT_UNDO_RESPONSE,
    SERVER_AUTH_OK,
    SERVER_CHALLENGE,
    SERVER_CHAT,
    SERVER_DIRECT_MESSAGE,
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
)


def receive(ws) -> dict:
    return ws.receive_json()


def receive_state(ws) -> dict:
    while True:
        message = ws.receive_json()
        if message["type"] == SERVER_GAME_STATE:
            return message["payload"]


def register(client: TestClient, nickname: str) -> dict:
    response = client.post(
        "/api/v1/auth/register",
        json={"nickname": nickname, "password": "secret123"},
    )
    if response.status_code != 200:
        raise AssertionError(response.text)
    return response.json()


def authenticate(ws, token: str) -> dict:
    ws.send_json(make_message(CLIENT_AUTH, {"token": token}))
    message = receive(ws)
    if message["type"] != SERVER_AUTH_OK:
        raise AssertionError(message)
    return message["payload"]


def create_room(ws) -> dict:
    ws.send_json(make_message(CLIENT_CREATE_ROOM))
    return receive_state(ws)


def join_room(ws, code: str) -> dict:
    ws.send_json(
        make_message(CLIENT_JOIN_ROOM, {"room_code": code})
    )
    return receive_state(ws)


def join_queue(ws) -> dict:
    ws.send_json(make_message(CLIENT_JOIN_QUEUE))
    return receive(ws)


def send_move(ws, fr: int, fc: int, tr: int, tc: int) -> None:
    ws.send_json(
        make_message(
            CLIENT_MOVE_INTENT,
            {
                "from_row": fr,
                "from_col": fc,
                "to_row": tr,
                "to_col": tc,
            },
            request_id="m1",
        )
    )


class OnlineServerTests(unittest.TestCase):
    """端到端 WebSocket 流程。"""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.app = create_app(Path(self.tmp.name) / "test.db")
        self.client = TestClient(self.app)
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)

    def _socket(self, nickname: str):
        info = register(self.client, nickname)
        ws = self.client.websocket_connect("/api/v1/ws")
        ws.__enter__()
        self.addCleanup(ws.__exit__, None, None, None)
        auth = authenticate(ws, info["token"])
        self.assertEqual(auth["nickname"], nickname)
        return ws, info

    def _open_pair(self):
        host, host_info = self._socket("红方棋友")
        host_state = create_room(host)
        code = host_state["room_code"]

        guest, guest_info = self._socket("黑方棋友")
        guest_state = join_room(guest, code)
        host_state = receive_state(host)
        return (
            host,
            guest,
            host_state,
            guest_state,
            code,
            host_info,
            guest_info,
        )

    def _queue_pair(self):
        host, _host_info = self._socket("排位甲")
        queued = join_queue(host)
        self.assertEqual(queued["type"], SERVER_QUEUE_STATUS)
        self.assertEqual(queued["payload"]["rating"], 1200)
        self.assertIn("正在匹配", queued["payload"]["message"])

        guest, _guest_info = self._socket("排位乙")
        guest.send_json(make_message(CLIENT_JOIN_QUEUE))
        host_state = receive_state(host)
        guest_state = receive_state(guest)
        return host, guest, host_state, guest_state

    # ------------------------------------------------------------------
    # 账号
    # ------------------------------------------------------------------
    def test_health(self) -> None:
        response = self.client.get("/api/v1/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")

    def test_register_and_login(self) -> None:
        info = register(self.client, "账号甲")
        self.assertEqual(info["nickname"], "账号甲")
        self.assertEqual(info["rating"], 1200)
        self.assertEqual(info["avatar"], "default:1")
        self.assertTrue(info["token"])

        login = self.client.post(
            "/api/v1/auth/login",
            json={"nickname": "账号甲", "password": "secret123"},
        )
        self.assertEqual(login.status_code, 200)
        self.assertEqual(login.json()["user_id"], info["user_id"])

        wrong = self.client.post(
            "/api/v1/auth/login",
            json={"nickname": "账号甲", "password": "wrong-pass"},
        )
        self.assertEqual(wrong.status_code, 401)

        duplicate = self.client.post(
            "/api/v1/auth/register",
            json={"nickname": "账号甲", "password": "secret123"},
        )
        self.assertEqual(duplicate.status_code, 409)

    def test_websocket_requires_auth(self) -> None:
        ws = self.client.websocket_connect("/api/v1/ws")
        ws.__enter__()
        self.addCleanup(ws.__exit__, None, None, None)
        ws.send_json(make_message(CLIENT_CREATE_ROOM))
        message = receive(ws)
        self.assertEqual(message["type"], SERVER_ERROR)
        self.assertIn("登录", message["payload"]["message"])

        ws.send_json(
            make_message(CLIENT_AUTH, {"token": "invalid-token"})
        )
        message = receive(ws)
        self.assertEqual(message["type"], SERVER_ERROR)
        self.assertIn("登录", message["payload"]["message"])

    # ------------------------------------------------------------------
    # 房间与对局
    # ------------------------------------------------------------------
    def test_create_and_join_room(self) -> None:
        (
            host,
            guest,
            host_state,
            guest_state,
            code,
            _host_info,
            _guest_info,
        ) = self._open_pair()
        del host, guest
        self.assertEqual(host_state["status"], "playing")
        self.assertEqual(host_state["your_side"], "red")
        self.assertEqual(guest_state["your_side"], "black")
        self.assertEqual(host_state["players"]["red"]["name"], "红方棋友")
        self.assertEqual(host_state["players"]["black"]["name"], "黑方棋友")
        self.assertEqual(host_state["move_count"], 0)
        self.assertEqual(len(host_state["board"]), 10)
        self.assertEqual(len(host_state["board"][0]), 9)
        self.assertEqual(len(code), 4)

    def test_reject_join_unknown_room(self) -> None:
        ws, _info = self._socket("棋友")
        ws.send_json(
            make_message(CLIENT_JOIN_ROOM, {"room_code": "ZZZZ"})
        )
        message = receive(ws)
        self.assertEqual(message["type"], SERVER_ERROR)

    def test_server_authoritative_move(self) -> None:
        host, guest, _, _, _, _, _ = self._open_pair()
        send_move(host, 6, 0, 5, 0)
        host_state = receive_state(host)
        guest_state = receive_state(guest)
        self.assertEqual(host_state["move_count"], 1)
        self.assertEqual(host_state["side_to_move"], "black")
        self.assertEqual(guest_state["move_count"], 1)
        self.assertEqual(guest_state["last_move"]["to_row"], 5)
        self.assertEqual(len(host_state["moves"]), 1)
        self.assertEqual(host_state["moves"][0]["from_row"], 6)
        self.assertEqual(host_state["moves"][0]["to_col"], 0)

    def test_wrong_turn_and_illegal_move_rejected(self) -> None:
        host, guest, _, _, _, _, _ = self._open_pair()
        send_move(guest, 3, 0, 4, 0)
        rejected = receive(guest)
        self.assertEqual(rejected["type"], SERVER_MOVE_REJECTED)
        self.assertIn("轮到你", rejected["payload"]["reason"])

        send_move(host, 9, 0, 9, 1)
        rejected = receive(host)
        self.assertEqual(rejected["type"], SERVER_MOVE_REJECTED)

    def test_undo_request_and_accept(self) -> None:
        host, guest, _, _, _, _, _ = self._open_pair()
        send_move(host, 6, 0, 5, 0)
        receive_state(host)
        receive_state(guest)

        guest.send_json(make_message(CLIENT_UNDO_REQUEST))
        requested = receive(host)
        self.assertEqual(requested["type"], SERVER_UNDO_REQUESTED)
        self.assertEqual(requested["payload"]["name"], "黑方棋友")
        receive_state(host)
        receive_state(guest)

        host.send_json(
            make_message(CLIENT_UNDO_RESPONSE, {"accept": True})
        )
        result = receive(host)
        self.assertEqual(result["type"], SERVER_UNDO_RESULT)
        self.assertTrue(result["payload"]["accepted"])
        guest_result = receive(guest)
        self.assertEqual(guest_result["type"], SERVER_UNDO_RESULT)
        host_state = receive_state(host)
        guest_state = receive_state(guest)
        self.assertEqual(host_state["move_count"], 0)
        self.assertEqual(host_state["side_to_move"], "red")
        self.assertEqual(guest_state["move_count"], 0)

    def test_undo_request_and_decline(self) -> None:
        host, guest, _, _, _, _, _ = self._open_pair()
        send_move(host, 6, 0, 5, 0)
        receive_state(host)
        receive_state(guest)

        guest.send_json(make_message(CLIENT_UNDO_REQUEST))
        self.assertEqual(receive(host)["type"], SERVER_UNDO_REQUESTED)
        receive_state(host)
        receive_state(guest)

        host.send_json(
            make_message(CLIENT_UNDO_RESPONSE, {"accept": False})
        )
        self.assertFalse(receive(host)["payload"]["accepted"])
        self.assertFalse(receive(guest)["payload"]["accepted"])
        host_state = receive_state(host)
        receive_state(guest)
        self.assertEqual(host_state["move_count"], 1)

    def test_resign(self) -> None:
        host, guest, _, _, _, _, _ = self._open_pair()
        host.send_json(make_message(CLIENT_RESIGN))
        host_state = receive_state(host)
        guest_state = receive_state(guest)
        self.assertEqual(host_state["status"], "finished")
        self.assertEqual(host_state["winner"], "black")
        self.assertEqual(host_state["end_reason"], "resign")
        self.assertEqual(guest_state["winner"], "black")

    def test_rematch_after_resign(self) -> None:
        host, guest, _, _, _, _, _ = self._open_pair()
        host.send_json(make_message(CLIENT_RESIGN))
        receive_state(host)
        receive_state(guest)

        host.send_json(make_message(CLIENT_REMATCH))
        requested = receive(guest)
        self.assertEqual(requested["type"], SERVER_REMATCH_REQUESTED)
        receive_state(host)
        receive_state(guest)

        guest.send_json(make_message(CLIENT_REMATCH))
        receive(host)
        host_state = receive_state(host)
        guest_state = receive_state(guest)
        self.assertEqual(host_state["status"], "playing")
        self.assertEqual(host_state["move_count"], 0)
        self.assertIsNone(host_state["winner"])
        self.assertEqual(guest_state["status"], "playing")

    def test_disconnect_marks_player_offline(self) -> None:
        host, guest, _, _, _, _, _ = self._open_pair()
        guest.__exit__(None, None, None)

        state = receive_state(host)
        self.assertFalse(state["players"]["black"]["connected"])
        self.assertTrue(state["players"]["red"]["connected"])

    def test_reconnect_with_same_account(self) -> None:
        host, guest, _, _, code, _host_info, guest_info = self._open_pair()
        guest.__exit__(None, None, None)
        receive_state(host)

        again = self.client.websocket_connect("/api/v1/ws")
        again.__enter__()
        self.addCleanup(again.__exit__, None, None, None)
        authenticate(again, guest_info["token"])
        state = join_room(again, code)
        self.assertEqual(state["your_side"], "black")
        self.assertTrue(state["players"]["black"]["connected"])
        host_state = receive_state(host)
        self.assertTrue(host_state["players"]["black"]["connected"])

    def test_room_full_rejects_third_player(self) -> None:
        _host, _guest, _, _, code, _, _ = self._open_pair()
        third, _info = self._socket("第三者")
        third.send_json(
            make_message(CLIENT_JOIN_ROOM, {"room_code": code})
        )
        message = receive(third)
        self.assertEqual(message["type"], SERVER_ERROR)

    def _friend_sockets(self):
        first_ws, first_info = self._socket("自建房甲")
        second_ws, second_info = self._socket("自建房乙")
        first_headers = {
            "Authorization": f"Bearer {first_info['token']}"
        }
        second_headers = {
            "Authorization": f"Bearer {second_info['token']}"
        }
        self.client.post(
            "/api/v1/profile/friends",
            json={"nickname": "自建房乙"},
            headers=first_headers,
        )
        self.client.post(
            "/api/v1/profile/friends/accept",
            json={"nickname": "自建房甲"},
            headers=second_headers,
        )
        return (
            first_ws,
            second_ws,
            first_headers,
            second_headers,
        )

    def test_self_built_room_invite_and_accept(self) -> None:
        host, guest, _host_headers, _guest_headers = (
            self._friend_sockets()
        )
        host_state = create_room(host)
        self.assertEqual(host_state["status"], "waiting")

        host.send_json(
            make_message(
                CLIENT_INVITE_FRIEND,
                {"nickname": "自建房乙"},
            )
        )
        invite_status = receive(host)
        self.assertEqual(
            invite_status["type"], SERVER_INVITE_RESULT
        )
        self.assertEqual(invite_status["payload"]["status"], "sent")
        challenge = receive(guest)
        self.assertEqual(challenge["type"], SERVER_CHALLENGE)
        self.assertEqual(challenge["payload"]["name"], "自建房甲")

        guest.send_json(
            make_message(
                CLIENT_CHALLENGE_RESPONSE,
                {
                    "challenge_id": challenge["payload"][
                        "challenge_id"
                    ],
                    "accept": True,
                },
            )
        )
        accepted = receive(host)
        self.assertEqual(accepted["type"], SERVER_INVITE_RESULT)
        self.assertTrue(accepted["payload"]["accepted"])
        host_state = receive_state(host)
        guest_state = receive_state(guest)
        self.assertEqual(host_state["status"], "playing")
        self.assertEqual(guest_state["status"], "playing")
        self.assertEqual(host_state["your_side"], "red")
        self.assertEqual(guest_state["your_side"], "black")
        self.assertEqual(
            host_state["players"]["black"]["name"], "自建房乙"
        )
        self.assertEqual(host_state["room_code"], guest_state["room_code"])

    def test_self_built_room_invite_declined(self) -> None:
        host, guest, _host_headers, _guest_headers = (
            self._friend_sockets()
        )
        room_state = create_room(host)
        host.send_json(
            make_message(
                CLIENT_INVITE_FRIEND,
                {"nickname": "自建房乙"},
            )
        )
        receive(host)
        challenge = receive(guest)
        self.assertEqual(challenge["type"], SERVER_CHALLENGE)
        guest.send_json(
            make_message(
                CLIENT_CHALLENGE_RESPONSE,
                {
                    "challenge_id": challenge["payload"][
                        "challenge_id"
                    ],
                    "accept": False,
                },
            )
        )
        declined = receive(host)
        self.assertEqual(declined["type"], SERVER_INVITE_RESULT)
        self.assertEqual(
            declined["payload"]["status"], "declined"
        )
        self.assertFalse(declined["payload"]["accepted"])
        room = self.app.state.room_manager.rooms[
            room_state["room_code"]
        ]
        self.assertEqual(room.status, "waiting")

    def test_self_built_room_requires_friend(self) -> None:
        host, _host_info = self._socket("自建房房主")
        create_room(host)
        # 建立一个不是好友的在线账号
        _other, _other_info = self._socket("陌生人棋友")
        host.send_json(
            make_message(
                CLIENT_INVITE_FRIEND,
                {"nickname": "陌生人棋友"},
            )
        )
        result = receive(host)
        self.assertEqual(result["type"], SERVER_INVITE_RESULT)
        self.assertEqual(result["payload"]["status"], "error")
        self.assertIn("好友", result["payload"]["reason"])

    # ------------------------------------------------------------------
    # 聊天
    # ------------------------------------------------------------------
    def test_room_chat_broadcast_and_rate_limit(self) -> None:
        host, guest, _, _, _, host_info, _ = self._open_pair()

        host.send_json(
            make_message(
                CLIENT_CHAT,
                {"kind": CHAT_KIND_TEXT, "content": "  好棋！ "},
                request_id="chat-first",
            )
        )
        host_message = receive(host)
        guest_message = receive(guest)
        self.assertEqual(host_message["type"], SERVER_CHAT)
        self.assertEqual(guest_message["type"], SERVER_CHAT)
        payload = host_message["payload"]
        self.assertEqual(payload["content"], "好棋！")
        self.assertEqual(payload["sender_name"], "红方棋友")
        self.assertEqual(
            payload["sender_id"], str(host_info["user_id"])
        )

        guest.send_json(
            make_message(
                CLIENT_CHAT,
                {
                    "kind": CHAT_KIND_EMOJI,
                    "content": EMOJI_PRESETS[0],
                },
                request_id="chat-emoji",
            )
        )
        self.assertEqual(receive(host)["type"], SERVER_CHAT)
        self.assertEqual(receive(guest)["type"], SERVER_CHAT)

        # 第一条“好棋”已经占用了 1 条额度，再发 CHAT_BURST - 1 条刚好用满。
        for index in range(CHAT_BURST - 1):
            host.send_json(
                make_message(
                    CLIENT_CHAT,
                    {
                        "kind": CHAT_KIND_TEXT,
                        "content": f"快点{index}",
                    },
                    request_id=f"burst-{index}",
                )
            )
            self.assertEqual(receive(host)["type"], SERVER_CHAT)
            self.assertEqual(receive(guest)["type"], SERVER_CHAT)

        host.send_json(
            make_message(
                CLIENT_CHAT,
                {"kind": CHAT_KIND_TEXT, "content": "再来一条"},
                request_id="burst-extra",
            )
        )
        error = receive(host)
        self.assertEqual(error["type"], SERVER_ERROR)
        self.assertEqual(error["request_id"], "burst-extra")
        self.assertIn("发言太快", error["payload"]["message"])

    def test_chat_rejected_while_waiting_for_opponent(self) -> None:
        host, _info = self._socket("等待房主")
        create_room(host)
        host.send_json(
            make_message(
                CLIENT_CHAT,
                {"kind": CHAT_KIND_TEXT, "content": "有人吗？"},
                request_id="waiting-chat",
            )
        )
        error = receive(host)
        self.assertEqual(error["type"], SERVER_ERROR)
        self.assertEqual(error["request_id"], "waiting-chat")
        self.assertIn("对手", error["payload"]["message"])

    def test_friend_direct_messages_and_unread(self) -> None:
        host, guest, host_headers, guest_headers = (
            self._friend_sockets()
        )

        friends = self.client.get(
            "/api/v1/profile/friends", headers=host_headers
        ).json()["friends"]
        self.assertEqual(len(friends), 1)
        self.assertEqual(friends[0]["nickname"], "自建房乙")
        self.assertTrue(friends[0]["online"])
        self.assertEqual(friends[0]["unread"], 0)

        sent = self.client.post(
            "/api/v1/messages",
            params={"nickname": "自建房乙"},
            json={"content": "  你好  "},
            headers=host_headers,
        )
        self.assertEqual(sent.status_code, 200, sent.text)
        sent_data = sent.json()
        self.assertEqual(sent_data["content"], "你好")
        self.assertEqual(sent_data["sender_name"], "自建房甲")
        self.assertTrue(sent_data["id"])

        push = receive(guest)
        self.assertEqual(push["type"], SERVER_DIRECT_MESSAGE)
        self.assertEqual(push["payload"]["content"], "你好")
        self.assertEqual(
            push["payload"]["sender_name"], "自建房甲"
        )

        guest_friends = self.client.get(
            "/api/v1/profile/friends", headers=guest_headers
        ).json()["friends"]
        by_name = {
            item["nickname"]: item for item in guest_friends
        }
        self.assertEqual(by_name["自建房甲"]["unread"], 1)

        history = self.client.get(
            "/api/v1/messages",
            params={"nickname": "自建房甲"},
            headers=guest_headers,
        )
        self.assertEqual(history.status_code, 200, history.text)
        messages = history.json()["messages"]
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0]["content"], "你好")
        self.assertEqual(
            messages[0]["sender_name"], "自建房甲"
        )

        guest_friends = self.client.get(
            "/api/v1/profile/friends", headers=guest_headers
        ).json()["friends"]
        by_name = {
            item["nickname"]: item for item in guest_friends
        }
        self.assertEqual(by_name["自建房甲"]["unread"], 0)

        reply = self.client.post(
            "/api/v1/messages",
            params={"nickname": "自建房甲"},
            json={"content": "你也好"},
            headers=guest_headers,
        )
        self.assertEqual(reply.status_code, 200, reply.text)
        push = receive(host)
        self.assertEqual(push["type"], SERVER_DIRECT_MESSAGE)
        self.assertEqual(push["payload"]["content"], "你也好")

        stranger = register(self.client, "陌生棋友")
        stranger_headers = {
            "Authorization": f"Bearer {stranger['token']}"
        }
        forbidden = self.client.post(
            "/api/v1/messages",
            params={"nickname": "自建房甲"},
            json={"content": "你好"},
            headers=stranger_headers,
        )
        self.assertEqual(forbidden.status_code, 403)

    def test_spectate_friend_game_is_read_only(self) -> None:
        (
            host,
            guest,
            _,
            _,
            code,
            host_info,
            _guest_info,
        ) = self._open_pair()
        spectator, spectator_info = self._socket("观战者")
        host_headers = {
            "Authorization": f"Bearer {host_info['token']}"
        }
        spectator_headers = {
            "Authorization": f"Bearer {spectator_info['token']}"
        }
        requested = self.client.post(
            "/api/v1/profile/friends",
            json={"nickname": "红方棋友"},
            headers=spectator_headers,
        )
        self.assertEqual(requested.status_code, 200, requested.text)
        accepted = self.client.post(
            "/api/v1/profile/friends/accept",
            json={"nickname": "观战者"},
            headers=host_headers,
        )
        self.assertEqual(accepted.status_code, 200, accepted.text)

        friends = self.client.get(
            "/api/v1/profile/friends", headers=spectator_headers
        ).json()["friends"]
        row = {
            item["nickname"]: item for item in friends
        }["红方棋友"]
        self.assertTrue(row["online"])
        self.assertTrue(row["in_game"])
        self.assertEqual(row["game_status"], "playing")
        self.assertTrue(code)

        spectator.send_json(
            make_message(
                CLIENT_SPECTATE, {"nickname": "红方棋友"}
            )
        )
        state = receive_state(spectator)
        self.assertTrue(state["spectator"])
        self.assertIsNone(state["your_side"])
        self.assertEqual(state["status"], "playing")
        self.assertEqual(
            state["players"]["red"]["name"], "红方棋友"
        )
        self.assertEqual(state["move_count"], 0)

        send_move(host, 6, 0, 5, 0)
        receive_state(host)
        receive_state(guest)
        spectator_state = receive_state(spectator)
        self.assertEqual(spectator_state["move_count"], 1)
        self.assertEqual(
            spectator_state["side_to_move"], "black"
        )

        send_move(spectator, 3, 0, 4, 0)
        rejected = receive(spectator)
        self.assertEqual(rejected["type"], SERVER_MOVE_REJECTED)
        self.assertIn("轮到你", rejected["payload"]["reason"])

        stranger, _stranger_info = self._socket("陌生观战者")
        stranger.send_json(
            make_message(
                CLIENT_SPECTATE, {"nickname": "红方棋友"}
            )
        )
        error = receive(stranger)
        self.assertEqual(error["type"], SERVER_ERROR)
        self.assertIn("好友", error["payload"]["message"])

    # ------------------------------------------------------------------
    # 排位匹配
    # ------------------------------------------------------------------
    def test_ranked_queue_matches_two_players(self) -> None:
        host, guest, host_state, guest_state = self._queue_pair()
        del host, guest
        self.assertTrue(host_state["ranked"])
        self.assertEqual(host_state["status"], "playing")
        self.assertEqual(host_state["your_side"], "red")
        self.assertEqual(guest_state["your_side"], "black")
        self.assertEqual(host_state["room_code"], guest_state["room_code"])
        self.assertEqual(
            host_state["players"]["red"]["rating"], 1200
        )
        self.assertEqual(
            guest_state["players"]["black"]["rating"], 1200
        )

    def test_ranked_resign_updates_elo(self) -> None:
        host, guest, host_state, guest_state = self._queue_pair()
        host.send_json(make_message(CLIENT_RESIGN))
        host_state = receive_state(host)
        guest_state = receive_state(guest)
        self.assertEqual(host_state["status"], "finished")
        self.assertEqual(host_state["winner"], "black")
        self.assertEqual(host_state["players"]["red"]["rating"], 1184)
        self.assertEqual(
            host_state["players"]["red"]["rating_delta"], -16
        )
        self.assertEqual(
            host_state["players"]["black"]["rating"], 1216
        )
        self.assertEqual(
            host_state["players"]["black"]["rating_delta"], 16
        )
        self.assertTrue(guest_state["ranked"])

        # 排位分已持久化：重新登录能看到新分数。
        login = self.client.post(
            "/api/v1/auth/login",
            json={"nickname": "排位乙", "password": "secret123"},
        )
        self.assertEqual(login.status_code, 200)
        self.assertEqual(login.json()["rating"], 1216)

    def test_ranked_rematch_keeps_rating_and_clears_delta(self) -> None:
        host, guest, _, _ = self._queue_pair()
        host.send_json(make_message(CLIENT_RESIGN))
        receive_state(host)
        receive_state(guest)

        host.send_json(make_message(CLIENT_REMATCH))
        self.assertEqual(
            receive(guest)["type"], SERVER_REMATCH_REQUESTED
        )
        receive_state(host)
        receive_state(guest)

        guest.send_json(make_message(CLIENT_REMATCH))
        self.assertEqual(
            receive(host)["type"], SERVER_REMATCH_REQUESTED
        )
        host_state = receive_state(host)
        receive_state(guest)
        self.assertEqual(host_state["status"], "playing")
        self.assertIsNone(
            host_state["players"]["red"]["rating_delta"]
        )
        self.assertEqual(host_state["players"]["red"]["rating"], 1184)
        self.assertEqual(
            host_state["players"]["black"]["rating"], 1216
        )

    def test_queue_cleanup_when_player_leaves(self) -> None:
        first, _info = self._socket("取消匹配甲")
        self.assertEqual(
            join_queue(first)["type"], SERVER_QUEUE_STATUS
        )
        self.assertEqual(
            len(self.app.state.room_manager.queue), 1
        )
        first.__exit__(None, None, None)
        self.assertEqual(
            len(self.app.state.room_manager.queue), 0
        )

        second, _info = self._socket("取消匹配乙")
        message = join_queue(second)
        self.assertEqual(message["type"], SERVER_QUEUE_STATUS)
        self.assertIn("正在匹配", message["payload"]["message"])

    def test_queue_rejects_same_account_twice(self) -> None:
        info = register(self.client, "重复账号")
        first = self.client.websocket_connect("/api/v1/ws")
        first.__enter__()
        self.addCleanup(first.__exit__, None, None, None)
        authenticate(first, info["token"])
        self.assertEqual(
            join_queue(first)["type"], SERVER_QUEUE_STATUS
        )

        second = self.client.websocket_connect("/api/v1/ws")
        second.__enter__()
        self.addCleanup(second.__exit__, None, None, None)
        authenticate(second, info["token"])
        second.send_json(make_message(CLIENT_JOIN_QUEUE))
        message = receive(second)
        self.assertEqual(message["type"], SERVER_ERROR)
        self.assertIn("匹配", message["payload"]["message"])

    # ------------------------------------------------------------------
    # 个人资料
    # ------------------------------------------------------------------
    def test_profile_avatar_friends_and_stats(self) -> None:
        host, host_info = self._socket("资料棋友甲")
        guest, guest_info = self._socket("资料棋友乙")
        host_state = create_room(host)
        code = host_state["room_code"]
        join_room(guest, code)
        receive_state(host)

        guest.send_json(make_message(CLIENT_RESIGN))
        receive_state(host)
        receive_state(guest)

        host_headers = {
            "Authorization": f"Bearer {host_info['token']}"
        }
        guest_headers = {
            "Authorization": f"Bearer {guest_info['token']}"
        }

        profile = self.client.get(
            "/api/v1/profile", headers=host_headers
        ).json()
        self.assertEqual(profile["nickname"], "资料棋友甲")
        self.assertEqual(profile["rating"], 1200)
        self.assertEqual(profile["title"], "棋士")
        self.assertEqual(profile["wins"], 1)
        self.assertEqual(profile["losses"], 0)
        self.assertEqual(profile["record_text"], "1胜 0和 0负")
        self.assertEqual(profile["win_rate"], 100.0)
        self.assertEqual(profile["best_streak"], 1)
        earned = {
            item["key"]
            for item in profile["achievements"]
            if item["earned"]
        }
        self.assertIn("first_game", earned)
        self.assertIn("first_win", earned)
        self.assertEqual(profile["avatar"], "default:1")
        self.assertNotIn("friends", profile)

        chosen = self.client.post(
            "/api/v1/profile/avatar",
            json={"avatar": "default:5"},
            headers=host_headers,
        )
        self.assertEqual(chosen.status_code, 200)
        self.assertEqual(chosen.json()["avatar"], "default:5")
        relogin = self.client.post(
            "/api/v1/auth/login",
            json={"nickname": "资料棋友甲", "password": "secret123"},
        )
        self.assertEqual(relogin.status_code, 200)
        self.assertEqual(relogin.json()["avatar"], "default:5")

        png = b"\x89PNG\r\n\x1a\n" + b"0" * 64
        uploaded = self.client.post(
            "/api/v1/profile/avatar/upload",
            content=png,
            headers={
                **host_headers,
                "Content-Type": "image/png",
            },
        )
        self.assertEqual(uploaded.status_code, 200)
        self.assertEqual(uploaded.json()["avatar"], "custom")
        image = self.client.get(
            "/api/v1/profile/avatar",
            params={"nickname": "资料棋友甲"},
        )
        self.assertEqual(image.status_code, 200)
        self.assertEqual(image.content, png)

        player = self.client.get(
            "/api/v1/players/detail",
            params={"nickname": "资料棋友乙"},
            headers=host_headers,
        ).json()
        self.assertEqual(player["nickname"], "资料棋友乙")
        self.assertFalse(player["is_self"])
        self.assertEqual(player["relationship"], "none")

        requested = self.client.post(
            "/api/v1/profile/friends",
            json={"nickname": "资料棋友乙"},
            headers=host_headers,
        )
        self.assertEqual(requested.status_code, 200)
        self.assertEqual(
            requested.json()["friend"]["nickname"], "资料棋友乙"
        )
        self.assertEqual(
            requested.json()["relationship"], "pending_out"
        )
        self.assertEqual(
            self.client.get(
                "/api/v1/players/资料棋友乙", headers=host_headers
            ).json()["relationship"],
            "pending_out",
        )

        host_friends = self.client.get(
            "/api/v1/profile/friends", headers=host_headers
        ).json()
        self.assertEqual(host_friends["friends"], [])
        self.assertEqual(len(host_friends["outgoing"]), 1)
        self.assertEqual(host_friends["incoming"], [])

        guest_friends = self.client.get(
            "/api/v1/profile/friends", headers=guest_headers
        ).json()
        self.assertEqual(len(guest_friends["incoming"]), 1)
        self.assertEqual(
            guest_friends["incoming"][0]["nickname"], "资料棋友甲"
        )

        duplicate = self.client.post(
            "/api/v1/profile/friends",
            json={"nickname": "资料棋友乙"},
            headers=host_headers,
        )
        self.assertEqual(duplicate.status_code, 409)

        accepted = self.client.post(
            "/api/v1/profile/friends/accept",
            json={"nickname": "资料棋友甲"},
            headers=guest_headers,
        )
        self.assertEqual(accepted.status_code, 200)
        self.assertEqual(accepted.json()["relationship"], "friend")

        host_friends = self.client.get(
            "/api/v1/profile/friends", headers=host_headers
        ).json()
        self.assertEqual(len(host_friends["friends"]), 1)
        self.assertEqual(
            host_friends["friends"][0]["nickname"], "资料棋友乙"
        )
        self.assertEqual(host_friends["outgoing"], [])
        self.assertEqual(
            self.client.get(
                "/api/v1/players/资料棋友乙", headers=host_headers
            ).json()["relationship"],
            "friend",
        )

        leaderboard = self.client.get(
            "/api/v1/players", headers=host_headers
        ).json()
        self.assertGreaterEqual(leaderboard["count"], 2)
        rows = {row["nickname"]: row for row in leaderboard["players"]}
        self.assertIn("资料棋友甲", rows)
        self.assertTrue(rows["资料棋友甲"]["is_self"])
        self.assertEqual(rows["资料棋友甲"]["rating"], 1200)
        self.assertEqual(rows["资料棋友甲"]["title"], "棋士")
        self.assertIn(rows["资料棋友甲"]["rank"], (1, 2))

        register(self.client, "空测试账号")
        search = self.client.get(
            "/api/v1/players/search",
            params={"q": "空测试"},
            headers=host_headers,
        )
        self.assertEqual(search.status_code, 200)
        found = search.json()["players"]
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["nickname"], "空测试账号")
        self.assertEqual(found[0]["relationship"], "none")

        board = self.client.get(
            "/api/v1/players", headers=host_headers
        ).json()["players"]
        board_rows = {row["nickname"]: row for row in board}
        self.assertIn("空测试账号", board_rows)
        self.assertEqual(board_rows["空测试账号"]["games"], 0)
        self.assertEqual(board_rows["空测试账号"]["rating"], 1200)
        self.assertFalse(board_rows["空测试账号"]["is_self"])

        own_player = self.client.get(
            "/api/v1/players/资料棋友甲", headers=host_headers
        ).json()
        self.assertTrue(own_player["is_self"])
        self.assertEqual(own_player["relationship"], "self")

        guest_profile = self.client.get(
            "/api/v1/profile", headers=guest_headers
        ).json()
        self.assertEqual(guest_profile["losses"], 1)
        self.assertEqual(guest_profile["wins"], 0)
        self.assertEqual(guest_profile["win_rate"], 0.0)

        anonymous = self.client.get("/api/v1/profile")
        self.assertEqual(anonymous.status_code, 401)
        self.assertEqual(
            self.client.get(
                "/api/v1/players/资料棋友甲"
            ).status_code,
            401,
        )

    def test_friend_request_decline_and_self(self) -> None:
        first = register(self.client, "好友甲")
        second = register(self.client, "好友乙")
        first_headers = {
            "Authorization": f"Bearer {first['token']}"
        }
        second_headers = {
            "Authorization": f"Bearer {second['token']}"
        }
        sent = self.client.post(
            "/api/v1/profile/friends",
            json={"nickname": "好友甲"},
            headers=second_headers,
        )
        self.assertEqual(sent.status_code, 200)
        self.assertEqual(sent.json()["relationship"], "pending_out")

        incoming = self.client.get(
            "/api/v1/profile/friends", headers=first_headers
        ).json()["incoming"]
        self.assertEqual(len(incoming), 1)

        declined = self.client.post(
            "/api/v1/profile/friends/decline",
            json={"nickname": "好友乙"},
            headers=first_headers,
        )
        self.assertEqual(declined.status_code, 200)
        after = self.client.get(
            "/api/v1/profile/friends", headers=first_headers
        ).json()
        self.assertEqual(after["incoming"], [])
        self.assertEqual(after["friends"], [])

        self_request = self.client.post(
            "/api/v1/profile/friends",
            json={"nickname": "好友甲"},
            headers=first_headers,
        )
        self.assertEqual(self_request.status_code, 400)


class SpectatorEndTests(unittest.IsolatedAsyncioTestCase):
    """房间关闭时结束观战的通知与状态清理。"""

    async def test_end_spectators_notifies_and_clears(self) -> None:
        class FakeWebSocket:
            def __init__(self) -> None:
                self.sent: list[dict] = []

            async def send_json(self, message: dict) -> None:
                self.sent.append(message)

        manager = RoomManager(None)  # type: ignore[arg-type]
        room = Room(code="ABCD")
        websocket = FakeWebSocket()
        conn = Connection(
            websocket=websocket,  # type: ignore[arg-type]
            user_id=3,
            name="观战者",
            room_code="ABCD",
            spectating=True,
        )
        room.spectators[3] = conn

        await manager._end_spectators(room, "对局已结束")

        self.assertEqual(room.spectators, {})
        self.assertFalse(conn.spectating)
        self.assertIsNone(conn.room_code)
        self.assertEqual(len(websocket.sent), 1)
        message = websocket.sent[0]
        self.assertEqual(message["type"], SERVER_SPECTATE_ENDED)
        self.assertEqual(
            message["payload"]["reason"], "对局已结束"
        )


if __name__ == "__main__":
    unittest.main()
