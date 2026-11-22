"""占位模块与协议基础测试。"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tests.qt_helpers import ensure_qt_app

ensure_qt_app()

from xiangqi.client.ai_engine import (  # noqa: E402
    AIDifficulty,
    SearchResult,
    search_best_move,
)
from xiangqi.client.puzzle_bank import load_puzzle_bank  # noqa: E402
from xiangqi.client.records import LocalRecordStore  # noqa: E402
from xiangqi.client.replay import ReplayTimeline  # noqa: E402
from xiangqi.client.replay_panel import ReplayPanel  # noqa: E402
from xiangqi.client.transport import Transport  # noqa: E402
from xiangqi.client.voice import VOICE_TEXTS, VoiceAnnouncer  # noqa: E402
from xiangqi.shared.achievements import (  # noqa: E402
    evaluate_achievements,
    normalize_achievement_keys,
)
from xiangqi.shared.errors import ProtocolError, RecordError  # noqa: E402
from xiangqi.shared.protocol import (  # noqa: E402
    CLIENT_MOVE_INTENT,
    PROTOCOL_VERSION,
    make_message,
    parse_message,
)
from xiangqi.shared.profile import (  # noqa: E402
    PlayerStats,
    next_title,
    title_for_rating,
)
from xiangqi.shared.puzzle import Puzzle  # noqa: E402
from xiangqi.shared.record import GameRecord  # noqa: E402
from xiangqi.shared.game_model import GameModel  # noqa: E402
from xiangqi.shared.rules import Move, Side  # noqa: E402


class ProtocolTests(unittest.TestCase):
    """协议信封。"""

    def test_round_trip(self) -> None:
        message = make_message(
            CLIENT_MOVE_INTENT,
            {"from_row": 6, "from_col": 0, "to_row": 5, "to_col": 0},
            "req-1",
        )
        self.assertEqual(message["protocol"], PROTOCOL_VERSION)
        message_type, payload, request_id = parse_message(message)
        self.assertEqual(message_type, CLIENT_MOVE_INTENT)
        self.assertEqual(payload["from_row"], 6)
        self.assertEqual(request_id, "req-1")

    def test_rejects_invalid_envelopes(self) -> None:
        with self.assertRaises(ProtocolError):
            make_message("unknown_type")
        with self.assertRaises(ProtocolError):
            parse_message({"protocol": 99, "type": CLIENT_MOVE_INTENT})
        with self.assertRaises(ProtocolError):
            parse_message("not-a-dict")
        with self.assertRaises(ProtocolError):
            parse_message(
                {"protocol": PROTOCOL_VERSION, "type": "unknown_type"}
            )


def sample_record(record_id: str = "r1") -> GameRecord:
    return GameRecord(
        record_id=record_id,
        created_at="2026-11-22T12:00:00+08:00",
        mode="online",
        moves=(Move(6, 0, 5, 0), Move(3, 0, 4, 0)),
        winner=Side.RED,
        result_reason="resign",
        red_name="甲",
        black_name="乙",
        rated=True,
        metadata={"room_code": "ABCD"},
    )


class RecordTests(unittest.TestCase):
    """棋谱序列化与 JSONL 存储。"""

    def test_record_round_trip(self) -> None:
        record = sample_record()
        data = record.to_dict()
        self.assertEqual(data["version"], 1)
        self.assertEqual(len(data["moves"]), 2)
        restored = GameRecord.from_dict(data)
        self.assertEqual(restored, record)

    def test_record_rejects_invalid_data(self) -> None:
        with self.assertRaises(RecordError):
            GameRecord.from_dict({})
        data = sample_record().to_dict()
        data["moves"] = [{"from_row": 99}]
        with self.assertRaises(RecordError):
            GameRecord.from_dict(data)

    def test_local_record_store_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = LocalRecordStore(Path(directory), max_records=2)
            self.assertEqual(store.path, Path(directory) / "games.jsonl")
            first = sample_record("r1")
            store.append(first)
            self.assertEqual(store.list_recent(), (first,))
            self.assertEqual(store.load("r1"), first)
            self.assertEqual(store.count(), 1)

            store.append(sample_record("r2"))
            store.append(sample_record("r3"))
            self.assertEqual(store.count(), 2)
            ids = [record.record_id for record in store.list_recent()]
            self.assertEqual(ids, ["r3", "r2"])

    def test_store_skips_corrupt_lines(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = LocalRecordStore(Path(directory))
            store.append(sample_record("good"))
            with store.path.open("a", encoding="utf-8") as handle:
                handle.write("not-json\n")
            records = store.list_recent()
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0].record_id, "good")

    def test_default_store_directory_is_under_xiangqi(self) -> None:
        store = LocalRecordStore()
        parts = store.directory.parts
        self.assertIn("Xiangqi", parts)
        self.assertEqual(store.directory.name, "records")


class OtherStubTests(unittest.TestCase):
    """题库、成就、AI、传输与面板占位。"""

    def test_puzzle_dataclass(self) -> None:
        puzzle = Puzzle("p1", "单车擒王")
        self.assertEqual(puzzle.puzzle_id, "p1")
        self.assertEqual(puzzle.description, "")
        self.assertEqual(load_puzzle_bank(), ())

    def test_achievements_catalog(self) -> None:
        self.assertEqual(normalize_achievement_keys(["a", "b"]), ())
        self.assertEqual(
            normalize_achievement_keys(["first_win", "first_win"]),
            ("first_win",),
        )
        states = evaluate_achievements(
            wins=10, losses=2, draws=0, best_streak=4, rating=1500
        )
        earned = {item.key for item in states if item.earned}
        self.assertIn("first_game", earned)
        self.assertIn("first_win", earned)
        self.assertIn("wins_10", earned)
        self.assertIn("streak_3", earned)
        self.assertIn("rank_1500", earned)
        self.assertNotIn("wins_50", earned)
        self.assertNotIn("rank_1800", earned)

    def test_titles_and_stats(self) -> None:
        self.assertEqual(title_for_rating(0), "棋童")
        self.assertEqual(title_for_rating(1200), "棋士")
        self.assertEqual(title_for_rating(1450), "上品棋士")
        self.assertEqual(title_for_rating(1800), "大师")
        self.assertEqual(title_for_rating(2600), "棋圣")
        self.assertEqual(next_title(1199).name, "棋士")
        self.assertEqual(next_title(1450).name, "棋师")
        self.assertIsNone(next_title(2300))
        stats = PlayerStats(wins=3, losses=1, draws=0)
        self.assertEqual(stats.games, 4)
        self.assertEqual(stats.win_rate, 75.0)
        self.assertEqual(stats.record_text, "3胜 0和 1负")

    def test_ai_api(self) -> None:
        self.assertEqual(AIDifficulty.EASY.label, "入门")
        self.assertEqual(AIDifficulty.MASTER.label, "大师")
        self.assertIsInstance(SearchResult(move=None), SearchResult)
        result = search_best_move(
            GameModel.initial().board,
            Side.RED,
            AIDifficulty.EASY,
        )
        self.assertIsNotNone(result.move)

    def test_transport_stub(self) -> None:
        transport = Transport()
        with self.assertRaises(NotImplementedError):
            transport.open("ws://localhost")
        with self.assertRaises(NotImplementedError):
            transport.send_message({})
        with self.assertRaises(NotImplementedError):
            transport.close()
        transport.deleteLater()

    def test_replay_timeline(self) -> None:
        timeline = ReplayTimeline((Move(6, 0, 5, 0), Move(3, 0, 4, 0)))
        self.assertTrue(timeline.at_start)
        self.assertIsNone(timeline.current_move)
        self.assertEqual(timeline.step(1), 1)
        self.assertEqual(timeline.current_move, Move(6, 0, 5, 0))
        self.assertEqual(timeline.step(5), 2)
        self.assertTrue(timeline.at_end)
        self.assertEqual(timeline.frame().board[5][0].kind.name, "PAWN")
        self.assertEqual(timeline.frame(0).move_count, 0)
        self.assertEqual(timeline.frame(1).move_count, 1)
        timeline.reset()
        self.assertTrue(timeline.at_start)

    def test_placeholder_replay_panel(self) -> None:
        replay = ReplayPanel()
        self.assertEqual(replay.objectName(), "replayPanel")
        replay.deleteLater()

    def test_voice_texts_and_offscreen_disable(self) -> None:
        self.assertEqual(VOICE_TEXTS["check"], "将军")
        self.assertEqual(VOICE_TEXTS["capture"], "吃")
        self.assertEqual(VOICE_TEXTS["checkmate"], "绝杀")
        announcer = VoiceAnnouncer()
        self.assertFalse(announcer.available)
        announcer.say("check")
        announcer.shutdown()


if __name__ == "__main__":
    unittest.main()
