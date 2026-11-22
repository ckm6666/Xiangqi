"""中国象棋核心规则：坐标、棋子、走法生成与胜负判定。

本模块完全不依赖 Qt，客户端界面、未来的 AI 与 FastAPI 服务端都复用同一份
规则，避免各端出现规则漂移。

坐标约定：
    * ``row`` 自上而下为 0～9，``col`` 自左向右为 0～8；
    * ``row 0`` 是黑方底线，``row 9`` 是红方底线；
    * 河界位于第 4 行与第 5 行之间：
      黑方半场为 rows 0～4，红方半场为 rows 5～9；
    * 九宫：黑方 rows 0～2、红方 rows 7～9，列均为 cols 3～5；
    * 红方先行，红方前进为 ``row - 1``，黑方前进为 ``row + 1``。

规则要点：
    * 将/帅不得出九宫，同列且中间无子时可“飞将”吃对方将/帅；
    * 仕/士只在九宫内斜走一步；相/象走田字且象眼不得被塞、不得过河；
    * 马走日字且马腿不得被蹩；车直线滑行；炮吃子必须恰隔一个炮架；
    * 兵/卒只能向前，过河后可左右移动；
    * 任何走法都不能使己方将/帅处于被将军状态；
    * 困毙（无合法着法且未被将军）判负，不是和棋。

当前版本暂不裁决长将、重复局面与和棋，相关枚举值保留给后续版本。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, IntEnum
from typing import Final, Mapping, Optional, Sequence

# ---------------------------------------------------------------------------
# 棋盘规则常量
# ---------------------------------------------------------------------------
BOARD_ROWS: Final[int] = 10
BOARD_COLS: Final[int] = 9

RIVER_TOP_ROW: Final[int] = 4  # 黑方半场最后一行
RIVER_BOTTOM_ROW: Final[int] = 5  # 红方半场第一行

PALACE_COL_MIN: Final[int] = 3
PALACE_COL_MAX: Final[int] = 5
BLACK_PALACE_ROW_MIN: Final[int] = 0
BLACK_PALACE_ROW_MAX: Final[int] = 2
RED_PALACE_ROW_MIN: Final[int] = 7
RED_PALACE_ROW_MAX: Final[int] = 9


class Side(Enum):
    """对弈双方（同时也是棋子颜色）。"""

    RED = "red"
    BLACK = "black"

    @property
    def label(self) -> str:
        """返回适合界面展示的中文名称。"""
        return "红方" if self is Side.RED else "黑方"

    @property
    def opponent(self) -> "Side":
        """返回另一方。"""
        return Side.BLACK if self is Side.RED else Side.RED

    @property
    def forward(self) -> int:
        """前进方向对应的行增量：红方向上（-1），黑方向下（+1）。"""
        return -1 if self is Side.RED else 1


class PieceKind(IntEnum):
    """棋子种类。整数值便于未来 AI 使用紧凑编码。"""

    KING = 1
    ADVISOR = 2
    ELEPHANT = 3
    HORSE = 4
    CHARIOT = 5
    CANNON = 6
    PAWN = 7

    @property
    def label(self) -> str:
        """通用中文名称（不区分红黑写法）。"""
        return _KIND_LABELS[self]


_KIND_LABELS: dict[PieceKind, str] = {
    PieceKind.KING: "帅",
    PieceKind.ADVISOR: "仕",
    PieceKind.ELEPHANT: "相",
    PieceKind.HORSE: "马",
    PieceKind.CHARIOT: "车",
    PieceKind.CANNON: "炮",
    PieceKind.PAWN: "兵",
}

# 棋面汉字：红方使用帥仕相馬車炮兵，黑方使用將士象馬車砲卒。
_GLYPHS: dict[tuple[Side, PieceKind], str] = {
    (Side.RED, PieceKind.KING): "帥",
    (Side.RED, PieceKind.ADVISOR): "仕",
    (Side.RED, PieceKind.ELEPHANT): "相",
    (Side.RED, PieceKind.HORSE): "馬",
    (Side.RED, PieceKind.CHARIOT): "車",
    (Side.RED, PieceKind.CANNON): "炮",
    (Side.RED, PieceKind.PAWN): "兵",
    (Side.BLACK, PieceKind.KING): "將",
    (Side.BLACK, PieceKind.ADVISOR): "士",
    (Side.BLACK, PieceKind.ELEPHANT): "象",
    (Side.BLACK, PieceKind.HORSE): "馬",
    (Side.BLACK, PieceKind.CHARIOT): "車",
    (Side.BLACK, PieceKind.CANNON): "砲",
    (Side.BLACK, PieceKind.PAWN): "卒",
}


@dataclass(frozen=True, slots=True)
class Piece:
    """一枚不可变棋子。"""

    side: Side
    kind: PieceKind

    @property
    def glyph(self) -> str:
        """棋面汉字。"""
        return _GLYPHS[(self.side, self.kind)]

    @property
    def code(self) -> int:
        """紧凑编码：红方为正、黑方为负，绝对值等于种类编号。"""
        sign = 1 if self.side is Side.RED else -1
        return int(self.kind) * sign

    @classmethod
    def from_code(cls, code: int) -> "Piece":
        """从紧凑编码还原棋子；非法编号抛出 ``ValueError``。"""
        if code == 0:
            raise ValueError("棋子编码不能为 0")
        try:
            kind = PieceKind(abs(code))
        except ValueError as exc:
            raise ValueError(f"未知的棋子编码：{code}") from exc
        return cls(Side.RED if code > 0 else Side.BLACK, kind)


@dataclass(frozen=True, slots=True)
class Move:
    """一手棋的不可变记录。"""

    from_row: int
    from_col: int
    to_row: int
    to_col: int
    captured: Optional[Piece] = None

    @property
    def origin(self) -> tuple[int, int]:
        """起点坐标。"""
        return (self.from_row, self.from_col)

    @property
    def target(self) -> tuple[int, int]:
        """终点坐标。"""
        return (self.to_row, self.to_col)


class EndReason(Enum):
    """对局结束原因。"""

    CHECKMATE = "checkmate"
    STALEMATE = "stalemate"
    REPETITION = "repetition"
    DRAW = "draw"
    RESIGN = "resign"
    TIMEOUT = "timeout"

    @property
    def label(self) -> str:
        """返回界面使用的中文名称。"""
        return _END_REASON_LABELS[self]


_END_REASON_LABELS: dict[EndReason, str] = {
    EndReason.CHECKMATE: "将死",
    EndReason.STALEMATE: "困毙",
    EndReason.REPETITION: "重复局面",
    EndReason.DRAW: "和棋",
    EndReason.RESIGN: "认输",
    EndReason.TIMEOUT: "超时",
}

Square = tuple[int, int]
Cell = Optional[Piece]
Board = tuple[tuple[Cell, ...], ...]
BoardLike = Sequence[Sequence[Cell]]

_ORTHOGONAL_STEPS: Final[tuple[tuple[int, int], ...]] = (
    (-1, 0),
    (1, 0),
    (0, -1),
    (0, 1),
)
_DIAGONAL_STEPS: Final[tuple[tuple[int, int], ...]] = (
    (-1, -1),
    (-1, 1),
    (1, -1),
    (1, 1),
)
_HORSE_STEPS: Final[tuple[tuple[int, int], ...]] = (
    (-2, -1),
    (-2, 1),
    (-1, -2),
    (-1, 2),
    (1, -2),
    (1, 2),
    (2, -1),
    (2, 1),
)


# ---------------------------------------------------------------------------
# 基础几何与棋盘
# ---------------------------------------------------------------------------
def in_bounds(row: int, col: int) -> bool:
    """判断坐标是否位于 10×9 棋盘内。"""
    return 0 <= row < BOARD_ROWS and 0 <= col < BOARD_COLS


def in_palace(side: Side, row: int, col: int) -> bool:
    """判断坐标是否属于指定方的九宫。"""
    if not PALACE_COL_MIN <= col <= PALACE_COL_MAX:
        return False
    if side is Side.RED:
        return RED_PALACE_ROW_MIN <= row <= RED_PALACE_ROW_MAX
    return BLACK_PALACE_ROW_MIN <= row <= BLACK_PALACE_ROW_MAX


def on_own_side(side: Side, row: int) -> bool:
    """判断行号是否在指定方半场内（相/象不得过河）。"""
    if side is Side.RED:
        return RIVER_BOTTOM_ROW <= row < BOARD_ROWS
    return 0 <= row <= RIVER_TOP_ROW


def empty_board() -> Board:
    """返回 10×9 的空棋盘快照。"""
    return tuple(tuple(None for _ in range(BOARD_COLS)) for _ in range(BOARD_ROWS))


def initial_board() -> Board:
    """返回标准初始局面。"""
    rows: list[list[Cell]] = [[None for _ in range(BOARD_COLS)] for _ in range(BOARD_ROWS)]
    back_rank: tuple[PieceKind, ...] = (
        PieceKind.CHARIOT,
        PieceKind.HORSE,
        PieceKind.ELEPHANT,
        PieceKind.ADVISOR,
        PieceKind.KING,
        PieceKind.ADVISOR,
        PieceKind.ELEPHANT,
        PieceKind.HORSE,
        PieceKind.CHARIOT,
    )
    for col, kind in enumerate(back_rank):
        rows[0][col] = Piece(Side.BLACK, kind)
        rows[9][col] = Piece(Side.RED, kind)
    for col in (1, 7):
        rows[2][col] = Piece(Side.BLACK, PieceKind.CANNON)
        rows[7][col] = Piece(Side.RED, PieceKind.CANNON)
    for col in (0, 2, 4, 6, 8):
        rows[3][col] = Piece(Side.BLACK, PieceKind.PAWN)
        rows[6][col] = Piece(Side.RED, PieceKind.PAWN)
    return tuple(tuple(row) for row in rows)


def find_king(board: BoardLike, side: Side) -> Optional[Square]:
    """查找指定方将/帅的位置；缺失时返回 None。"""
    for row in range(BOARD_ROWS):
        for col in range(BOARD_COLS):
            piece = board[row][col]
            if piece is not None and piece.side is side and piece.kind is PieceKind.KING:
                return (row, col)
    return None


def kings_facing(board: BoardLike) -> bool:
    """判断双方将/帅是否同列照面（中间无子）。"""
    red_king = find_king(board, Side.RED)
    black_king = find_king(board, Side.BLACK)
    if red_king is None or black_king is None:
        return False
    if red_king[1] != black_king[1]:
        return False
    col = red_king[1]
    top, bottom = sorted((red_king[0], black_king[0]))
    return all(board[row][col] is None for row in range(top + 1, bottom))


# ---------------------------------------------------------------------------
# 走法生成
# ---------------------------------------------------------------------------
def _can_land(board: BoardLike, side: Side, row: int, col: int) -> bool:
    """目标格在棋盘内且不是己方棋子。"""
    if not in_bounds(row, col):
        return False
    target = board[row][col]
    return target is None or target.side is not side


def _add_if_landable(
    board: BoardLike,
    side: Side,
    row: int,
    col: int,
    moves: list[Square],
) -> None:
    """把可落子目标加入列表。"""
    if _can_land(board, side, row, col):
        moves.append((row, col))


def _chariot_moves(
    board: BoardLike, piece: Piece, row: int, col: int
) -> list[Square]:
    """车的四方向滑行。"""
    moves: list[Square] = []
    for dr, dc in _ORTHOGONAL_STEPS:
        r, c = row + dr, col + dc
        while in_bounds(r, c):
            target = board[r][c]
            if target is None:
                moves.append((r, c))
            else:
                if target.side is not piece.side:
                    moves.append((r, c))
                break
            r += dr
            c += dc
    return moves


def _cannon_moves(
    board: BoardLike, piece: Piece, row: int, col: int
) -> list[Square]:
    """炮的走法：无炮架走空位，隔一个炮架吃敌子。"""
    moves: list[Square] = []
    for dr, dc in _ORTHOGONAL_STEPS:
        r, c = row + dr, col + dc
        # 炮架之前：只能走空位。
        while in_bounds(r, c) and board[r][c] is None:
            moves.append((r, c))
            r += dr
            c += dc
        if not in_bounds(r, c):
            continue
        # 越过炮架（board[r][c] 必定是棋子），继续找第一个目标。
        r += dr
        c += dc
        while in_bounds(r, c):
            target = board[r][c]
            if target is not None:
                if target.side is not piece.side:
                    moves.append((r, c))
                break
            r += dr
            c += dc
    return moves


def _horse_moves(
    board: BoardLike, piece: Piece, row: int, col: int
) -> list[Square]:
    """马的日字走法，含蹩马腿判断。"""
    moves: list[Square] = []
    for dr, dc in _HORSE_STEPS:
        target_r, target_c = row + dr, col + dc
        # 目标越界时马腿也可能越界，必须先排除目标再访问棋盘。
        if not in_bounds(target_r, target_c):
            continue
        if abs(dr) == 2:
            leg_r, leg_c = row + dr // 2, col
        else:
            leg_r, leg_c = row, col + dc // 2
        if board[leg_r][leg_c] is not None:
            continue
        _add_if_landable(board, piece.side, target_r, target_c, moves)
    return moves


def _elephant_moves(
    board: BoardLike, piece: Piece, row: int, col: int
) -> list[Square]:
    """相的田字走法，含塞象眼与不过河限制。"""
    moves: list[Square] = []
    for dr, dc in _DIAGONAL_STEPS:
        step_r, step_c = dr * 2, dc * 2
        eye_r, eye_c = row + dr, col + dc
        target_r, target_c = row + step_r, col + step_c
        if not in_bounds(target_r, target_c):
            continue
        if not on_own_side(piece.side, target_r):
            continue
        if board[eye_r][eye_c] is not None:
            continue
        _add_if_landable(board, piece.side, target_r, target_c, moves)
    return moves


def _advisor_moves(
    board: BoardLike, piece: Piece, row: int, col: int
) -> list[Square]:
    """仕/士在九宫内的斜向一步。"""
    moves: list[Square] = []
    for dr, dc in _DIAGONAL_STEPS:
        r, c = row + dr, col + dc
        if not in_palace(piece.side, r, c):
            continue
        _add_if_landable(board, piece.side, r, c, moves)
    return moves


def _pawn_moves(
    board: BoardLike, piece: Piece, row: int, col: int
) -> list[Square]:
    """兵/卒：向前一步，过河后可左右一步。"""
    moves: list[Square] = []
    forward_row = row + piece.side.forward
    _add_if_landable(board, piece.side, forward_row, col, moves)

    crossed_river = (
        row <= RIVER_TOP_ROW if piece.side is Side.RED else row >= RIVER_BOTTOM_ROW
    )
    if crossed_river:
        _add_if_landable(board, piece.side, row, col - 1, moves)
        _add_if_landable(board, piece.side, row, col + 1, moves)
    return moves


def _king_moves(
    board: BoardLike, piece: Piece, row: int, col: int
) -> list[Square]:
    """将/帅：九宫内四方向一步，外加飞将吃对方将/帅。"""
    moves: list[Square] = []
    for dr, dc in _ORTHOGONAL_STEPS:
        r, c = row + dr, col + dc
        if not in_palace(piece.side, r, c):
            continue
        _add_if_landable(board, piece.side, r, c, moves)

    opponent_king = find_king(board, piece.side.opponent)
    if opponent_king is not None and opponent_king[1] == col:
        target_row = opponent_king[0]
        top, bottom = sorted((row, target_row))
        if all(board[r][col] is None for r in range(top + 1, bottom)):
            moves.append(opponent_king)
    return moves


def pseudo_legal_moves_from(
    board: BoardLike,
    row: int,
    col: int,
) -> tuple[Square, ...]:
    """生成指定棋子的伪合法目的地（不检查走后己方是否被将军）。

    伪合法走法会排除己方棋子占据的目标；将/帅的飞将吃子也包含在内，
    供 :func:`is_in_check` 检测“将帅照面”。
    """
    if not in_bounds(row, col):
        return ()
    piece = board[row][col]
    if piece is None:
        return ()

    if piece.kind is PieceKind.CHARIOT:
        moves = _chariot_moves(board, piece, row, col)
    elif piece.kind is PieceKind.CANNON:
        moves = _cannon_moves(board, piece, row, col)
    elif piece.kind is PieceKind.HORSE:
        moves = _horse_moves(board, piece, row, col)
    elif piece.kind is PieceKind.ELEPHANT:
        moves = _elephant_moves(board, piece, row, col)
    elif piece.kind is PieceKind.ADVISOR:
        moves = _advisor_moves(board, piece, row, col)
    elif piece.kind is PieceKind.PAWN:
        moves = _pawn_moves(board, piece, row, col)
    else:
        moves = _king_moves(board, piece, row, col)
    return tuple(moves)


def _move_for(board: BoardLike, row: int, col: int, target: Square) -> Move:
    """根据起点、终点构造带被吃子的 Move。"""
    to_row, to_col = target
    return Move(
        from_row=row,
        from_col=col,
        to_row=to_row,
        to_col=to_col,
        captured=board[to_row][to_col],
    )


def generate_pseudo_legal_moves(board: BoardLike, side: Side) -> tuple[Move, ...]:
    """生成指定方的全部伪合法着法。"""
    moves: list[Move] = []
    for row in range(BOARD_ROWS):
        for col in range(BOARD_COLS):
            piece = board[row][col]
            if piece is None or piece.side is not side:
                continue
            for target in pseudo_legal_moves_from(board, row, col):
                moves.append(_move_for(board, row, col, target))
    return tuple(moves)


def apply_move_to_board(board: BoardLike, move: Move) -> Board:
    """复制棋盘并应用一手棋（不校验合法性）。"""
    rows: list[list[Cell]] = [list(row) for row in board]
    piece = rows[move.from_row][move.from_col]
    rows[move.from_row][move.from_col] = None
    rows[move.to_row][move.to_col] = piece
    return tuple(tuple(row) for row in rows)


# ---------------------------------------------------------------------------
# 将军与胜负
# ---------------------------------------------------------------------------
def is_in_check(board: BoardLike, side: Side) -> bool:
    """判断指定方是否正被将军。

    若该方将/帅缺失（数据损坏或已被吃），防御性返回 True。
    """
    king_square = find_king(board, side)
    if king_square is None:
        return True

    opponent = side.opponent
    for row in range(BOARD_ROWS):
        for col in range(BOARD_COLS):
            piece = board[row][col]
            if piece is None or piece.side is not opponent:
                continue
            if king_square in pseudo_legal_moves_from(board, row, col):
                return True
    return False


def is_legal_move(
    board: BoardLike,
    side: Side,
    from_row: int,
    from_col: int,
    to_row: int,
    to_col: int,
) -> bool:
    """判断指定方的一手棋是否完全合法（含不可送将）。"""
    if not in_bounds(from_row, from_col) or not in_bounds(to_row, to_col):
        return False
    piece = board[from_row][from_col]
    if piece is None or piece.side is not side:
        return False
    if (to_row, to_col) not in pseudo_legal_moves_from(board, from_row, from_col):
        return False
    move = _move_for(board, from_row, from_col, (to_row, to_col))
    next_board = apply_move_to_board(board, move)
    return not is_in_check(next_board, side)


def legal_moves_from(
    board: BoardLike,
    row: int,
    col: int,
) -> tuple[Move, ...]:
    """返回指定棋子的全部合法着法。"""
    if not in_bounds(row, col):
        return ()
    piece = board[row][col]
    if piece is None:
        return ()
    moves: list[Move] = []
    for target in pseudo_legal_moves_from(board, row, col):
        move = _move_for(board, row, col, target)
        if not is_in_check(apply_move_to_board(board, move), piece.side):
            moves.append(move)
    return tuple(moves)


def generate_legal_moves(board: BoardLike, side: Side) -> tuple[Move, ...]:
    """生成指定方的全部合法着法。"""
    moves: list[Move] = []
    for move in generate_pseudo_legal_moves(board, side):
        next_board = apply_move_to_board(board, move)
        if not is_in_check(next_board, side):
            moves.append(move)
    return tuple(moves)


def has_legal_move(board: BoardLike, side: Side) -> bool:
    """判断指定方是否至少有一手合法着法（短路求值）。"""
    for move in generate_pseudo_legal_moves(board, side):
        next_board = apply_move_to_board(board, move)
        if not is_in_check(next_board, side):
            return True
    return False


def make_move(
    board: BoardLike,
    side: Side,
    from_row: int,
    from_col: int,
    to_row: int,
    to_col: int,
) -> Optional[Move]:
    """若该手合法则返回带被吃子的 Move，否则返回 None。"""
    if not is_legal_move(board, side, from_row, from_col, to_row, to_col):
        return None
    return _move_for(board, from_row, from_col, (to_row, to_col))


def is_checkmate(board: BoardLike, side_to_move: Side) -> bool:
    """判断轮到走棋的一方是否被将死。"""
    return is_in_check(board, side_to_move) and not has_legal_move(board, side_to_move)


def is_stalemate(board: BoardLike, side_to_move: Side) -> bool:
    """判断轮到走棋的一方是否被困毙（无合法着法但未被将军）。"""
    return (
        not is_in_check(board, side_to_move)
        and not has_legal_move(board, side_to_move)
    )


def evaluate_status(
    board: BoardLike,
    side_to_move: Side,
) -> tuple[Optional[Side], Optional[EndReason]]:
    """评估当前局面。

    返回：
        ``(胜方, 结束原因)``；对局仍可继续时返回 ``(None, None)``。
        将死与困毙都判轮走方输，因此胜方都是 ``side_to_move.opponent``。
    """
    if has_legal_move(board, side_to_move):
        return (None, None)
    if is_in_check(board, side_to_move):
        return (side_to_move.opponent, EndReason.CHECKMATE)
    return (side_to_move.opponent, EndReason.STALEMATE)


__all__ = [
    "BOARD_ROWS",
    "BOARD_COLS",
    "RIVER_TOP_ROW",
    "RIVER_BOTTOM_ROW",
    "PALACE_COL_MIN",
    "PALACE_COL_MAX",
    "Side",
    "PieceKind",
    "Piece",
    "Move",
    "EndReason",
    "Square",
    "Cell",
    "Board",
    "BoardLike",
    "in_bounds",
    "in_palace",
    "on_own_side",
    "empty_board",
    "initial_board",
    "find_king",
    "kings_facing",
    "pseudo_legal_moves_from",
    "generate_pseudo_legal_moves",
    "apply_move_to_board",
    "is_in_check",
    "is_legal_move",
    "legal_moves_from",
    "generate_legal_moves",
    "has_legal_move",
    "make_move",
    "is_checkmate",
    "is_stalemate",
    "evaluate_status",
]
