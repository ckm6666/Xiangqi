"""将军、飞将、牵制、将死与困毙测试。"""

from __future__ import annotations

import unittest

from tests.helpers import board_with, piece
from xiangqi.shared.rules import (
    EndReason,
    PieceKind,
    Side,
    apply_move_to_board,
    evaluate_status,
    generate_legal_moves,
    is_checkmate,
    is_in_check,
    is_stalemate,
    kings_facing,
    legal_moves_from,
    pseudo_legal_moves_from,
)


class CheckDetectionTests(unittest.TestCase):
    """各兵种将军与飞将。"""

    def test_chariot_check(self) -> None:
        board = board_with(
            {(0, 0): piece(PieceKind.CHARIOT, Side.RED)},
            red_king=(9, 3),
            black_king=(0, 4),
        )
        self.assertTrue(is_in_check(board, Side.BLACK))
        self.assertFalse(is_in_check(board, Side.RED))

    def test_cannon_requires_exactly_one_screen(self) -> None:
        cannon = {(0, 0): piece(PieceKind.CANNON, Side.RED)}
        no_screen = board_with(
            cannon, red_king=(9, 3), black_king=(0, 4)
        )
        one_screen = board_with(
            {
                **cannon,
                (0, 2): piece(PieceKind.PAWN, Side.BLACK),
            },
            red_king=(9, 3),
            black_king=(0, 4),
        )
        two_screens = board_with(
            {
                **cannon,
                (0, 1): piece(PieceKind.PAWN, Side.BLACK),
                (0, 2): piece(PieceKind.PAWN, Side.BLACK),
            },
            red_king=(9, 3),
            black_king=(0, 4),
        )
        self.assertFalse(is_in_check(no_screen, Side.BLACK))
        self.assertTrue(is_in_check(one_screen, Side.BLACK))
        self.assertFalse(is_in_check(two_screens, Side.BLACK))

    def test_horse_check_and_blocked_leg(self) -> None:
        horse = {(2, 3): piece(PieceKind.HORSE, Side.RED)}
        clear = board_with(horse, red_king=(9, 3), black_king=(0, 4))
        blocked = board_with(
            {**horse, (1, 3): piece(PieceKind.PAWN, Side.BLACK)},
            red_king=(9, 3),
            black_king=(0, 4),
        )
        self.assertTrue(is_in_check(clear, Side.BLACK))
        self.assertFalse(is_in_check(blocked, Side.BLACK))

    def test_pawn_check(self) -> None:
        board = board_with(
            {(1, 4): piece(PieceKind.PAWN, Side.RED)},
            red_king=(9, 3),
            black_king=(0, 4),
        )
        self.assertTrue(is_in_check(board, Side.BLACK))

    def test_kings_facing_is_check_for_both_sides(self) -> None:
        board = board_with(red_king=(9, 4), black_king=(0, 4))
        self.assertTrue(kings_facing(board))
        self.assertTrue(is_in_check(board, Side.RED))
        self.assertTrue(is_in_check(board, Side.BLACK))

    def test_kings_facing_blocked_by_piece(self) -> None:
        board = board_with(
            {(4, 4): piece(PieceKind.PAWN, Side.RED)},
            red_king=(9, 4),
            black_king=(0, 4),
        )
        self.assertFalse(kings_facing(board))
        self.assertFalse(is_in_check(board, Side.RED))
        self.assertFalse(is_in_check(board, Side.BLACK))

    def test_king_pseudo_move_includes_flying_general(self) -> None:
        board = board_with(red_king=(9, 4), black_king=(0, 4))
        self.assertIn((0, 4), pseudo_legal_moves_from(board, 9, 4))


class LegalMoveTests(unittest.TestCase):
    """合法着法过滤。"""

    def test_pinned_horse_cannot_leave_file(self) -> None:
        board = board_with(
            {
                (0, 0): piece(PieceKind.CHARIOT, Side.RED),
                (0, 3): piece(PieceKind.HORSE, Side.BLACK),
            },
            red_king=(9, 3),
            black_king=(0, 4),
        )
        self.assertFalse(is_in_check(board, Side.BLACK))
        self.assertEqual(legal_moves_from(board, 0, 3), ())

    def test_king_cannot_move_into_attacked_square(self) -> None:
        board = board_with(
            {(1, 0): piece(PieceKind.CHARIOT, Side.RED)},
            red_king=(9, 3),
            black_king=(0, 4),
        )
        targets = {move.target for move in legal_moves_from(board, 0, 4)}
        # (1,4) 被车控制；(0,3) 与红帅照面；(0,5) 是唯一安全格。
        self.assertEqual(targets, {(0, 5)})

    def test_moving_last_blocker_exposes_flying_general(self) -> None:
        board = board_with(
            {(4, 4): piece(PieceKind.HORSE, Side.BLACK)},
            red_king=(9, 4),
            black_king=(0, 4),
            side=Side.BLACK,
        )
        self.assertFalse(is_in_check(board, Side.BLACK))
        self.assertEqual(legal_moves_from(board, 4, 4), ())
        # 黑将离开中线后仍可活动。
        self.assertTrue(legal_moves_from(board, 0, 4))

    def test_legal_moves_never_leave_own_king_in_check(self) -> None:
        board = board_with(
            {
                (0, 0): piece(PieceKind.CHARIOT, Side.RED),
                (0, 3): piece(PieceKind.HORSE, Side.BLACK),
            },
            red_king=(9, 3),
            black_king=(0, 4),
        )
        for move in generate_legal_moves(board, Side.BLACK):
            next_board = apply_move_to_board(board, move)
            self.assertFalse(is_in_check(next_board, Side.BLACK))


class CheckmateTests(unittest.TestCase):
    """将死判定。"""

    def _checkmate_board(self):
        return board_with(
            {
                (0, 3): piece(PieceKind.CHARIOT, Side.RED),
                (2, 2): piece(PieceKind.HORSE, Side.RED),
                (4, 4): piece(PieceKind.PAWN, Side.RED),
            },
            red_king=(9, 4),
            black_king=(0, 4),
            side=Side.BLACK,
        )

    def test_checkmate_position(self) -> None:
        board = self._checkmate_board()
        self.assertTrue(is_in_check(board, Side.BLACK))
        self.assertTrue(is_checkmate(board, Side.BLACK))
        self.assertFalse(is_stalemate(board, Side.BLACK))
        self.assertEqual(
            evaluate_status(board, Side.BLACK),
            (Side.RED, EndReason.CHECKMATE),
        )

    def test_check_but_not_mate(self) -> None:
        board = board_with(
            {(0, 0): piece(PieceKind.CHARIOT, Side.RED)},
            red_king=(9, 3),
            black_king=(0, 4),
            side=Side.BLACK,
        )
        self.assertTrue(is_in_check(board, Side.BLACK))
        self.assertFalse(is_checkmate(board, Side.BLACK))


class StalemateTests(unittest.TestCase):
    """困毙：无合法着法但未被将军，判负而非和棋。"""

    def _stalemate_board(self):
        return board_with(
            {
                (1, 3): piece(PieceKind.CHARIOT, Side.RED),
                (1, 5): piece(PieceKind.CHARIOT, Side.RED),
                (4, 4): piece(PieceKind.PAWN, Side.RED),
            },
            red_king=(9, 4),
            black_king=(0, 4),
            side=Side.BLACK,
        )

    def test_stalemate_position(self) -> None:
        board = self._stalemate_board()
        self.assertFalse(is_in_check(board, Side.BLACK))
        self.assertFalse(is_checkmate(board, Side.BLACK))
        self.assertTrue(is_stalemate(board, Side.BLACK))
        self.assertEqual(
            evaluate_status(board, Side.BLACK),
            (Side.RED, EndReason.STALEMATE),
        )

    def test_stalemate_is_loss_not_draw(self) -> None:
        board = self._stalemate_board()
        winner, reason = evaluate_status(board, Side.BLACK)
        self.assertIs(winner, Side.RED)
        self.assertIs(reason, EndReason.STALEMATE)


if __name__ == "__main__":
    unittest.main()
