"""AI 引擎测试：合法性、将杀、吃子、评估、快速将军检测。"""

from __future__ import annotations

import random
import unittest
from threading import Event

from tests.helpers import board_with, model_with, piece
from xiangqi.client.ai_engine import (
    AIDifficulty,
    MATE_SCORE,
    SearchConfig,
    _Position,
    evaluate_board,
    is_in_check_fast,
    search_best_move,
)
from xiangqi.shared.game_model import GameModel
from xiangqi.shared.rules import (
    PieceKind,
    Side,
    generate_legal_moves,
    is_in_check,
    is_legal_move,
)


def _config(**overrides) -> SearchConfig:
    base = dict(
        max_depth=2,
        time_limit=1.5,
        node_limit=60_000,
        quiescence_depth=1,
        random_top_k=0,
    )
    base.update(overrides)
    return SearchConfig(**base)


class SearchTests(unittest.TestCase):
    """搜索入口与基本战术。"""

    def test_initial_position_returns_legal_move(self) -> None:
        board = GameModel.initial().board
        for difficulty in AIDifficulty:
            with self.subTest(difficulty=difficulty):
                result = search_best_move(board, Side.RED, difficulty)
                self.assertIsNotNone(result.move)
                assert result.move is not None
                self.assertTrue(
                    is_legal_move(
                        board,
                        Side.RED,
                        result.move.from_row,
                        result.move.from_col,
                        result.move.to_row,
                        result.move.to_col,
                    )
                )

    def test_finds_mate_in_one(self) -> None:
        model = model_with(
            {
                (1, 3): piece(PieceKind.CHARIOT, Side.RED),
                (2, 2): piece(PieceKind.HORSE, Side.RED),
                (4, 4): piece(PieceKind.PAWN, Side.RED),
            },
            red_king=(9, 4),
            black_king=(0, 4),
        )
        result = search_best_move(
            model.board,
            Side.RED,
            config_override=_config(),
        )
        self.assertEqual(result.move.target, (0, 3))
        self.assertGreaterEqual(result.score, MATE_SCORE - 10)

    def test_captures_hanging_chariot(self) -> None:
        board = board_with(
            {
                (5, 0): piece(PieceKind.CHARIOT, Side.RED),
                (5, 4): piece(PieceKind.CHARIOT, Side.BLACK),
            }
        )
        result = search_best_move(
            board,
            Side.RED,
            config_override=_config(),
        )
        self.assertIsNotNone(result.move)
        assert result.move is not None
        self.assertEqual(result.move.target, (5, 4))
        self.assertIsNotNone(result.move.captured)

    def test_no_legal_move_returns_none(self) -> None:
        model = model_with(
            {
                (1, 3): piece(PieceKind.CHARIOT, Side.RED),
                (2, 2): piece(PieceKind.HORSE, Side.RED),
                (4, 4): piece(PieceKind.PAWN, Side.RED),
            },
            red_king=(9, 4),
            black_king=(0, 4),
        )
        self.assertIsNotNone(model.apply_move(1, 3, 0, 3))
        result = search_best_move(
            model.board,
            Side.BLACK,
            config_override=_config(),
        )
        self.assertIsNone(result.move)

    def test_cancel_event_returns_no_move(self) -> None:
        event = Event()
        event.set()
        result = search_best_move(
            GameModel.initial().board,
            Side.RED,
            AIDifficulty.MEDIUM,
            cancel_event=event,
        )
        self.assertIsNone(result.move)


class EvaluationTests(unittest.TestCase):
    """评估与快速将军检测。"""

    def test_material_advantage_is_positive(self) -> None:
        base = board_with(
            {(5, 0): piece(PieceKind.CHARIOT, Side.RED)}
        )
        self.assertGreater(evaluate_board(base, Side.RED), 0)
        self.assertLess(evaluate_board(base, Side.BLACK), 0)
        self.assertEqual(
            evaluate_board(base, Side.RED),
            -evaluate_board(base, Side.BLACK),
        )

    def test_fast_check_matches_shared_rules(self) -> None:
        random.seed(11)
        model = GameModel.initial()
        for _ in range(50):
            for side in Side:
                self.assertEqual(
                    is_in_check_fast(model.board, side),
                    is_in_check(model.board, side),
                    msg=f"ply={model.move_count} side={side}",
                )
            if model.is_game_over:
                break
            moves = model.all_legal_moves()
            if not moves:
                break
            move = random.choice(moves)
            self.assertIsNotNone(
                model.apply_move(
                    move.from_row,
                    move.from_col,
                    move.to_row,
                    move.to_col,
                )
            )

    def test_fast_check_detects_flying_general(self) -> None:
        board = board_with(red_king=(9, 4), black_king=(0, 4))
        self.assertTrue(is_in_check_fast(board, Side.RED))
        self.assertTrue(is_in_check_fast(board, Side.BLACK))

    def test_fast_check_cannon_screen(self) -> None:
        board = board_with(
            {
                (0, 0): piece(PieceKind.CANNON, Side.RED),
                (0, 2): piece(PieceKind.PAWN, Side.RED),
            },
            red_king=(9, 3),
            black_king=(0, 4),
        )
        self.assertTrue(is_in_check_fast(board, Side.BLACK))

    def test_legal_move_generation_matches_shared_rules(self) -> None:
        random.seed(23)
        model = GameModel.initial()
        for _ in range(40):
            position = _Position(model.board)
            for side in Side:
                ai_moves = {
                    (from_index, to_index)
                    for from_index, to_index, _ in position.legal_moves(side)
                }
                shared_moves = {
                    (
                        move.from_row * 9 + move.from_col,
                        move.to_row * 9 + move.to_col,
                    )
                    for move in generate_legal_moves(model.board, side)
                }
                self.assertEqual(
                    ai_moves,
                    shared_moves,
                    msg=f"ply={model.move_count} side={side}",
                )
            if model.is_game_over:
                break
            moves = model.all_legal_moves()
            if not moves:
                break
            move = random.choice(moves)
            self.assertIsNotNone(
                model.apply_move(
                    move.from_row,
                    move.from_col,
                    move.to_row,
                    move.to_col,
                )
            )


if __name__ == "__main__":
    unittest.main()
