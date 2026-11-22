"""主窗口 offscreen 流程测试。"""

from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from tests.qt_helpers import ensure_qt_app

APP = ensure_qt_app()

from PySide6.QtCore import Qt, QTimer  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QLabel  # noqa: E402

from tests.fakes import (  # noqa: E402
    FakeAIWorker,
    FakeAudioManager,
    FakeTransport,
    FakeVoiceAnnouncer,
)
from tests.helpers import model_with, piece  # noqa: E402
from xiangqi.client.ai_engine import AIDifficulty  # noqa: E402
from xiangqi.client.board_view import BoardView  # noqa: E402
from xiangqi.client.constants import AI_START_DELAY_MS, APP_VERSION  # noqa: E402
from xiangqi.client.main_window import GameMode, MainWindow  # noqa: E402
from xiangqi.client.modal_overlay import ModalOverlay  # noqa: E402
from xiangqi.client.records import LocalRecordStore  # noqa: E402
from xiangqi.client.sessions import (  # noqa: E402
    AIGameSession,
    LocalGameSession,
    OnlineGameSession,
)
from xiangqi.shared.game_model import GameModel  # noqa: E402
from xiangqi.shared.record import GameRecord  # noqa: E402
from xiangqi.shared.protocol import (  # noqa: E402
    SERVER_AUTH_OK,
    SERVER_GAME_STATE,
    SERVER_INVITE_RESULT,
    SERVER_QUEUE_STATUS,
    SERVER_UNDO_REQUESTED,
    make_message,
    serialize_board,
)
from xiangqi.shared.rules import (  # noqa: E402
    EndReason,
    Move,
    PieceKind,
    Side,
)


AUTH_OK_PAYLOAD = {
    "user_id": 1,
    "nickname": "甲",
    "rating": 1200,
}


def online_state(**overrides) -> dict:
    board = overrides.pop("board", None)
    payload = {
        "room_code": "ABCD",
        "status": "playing",
        "ranked": False,
        "your_side": "red",
        "players": {
            "red": {"name": "甲", "connected": True},
            "black": {"name": "乙", "connected": True},
        },
        "board": serialize_board(
            board if board is not None else GameModel.initial().board
        ),
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


def checkmate_model():
    """一步将死红方的局面（红方走 (1,3)->(0,3)）。"""
    return model_with(
        {
            (1, 3): piece(PieceKind.CHARIOT, Side.RED),
            (2, 2): piece(PieceKind.HORSE, Side.RED),
            (4, 4): piece(PieceKind.PAWN, Side.RED),
        },
        red_king=(9, 4),
        black_king=(0, 4),
    )


def stalemate_model():
    """一步困毙黑方的局面（红方走 (2,5)->(1,5)）。"""
    return model_with(
        {
            (1, 3): piece(PieceKind.CHARIOT, Side.RED),
            (2, 5): piece(PieceKind.CHARIOT, Side.RED),
            (4, 4): piece(PieceKind.PAWN, Side.RED),
        },
        red_king=(9, 4),
        black_king=(0, 4),
    )


class MainWindowTests(unittest.TestCase):
    """菜单、选中落子、弹窗与终局流程。"""

    def setUp(self) -> None:
        self.audio = FakeAudioManager()
        self.voice = FakeVoiceAnnouncer()
        self._patches = [
            patch(
                "xiangqi.client.sound_control.get_audio_manager",
                return_value=self.audio,
            ),
            patch(
                "xiangqi.client.main_window.get_audio_manager",
                return_value=self.audio,
            ),
            patch(
                "xiangqi.client.sessions.ai.AIWorker",
                FakeAIWorker,
            ),
            patch(
                "xiangqi.client.main_window.get_voice_announcer",
                return_value=self.voice,
            ),
        ]
        for item in self._patches:
            item.start()
        self.addCleanup(self._stop_patches)
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.record_store = LocalRecordStore(Path(self.temp_dir.name))
        self.window = MainWindow(record_store=self.record_store)
        self.addCleanup(self.window.deleteLater)

        self.online_transports: list[FakeTransport] = []

        def make_transport(parent):
            transport = FakeTransport(parent)
            self.online_transports.append(transport)
            return transport

        self.window.online_page._transport_factory = make_transport

    def _stop_patches(self) -> None:
        for item in self._patches:
            item.stop()

    def _start_and_move(self) -> None:
        self.window.start_local_game()
        self.window._on_cell_clicked(6, 0)
        self.window._on_cell_clicked(5, 0)

    def _install_session(self, model) -> LocalGameSession:
        session = LocalGameSession(model)
        self.window._session = session
        self.window._connect_session(session)
        self.window._sync_ui()
        return session

    def test_menu_is_initial_page(self) -> None:
        self.assertIs(self.window.stack.currentWidget(), self.window.menu_page)
        self.assertEqual(self.window.local_button.text(), "本地双人")
        self.assertEqual(self.window.ai_button.text(), "人机对战")
        self.assertEqual(self.window.online_button.text(), "联机对战")
        self.assertEqual(self.window.replay_button.text(), "棋谱复盘")
        self.assertEqual(self.window.puzzle_button.text(), "残局挑战")
        self.assertEqual(
            self.window.online_button.objectName(), "menuPrimaryButton"
        )
        version = self.window.findChild(QLabel, "menuVersion")
        self.assertIsNotNone(version)
        assert version is not None
        self.assertIn(APP_VERSION, version.text())
        self.assertFalse(self.window._undo_shortcut.isEnabled())
        self.assertFalse(self.window._restart_shortcut.isEnabled())

    def test_start_local_game(self) -> None:
        self.window.start_local_game()
        self.assertIs(self.window.stack.currentWidget(), self.window.game_page)
        self.assertIsInstance(self.window.session, LocalGameSession)
        self.assertTrue(self.window._undo_shortcut.isEnabled())
        self.assertTrue(self.window._restart_shortcut.isEnabled())
        self.assertIn("本地双人", self.window.local_mode_label.text())
        self.assertEqual(self.window.red_card.property("active"), "true")
        self.assertEqual(self.window.turn_pill.text(), "红方回合")
        self.assertIn("第 0 手", self.window.move_label.text())
        self.assertIn("start", self.audio.played)

    def test_selection_then_move(self) -> None:
        self.window.start_local_game()
        self.window._on_cell_clicked(6, 0)
        self.assertEqual(self.window.selected, (6, 0))
        self.assertEqual(self.window.board_widget.view.selected, (6, 0))
        self.assertIn((5, 0), self.window.board_widget.view.legal_targets)

        self.window._on_cell_clicked(5, 0)
        self.assertIsNone(self.window.selected)
        self.assertEqual(self.window.session.view.move_count, 1)
        self.assertIs(self.window.session.view.side_to_move, Side.BLACK)
        self.assertEqual(self.window.turn_pill.text(), "黑方回合")
        self.assertIn("第 1 手", self.window.move_label.text())
        self.assertIn("move", self.audio.played)

    def test_empty_and_enemy_squares_do_not_select(self) -> None:
        self.window.start_local_game()
        self.window._on_cell_clicked(5, 4)
        self.assertIsNone(self.window.selected)
        self.window._on_cell_clicked(3, 0)
        self.assertIsNone(self.window.selected)

    def test_clicking_other_own_piece_reselects(self) -> None:
        self.window.start_local_game()
        self.window._on_cell_clicked(9, 0)
        self.assertEqual(self.window.selected, (9, 0))
        self.window._on_cell_clicked(9, 1)
        self.assertEqual(self.window.selected, (9, 1))
        self.window._on_cell_clicked(3, 0)
        self.assertIsNone(self.window.selected)

    def test_undo(self) -> None:
        self._start_and_move()
        self.assertTrue(self.window.undo_button.isEnabled())
        self.window._undo_move()
        self.assertEqual(self.window.session.view.move_count, 0)
        self.assertIs(self.window.session.view.side_to_move, Side.RED)
        self.assertEqual(self.window.turn_pill.text(), "红方回合")
        self.assertFalse(self.window.undo_button.isEnabled())

    def test_restart_requires_confirmation(self) -> None:
        self._start_and_move()
        original = self.window.session

        QTimer.singleShot(
            0, lambda: self.window.active_modal().reject()
        )
        self.window._request_restart()
        self.assertIs(self.window.session, original)
        self.assertEqual(self.window.session.view.move_count, 1)

        QTimer.singleShot(
            0, lambda: self.window.active_modal().accept()
        )
        self.window._request_restart()
        self.assertIsNot(self.window.session, original)
        self.assertEqual(self.window.session.view.move_count, 0)

    def test_return_to_menu_requires_confirmation(self) -> None:
        self._start_and_move()
        QTimer.singleShot(
            0, lambda: self.window.active_modal().reject()
        )
        self.window.show_main_menu()
        self.assertIs(self.window.stack.currentWidget(), self.window.game_page)

        QTimer.singleShot(
            0, lambda: self.window.active_modal().accept()
        )
        self.window.show_main_menu()
        self.assertIs(self.window.stack.currentWidget(), self.window.menu_page)
        self.assertFalse(self.window._undo_shortcut.isEnabled())

    def test_placeholder_menu_buttons_show_notice(self) -> None:
        QTimer.singleShot(
            0, lambda: self.window.active_modal().accept()
        )
        self.window.puzzle_button.click()
        self.assertIs(self.window.stack.currentWidget(), self.window.menu_page)
        self.assertIsNone(self.window.active_modal())

    def test_result_presentation_checkmate(self) -> None:
        model = checkmate_model()
        self.assertIsNotNone(model.apply_move(1, 3, 0, 3))
        view = BoardView.from_model(model)
        presentation = self.window._build_result_presentation(view)
        self.assertEqual(presentation.title, "红方胜")
        self.assertEqual(presentation.subtitle, "将死")
        self.assertIn("本局共 1 手", presentation.detail)
        self.assertEqual(presentation.seal_text, "胜")

    def test_result_presentation_stalemate(self) -> None:
        model = stalemate_model()
        self.assertIsNotNone(model.apply_move(2, 5, 1, 5))
        self.assertIs(model.end_reason, EndReason.STALEMATE)
        view = BoardView.from_model(model)
        presentation = self.window._build_result_presentation(view)
        self.assertEqual(presentation.title, "红方胜")
        self.assertEqual(presentation.subtitle, "困毙")

    def test_result_dialog_view_board_keeps_game_over(self) -> None:
        self.window.start_local_game()
        model = checkmate_model()
        model.apply_move(1, 3, 0, 3)
        session = self._install_session(model)

        QTimer.singleShot(
            0, lambda: self.window.active_modal().reject()
        )
        self.window._show_result_dialog()
        self.assertIs(self.window.session, session)
        self.assertTrue(self.window.session.view.is_game_over)

    def test_result_dialog_restart_starts_new_game(self) -> None:
        self.window.start_local_game()
        model = checkmate_model()
        model.apply_move(1, 3, 0, 3)
        old_session = self._install_session(model)

        QTimer.singleShot(
            0, lambda: self.window.active_modal().accept()
        )
        self.window._show_result_dialog()
        self.assertIsNot(self.window.session, old_session)
        self.assertEqual(self.window.session.view.move_count, 0)
        self.assertFalse(self.window.session.view.is_game_over)

    def test_game_over_saves_record(self) -> None:
        self._start_local_with_model(checkmate_model())
        self.window._on_cell_clicked(1, 3)
        self.window._on_cell_clicked(0, 3)
        self.window._result_timer.stop()

        self.assertEqual(self.record_store.count(), 1)
        record = self.record_store.list_recent()[0]
        self.assertEqual(record.mode, "local")
        self.assertIs(record.winner, Side.RED)
        self.assertEqual(record.result_reason, "checkmate")
        self.assertEqual(len(record.moves), 1)

    def test_replay_page_shows_stored_record(self) -> None:
        self.record_store.append(
            GameRecord(
                record_id="replay-1",
                created_at="2026-11-22T12:00:00+08:00",
                mode="local",
                moves=(Move(6, 0, 5, 0), Move(3, 0, 4, 0)),
                winner=None,
                result_reason="",
                red_name="红方",
                black_name="黑方",
            )
        )
        self.window.replay_button.click()
        self.assertIs(
            self.window.stack.currentWidget(), self.window.replay_page
        )
        replay = self.window.replay_page
        self.assertEqual(len(replay.records), 1)
        timeline = replay.timeline
        self.assertIsNotNone(timeline)
        assert timeline is not None
        self.assertEqual(timeline.length, 2)

        replay._step(1)
        self.assertEqual(replay.board.view.move_count, 1)
        self.assertIn("第 1 / 2 手", replay.frame_label.text())
        replay._step(1)
        self.assertEqual(replay.board.view.move_count, 2)
        self.assertFalse(replay.next_button.isEnabled())
        replay.back_button.click()
        self.assertIs(
            self.window.stack.currentWidget(), self.window.menu_page
        )

    # ------------------------------------------------------------------
    # 人机对战
    # ------------------------------------------------------------------
    def test_ai_button_starts_ai_game(self) -> None:
        self.window.ai_button.click()
        self.assertIs(self.window.stack.currentWidget(), self.window.game_page)
        self.assertIsInstance(self.window.session, AIGameSession)
        self.assertFalse(self.window.difficulty_group.isHidden())
        self.assertFalse(self.window.first_group.isHidden())
        self.assertEqual(self.window.local_mode_label.text(), "人机对战")
        self.assertEqual(self.window.red_card._name_label.text(), "你")
        self.assertEqual(
            self.window.black_card._name_label.text(), "AI（业余）"
        )

    def test_ai_replies_to_human_move(self) -> None:
        self.window.start_ai_game()
        session = self.window.session
        self.assertIsInstance(session, AIGameSession)
        self.window._on_cell_clicked(6, 0)
        self.window._on_cell_clicked(5, 0)

        self.assertTrue(session.busy)
        self.assertFalse(session.accepts_human_input)
        self.assertEqual(self.window.turn_pill.text(), "AI 思考中…")
        self.assertIn("AI 思考中", self.window.move_label.text())
        self.assertFalse(self.window.board_widget._interaction_enabled)
        self.assertTrue(self.window.board_widget.is_animating)

        # 人落子的动画必须完整播放，AI 搜索要等动画结束后才开始。
        QTest.qWait(150)
        self.assertTrue(self.window.board_widget.is_animating)
        self.assertEqual(session.view.move_count, 1)

        QTest.qWait(AI_START_DELAY_MS + 120)
        self.assertEqual(session.view.move_count, 2)
        self.assertIs(session.view.side_to_move, Side.RED)
        self.assertFalse(session.busy)
        self.assertTrue(session.accepts_human_input)
        self.assertEqual(self.window.turn_pill.text(), "你的回合")
        self.assertIn("你行棋", self.window.move_label.text())

    def test_ai_first_setting(self) -> None:
        self.window.start_ai_game()
        index = self.window._combo_index_for_data(
            self.window.first_combo, Side.BLACK
        )
        self.window.first_combo.setCurrentIndex(index)
        self.assertIs(self.window._human_side, Side.BLACK)

        QTest.qWait(30)
        session = self.window.session
        self.assertIsInstance(session, AIGameSession)
        self.assertEqual(session.view.move_count, 1)
        self.assertIs(session.view.side_to_move, Side.BLACK)
        self.assertEqual(self.window.red_card._name_label.text(), "AI（业余）")
        self.assertEqual(self.window.black_card._name_label.text(), "你")
        self.assertEqual(self.window.turn_pill.text(), "你的回合")

    def test_switch_first_side_requires_confirmation(self) -> None:
        self.window.start_ai_game()
        self.window._on_cell_clicked(6, 0)
        self.window._on_cell_clicked(5, 0)
        QTest.qWait(AI_START_DELAY_MS + 120)
        self.assertEqual(self.window.session.view.move_count, 2)

        black_index = self.window._combo_index_for_data(
            self.window.first_combo, Side.BLACK
        )
        QTimer.singleShot(0, lambda: self.window.active_modal().reject())
        self.window.first_combo.setCurrentIndex(black_index)
        self.assertIs(self.window._human_side, Side.RED)
        self.assertEqual(self.window.session.view.move_count, 2)

        QTimer.singleShot(0, lambda: self.window.active_modal().accept())
        self.window.first_combo.setCurrentIndex(black_index)
        self.assertIs(self.window._human_side, Side.BLACK)
        QTest.qWait(30)
        self.assertEqual(self.window.session.view.move_count, 1)
        self.assertIs(self.window.session.view.side_to_move, Side.BLACK)

    def test_difficulty_change_updates_session(self) -> None:
        self.window.start_ai_game()
        session = self.window.session
        self.assertIsInstance(session, AIGameSession)
        index = self.window._combo_index_for_data(
            self.window.difficulty_combo, AIDifficulty.HARD
        )
        self.window.difficulty_combo.setCurrentIndex(index)
        self.assertIs(session.difficulty, AIDifficulty.HARD)
        self.assertEqual(
            self.window.black_card._name_label.text(), "AI（高手）"
        )

    def test_ai_result_presentation_win_and_lose(self) -> None:
        self.window._game_mode = GameMode.AI
        self.window._human_side = Side.RED
        self.window._difficulty = AIDifficulty.MEDIUM

        model = checkmate_model()
        model.apply_move(1, 3, 0, 3)
        win_view = BoardView.from_model(model)
        win = self.window._build_result_presentation(win_view)
        self.assertEqual(win.kind, "win")
        self.assertEqual(win.title, "胜利")
        self.assertIn("将死", win.subtitle)

        lose_view = BoardView(
            board=model.board,
            side_to_move=Side.RED,
            last_move=None,
            is_check=False,
            winner=Side.BLACK,
            end_reason=EndReason.CHECKMATE,
            is_game_over=True,
            move_count=12,
        )
        lose = self.window._build_result_presentation(lose_view)
        self.assertEqual(lose.kind, "lose")
        self.assertEqual(lose.title, "惜败")
        self.assertEqual(lose.seal_text, "负")

    # ------------------------------------------------------------------
    # 联机对战
    # ------------------------------------------------------------------
    def _enter_online_game(self) -> FakeTransport:
        self.window.online_button.click()
        self.window.online_page.apply_auth("token", "甲", 1200)
        self.window.online_page.create_button.click()
        transport = self.online_transports[-1]
        transport.simulate_connected()
        self.assertEqual(transport.sent[-1]["type"], "auth")
        transport.server_send(
            make_message(SERVER_AUTH_OK, AUTH_OK_PAYLOAD)
        )
        self.assertEqual(
            transport.sent[-1]["type"], "create_room"
        )
        transport.server_send(
            make_message(SERVER_GAME_STATE, online_state())
        )
        return transport

    def _enter_ranked_game(self) -> FakeTransport:
        self.window.online_button.click()
        self.window.online_page.apply_auth("token", "甲", 1200)
        self.window.online_page.ranked_button.click()
        transport = self.online_transports[-1]
        transport.simulate_connected()
        transport.server_send(
            make_message(SERVER_AUTH_OK, AUTH_OK_PAYLOAD)
        )
        self.assertEqual(transport.sent[-1]["type"], "join_queue")
        transport.server_send(
            make_message(
                SERVER_QUEUE_STATUS,
                {"message": "正在匹配…（第 1 位）"},
            )
        )
        transport.server_send(
            make_message(
                SERVER_GAME_STATE, online_state(ranked=True)
            )
        )
        return transport

    def test_online_button_opens_lobby(self) -> None:
        self.window.online_button.click()
        self.assertIs(
            self.window.stack.currentWidget(), self.window.online_page
        )
        self.assertFalse(self.window._undo_shortcut.isEnabled())

    def test_online_flow_and_move(self) -> None:
        transport = self._enter_online_game()
        self.assertIs(
            self.window.stack.currentWidget(), self.window.game_page
        )
        self.assertIsInstance(self.window.session, OnlineGameSession)
        self.assertIs(self.window._game_mode, GameMode.ONLINE)
        self.assertIn("自建房", self.window.local_mode_label.text())
        self.assertEqual(self.window.restart_button.text(), "认输")
        self.assertEqual(self.window.menu_back_button.text(), "离开房间")
        self.assertEqual(self.window.turn_pill.text(), "你的回合")
        self.assertTrue(self.window.board_widget._interaction_enabled)

        self.window._on_cell_clicked(6, 0)
        self.window._on_cell_clicked(5, 0)
        self.assertEqual(transport.sent[-1]["type"], "move_intent")
        self.assertEqual(self.window.turn_pill.text(), "同步中…")
        self.assertFalse(self.window.board_widget._interaction_enabled)

        moved_model = GameModel.initial()
        self.assertIsNotNone(moved_model.apply_move(6, 0, 5, 0))
        transport.server_send(
            make_message(
                SERVER_GAME_STATE,
                online_state(
                    board=moved_model.board,
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
        )
        self.assertEqual(self.window.turn_pill.text(), "等待对手…")
        self.assertFalse(self.window.board_widget._interaction_enabled)
        self.assertTrue(self.window.board_widget.is_animating)

    def test_online_waiting_room(self) -> None:
        self.window.online_button.click()
        self.window.online_page.apply_auth("token", "甲", 1200)
        self.window.online_page.create_button.click()
        transport = self.online_transports[-1]
        transport.simulate_connected()
        transport.server_send(
            make_message(SERVER_AUTH_OK, AUTH_OK_PAYLOAD)
        )
        transport.server_send(
            make_message(
                SERVER_GAME_STATE,
                online_state(
                    status="waiting",
                    players={
                        "red": {"name": "甲", "connected": True},
                        "black": {"name": "", "connected": False},
                    },
                ),
            )
        )
        self.assertEqual(
            self.window.turn_pill.text(), "等待好友接受挑战…"
        )
        self.assertFalse(self.window.restart_button.isEnabled())
        self.assertIn("等待好友", self.window.move_label.text())
        self.assertFalse(self.window.invite_button.isHidden())
        self.assertTrue(self.window.invite_button.isEnabled())

    def test_invite_accept_reenables_board(self) -> None:
        """好友接受挑战后关闭邀请窗口，主棋盘必须恢复可操作。"""
        self.window.online_button.click()
        self.window.online_page.apply_auth("token", "甲", 1200)
        self.window.online_page.create_button.click()
        transport = self.online_transports[-1]
        transport.simulate_connected()
        transport.server_send(
            make_message(SERVER_AUTH_OK, AUTH_OK_PAYLOAD)
        )
        transport.server_send(
            make_message(
                SERVER_GAME_STATE,
                online_state(
                    status="waiting",
                    players={
                        "red": {"name": "甲", "connected": True},
                        "black": {"name": "", "connected": False},
                    },
                ),
            )
        )
        self.assertFalse(self.window.board_widget._interaction_enabled)

        class FakeInviteOverlay(ModalOverlay):
            def __init__(
                self, api, base_url, token, session, *, parent=None
            ) -> None:
                del api, base_url, token, session
                super().__init__(parent, object_name="fakeInviteDialog")

        def friend_accepts() -> None:
            transport.server_send(
                make_message(
                    SERVER_INVITE_RESULT,
                    {
                        "status": "accepted",
                        "accepted": True,
                        "name": "乙",
                    },
                )
            )
            transport.server_send(
                make_message(
                    SERVER_GAME_STATE,
                    online_state(
                        status="playing",
                        players={
                            "red": {"name": "甲", "connected": True},
                            "black": {"name": "乙", "connected": True},
                        },
                    ),
                )
            )

        QTimer.singleShot(0, friend_accepts)
        with patch(
            "xiangqi.client.main_window.InviteFriendOverlay",
            FakeInviteOverlay,
        ):
            self.window.invite_button.click()

        self.assertFalse(self.window._modal_dialog_open)
        self.assertIsNone(self.window._invite_overlay)
        self.assertTrue(self.window.session.accepts_human_input)
        self.assertTrue(self.window.board_widget._interaction_enabled)

    def test_online_black_perspective_flips_board(self) -> None:
        self.window.online_button.click()
        self.window.online_page.apply_auth("token", "甲", 1200)
        self.window.online_page.create_button.click()
        transport = self.online_transports[-1]
        transport.simulate_connected()
        transport.server_send(
            make_message(SERVER_AUTH_OK, AUTH_OK_PAYLOAD)
        )
        transport.server_send(
            make_message(
                SERVER_GAME_STATE,
                online_state(
                    your_side="black",
                    side_to_move="red",
                    players={
                        "red": {"name": "乙", "connected": True},
                        "black": {"name": "甲", "connected": True},
                    },
                ),
            )
        )
        self.assertIs(self.window.session.human_side, Side.BLACK)
        self.assertTrue(self.window.board_widget.flipped)
        # 黑方底线 (0, 0) 在翻转后应显示在红方底线 (9, 0) 的下方。
        widget = self.window.board_widget
        self.assertGreater(
            widget.cell_center(0, 0).y(),
            widget.cell_center(9, 0).y(),
        )

        self.window.start_local_game()
        self.assertFalse(self.window.board_widget.flipped)

    def test_online_black_click_uses_logical_coordinates(self) -> None:
        self.window.online_button.click()
        self.window.online_page.apply_auth("token", "甲", 1200)
        self.window.online_page.create_button.click()
        transport = self.online_transports[-1]
        transport.simulate_connected()
        transport.server_send(
            make_message(SERVER_AUTH_OK, AUTH_OK_PAYLOAD)
        )
        transport.server_send(
            make_message(
                SERVER_GAME_STATE,
                online_state(
                    your_side="black",
                    side_to_move="black",
                    players={
                        "red": {"name": "乙", "connected": True},
                        "black": {"name": "甲", "connected": True},
                    },
                ),
            )
        )
        widget = self.window.board_widget
        self.assertTrue(widget.flipped)
        self.assertTrue(widget._interaction_enabled)
        self.window.show()
        APP.processEvents()

        QTest.mouseClick(
            widget,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
            widget.cell_center(3, 0).toPoint(),
        )
        APP.processEvents()
        self.assertEqual(self.window.selected, (3, 0))

        QTest.mouseClick(
            widget,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
            widget.cell_center(4, 0).toPoint(),
        )
        APP.processEvents()
        self.assertEqual(transport.sent[-1]["type"], "move_intent")
        payload = transport.sent[-1]["payload"]
        self.assertEqual(
            (
                payload["from_row"],
                payload["from_col"],
                payload["to_row"],
                payload["to_col"],
            ),
            (3, 0, 4, 0),
        )

    def test_online_undo_request_dialog(self) -> None:
        transport = self._enter_online_game()
        self.window._on_cell_clicked(6, 0)
        self.window._on_cell_clicked(5, 0)
        transport.server_send(
            make_message(
                SERVER_GAME_STATE,
                online_state(side_to_move="black", move_count=1),
            )
        )

        QTimer.singleShot(
            0, lambda: self.window.active_modal().accept()
        )
        transport.server_send(
            make_message(
                SERVER_UNDO_REQUESTED,
                {"name": "乙", "side": "black"},
            )
        )
        self.assertEqual(transport.sent[-1]["type"], "undo_response")
        self.assertTrue(transport.sent[-1]["payload"]["accept"])

    def test_online_resign(self) -> None:
        transport = self._enter_online_game()
        QTimer.singleShot(
            0, lambda: self.window.active_modal().accept()
        )
        self.window._request_restart()
        self.assertEqual(transport.sent[-1]["type"], "resign")

    def test_online_leave_requires_confirmation(self) -> None:
        transport = self._enter_online_game()
        QTimer.singleShot(
            0, lambda: self.window.active_modal().reject()
        )
        self.window.show_main_menu()
        self.assertIs(
            self.window.stack.currentWidget(), self.window.game_page
        )

        QTimer.singleShot(
            0, lambda: self.window.active_modal().accept()
        )
        self.window.show_main_menu()
        self.assertIs(
            self.window.stack.currentWidget(), self.window.online_page
        )
        self.assertTrue(transport.closed)
        self.assertTrue(self.window.online_page.ranked_button.isEnabled())

    def test_ranked_match_ui_and_rating_result(self) -> None:
        transport = self._enter_ranked_game()
        self.assertIs(
            self.window.stack.currentWidget(), self.window.game_page
        )
        self.assertIsInstance(self.window.session, OnlineGameSession)
        self.assertTrue(self.window.session.ranked)
        self.assertIn("排位赛", self.window.local_mode_label.text())
        self.assertIn(
            "1200分", self.window.red_card._status_label.text()
        )
        self.assertIn(
            "1200分", self.window.black_card._status_label.text()
        )

        transport.server_send(
            make_message(
                SERVER_GAME_STATE,
                online_state(
                    status="finished",
                    ranked=True,
                    winner="red",
                    end_reason="resign",
                    move_count=0,
                    players={
                        "red": {
                            "name": "甲",
                            "connected": True,
                            "rating": 1216,
                            "rating_delta": 16,
                        },
                        "black": {
                            "name": "乙",
                            "connected": True,
                            "rating": 1184,
                            "rating_delta": -16,
                        },
                    },
                ),
            )
        )
        self.window._result_timer.stop()
        session = self.window.session
        presentation = self.window._build_result_presentation(
            session.view
        )
        self.assertEqual(presentation.title, "胜利")
        self.assertIn("排位分 +16", presentation.detail)
        self.assertIn("1216分", self.window.red_card._status_label.text())

    def test_online_game_over_saves_record_with_move_history(self) -> None:
        transport = self._enter_ranked_game()
        transport.server_send(
            make_message(
                SERVER_GAME_STATE,
                online_state(
                    status="finished",
                    ranked=True,
                    winner="red",
                    end_reason="resign",
                    move_count=1,
                    side_to_move="black",
                    moves=[
                        {
                            "from_row": 6,
                            "from_col": 0,
                            "to_row": 5,
                            "to_col": 0,
                        }
                    ],
                    players={
                        "red": {
                            "name": "甲",
                            "connected": True,
                            "rating": 1216,
                            "rating_delta": 16,
                        },
                        "black": {
                            "name": "乙",
                            "connected": True,
                            "rating": 1184,
                            "rating_delta": -16,
                        },
                    },
                ),
            )
        )
        self.window._result_timer.stop()
        session = self.window.session
        self.assertIsInstance(session, OnlineGameSession)
        self.assertEqual(len(session.move_history), 1)
        self.assertEqual(self.record_store.count(), 1)
        record = self.record_store.list_recent()[0]
        self.assertEqual(record.mode, "online")
        self.assertTrue(record.rated)
        self.assertIs(record.winner, Side.RED)
        self.assertEqual(record.result_reason, "resign")
        self.assertEqual(len(record.moves), 1)
        self.assertEqual(record.red_name, "甲")
        self.assertEqual(record.black_name, "乙")
        self.assertEqual(record.metadata.get("room_code"), "ABCD")

    def test_social_profile_routes_self_and_others(self) -> None:
        self.window.online_page.apply_auth("token", "甲", 1200)
        calls: list[object] = []

        class FakeOverlay:
            def __init__(
                self,
                api,
                base_url,
                token,
                nickname=None,
                *,
                parent=None,
            ) -> None:
                del api, base_url, token, parent
                calls.append(nickname)
                self.profile = None
                self.avatar_pixmap = None

            def exec(self) -> None:
                return None

            def deleteLater(self) -> None:
                return None

        with patch(
            "xiangqi.client.main_window.ProfileOverlay",
            FakeOverlay,
        ):
            self.window._on_social_profile_requested("甲")
            self.window._on_social_profile_requested("乙")
        self.assertEqual(calls, [None, "乙"])

    def test_challenge_dialog_accept_and_decline(self) -> None:
        self.window.online_page.apply_auth("token", "甲", 1200)
        responses: list[tuple[str, bool]] = []

        def respond(challenge_id, accept):
            responses.append((challenge_id, accept))
            return True

        self.window.online_page.respond_challenge = respond
        QTimer.singleShot(
            0, lambda: self.window.active_modal().accept()
        )
        self.window._on_challenge_received("c1", "好友乙")
        self.assertEqual(responses, [("c1", True)])
        self.assertFalse(self.window._modal_dialog_open)

        QTimer.singleShot(
            0, lambda: self.window.active_modal().reject()
        )
        self.window._on_challenge_received("c2", "好友乙")
        self.assertEqual(responses[-1], ("c2", False))

    def test_social_windows_open_and_reset_modal_state(self) -> None:
        from PySide6.QtCore import QObject, Signal

        self.window.online_page.apply_auth("token", "甲", 1200)

        class FakeOverlay(QObject):
            profile_requested = Signal(str)

            def __init__(self, *args, **kwargs) -> None:
                del args, kwargs
                super().__init__()

            def exec(self) -> None:
                return None

            def deleteLater(self) -> None:
                return None

        with patch(
            "xiangqi.client.main_window.FriendsOverlay",
            FakeOverlay,
        ):
            self.window._open_friends_window()
        self.assertFalse(self.window._modal_dialog_open)

        with patch(
            "xiangqi.client.main_window.LeaderboardOverlay",
            FakeOverlay,
        ):
            self.window._open_leaderboard_window()
        self.assertFalse(self.window._modal_dialog_open)

    def test_online_result_presentation(self) -> None:
        self._enter_online_game()
        session = self.window.session
        self.assertIsInstance(session, OnlineGameSession)
        win_view = BoardView(
            board=GameModel.initial().board,
            side_to_move=Side.BLACK,
            last_move=None,
            is_check=False,
            winner=Side.RED,
            end_reason=EndReason.CHECKMATE,
            is_game_over=True,
            move_count=1,
        )
        win = self.window._build_result_presentation(win_view)
        self.assertEqual(win.kind, "win")
        self.assertEqual(win.title, "胜利")
        self.assertIn("对手：乙", win.subtitle)

        lose_view = BoardView(
            board=GameModel.initial().board,
            side_to_move=Side.RED,
            last_move=None,
            is_check=False,
            winner=Side.BLACK,
            end_reason=EndReason.RESIGN,
            is_game_over=True,
            move_count=4,
        )
        lose = self.window._build_result_presentation(lose_view)
        self.assertEqual(lose.kind, "lose")
        self.assertEqual(lose.title, "惜败")
        self.assertEqual(lose.seal_text, "负")

    # ------------------------------------------------------------------
    # 动效与语音
    # ------------------------------------------------------------------
    def _start_local_with_model(self, model) -> LocalGameSession:
        self.window.start_local_game()
        return self._install_session(model)

    def test_capture_voice_and_effect(self) -> None:
        model = model_with(
            {
                (5, 0): piece(PieceKind.CHARIOT, Side.RED),
                (5, 3): piece(PieceKind.PAWN, Side.BLACK),
            }
        )
        self._start_local_with_model(model)
        self.window._on_cell_clicked(5, 0)
        self.window._on_cell_clicked(5, 3)

        self.assertEqual(self.voice.spoken, ["capture"])
        self.assertEqual(self.window.board_widget.effect_kind, "capture")
        self.assertTrue(self.window.board_widget.is_animating)
        self.assertIn("move", self.audio.played)

    def test_check_voice_and_effect(self) -> None:
        model = model_with(
            {(1, 0): piece(PieceKind.CHARIOT, Side.RED)},
            red_king=(9, 3),
            black_king=(0, 4),
        )
        self._start_local_with_model(model)
        self.window._on_cell_clicked(1, 0)
        self.window._on_cell_clicked(0, 0)

        self.assertEqual(self.voice.spoken, ["check"])
        self.assertEqual(self.window.board_widget.effect_kind, "check")
        self.assertTrue(self.window.session.view.is_check)
        self.assertFalse(self.window.session.view.is_game_over)

    def test_checkmate_voice_effect_and_delayed_result(self) -> None:
        model = model_with(
            {
                (1, 3): piece(PieceKind.CHARIOT, Side.RED),
                (2, 2): piece(PieceKind.HORSE, Side.RED),
                (4, 4): piece(PieceKind.PAWN, Side.RED),
            },
            red_king=(9, 4),
            black_king=(0, 4),
        )
        self._start_local_with_model(model)
        self.window._on_cell_clicked(1, 3)
        self.window._on_cell_clicked(0, 3)

        self.assertTrue(self.window.session.view.is_game_over)
        self.assertEqual(self.voice.spoken, ["checkmate"])
        self.assertEqual(
            self.window.board_widget.effect_kind, "checkmate"
        )
        self.assertGreater(
            self.window.board_widget.effect_remaining_ms(), 1000
        )
        self.assertTrue(self.window._result_timer.isActive())
        self.assertGreater(
            self.window._result_timer.remainingTime(), 1000
        )
        self.assertIsNone(self.window.active_modal())
        self.assertNotIn("win", self.audio.played)
        self.window._result_timer.stop()

    def test_checkmate_result_opens_after_effect(self) -> None:
        model = model_with(
            {
                (1, 3): piece(PieceKind.CHARIOT, Side.RED),
                (2, 2): piece(PieceKind.HORSE, Side.RED),
                (4, 4): piece(PieceKind.PAWN, Side.RED),
            },
            red_king=(9, 4),
            black_king=(0, 4),
        )
        self._start_local_with_model(model)
        started = time.monotonic()
        appeared: list[float] = []

        def poll_result_dialog() -> None:
            modal = self.window.active_modal()
            if modal is not None:
                appeared.append(time.monotonic() - started)
                modal.reject()
                return
            QTimer.singleShot(20, poll_result_dialog)

        QTimer.singleShot(20, poll_result_dialog)
        self.window._on_cell_clicked(1, 3)
        self.window._on_cell_clicked(0, 3)
        QTest.qWait(2400)

        self.assertTrue(appeared)
        self.assertGreaterEqual(appeared[0], 1.4)
        self.assertIsNone(self.window.active_modal())

    def test_close_event_marks_closing(self) -> None:
        self.window.show()
        APP.processEvents()
        self.window.close()
        self.assertTrue(self.window._closing)


if __name__ == "__main__":
    unittest.main()
