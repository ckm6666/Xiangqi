"""资料、排行榜、好友窗口与头像工具测试（offscreen）。"""

from __future__ import annotations

import unittest

from tests.qt_helpers import ensure_qt_app

APP = ensure_qt_app()

from PySide6.QtCore import QObject, Signal  # noqa: E402
from PySide6.QtGui import QColor, QImage  # noqa: E402
from PySide6.QtWidgets import QLabel, QPushButton  # noqa: E402

from xiangqi.client.avatars import (  # noqa: E402
    encode_png_bytes,
    pixmap_from_png_bytes,
    render_default_avatar,
)
from xiangqi.client.friends_overlay import FriendsOverlay  # noqa: E402
from xiangqi.client.invite_overlay import InviteFriendOverlay  # noqa: E402
from xiangqi.client.leaderboard_overlay import (  # noqa: E402
    LeaderboardOverlay,
)
from xiangqi.client.profile_overlay import ProfileOverlay  # noqa: E402


class FakeProfileApi(QObject):
    """记录资料/排行榜/好友窗口发出的请求。"""

    profile_loaded = Signal(object)
    profile_updated = Signal(object)
    player_loaded = Signal(object)
    leaderboard_loaded = Signal(object)
    friends_loaded = Signal(object)
    search_loaded = Signal(object)
    friend_request_sent = Signal(object)
    friend_request_resolved = Signal(object)
    avatar_loaded = Signal(bytes)
    avatar_for_loaded = Signal(str, bytes)
    failed = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.fetched = 0
        self.player_fetches: list[str] = []
        self.leaderboard_fetches = 0
        self.friends_fetches = 0
        self.searches: list[str] = []
        self.avatar_choices: list[str] = []
        self.requests: list[str] = []
        self.accepts: list[str] = []
        self.declines: list[str] = []
        self.avatar_requests: list[str] = []

    def fetch_profile(self, base_url: str, token: str) -> None:
        del base_url, token
        self.fetched += 1

    def fetch_player_profile(
        self, base_url: str, token: str, nickname: str
    ) -> None:
        del base_url, token
        self.player_fetches.append(nickname)

    def fetch_leaderboard(
        self, base_url: str, token: str, limit: int = 50
    ) -> None:
        del base_url, token, limit
        self.leaderboard_fetches += 1

    def fetch_friends(self, base_url: str, token: str) -> None:
        del base_url, token
        self.friends_fetches += 1

    def search_players(
        self, base_url: str, token: str, query: str
    ) -> None:
        del base_url, token
        self.searches.append(query)

    def choose_default_avatar(
        self, base_url: str, token: str, avatar_id: str
    ) -> None:
        del base_url, token
        self.avatar_choices.append(avatar_id)

    def upload_avatar(
        self, base_url: str, token: str, png_bytes: bytes
    ) -> None:
        del base_url, token, png_bytes

    def request_friend(
        self, base_url: str, token: str, nickname: str
    ) -> None:
        del base_url, token
        self.requests.append(nickname)

    def accept_friend(
        self, base_url: str, token: str, nickname: str
    ) -> None:
        del base_url, token
        self.accepts.append(nickname)

    def decline_friend(
        self, base_url: str, token: str, nickname: str
    ) -> None:
        del base_url, token
        self.declines.append(nickname)

    def fetch_avatar(self, base_url: str, nickname: str) -> None:
        del base_url
        self.avatar_requests.append(nickname)


def profile_payload(relationship: str | None = None) -> dict:
    payload = {
        "nickname": "测试棋友",
        "rating": 1620,
        "title": "棋师",
        "next_title": {"name": "大师", "min_rating": 1800},
        "wins": 12,
        "losses": 5,
        "draws": 1,
        "games": 18,
        "win_rate": 66.7,
        "record_text": "12胜 1和 5负",
        "current_streak": 2,
        "best_streak": 4,
        "avatar": "default:3",
        "achievements": [
            {
                "key": "first_game",
                "name": "初涉楚河",
                "description": "完成第一局联机对局",
                "earned": True,
            },
            {
                "key": "wins_50",
                "name": "百战不殆",
                "description": "累计赢得 50 局联机对局",
                "earned": False,
            },
        ],
    }
    if relationship is not None:
        payload["relationship"] = relationship
    return payload


class AvatarTests(unittest.TestCase):
    def test_default_avatars_render(self) -> None:
        for avatar_id in ("default:1", "default:6", "unknown"):
            pixmap = render_default_avatar(avatar_id, 64, dpr=1.0)
            self.assertFalse(pixmap.isNull())
            self.assertEqual(pixmap.width(), 64)

    def test_png_round_trip(self) -> None:
        image = QImage(120, 80, QImage.Format.Format_RGB32)
        image.fill(QColor("#9E3B2E"))
        data = encode_png_bytes(image, 64)
        self.assertTrue(data.startswith(b"\x89PNG"))
        pixmap = pixmap_from_png_bytes(data, 48, dpr=1.0)
        self.assertIsNotNone(pixmap)
        assert pixmap is not None
        self.assertEqual(pixmap.width(), 48)


class ProfileOverlayTests(unittest.TestCase):
    def _own_overlay(self) -> tuple[FakeProfileApi, ProfileOverlay]:
        api = FakeProfileApi()
        overlay = ProfileOverlay(
            api, "http://127.0.0.1:8765", "token"
        )
        self.addCleanup(overlay.deleteLater)
        self.assertEqual(api.fetched, 1)
        return api, overlay

    def _other_overlay(
        self, nickname: str = "他人"
    ) -> tuple[FakeProfileApi, ProfileOverlay]:
        api = FakeProfileApi()
        overlay = ProfileOverlay(
            api, "http://127.0.0.1:8765", "token", nickname
        )
        self.addCleanup(overlay.deleteLater)
        self.assertEqual(api.player_fetches, [nickname])
        return api, overlay

    def test_own_profile_has_no_friend_button(self) -> None:
        _api, overlay = self._own_overlay()
        overlay._on_profile_loaded(profile_payload("self"))
        self.assertTrue(overlay.is_self)
        self.assertTrue(overlay.friend_button.isHidden())
        self.assertEqual(overlay.name_label.text(), "测试棋友")
        self.assertIn("棋师", overlay.identity_label.text())
        self.assertIn("1620", overlay.identity_label.text())
        self.assertEqual(
            overlay._stat_labels["record"].text(), "12胜 1和 5负"
        )
        self.assertEqual(
            overlay._stat_labels["win_rate"].text(), "66.7%"
        )
        self.assertEqual(overlay._stat_labels["streak"].text(), "4")
        self.assertIn("180", overlay.progress_label.text())
        self.assertIn("1/2", overlay.achievement_title.text())
        self.assertFalse(overlay.avatar_section.isHidden())

    def test_other_profile_friend_request_flow(self) -> None:
        api, overlay = self._other_overlay("好友甲")
        overlay._on_player_loaded(profile_payload("none"))
        self.assertFalse(overlay.friend_button.isHidden())
        self.assertEqual(overlay.friend_button.text(), "申请加好友")
        self.assertTrue(overlay.friend_button.isEnabled())
        self.assertTrue(overlay.avatar_section.isHidden())

        overlay.friend_button.click()
        self.assertEqual(api.requests, ["好友甲"])
        self.assertFalse(overlay.friend_button.isEnabled())
        overlay._on_friend_request_sent(
            {"relationship": "pending_out"}
        )
        self.assertEqual(overlay.friend_button.text(), "已发送申请")
        self.assertFalse(overlay.friend_button.isEnabled())

    def test_other_profile_accepts_incoming_request(self) -> None:
        api, overlay = self._other_overlay("好友乙")
        overlay._on_player_loaded(profile_payload("pending_in"))
        self.assertEqual(overlay.friend_button.text(), "同意好友申请")
        overlay.friend_button.click()
        self.assertEqual(api.accepts, ["好友乙"])
        overlay._on_friend_resolved({"relationship": "friend"})
        self.assertEqual(overlay.friend_button.text(), "已是好友")
        self.assertFalse(overlay.friend_button.isEnabled())

    def test_existing_friend_button_disabled(self) -> None:
        _api, overlay = self._other_overlay("好友丙")
        overlay._on_player_loaded(profile_payload("friend"))
        self.assertEqual(overlay.friend_button.text(), "已是好友")
        self.assertFalse(overlay.friend_button.isEnabled())

    def test_choose_avatar_calls_api(self) -> None:
        api, overlay = self._own_overlay()
        overlay._on_profile_loaded(profile_payload("self"))
        overlay._choose_avatar("default:5")
        self.assertEqual(api.avatar_choices, ["default:5"])

    def test_custom_avatar_fetch(self) -> None:
        api, overlay = self._own_overlay()
        payload = profile_payload("self")
        payload["avatar"] = "custom"
        overlay._on_profile_loaded(payload)
        self.assertEqual(api.avatar_requests, ["测试棋友"])


class LeaderboardOverlayTests(unittest.TestCase):
    def setUp(self) -> None:
        self.api = FakeProfileApi()
        self.overlay = LeaderboardOverlay(
            self.api, "http://127.0.0.1:8765", "token"
        )
        self.addCleanup(self.overlay.deleteLater)
        self.assertEqual(self.api.leaderboard_fetches, 1)

    def test_rows_and_avatar_click(self) -> None:
        requested: list[str] = []
        self.overlay.profile_requested.connect(requested.append)
        self.overlay._on_loaded(
            {
                "players": [
                    {
                        "rank": 1,
                        "nickname": "榜首",
                        "rating": 2100,
                        "title": "特级大师",
                        "avatar": "default:2",
                        "record_text": "20胜 1和 3负",
                        "is_self": False,
                    },
                    {
                        "rank": 2,
                        "nickname": "自己",
                        "rating": 1800,
                        "title": "大师",
                        "avatar": "custom",
                        "record_text": "10胜 0和 5负",
                        "is_self": True,
                    },
                ],
                "count": 2,
            }
        )
        self.assertIn("榜首", self.overlay._avatar_buttons)
        self.assertIn("自己", self.overlay._avatar_buttons)
        self.assertIn("自己", self.api.avatar_requests)
        self.overlay._avatar_buttons["榜首"].click()
        self.assertEqual(requested, ["榜首"])

    def test_avatar_for_loaded_updates_icon(self) -> None:
        self.overlay._on_loaded(
            {
                "players": [
                    {
                        "rank": 1,
                        "nickname": "自定义",
                        "rating": 2000,
                        "title": "特级大师",
                        "avatar": "custom",
                        "record_text": "",
                        "is_self": False,
                    }
                ]
            }
        )
        image = QImage(40, 40, QImage.Format.Format_RGB32)
        image.fill(QColor("#9E3B2E"))
        from xiangqi.client.avatars import encode_png_bytes

        data = encode_png_bytes(image, 40)
        self.overlay._on_avatar_loaded("自定义", data)
        self.assertFalse(
            self.overlay._avatar_buttons["自定义"].icon().isNull()
        )


class FriendsOverlayTests(unittest.TestCase):
    def setUp(self) -> None:
        self.api = FakeProfileApi()
        self.overlay = FriendsOverlay(
            self.api, "http://127.0.0.1:8765", "token"
        )
        self.addCleanup(self.overlay.deleteLater)
        self.assertEqual(self.api.friends_fetches, 1)

    def test_lists_and_accept_decline(self) -> None:
        self.overlay._on_loaded(
            {
                "friends": [
                    {
                        "nickname": "好友甲",
                        "rating": 1200,
                        "title": "棋士",
                        "avatar": "default:1",
                    }
                ],
                "incoming": [
                    {
                        "nickname": "申请人",
                        "rating": 1500,
                        "title": "上品棋士",
                        "avatar": "default:3",
                    }
                ],
                "outgoing": [
                    {
                        "nickname": "等待中",
                        "rating": 1300,
                        "title": "棋士",
                        "avatar": "default:4",
                    }
                ],
            }
        )
        labels = {
            label.text()
            for label in self.overlay.findChildren(QLabel)
        }
        self.assertIn("好友甲", labels)
        self.assertIn("申请人", labels)
        self.assertIn("等待中", labels)
        self.assertIn("好友 1 位 · 待处理申请 1 条", labels)

        self.overlay._accept("申请人")
        self.assertEqual(self.api.accepts, ["申请人"])
        self.overlay._decline("申请人")
        self.assertEqual(self.api.declines, ["申请人"])

    def test_profile_avatar_request(self) -> None:
        requested: list[str] = []
        self.overlay.profile_requested.connect(requested.append)
        self.overlay._on_loaded(
            {
                "friends": [
                    {
                        "nickname": "好友甲",
                        "rating": 1200,
                        "title": "棋士",
                        "avatar": "default:2",
                    }
                ],
                "incoming": [],
                "outgoing": [],
            }
        )
        self.overlay._avatar_buttons["好友甲"].click()
        self.assertEqual(requested, ["好友甲"])

    def test_friend_chat_button_unread_and_presence(self) -> None:
        events: list[tuple[str, str, bool]] = []
        self.overlay.chat_requested.connect(
            lambda nickname, avatar, online: events.append(
                (nickname, avatar, online)
            )
        )
        self.overlay._on_loaded(
            {
                "friends": [
                    {
                        "nickname": "好友甲",
                        "rating": 1200,
                        "title": "棋士",
                        "avatar": "default:2",
                        "online": True,
                        "unread": 2,
                    }
                ],
                "incoming": [],
                "outgoing": [],
            }
        )
        labels = {
            label.text()
            for label in self.overlay.findChildren(QLabel)
        }
        self.assertIn("● 在线 · 空闲", labels)
        self.assertIn("2 条未读", labels)
        chat_buttons = [
            button
            for button in self.overlay.findChildren(QPushButton)
            if button.text() == "聊天"
        ]
        self.assertTrue(chat_buttons)
        chat_buttons[0].click()
        self.assertEqual(
            events, [("好友甲", "default:2", True)]
        )

    def test_spectate_button_only_enabled_in_game(self) -> None:
        requested: list[str] = []
        self.overlay.spectate_requested.connect(requested.append)
        self.overlay._on_loaded(
            {
                "friends": [
                    {
                        "nickname": "对局中",
                        "rating": 1200,
                        "title": "棋士",
                        "avatar": "default:1",
                        "online": True,
                        "in_game": True,
                        "game_status": "playing",
                    },
                    {
                        "nickname": "空闲",
                        "rating": 1200,
                        "title": "棋士",
                        "avatar": "default:2",
                        "online": True,
                        "in_game": False,
                        "game_status": "",
                    },
                ],
                "incoming": [],
                "outgoing": [],
            }
        )
        labels = {
            label.text()
            for label in self.overlay.findChildren(QLabel)
        }
        self.assertIn("● 在线 · 对局中", labels)
        self.assertIn("● 在线 · 空闲", labels)

        spectate_buttons = [
            button
            for button in self.overlay.findChildren(QPushButton)
            if button.text() == "观战"
        ]
        self.assertEqual(len(spectate_buttons), 2)
        enabled = [
            button.isEnabled() for button in spectate_buttons
        ]
        self.assertEqual(enabled, [True, False])
        spectate_buttons[0].click()
        spectate_buttons[1].click()
        self.assertEqual(requested, ["对局中"])

    def test_search_players_and_open_profile(self) -> None:
        requested: list[str] = []
        self.overlay.profile_requested.connect(requested.append)
        self.overlay.search_input.setText("棋")
        self.overlay._run_search()
        self.assertEqual(self.api.searches, ["棋"])
        self.overlay._on_search_loaded(
            {
                "query": "棋",
                "players": [
                    {
                        "nickname": "搜索棋友",
                        "rating": 1500,
                        "title": "上品棋士",
                        "avatar": "default:5",
                        "relationship": "none",
                    }
                ],
            }
        )
        labels = {
            label.text()
            for label in self.overlay.findChildren(QLabel)
        }
        self.assertIn("搜索结果：棋", labels)
        self.assertIn("搜索棋友", labels)
        self.assertIn("点击头像查看资料", labels)
        self.overlay._avatar_buttons["搜索棋友"].click()
        self.assertEqual(requested, ["搜索棋友"])


class FakeInviteSession(QObject):
    invite_status = Signal(str)
    invite_result = Signal(bool, str)

    def __init__(self) -> None:
        super().__init__()
        self.invited: list[str] = []

    def invite_friend(self, nickname: str) -> bool:
        self.invited.append(nickname)
        return True


class InviteFriendOverlayTests(unittest.TestCase):
    def test_invite_from_friend_list(self) -> None:
        api = FakeProfileApi()
        session = FakeInviteSession()
        overlay = InviteFriendOverlay(
            api,
            "http://127.0.0.1:8765",
            "token",
            session,
        )
        self.addCleanup(overlay.deleteLater)
        self.assertEqual(api.friends_fetches, 1)
        overlay._on_friends_loaded(
            {
                "friends": [
                    {
                        "nickname": "好友甲",
                        "rating": 1200,
                        "title": "棋士",
                        "avatar": "default:1",
                    },
                    {
                        "nickname": "好友乙",
                        "rating": 1500,
                        "title": "上品棋士",
                        "avatar": "default:2",
                    },
                ]
            }
        )
        labels = {
            label.text() for label in overlay.findChildren(QLabel)
        }
        self.assertIn("好友甲", labels)
        self.assertIn("好友乙", labels)
        self.assertEqual(len(overlay._invite_buttons), 2)
        overlay._invite_buttons[0].click()
        self.assertEqual(session.invited, ["好友甲"])
        self.assertFalse(overlay._invite_buttons[0].isEnabled())

        session.invite_result.emit(False, "好友不在线")
        self.assertTrue(overlay._invite_buttons[0].isEnabled())
        self.assertIn("好友不在线", overlay.status_label.text())


if __name__ == "__main__":
    unittest.main()
