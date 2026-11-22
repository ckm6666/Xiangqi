"""棋子走法测试：车、马、炮、相、仕、兵/卒、将/帅。"""

from __future__ import annotations

import unittest

from tests.helpers import board_with, piece
from xiangqi.shared.rules import (
    BOARD_COLS,
    BOARD_ROWS,
    PieceKind,
    Side,
    generate_pseudo_legal_moves,
    in_bounds,
    initial_board,
    pseudo_legal_moves_from,
)


class InitialBoardTests(unittest.TestCase):
    """标准初始局面。"""

    def test_dimensions_and_piece_count(self) -> None:
        board = initial_board()
        self.assertEqual(len(board), BOARD_ROWS)
        self.assertTrue(all(len(row) == BOARD_COLS for row in board))
        pieces = [cell for row in board for cell in row if cell is not None]
        self.assertEqual(len(pieces), 32)
        self.assertEqual(
            sum(1 for cell in pieces if cell.side is Side.RED), 16
        )
        self.assertEqual(
            sum(1 for cell in pieces if cell.side is Side.BLACK), 16
        )

    def test_back_rank_layout(self) -> None:
        board = initial_board()
        self.assertEqual(
            "".join(board[0][col].glyph for col in range(9)), "車馬象士將士象馬車"
        )
        self.assertEqual(
            "".join(board[9][col].glyph for col in range(9)), "車馬相仕帥仕相馬車"
        )
        self.assertEqual(board[2][1].glyph, "砲")
        self.assertEqual(board[2][7].glyph, "砲")
        self.assertEqual(board[7][1].glyph, "炮")
        self.assertEqual(board[7][7].glyph, "炮")
        for col in (0, 2, 4, 6, 8):
            self.assertEqual(board[3][col].glyph, "卒")
            self.assertEqual(board[6][col].glyph, "兵")

    def test_piece_code_round_trip(self) -> None:
        for kind in PieceKind:
            for side in Side:
                original = piece(kind, side)
                self.assertEqual(original, type(original).from_code(original.code))


class KingTests(unittest.TestCase):
    """将/帅的九宫限制与飞将。"""

    def test_king_steps_inside_palace(self) -> None:
        board = board_with(red_king=(9, 4))
        targets = set(pseudo_legal_moves_from(board, 9, 4))
        self.assertEqual(targets, {(8, 4), (9, 3), (9, 5)})

    def test_king_cannot_leave_palace(self) -> None:
        board = board_with(red_king=(8, 3))
        targets = set(pseudo_legal_moves_from(board, 8, 3))
        # 向左、向下都会离开九宫；向上、向右仍在九宫。
        self.assertNotIn((8, 2), targets)
        self.assertNotIn((9, 2), targets)
        self.assertIn((7, 3), targets)
        self.assertIn((8, 4), targets)

    def test_black_king_moves(self) -> None:
        board = board_with(black_king=(0, 4))
        targets = set(pseudo_legal_moves_from(board, 0, 4))
        self.assertEqual(targets, {(0, 3), (0, 5), (1, 4)})

    def test_flying_general_capture_when_file_is_open(self) -> None:
        board = board_with(red_king=(9, 4), black_king=(0, 4))
        targets = set(pseudo_legal_moves_from(board, 9, 4))
        self.assertIn((0, 4), targets)

    def test_flying_general_blocked_by_piece(self) -> None:
        board = board_with(
            {(4, 4): piece(PieceKind.PAWN, Side.RED)},
            red_king=(9, 4),
            black_king=(0, 4),
        )
        targets = set(pseudo_legal_moves_from(board, 9, 4))
        self.assertNotIn((0, 4), targets)


class AdvisorTests(unittest.TestCase):
    """仕/士只走九宫内的斜线。"""

    def test_advisor_diagonal_inside_palace(self) -> None:
        board = board_with({(8, 4): piece(PieceKind.ADVISOR, Side.RED)})
        targets = set(pseudo_legal_moves_from(board, 8, 4))
        self.assertEqual(targets, {(7, 3), (7, 5), (9, 5)})

    def test_advisor_cannot_leave_palace(self) -> None:
        board = board_with({(7, 4): piece(PieceKind.ADVISOR, Side.RED)})
        targets = set(pseudo_legal_moves_from(board, 7, 4))
        self.assertEqual(targets, {(8, 3), (8, 5)})

    def test_black_advisor(self) -> None:
        board = board_with(
            {(1, 4): piece(PieceKind.ADVISOR, Side.BLACK)},
            black_king=(0, 4),
        )
        targets = set(pseudo_legal_moves_from(board, 1, 4))
        self.assertEqual(targets, {(0, 3), (0, 5), (2, 3), (2, 5)})


class ElephantTests(unittest.TestCase):
    """相/象走田、塞象眼、不过河。"""

    def test_elephant_targets(self) -> None:
        board = board_with({(7, 4): piece(PieceKind.ELEPHANT, Side.RED)})
        targets = set(pseudo_legal_moves_from(board, 7, 4))
        self.assertEqual(targets, {(5, 2), (5, 6), (9, 2), (9, 6)})

    def test_elephant_eye_blocks(self) -> None:
        board = board_with(
            {
                (7, 4): piece(PieceKind.ELEPHANT, Side.RED),
                (6, 3): piece(PieceKind.PAWN, Side.RED),
            }
        )
        targets = set(pseudo_legal_moves_from(board, 7, 4))
        self.assertNotIn((5, 2), targets)
        self.assertIn((5, 6), targets)

    def test_red_elephant_cannot_cross_river(self) -> None:
        board = board_with({(5, 4): piece(PieceKind.ELEPHANT, Side.RED)})
        targets = set(pseudo_legal_moves_from(board, 5, 4))
        self.assertEqual(targets, {(7, 2), (7, 6)})

    def test_black_elephant_cannot_cross_river(self) -> None:
        board = board_with({(4, 4): piece(PieceKind.ELEPHANT, Side.BLACK)})
        targets = set(pseudo_legal_moves_from(board, 4, 4))
        self.assertEqual(targets, {(2, 2), (2, 6)})


class HorseTests(unittest.TestCase):
    """马的日字走法与蹩马腿。"""

    def test_horse_all_eight_moves(self) -> None:
        board = board_with({(5, 4): piece(PieceKind.HORSE, Side.RED)})
        targets = set(pseudo_legal_moves_from(board, 5, 4))
        self.assertEqual(
            targets,
            {
                (3, 3),
                (3, 5),
                (4, 2),
                (4, 6),
                (6, 2),
                (6, 6),
                (7, 3),
                (7, 5),
            },
        )

    def test_horse_leg_blocks_two_moves(self) -> None:
        board = board_with(
            {
                (5, 4): piece(PieceKind.HORSE, Side.RED),
                (4, 4): piece(PieceKind.PAWN, Side.BLACK),
            }
        )
        targets = set(pseudo_legal_moves_from(board, 5, 4))
        self.assertNotIn((3, 3), targets)
        self.assertNotIn((3, 5), targets)
        self.assertIn((4, 2), targets)

    def test_horse_horizontal_leg_block(self) -> None:
        board = board_with(
            {
                (5, 4): piece(PieceKind.HORSE, Side.RED),
                (5, 5): piece(PieceKind.PAWN, Side.RED),
            }
        )
        targets = set(pseudo_legal_moves_from(board, 5, 4))
        self.assertNotIn((4, 6), targets)
        self.assertNotIn((6, 6), targets)
        self.assertIn((3, 5), targets)

    def test_horse_cannot_capture_own_piece(self) -> None:
        board = board_with(
            {
                (5, 4): piece(PieceKind.HORSE, Side.RED),
                (3, 3): piece(PieceKind.PAWN, Side.RED),
                (3, 5): piece(PieceKind.PAWN, Side.BLACK),
            }
        )
        targets = set(pseudo_legal_moves_from(board, 5, 4))
        self.assertNotIn((3, 3), targets)
        self.assertIn((3, 5), targets)


class ChariotTests(unittest.TestCase):
    """车的直线滑行与阻挡。"""

    def test_chariot_moves_on_open_board(self) -> None:
        board = board_with({(5, 4): piece(PieceKind.CHARIOT, Side.RED)})
        targets = set(pseudo_legal_moves_from(board, 5, 4))
        self.assertEqual(len(targets), 17)
        self.assertIn((0, 4), targets)
        self.assertIn((9, 4), targets)
        self.assertIn((5, 0), targets)
        self.assertIn((5, 8), targets)

    def test_chariot_stops_before_own_piece(self) -> None:
        board = board_with(
            {
                (5, 4): piece(PieceKind.CHARIOT, Side.RED),
                (5, 6): piece(PieceKind.PAWN, Side.RED),
            }
        )
        targets = set(pseudo_legal_moves_from(board, 5, 4))
        self.assertIn((5, 5), targets)
        self.assertNotIn((5, 6), targets)
        self.assertNotIn((5, 7), targets)

    def test_chariot_captures_first_enemy_and_stops(self) -> None:
        board = board_with(
            {
                (5, 4): piece(PieceKind.CHARIOT, Side.RED),
                (5, 7): piece(PieceKind.PAWN, Side.BLACK),
            }
        )
        targets = set(pseudo_legal_moves_from(board, 5, 4))
        self.assertIn((5, 5), targets)
        self.assertIn((5, 6), targets)
        self.assertIn((5, 7), targets)
        self.assertNotIn((5, 8), targets)

    def test_chariot_cannot_jump(self) -> None:
        board = board_with(
            {
                (5, 4): piece(PieceKind.CHARIOT, Side.RED),
                (5, 5): piece(PieceKind.PAWN, Side.RED),
                (5, 6): piece(PieceKind.PAWN, Side.BLACK),
            }
        )
        targets = set(pseudo_legal_moves_from(board, 5, 4))
        self.assertNotIn((5, 5), targets)
        self.assertNotIn((5, 6), targets)


class CannonTests(unittest.TestCase):
    """炮的炮架规则。"""

    def test_cannon_moves_without_screen(self) -> None:
        board = board_with({(5, 4): piece(PieceKind.CANNON, Side.RED)})
        targets = set(pseudo_legal_moves_from(board, 5, 4))
        self.assertEqual(len(targets), 17)

    def test_cannon_cannot_capture_without_screen(self) -> None:
        board = board_with(
            {
                (5, 4): piece(PieceKind.CANNON, Side.RED),
                (5, 7): piece(PieceKind.PAWN, Side.BLACK),
            }
        )
        targets = set(pseudo_legal_moves_from(board, 5, 4))
        self.assertIn((5, 5), targets)
        self.assertIn((5, 6), targets)
        self.assertNotIn((5, 7), targets)

    def test_cannon_captures_with_exactly_one_screen(self) -> None:
        board = board_with(
            {
                (5, 4): piece(PieceKind.CANNON, Side.RED),
                (5, 5): piece(PieceKind.PAWN, Side.RED),
                (5, 7): piece(PieceKind.PAWN, Side.BLACK),
            }
        )
        targets = set(pseudo_legal_moves_from(board, 5, 4))
        self.assertNotIn((5, 5), targets)
        self.assertNotIn((5, 6), targets)
        self.assertIn((5, 7), targets)

    def test_cannon_stops_at_two_screens(self) -> None:
        board = board_with(
            {
                (5, 4): piece(PieceKind.CANNON, Side.RED),
                (5, 5): piece(PieceKind.PAWN, Side.RED),
                (5, 6): piece(PieceKind.PAWN, Side.BLACK),
                (5, 7): piece(PieceKind.PAWN, Side.BLACK),
            }
        )
        targets = set(pseudo_legal_moves_from(board, 5, 4))
        self.assertIn((5, 6), targets)
        self.assertNotIn((5, 7), targets)

    def test_cannon_cannot_capture_screen_itself(self) -> None:
        board = board_with(
            {
                (5, 4): piece(PieceKind.CANNON, Side.RED),
                (5, 5): piece(PieceKind.PAWN, Side.BLACK),
            }
        )
        targets = set(pseudo_legal_moves_from(board, 5, 4))
        self.assertNotIn((5, 5), targets)

    def test_cannon_cannot_capture_own_piece_beyond_screen(self) -> None:
        board = board_with(
            {
                (5, 4): piece(PieceKind.CANNON, Side.RED),
                (5, 5): piece(PieceKind.PAWN, Side.BLACK),
                (5, 7): piece(PieceKind.PAWN, Side.RED),
            }
        )
        targets = set(pseudo_legal_moves_from(board, 5, 4))
        self.assertNotIn((5, 7), targets)


class PawnTests(unittest.TestCase):
    """兵/卒前进与过河横走。"""

    def test_red_pawn_before_river(self) -> None:
        board = board_with({(6, 2): piece(PieceKind.PAWN, Side.RED)})
        targets = set(pseudo_legal_moves_from(board, 6, 2))
        self.assertEqual(targets, {(5, 2)})

    def test_red_pawn_after_river(self) -> None:
        board = board_with({(4, 2): piece(PieceKind.PAWN, Side.RED)})
        targets = set(pseudo_legal_moves_from(board, 4, 2))
        self.assertEqual(targets, {(3, 2), (4, 1), (4, 3)})

    def test_red_pawn_on_last_rank_moves_sideways(self) -> None:
        board = board_with({(0, 2): piece(PieceKind.PAWN, Side.RED)})
        targets = set(pseudo_legal_moves_from(board, 0, 2))
        self.assertEqual(targets, {(0, 1), (0, 3)})

    def test_black_pawn_before_river(self) -> None:
        board = board_with({(3, 2): piece(PieceKind.PAWN, Side.BLACK)})
        targets = set(pseudo_legal_moves_from(board, 3, 2))
        self.assertEqual(targets, {(4, 2)})

    def test_black_pawn_after_river(self) -> None:
        board = board_with({(5, 2): piece(PieceKind.PAWN, Side.BLACK)})
        targets = set(pseudo_legal_moves_from(board, 5, 2))
        self.assertEqual(targets, {(6, 2), (5, 1), (5, 3)})

    def test_black_pawn_on_last_rank_moves_sideways(self) -> None:
        board = board_with(
            {(9, 2): piece(PieceKind.PAWN, Side.BLACK)},
            red_king=(7, 3),
        )
        targets = set(pseudo_legal_moves_from(board, 9, 2))
        self.assertEqual(targets, {(9, 1), (9, 3)})


class GenerationTests(unittest.TestCase):
    """整体生成约束。"""

    def test_all_targets_are_in_bounds(self) -> None:
        board = initial_board()
        for row in range(BOARD_ROWS):
            for col in range(BOARD_COLS):
                for target in pseudo_legal_moves_from(board, row, col):
                    self.assertTrue(in_bounds(*target))

    def test_generate_only_requested_side(self) -> None:
        board = initial_board()
        moves = generate_pseudo_legal_moves(board, Side.RED)
        self.assertTrue(moves)
        for move in moves:
            self.assertIs(board[move.from_row][move.from_col].side, Side.RED)
            self.assertIs(board[move.to_row][move.to_col], move.captured)


if __name__ == "__main__":
    unittest.main()
