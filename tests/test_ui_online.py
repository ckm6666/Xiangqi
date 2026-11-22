"""联机大厅页测试：登录/注册、房间与排位入口。"""

from __future__ import annotations

import unittest

from tests.qt_helpers import ensure_qt_app

APP = ensure_qt_app()

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QLineEdit  # noqa: E402

from tests.fakes import FakeAuthApi, FakeTransport  # noqa: E402
from xiangqi.client.config import AppConfig  # noqa: E402
from xiangqi.client.online_panel import DEFAULT_WS_URL, OnlinePanel  # noqa: E402
from xiangqi.shared.game_model import GameModel  # noqa: E402
from xiangqi.shared.protocol import (  # noqa: E402
    SERVER_AUTH_OK,
    SERVER_CHALLENGE,
    SERVER_ERROR,
    SERVER_GAME_STATE,
    SERVER_QUEUE_STATUS,
    make_message,
    serialize_board,
)


def state_payload(**overrides) -> dict:
    payload = {
        "room_code": "ABCD",
        "status": "playing",
        "ranked": False,
        "your_side": "red",
        "players": {
            "red": {"name": "甲", "connected": True},
            "black": {"name": "乙", "connected": True},
        },
        "board": serialize_board(GameModel.initial().board),
        "side_to_move": "red",
        "last_move": None,
        "is_check": False,
        "winner": None,
        "end_reason": None,
        "move_count": 0,
        "undo_requester": None,
        "rematch_requests": [],
        "state_version": 1,
    }
    payload.update(overrides)
    return payload


AUTH_OK = {
    "user_id": 1,
    "nickname": "甲",
    "rating": 1200,
}


class OnlinePanelTests(unittest.TestCase):
    """账号表单、认证与游戏入口。"""

    def setUp(self) -> None:
        self.transports: list[FakeTransport] = []
        self.auth = FakeAuthApi()

        def transport_factory(parent):
            transport = FakeTransport(parent)
            self.transports.append(transport)
            return transport

        self.panel = OnlinePanel(
            AppConfig(),
            transport_factory=transport_factory,
            auth_factory=lambda parent: self.auth,
        )
        self.addCleanup(self.panel.deleteLater)

    def _authenticate_ws(self, transport: FakeTransport) -> None:
        transport.simulate_connected()
        self.assertEqual(transport.sent[-1]["type"], "auth")
        transport.server_send(
            make_message(SERVER_AUTH_OK, AUTH_OK)
        )

    def test_defaults(self) -> None:
        self.assertEqual(self.panel.url_input.text(), DEFAULT_WS_URL)
        self.assertEqual(self.panel.name_input.text(), "")
        self.assertEqual(
            self.panel.password_input.echoMode(),
            QLineEdit.EchoMode.Password,
        )
        self.assertEqual(self.panel.login_button.text(), "登录")
        self.assertEqual(self.panel.register_button.text(), "注册")
        self.assertFalse(self.panel.login_form.isHidden())
        self.assertTrue(self.panel.lobby_form.isHidden())
        self.assertEqual(
            self.panel.ranked_button.text(), "排位匹配"
        )
        self.assertEqual(
            self.panel.ranked_button.objectName(), "menuPrimaryButton"
        )
        self.assertTrue(self.panel.cancel_queue_button.isHidden())
        self.assertEqual(self.panel.profile_button.text(), "个人信息")
        self.assertEqual(self.panel.friends_button.text(), "好友")
        self.assertEqual(
            self.panel.leaderboard_button.text(), "排行榜"
        )
        self.assertEqual(self.panel.create_button.text(), "自建房")
        self.assertFalse(hasattr(self.panel, "join_button"))
        self.assertFalse(hasattr(self.panel, "room_input"))

    def test_login_flow_and_logout(self) -> None:
        self.panel.name_input.setText("账号甲")
        self.panel.password_input.setText("secret123")
        self.panel.login_button.click()

        self.assertEqual(self.auth.calls[-1][0], "login")
        self.assertEqual(
            self.auth.calls[-1][1],
            OnlinePanel._http_base(DEFAULT_WS_URL),
        )
        self.assertEqual(self.auth.calls[-1][2], "账号甲")
        self.assertFalse(self.panel.login_button.isEnabled())

        self.auth.succeed("token-1", "账号甲", 1234)
        self.assertTrue(self.panel.login_form.isHidden())
        self.assertFalse(self.panel.lobby_form.isHidden())
        self.assertIn("账号甲", self.panel.account_label.text())
        self.assertIn("1234分", self.panel.account_label.text())

        self.panel.logout_button.click()
        self.assertFalse(self.panel.login_form.isHidden())
        self.assertTrue(self.panel.lobby_form.isHidden())

    def test_enter_logs_in(self) -> None:
        self.panel.name_input.setText("账号甲")
        self.panel.password_input.setText("secret123")
        QTest.keyClick(
            self.panel.password_input, Qt.Key.Key_Return
        )
        self.assertEqual(self.auth.calls[-1][0], "login")
        self.assertEqual(
            self.auth.calls[-1][2:], ("账号甲", "secret123")
        )
        self.assertFalse(self.panel.login_button.isEnabled())

    def test_register_flow(self) -> None:
        self.panel.name_input.setText("新棋友")
        self.panel.password_input.setText("secret123")
        self.panel.register_button.click()
        self.assertEqual(self.auth.calls[-1][0], "register")
        self.auth.succeed("token-2", "新棋友", 1200)
        self.assertFalse(self.panel.lobby_form.isHidden())

    def test_login_failure_and_invalid_input(self) -> None:
        self.panel.url_input.setText("http://localhost")
        self.panel.login_button.click()
        self.assertIn("ws://", self.panel.status_label.text())
        self.assertEqual(self.auth.calls, [])

        self.panel.url_input.setText(DEFAULT_WS_URL)
        self.panel.name_input.setText("账号甲")
        self.panel.password_input.setText("secret123")
        self.panel.login_button.click()
        self.auth.fail("密码错误")
        self.assertIn("密码错误", self.panel.status_label.text())
        self.assertTrue(self.panel.login_button.isEnabled())

    def test_create_flow_hands_off_session(self) -> None:
        ready: list[object] = []
        self.panel.session_ready.connect(ready.append)
        self.panel.apply_auth("token", "甲", 1200)
        self.panel.create_button.click()

        self.assertEqual(len(self.transports), 2)
        transport = self.transports[-1]
        self.assertEqual(transport.opened, [DEFAULT_WS_URL])
        self._authenticate_ws(transport)
        self.assertEqual(transport.sent[-1]["type"], "create_room")
        transport.server_send(
            make_message(SERVER_GAME_STATE, state_payload())
        )
        self.assertEqual(len(ready), 1)
        self.assertIsNone(self.panel._session)
        self.assertTrue(self.panel.create_button.isEnabled())

    def test_lobby_challenge_can_be_accepted(self) -> None:
        ready: list[object] = []
        challenges: list[tuple[str, str]] = []
        self.panel.session_ready.connect(ready.append)
        self.panel.challenge_received.connect(
            lambda challenge_id, name: challenges.append(
                (challenge_id, name)
            )
        )
        self.panel.apply_auth("token", "甲", 1200)
        lobby = self.transports[0]
        self._authenticate_ws(lobby)
        lobby.server_send(
            make_message(
                SERVER_CHALLENGE,
                {"challenge_id": "c1", "name": "好友乙"},
            )
        )
        self.assertEqual(challenges, [("c1", "好友乙")])
        self.assertTrue(self.panel.respond_challenge("c1", True))
        self.assertEqual(
            lobby.sent[-1]["type"], "challenge_response"
        )
        self.assertTrue(lobby.sent[-1]["payload"]["accept"])

        lobby.server_send(
            make_message(
                SERVER_GAME_STATE,
                state_payload(
                    your_side="black",
                    players={
                        "red": {"name": "好友乙", "connected": True},
                        "black": {"name": "甲", "connected": True},
                    },
                ),
            )
        )
        self.assertEqual(len(ready), 1)
        self.assertIsNone(self.panel._lobby_session)

    def test_connection_error_resets_panel(self) -> None:
        self.panel.apply_auth("token", "甲", 1200)
        self.panel.create_button.click()
        transport = self.transports[-1]
        self._authenticate_ws(transport)
        transport.server_send(
            make_message(SERVER_ERROR, {"message": "房间不存在"})
        )
        self.assertIn("房间不存在", self.panel.status_label.text())
        self.assertIsNone(self.panel._session)
        self.assertTrue(self.panel.create_button.isEnabled())
        self.assertTrue(transport.closed)

    def test_ranked_queue_flow(self) -> None:
        ready: list[object] = []
        self.panel.session_ready.connect(ready.append)
        self.panel.apply_auth("token", "甲", 1200)
        self.panel.ranked_button.click()

        transport = self.transports[-1]
        self._authenticate_ws(transport)
        self.assertEqual(transport.sent[-1]["type"], "join_queue")
        transport.server_send(
            make_message(
                SERVER_QUEUE_STATUS,
                {"message": "正在匹配…（第 1 位）"},
            )
        )
        self.assertIn("正在匹配", self.panel.status_label.text())

        transport.server_send(
            make_message(
                SERVER_GAME_STATE,
                state_payload(ranked=True),
            )
        )
        self.assertEqual(len(ready), 1)
        self.assertIsNone(self.panel._session)

    def test_ranked_queue_can_be_cancelled(self) -> None:
        self.panel.apply_auth("token", "甲", 1200)
        self.panel.ranked_button.click()
        transport = self.transports[-1]
        self._authenticate_ws(transport)
        transport.server_send(
            make_message(
                SERVER_QUEUE_STATUS,
                {"message": "正在匹配…（第 1 位）"},
            )
        )
        self.assertFalse(self.panel.cancel_queue_button.isHidden())
        self.assertEqual(self.panel.ranked_button.text(), "匹配中…")
        self.assertFalse(self.panel.ranked_button.isEnabled())

        self.panel.cancel_queue_button.click()
        self.assertEqual(transport.sent[-1]["type"], "leave")
        self.assertTrue(transport.closed)
        self.assertIsNone(self.panel._session)
        self.assertTrue(self.panel.cancel_queue_button.isHidden())
        self.assertTrue(self.panel.ranked_button.isEnabled())
        self.assertIn("已取消", self.panel.status_label.text())

    def test_profile_button_emits_signal(self) -> None:
        events: list[bool] = []
        friend_events: list[bool] = []
        board_events: list[bool] = []
        self.panel.profile_requested.connect(
            lambda: events.append(True)
        )
        self.panel.friends_requested.connect(
            lambda: friend_events.append(True)
        )
        self.panel.leaderboard_requested.connect(
            lambda: board_events.append(True)
        )
        self.panel.apply_auth("token", "甲", 1200)
        self.panel.profile_button.click()
        self.panel.avatar_button.click()
        self.assertEqual(events, [True, True])
        self.panel.friends_button.click()
        self.panel.leaderboard_button.click()
        self.assertEqual(friend_events, [True])
        self.assertEqual(board_events, [True])

    def test_back_emits_signal(self) -> None:
        events: list[bool] = []
        self.panel.back_requested.connect(lambda: events.append(True))
        self.panel.back_button.click()
        self.assertEqual(events, [True])


if __name__ == "__main__":
    unittest.main()
