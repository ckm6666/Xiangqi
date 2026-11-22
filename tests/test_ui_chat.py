"""好友私聊窗口测试（offscreen）。"""

from __future__ import annotations

import unittest

from tests.qt_helpers import ensure_qt_app

APP = ensure_qt_app()

from PySide6.QtCore import QObject, Qt, Signal  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402

from xiangqi.client.danmaku import DanmakuOverlay  # noqa: E402
from xiangqi.client.private_chat_overlay import (  # noqa: E402
    PrivateChatOverlay,
)


class DanmakuOverlayTests(unittest.TestCase):
    def test_transparent_and_lifecycle(self) -> None:
        overlay = DanmakuOverlay()
        overlay.resize(320, 240)
        self.addCleanup(overlay.deleteLater)
        self.assertTrue(
            overlay.testAttribute(
                Qt.WidgetAttribute.WA_TransparentForMouseEvents
            )
        )
        self.assertEqual(overlay.active_count(), 0)
        overlay.push_text("好棋！", True)
        overlay.push_emoji("\U0001F44D", False)
        self.assertEqual(overlay.active_count(), 2)
        self.assertFalse(overlay.grab().isNull())
        overlay.clear()
        self.assertEqual(overlay.active_count(), 0)


class FakeChatApi(QObject):
    messages_loaded = Signal(str, object)
    message_sent = Signal(str, object)
    messages_read = Signal(str, object)
    failed = Signal(str, str)

    def __init__(self) -> None:
        super().__init__()
        self.fetch_calls: list[tuple] = []
        self.sent: list[tuple[str, str]] = []
        self.read: list[tuple[str, list[str]]] = []

    def fetch_messages(
        self,
        base_url: str,
        token: str,
        nickname: str,
        limit: int = 50,
    ) -> None:
        self.fetch_calls.append(
            (base_url, token, nickname, limit)
        )

    def send_message(
        self,
        base_url: str,
        token: str,
        nickname: str,
        content: str,
    ) -> None:
        del base_url, token
        self.sent.append((nickname, content))

    def mark_messages_read(
        self,
        base_url: str,
        token: str,
        nickname: str,
        message_ids: list[str],
    ) -> None:
        del base_url, token
        self.read.append((nickname, list(message_ids)))


def message_entry(
    message_id: str,
    sender_id: str,
    sender_name: str,
    content: str,
    *,
    recipient_id: str = "1",
    sent_at_ms: int = 1000,
) -> dict:
    return {
        "id": message_id,
        "sender_id": sender_id,
        "sender_name": sender_name,
        "recipient_id": recipient_id,
        "content": content,
        "sent_at_ms": sent_at_ms,
    }


class PrivateChatOverlayTests(unittest.TestCase):
    def setUp(self) -> None:
        self.api = FakeChatApi()
        self.overlay = PrivateChatOverlay(
            self.api,
            "http://127.0.0.1:8765",
            "token",
            "好友甲",
            "我",
            avatar="default:2",
            online=True,
        )
        self.addCleanup(self.overlay.deleteLater)

    def test_fetches_history_on_open(self) -> None:
        self.assertEqual(
            self.api.fetch_calls,
            [
                (
                    "http://127.0.0.1:8765",
                    "token",
                    "好友甲",
                    100,
                )
            ],
        )

    def test_history_is_rendered(self) -> None:
        self.api.messages_loaded.emit(
            "好友甲",
            {
                "messages": [
                    message_entry(
                        "1", "2", "好友甲", "你好", sent_at_ms=1000
                    ),
                    message_entry(
                        "2", "1", "我", "你也好", sent_at_ms=2000
                    ),
                ]
            },
        )
        text = self.overlay.messages_view.toPlainText()
        self.assertIn("你好", text)
        self.assertIn("你也好", text)

    def test_send_success_and_failure_restore(self) -> None:
        self.overlay.input.setText(" 在吗 ")
        self.overlay.send_button.click()
        self.assertEqual(self.api.sent, [("好友甲", "在吗")])
        self.assertEqual(self.overlay.input.text(), "")
        self.assertEqual(self.overlay.last_draft, "在吗")

        self.api.message_sent.emit(
            "好友甲",
            message_entry("3", "1", "我", "在吗"),
        )
        self.assertEqual(self.overlay.last_draft, "")
        self.assertIn("在吗", self.overlay.messages_view.toPlainText())

        self.overlay.input.setText("失败消息")
        self.overlay.send_button.click()
        self.api.failed.emit("好友甲", "网络错误")
        self.assertEqual(self.overlay.input.text(), "失败消息")
        self.assertIn("网络错误", self.overlay.status_label.text())

    def test_realtime_message_dedup_and_read(self) -> None:
        self.overlay.show()
        APP.processEvents()
        message = message_entry("9", "2", "好友甲", "实时消息")
        self.overlay.append_realtime(message)
        self.overlay.append_realtime(message)
        text = self.overlay.messages_view.toPlainText()
        self.assertEqual(text.count("实时消息"), 1)

        QTest.qWait(250)
        self.assertTrue(
            any(
                ids == ["9"]
                for _nickname, ids in self.api.read
            )
        )
        self.overlay.close()

    def test_history_merges_with_realtime_dedup(self) -> None:
        message = message_entry("5", "2", "好友甲", "同一条消息")
        self.overlay.append_realtime(message)
        self.api.messages_loaded.emit(
            "好友甲", {"messages": [message]}
        )
        self.assertEqual(
            self.overlay.messages_view.toPlainText().count(
                "同一条消息"
            ),
            1,
        )


if __name__ == "__main__":
    unittest.main()
