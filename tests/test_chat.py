"""共享聊天校验、联机会话聊天与私聊消息模型测试。"""

from __future__ import annotations

import time
import unittest

from tests.qt_helpers import ensure_qt_app

ensure_qt_app()

from tests.fakes import FakeTransport  # noqa: E402
from xiangqi.client.sessions.online import (  # noqa: E402
    ACTION_CREATE,
    STATUS_WAITING,
    OnlineGameSession,
)
from xiangqi.shared.chat import (  # noqa: E402
    CHAT_BURST,
    CHAT_INTERVAL_SECONDS,
    CHAT_KIND_EMOJI,
    CHAT_KIND_TEXT,
    CHAT_KINDS,
    COMMENT_PRESETS,
    EMOJI_PRESETS,
    MAX_COMMENT_LENGTH,
    MAX_EMOJI_LENGTH,
    MAX_SENDER_NAME_LENGTH,
    ChatMessage,
    build_chat_payload,
    is_emoji_preset,
    normalize_chat_content,
    parse_chat_message,
)
from xiangqi.shared.errors import ProtocolError  # noqa: E402
from xiangqi.shared.game_model import GameModel  # noqa: E402
from xiangqi.shared.protocol import (  # noqa: E402
    CLIENT_CHAT,
    SERVER_AUTH_OK,
    SERVER_CHAT,
    SERVER_DIRECT_MESSAGE,
    SERVER_ERROR,
    SERVER_GAME_STATE,
    make_message,
    serialize_board,
)
from xiangqi.shared.social import (  # noqa: E402
    MAX_DIRECT_MESSAGE_LENGTH,
    DirectMessage,
    SocialError,
    normalize_direct_message,
    parse_direct_message,
)


def state_payload(
    *,
    status: str = "playing",
    your_side: str = "red",
    side_to_move: str = "red",
) -> dict:
    return {
        "room_code": "ABCD",
        "status": status,
        "ranked": False,
        "your_side": your_side,
        "players": {
            "red": {
                "name": "甲",
                "connected": True,
                "rating": 1200,
                "rating_delta": None,
            },
            "black": {
                "name": "乙",
                "connected": True,
                "rating": 1200,
                "rating_delta": None,
            },
        },
        "board": serialize_board(GameModel.initial().board),
        "side_to_move": side_to_move,
        "last_move": None,
        "is_check": False,
        "winner": None,
        "end_reason": None,
        "move_count": 0,
        "undo_requester": None,
        "rematch_requests": [],
        "state_version": 1,
    }


def make_session(
    *,
    status: str = "playing",
    your_side: str = "red",
) -> tuple[FakeTransport, OnlineGameSession]:
    transport = FakeTransport()
    session = OnlineGameSession(
        transport, token="token", action=ACTION_CREATE
    )
    session.connect_to("ws://localhost:8000/api/v1/ws")
    transport.simulate_connected()
    transport.server_send(
        make_message(
            SERVER_AUTH_OK,
            {
                "user_id": 7,
                "nickname": "甲",
                "rating": 1200,
            },
        )
    )
    transport.server_send(
        make_message(
            SERVER_GAME_STATE,
            state_payload(status=status, your_side=your_side),
        )
    )
    return transport, session


class ChatContentValidationTests(unittest.TestCase):
    """normalize_chat_content / parse_chat_message 规则。"""

    def test_unknown_kind_is_rejected(self) -> None:
        with self.assertRaises(ProtocolError):
            normalize_chat_content("sticker", "😀")

    def test_non_string_content_is_rejected(self) -> None:
        with self.assertRaises(ProtocolError):
            normalize_chat_content(CHAT_KIND_TEXT, 123)
        with self.assertRaises(ProtocolError):
            normalize_chat_content(CHAT_KIND_EMOJI, None)

    def test_non_preset_emoji_is_rejected(self) -> None:
        with self.assertRaises(ProtocolError):
            normalize_chat_content(CHAT_KIND_EMOJI, "😀")

    def test_empty_comment_is_rejected(self) -> None:
        with self.assertRaises(ProtocolError):
            normalize_chat_content(CHAT_KIND_TEXT, "")
        with self.assertRaises(ProtocolError):
            normalize_chat_content(CHAT_KIND_TEXT, "   \n\t ")

    def test_overlong_comment_is_rejected(self) -> None:
        with self.assertRaises(ProtocolError):
            normalize_chat_content(
                CHAT_KIND_TEXT, "评" * (MAX_COMMENT_LENGTH + 1)
            )

    def test_valid_emoji_and_comment_are_accepted(self) -> None:
        for emoji in EMOJI_PRESETS:
            self.assertEqual(
                normalize_chat_content(CHAT_KIND_EMOJI, emoji),
                emoji,
            )
        self.assertEqual(
            normalize_chat_content(CHAT_KIND_TEXT, "  好棋！  "),
            "好棋！",
        )

    def test_payload_builder_and_presets(self) -> None:
        self.assertEqual(
            build_chat_payload(CHAT_KIND_TEXT, " 你好 "),
            {"kind": "text", "content": "你好"},
        )
        self.assertTrue(is_emoji_preset(EMOJI_PRESETS[0]))
        self.assertFalse(is_emoji_preset("😀"))

    def test_module_constants(self) -> None:
        self.assertEqual(
            CHAT_KINDS, (CHAT_KIND_EMOJI, CHAT_KIND_TEXT)
        )
        self.assertEqual(len(COMMENT_PRESETS), 8)
        self.assertEqual(len(EMOJI_PRESETS), 12)
        self.assertEqual(MAX_EMOJI_LENGTH, 8)
        self.assertEqual(CHAT_BURST, 3)
        self.assertAlmostEqual(CHAT_INTERVAL_SECONDS, 0.8)

    def test_parse_chat_message(self) -> None:
        message = parse_chat_message(
            {
                "kind": "text",
                "content": "好棋！",
                "sender_id": "u1",
                "sender_name": "甲",
                "sent_at_ms": 1234,
            }
        )
        self.assertIsInstance(message, ChatMessage)
        self.assertEqual(message.content, "好棋！")
        self.assertEqual(message.sender_name, "甲")
        self.assertEqual(message.sent_at_ms, 1234)

    def test_invalid_chat_frames_are_rejected(self) -> None:
        for payload in (
            {"kind": "text", "content": "好棋！"},
            {"kind": "sticker", "content": "好棋！", "sender_id": "u1"},
            {"kind": "text", "content": "", "sender_id": "u1"},
        ):
            with self.subTest(payload=payload):
                with self.assertRaises(ProtocolError):
                    parse_chat_message(payload)
        message = parse_chat_message(
            {
                "kind": "text",
                "content": "好棋",
                "sender_id": "u1",
                "sender_name": "  " + "名" * 80 + "  ",
                "sent_at_ms": True,
            }
        )
        self.assertEqual(
            len(message.sender_name), MAX_SENDER_NAME_LENGTH
        )
        self.assertEqual(message.sent_at_ms, 0)

    def test_text_is_sanitized(self) -> None:
        result = normalize_chat_content(
            CHAT_KIND_TEXT, "好棋\n\r\t！​‮"
        )
        self.assertEqual(result, "好棋 ！")


class DirectMessageModelTests(unittest.TestCase):
    """私聊正文与消息解析。"""

    def test_normalize_direct_message(self) -> None:
        self.assertEqual(
            normalize_direct_message("  你好  "), "你好"
        )
        with self.assertRaises(SocialError):
            normalize_direct_message("   ")
        with self.assertRaises(SocialError):
            normalize_direct_message(
                "字" * (MAX_DIRECT_MESSAGE_LENGTH + 1)
            )

    def test_parse_direct_message(self) -> None:
        message = parse_direct_message(
            {
                "id": "12",
                "sender_id": "7",
                "sender_name": "甲",
                "recipient_id": "8",
                "content": "你好",
                "sent_at_ms": 99,
            }
        )
        self.assertIsInstance(message, DirectMessage)
        self.assertEqual(message.id, "12")
        self.assertEqual(message.sender_name, "甲")
        self.assertEqual(message.sent_at_ms, 99)

    def test_invalid_direct_message_is_rejected(self) -> None:
        with self.assertRaises(SocialError):
            parse_direct_message(
                {"id": "1", "sender_id": "7", "content": "你好"}
            )


class OnlineSessionChatTests(unittest.TestCase):
    """联机会话的发言、冷却、接收与错误归属。"""

    def test_send_text_and_emoji(self) -> None:
        transport, session = make_session()
        self.addCleanup(session.shutdown)

        self.assertTrue(session.send_comment("  好棋！ "))
        sent = transport.sent[-1]
        self.assertEqual(sent["type"], CLIENT_CHAT)
        self.assertEqual(
            sent["payload"], {"kind": "text", "content": "好棋！"}
        )
        self.assertTrue(sent.get("request_id"))

        session._last_chat_at = (
            time.monotonic() - CHAT_INTERVAL_SECONDS - 0.1
        )
        self.assertTrue(session.send_emoji(EMOJI_PRESETS[0]))
        self.assertEqual(
            transport.sent[-1]["payload"],
            {"kind": "emoji", "content": EMOJI_PRESETS[0]},
        )

    def test_invalid_content_uses_chat_failed_only(self) -> None:
        transport, session = make_session()
        failures: list[str] = []
        errors: list[str] = []
        session.chat_failed.connect(failures.append)
        session.error.connect(errors.append)
        self.addCleanup(session.shutdown)

        self.assertFalse(session.send_comment("   "))
        self.assertFalse(session.send_emoji("😀"))
        self.assertTrue(failures)
        self.assertEqual(errors, [])
        self.assertEqual(
            [
                message
                for message in transport.sent
                if message["type"] == CLIENT_CHAT
            ],
            [],
        )

    def test_cooldown_blocks_second_send(self) -> None:
        transport, session = make_session()
        self.addCleanup(session.shutdown)
        self.assertTrue(session.send_comment("第一条"))
        self.assertFalse(session.send_comment("第二条"))
        self.assertEqual(
            len(
                [
                    message
                    for message in transport.sent
                    if message["type"] == CLIENT_CHAT
                ]
            ),
            1,
        )

    def test_chat_not_available_while_waiting(self) -> None:
        transport, session = make_session(status=STATUS_WAITING)
        self.addCleanup(session.shutdown)
        self.assertFalse(session.chat_available)
        self.assertFalse(session.send_comment("有人吗"))
        self.assertEqual(
            [
                message
                for message in transport.sent
                if message["type"] == CLIENT_CHAT
            ],
            [],
        )

    def test_chat_received(self) -> None:
        transport, session = make_session()
        received: list[ChatMessage] = []
        session.chat_received.connect(received.append)
        self.addCleanup(session.shutdown)

        transport.server_send(
            make_message(
                SERVER_CHAT,
                {
                    "kind": "emoji",
                    "content": EMOJI_PRESETS[1],
                    "sender_id": "8",
                    "sender_name": "乙",
                    "sent_at_ms": 42,
                },
            )
        )
        self.assertEqual(len(received), 1)
        self.assertEqual(received[0].sender_name, "乙")
        self.assertEqual(received[0].sent_at_ms, 42)

        # 非法帧安静丢弃。
        transport.server_send(
            make_message(
                SERVER_CHAT,
                {"kind": "text", "content": "好棋"},
            )
        )
        self.assertEqual(len(received), 1)

    def test_server_rejection_routes_to_chat_failed(self) -> None:
        transport, session = make_session()
        failures: list[str] = []
        errors: list[str] = []
        session.chat_failed.connect(failures.append)
        session.error.connect(errors.append)
        self.addCleanup(session.shutdown)

        session.send_comment("好棋")
        request_id = transport.sent[-1]["request_id"]
        transport.server_send(
            make_message(
                SERVER_ERROR,
                {"message": "发言太快，请稍候"},
                request_id=request_id,
            )
        )
        self.assertEqual(failures, ["发言太快，请稍候"])
        self.assertEqual(errors, [])

    def test_direct_message_push(self) -> None:
        transport, session = make_session()
        received: list[DirectMessage] = []
        session.direct_message.connect(received.append)
        self.addCleanup(session.shutdown)

        transport.server_send(
            make_message(
                SERVER_DIRECT_MESSAGE,
                {
                    "id": "5",
                    "sender_id": "8",
                    "sender_name": "乙",
                    "recipient_id": "7",
                    "content": "你好",
                    "sent_at_ms": 100,
                },
            )
        )
        self.assertEqual(len(received), 1)
        self.assertEqual(received[0].content, "你好")


if __name__ == "__main__":
    unittest.main()
