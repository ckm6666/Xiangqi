"""GameModel 生命周期与终局语义测试。"""

from __future__ import annotations

import unittest

from tests.helpers import model_with, piece
from xiangqi.shared.game_model import GameModel
from xiangqi.shared.rules import (
    EndReason,
    Move,
    PieceKind,
    Side,
)


class InitialStateTests(unittest.TestCase):
    """初始局面只读状态。"""

    def test_initial_state(self) -> None:
        model = GameModel.initial()
        self.assertIs(model.side_to_move, Side.RED)
        self.assertEqual(model.move_count, 0)
        self.assertIsNone(model.last_move)
        self.assertIsNone(model.winner)
        self.assertIsNone(model.end_reason)
        self.assertFalse(model.is_game_over)
        self.assertFalse(model.is_check)
        self.assertIs(model.board[9][4].kind, PieceKind.KING)
        self.assertIs(model.board[9][4].side, Side.RED)
        self.assertIs(model.board[0][4].side, Side.BLACK)
        pieces = [cell for row in model.board for cell in row if cell is not None]
        self.assertEqual(len(pieces), 32)

    def test_initial_pawn_move(self) -> None:
        model = GameModel.initial()
        move = model.apply_move(6, 0, 5, 0)
        self.assertIsNotNone(move)
        assert move is not None
        self.assertEqual(move.origin, (6, 0))
        self.assertEqual(move.target, (5, 0))
        self.assertIsNone(move.captured)
        self.assertIs(model.side_to_move, Side.BLACK)
        self.assertEqual(model.move_count, 1)
        self.assertEqual(model.last_move, move)
        self.assertIs(model.board[5][0].side, Side.RED)
        self.assertIsNone(model.board[6][0])

    def test_reject_wrong_side_occupied_and_out_of_bounds(self) -> None:
        model = GameModel.initial()
        self.assertIsNone(model.apply_move(3, 0, 4, 0))  # 黑方棋子，红方回合
        self.assertIsNone(model.apply_move(9, 0, 9, 1))  # 目标被己方马占据
        self.assertIsNone(model.apply_move(6, 0, -1, 0))  # 越界
        self.assertEqual(model.move_count, 0)
        self.assertIs(model.side_to_move, Side.RED)


class CaptureAndCheckTests(unittest.TestCase):
    """吃子、送将拒绝与将军状态。"""

    def test_capture_records_captured_piece(self) -> None:
        model = model_with(
            {
                (5, 0): piece(PieceKind.CHARIOT, Side.RED),
                (5, 3): piece(PieceKind.PAWN, Side.BLACK),
            }
        )
        move = model.apply_move(5, 0, 5, 3)
        self.assertIsNotNone(move)
        assert move is not None
        self.assertIsNotNone(move.captured)
        self.assertIs(move.captured.kind, PieceKind.PAWN)
        self.assertIs(move.captured.side, Side.BLACK)
        self.assertIs(model.board[5][3].side, Side.RED)

    def test_move_exposing_own_king_is_rejected(self) -> None:
        model = model_with(
            {(4, 4): piece(PieceKind.CHARIOT, Side.RED)},
            red_king=(9, 4),
            black_king=(0, 4),
        )
        self.assertIsNone(model.apply_move(4, 4, 4, 3))
        self.assertEqual(model.move_count, 0)

    def test_is_check_property(self) -> None:
        model = model_with(
            {(9, 8): piece(PieceKind.CHARIOT, Side.BLACK)},
            red_king=(9, 3),
            black_king=(0, 5),
        )
        self.assertTrue(model.is_check)

    def test_all_legal_moves_belong_to_side_to_move(self) -> None:
        model = GameModel.initial()
        moves = model.all_legal_moves()
        self.assertTrue(moves)
        for move in moves:
            self.assertIs(model.board[move.from_row][move.from_col].side, Side.RED)


class CheckmateAndStalemateTests(unittest.TestCase):
    """将死/困毙后的终局状态与悔棋恢复。"""

    def test_checkmate_ends_game(self) -> None:
        model = model_with(
            {
                (1, 3): piece(PieceKind.CHARIOT, Side.RED),
                (2, 2): piece(PieceKind.HORSE, Side.RED),
                (4, 4): piece(PieceKind.PAWN, Side.RED),
            },
            red_king=(9, 4),
            black_king=(0, 4),
        )
        move = model.apply_move(1, 3, 0, 3)
        self.assertIsNotNone(move)
        self.assertIs(model.side_to_move, Side.BLACK)
        self.assertTrue(model.is_game_over)
        self.assertTrue(model.is_checkmate)
        self.assertFalse(model.is_stalemate)
        self.assertIs(model.winner, Side.RED)
        self.assertIs(model.end_reason, EndReason.CHECKMATE)
        self.assertIsNone(model.apply_move(0, 4, 0, 5))

        self.assertTrue(model.undo())
        self.assertFalse(model.is_game_over)
        self.assertIsNone(model.winner)
        self.assertIsNone(model.end_reason)
        self.assertIs(model.side_to_move, Side.RED)
        self.assertEqual(model.move_count, 0)

    def test_stalemate_ends_game_as_loss(self) -> None:
        model = model_with(
            {
                (1, 3): piece(PieceKind.CHARIOT, Side.RED),
                (2, 5): piece(PieceKind.CHARIOT, Side.RED),
                (4, 4): piece(PieceKind.PAWN, Side.RED),
            },
            red_king=(9, 4),
            black_king=(0, 4),
        )
        move = model.apply_move(2, 5, 1, 5)
        self.assertIsNotNone(move)
        self.assertTrue(model.is_game_over)
        self.assertFalse(model.is_checkmate)
        self.assertTrue(model.is_stalemate)
        self.assertIs(model.winner, Side.RED)
        self.assertIs(model.end_reason, EndReason.STALEMATE)


class UndoResetTests(unittest.TestCase):
    """悔棋与重置。"""

    def test_undo_normal_move(self) -> None:
        model = GameModel.initial()
        model.apply_move(6, 0, 5, 0)
        self.assertTrue(model.undo())
        self.assertIs(model.side_to_move, Side.RED)
        self.assertEqual(model.move_count, 0)
        self.assertIs(model.board[6][0].side, Side.RED)
        self.assertIsNone(model.board[5][0])

    def test_undo_capture_restores_piece(self) -> None:
        model = model_with(
            {
                (5, 0): piece(PieceKind.CHARIOT, Side.RED),
                (5, 3): piece(PieceKind.PAWN, Side.BLACK),
            }
        )
        model.apply_move(5, 0, 5, 3)
        self.assertTrue(model.undo())
        self.assertIs(model.board[5][3].side, Side.BLACK)
        self.assertIs(model.board[5][3].kind, PieceKind.PAWN)
        self.assertIs(model.board[5][0].side, Side.RED)
        self.assertIs(model.side_to_move, Side.RED)

    def test_undo_empty_history_returns_false(self) -> None:
        self.assertFalse(GameModel.initial().undo())

    def test_reset(self) -> None:
        model = GameModel.initial()
        model.apply_move(6, 0, 5, 0)
        model.apply_move(3, 0, 4, 0)
        model.reset()
        self.assertIs(model.side_to_move, Side.RED)
        self.assertEqual(model.move_count, 0)
        self.assertIsNone(model.winner)
        self.assertIs(model.board[6][0].side, Side.RED)
        self.assertIs(model.board[3][0].side, Side.BLACK)


class SetupAndReplayTests(unittest.TestCase):
    """from_setup 校验与 from_moves 重建。"""

    def test_from_setup_requires_one_king_per_side(self) -> None:
        with self.assertRaises(ValueError):
            GameModel.from_setup(
                {(9, 4): piece(PieceKind.KING, Side.RED)},
                Side.RED,
            )

    def test_from_setup_rejects_out_of_bounds(self) -> None:
        with self.assertRaises(ValueError):
            GameModel.from_setup(
                {
                    (9, 4): piece(PieceKind.KING, Side.RED),
                    (0, 4): piece(PieceKind.KING, Side.BLACK),
                    (10, 0): piece(PieceKind.PAWN, Side.RED),
                },
                Side.RED,
            )

    def test_from_setup_rejects_non_piece(self) -> None:
        with self.assertRaises(ValueError):
            GameModel.from_setup(
                {
                    (9, 4): piece(PieceKind.KING, Side.RED),
                    (0, 4): piece(PieceKind.KING, Side.BLACK),
                    (5, 5): "not-a-piece",  # type: ignore[dict-item]
                },
                Side.RED,
            )

    def test_from_moves_rebuilds_position(self) -> None:
        moves = [
            Move(6, 0, 5, 0),
            Move(3, 0, 4, 0),
            Move(6, 2, 5, 2),
        ]
        model = GameModel.from_moves(moves)
        self.assertEqual(model.move_count, 3)
        self.assertIs(model.side_to_move, Side.BLACK)
        self.assertIs(model.board[5][0].side, Side.RED)
        self.assertIs(model.board[4][0].side, Side.BLACK)
        self.assertIs(model.board[5][2].side, Side.RED)

    def test_from_moves_rejects_illegal_history(self) -> None:
        with self.assertRaises(ValueError) as context:
            GameModel.from_moves([Move(6, 0, 4, 0)])
        self.assertIn("第 1 手", str(context.exception))

    def test_from_moves_rejects_non_move(self) -> None:
        with self.assertRaises(ValueError):
            GameModel.from_moves([object()])  # type: ignore[list-item]


if __name__ == "__main__":
    unittest.main()
