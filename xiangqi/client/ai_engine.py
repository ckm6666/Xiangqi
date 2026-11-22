"""中国象棋 AI 引擎（纯 Python，不依赖 Qt）。

搜索流程：
    * 扁平 90 格整数棋盘，走子/撤销不复制棋盘；
    * 增量定位双方将/帅，快速“受攻击”检测；
    * alpha-beta 迭代加深、吃子静态搜索、MVV-LVA + 历史启发排序；
    * 按难度配置深度、思考时间、节点上限与随机性。

对外入口：
    :class:`XiangqiAI` / :func:`search_best_move` 返回包含着法、评分、
    搜索深度与节点数的 :class:`SearchResult`。``cancel_event`` 为
    ``threading.Event``，供后台线程在悔棋/重开/关窗时尽快中止搜索。
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass
from enum import Enum
from threading import Event
from typing import Final, Optional

from xiangqi.shared.rules import (
    BOARD_COLS,
    BOARD_ROWS,
    BoardLike,
    Move,
    Piece,
    PieceKind,
    Side,
)

MATE_SCORE: Final[int] = 1_000_000
INFINITY: Final[int] = 10**9
_MAX_PLY: Final[int] = 64

MATERIAL_VALUES: Final[dict[PieceKind, int]] = {
    PieceKind.KING: 100_000,
    PieceKind.CHARIOT: 900,
    PieceKind.CANNON: 450,
    PieceKind.HORSE: 400,
    PieceKind.ADVISOR: 200,
    PieceKind.ELEPHANT: 200,
    PieceKind.PAWN: 100,
}

_ORTHOGONAL: Final[tuple[tuple[int, int], ...]] = (
    (-1, 0),
    (1, 0),
    (0, -1),
    (0, 1),
)
_DIAGONAL: Final[tuple[tuple[int, int], ...]] = (
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


class AIDifficulty(Enum):
    """AI 难度。"""

    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"
    MASTER = "master"

    @property
    def label(self) -> str:
        return _DIFFICULTY_LABELS[self]


_DIFFICULTY_LABELS: dict[AIDifficulty, str] = {
    AIDifficulty.EASY: "入门",
    AIDifficulty.MEDIUM: "业余",
    AIDifficulty.HARD: "高手",
    AIDifficulty.MASTER: "大师",
}


@dataclass(frozen=True)
class SearchConfig:
    """一次搜索的资源配置。"""

    max_depth: int
    time_limit: float
    node_limit: int
    quiescence_depth: int = 2
    random_top_k: int = 0


DIFFICULTY_CONFIGS: dict[AIDifficulty, SearchConfig] = {
    AIDifficulty.EASY: SearchConfig(
        max_depth=1,
        time_limit=0.25,
        node_limit=3_000,
        quiescence_depth=0,
        random_top_k=4,
    ),
    AIDifficulty.MEDIUM: SearchConfig(
        max_depth=3,
        time_limit=0.8,
        node_limit=30_000,
        quiescence_depth=2,
    ),
    AIDifficulty.HARD: SearchConfig(
        max_depth=4,
        time_limit=1.5,
        node_limit=80_000,
        quiescence_depth=3,
    ),
    AIDifficulty.MASTER: SearchConfig(
        max_depth=5,
        time_limit=2.5,
        node_limit=150_000,
        quiescence_depth=4,
    ),
}


@dataclass(frozen=True)
class SearchResult:
    """一次搜索的结果。"""

    move: Optional[Move]
    score: int = 0
    depth: int = 0
    nodes: int = 0
    elapsed: float = 0.0


class _Timeout(Exception):
    """搜索达到时间/节点上限。"""


class _Cancelled(Exception):
    """外部请求取消搜索。"""


def _sign(side: Side) -> int:
    return 1 if side is Side.RED else -1


def _opponent_sign(sign: int) -> int:
    return -sign


def _crossed_river(side: Side, row: int) -> bool:
    if side is Side.RED:
        return row <= 4
    return row >= 5


def _in_palace(side: Side, row: int, col: int) -> bool:
    if not 3 <= col <= 5:
        return False
    if side is Side.RED:
        return 7 <= row <= 9
    return 0 <= row <= 2


def _on_own_side(side: Side, row: int) -> bool:
    return row >= 5 if side is Side.RED else row <= 4


def _positional_bonus(kind: PieceKind, row: int, col: int, side: Side) -> int:
    """轻量位置分：鼓励兵过河、马炮占中路、车活跃。"""
    if side is Side.BLACK:
        row = 9 - row
    center = 4 - abs(col - 4)

    if kind is PieceKind.PAWN:
        bonus = max(0, 6 - row) * 8
        if row <= 4:
            bonus += 18
        return bonus + center * 3
    if kind is PieceKind.HORSE:
        return center * 5 + max(0, 5 - row) * 2
    if kind is PieceKind.CANNON:
        return center * 4 + max(0, 5 - row) * 2
    if kind is PieceKind.CHARIOT:
        return center * 2 + max(0, 5 - row) * 2
    if kind is PieceKind.KING:
        return center
    return 0


class _Position:
    """扁平整数棋盘，供搜索高频读写。

    空格为 0，红方棋子为 ``+PieceKind``，黑方为 ``-PieceKind``。
    """

    __slots__ = ("cells", "_king_index")

    def __init__(self, board: BoardLike) -> None:
        cells = [0] * (BOARD_ROWS * BOARD_COLS)
        king_index: dict[Side, int] = {}
        for row in range(BOARD_ROWS):
            for col in range(BOARD_COLS):
                piece = board[row][col]
                if piece is None:
                    continue
                code = piece.code
                index = row * BOARD_COLS + col
                cells[index] = code
                if piece.kind is PieceKind.KING:
                    king_index[piece.side] = index
        self.cells = cells
        self._king_index = king_index

    # ------------------------------------------------------------------
    # 基础访问
    # ------------------------------------------------------------------
    def make(self, move: tuple[int, int, int]) -> int:
        """落子并返回被吃子编码。"""
        from_index, to_index, captured = move
        code = self.cells[from_index]
        self.cells[from_index] = 0
        self.cells[to_index] = code
        if abs(code) == PieceKind.KING:
            self._king_index[Side.RED if code > 0 else Side.BLACK] = to_index
        return captured

    def unmake(self, move: tuple[int, int, int], captured: int) -> None:
        """撤销落子。"""
        from_index, to_index, _ = move
        code = self.cells[to_index]
        self.cells[to_index] = captured
        self.cells[from_index] = code
        if abs(code) == PieceKind.KING:
            self._king_index[Side.RED if code > 0 else Side.BLACK] = from_index

    # ------------------------------------------------------------------
    # 走法生成
    # ------------------------------------------------------------------
    def _add_target(
        self,
        moves: list[tuple[int, int, int]],
        sign: int,
        from_row: int,
        from_col: int,
        to_row: int,
        to_col: int,
        captures_only: bool,
    ) -> None:
        if not (0 <= to_row < BOARD_ROWS and 0 <= to_col < BOARD_COLS):
            return
        to_index = to_row * BOARD_COLS + to_col
        target = self.cells[to_index]
        if target != 0 and (target > 0) == (sign > 0):
            return
        if captures_only and target == 0:
            return
        moves.append(
            (
                from_row * BOARD_COLS + from_col,
                to_index,
                target,
            )
        )

    def pseudo_moves(
        self,
        side: Side,
        captures_only: bool = False,
    ) -> list[tuple[int, int, int]]:
        """生成伪合法着法（不检查送将）。"""
        sign = _sign(side)
        moves: list[tuple[int, int, int]] = []
        cells = self.cells

        for index, code in enumerate(cells):
            if code == 0 or (code > 0) != (sign > 0):
                continue
            row, col = divmod(index, BOARD_COLS)
            kind = abs(code)

            if kind == PieceKind.CHARIOT:
                for dr, dc in _ORTHOGONAL:
                    r, c = row + dr, col + dc
                    while 0 <= r < BOARD_ROWS and 0 <= c < BOARD_COLS:
                        target = cells[r * BOARD_COLS + c]
                        if target == 0:
                            if not captures_only:
                                moves.append((index, r * BOARD_COLS + c, 0))
                        else:
                            if (target > 0) != (sign > 0):
                                moves.append((index, r * BOARD_COLS + c, target))
                            break
                        r += dr
                        c += dc

            elif kind == PieceKind.CANNON:
                for dr, dc in _ORTHOGONAL:
                    r, c = row + dr, col + dc
                    while 0 <= r < BOARD_ROWS and 0 <= c < BOARD_COLS:
                        target = cells[r * BOARD_COLS + c]
                        if target != 0:
                            break
                        if not captures_only:
                            moves.append((index, r * BOARD_COLS + c, 0))
                        r += dr
                        c += dc
                    r += dr
                    c += dc
                    while 0 <= r < BOARD_ROWS and 0 <= c < BOARD_COLS:
                        target = cells[r * BOARD_COLS + c]
                        if target != 0:
                            if (target > 0) != (sign > 0):
                                moves.append((index, r * BOARD_COLS + c, target))
                            break
                        r += dr
                        c += dc

            elif kind == PieceKind.HORSE:
                for dr, dc in _HORSE_STEPS:
                    target_row, target_col = row + dr, col + dc
                    if not (
                        0 <= target_row < BOARD_ROWS
                        and 0 <= target_col < BOARD_COLS
                    ):
                        continue
                    if abs(dr) == 2:
                        leg_row, leg_col = row + dr // 2, col
                    else:
                        leg_row, leg_col = row, col + dc // 2
                    if cells[leg_row * BOARD_COLS + leg_col] != 0:
                        continue
                    self._add_target(
                        moves,
                        sign,
                        row,
                        col,
                        target_row,
                        target_col,
                        captures_only,
                    )

            elif kind == PieceKind.ELEPHANT:
                for dr, dc in _DIAGONAL:
                    target_row, target_col = row + dr * 2, col + dc * 2
                    if not (
                        0 <= target_row < BOARD_ROWS
                        and 0 <= target_col < BOARD_COLS
                    ):
                        continue
                    if not _on_own_side(side, target_row):
                        continue
                    eye_row, eye_col = row + dr, col + dc
                    if cells[eye_row * BOARD_COLS + eye_col] != 0:
                        continue
                    self._add_target(
                        moves,
                        sign,
                        row,
                        col,
                        target_row,
                        target_col,
                        captures_only,
                    )

            elif kind == PieceKind.ADVISOR:
                for dr, dc in _DIAGONAL:
                    target_row, target_col = row + dr, col + dc
                    if not _in_palace(side, target_row, target_col):
                        continue
                    self._add_target(
                        moves,
                        sign,
                        row,
                        col,
                        target_row,
                        target_col,
                        captures_only,
                    )

            elif kind == PieceKind.PAWN:
                forward_row = row + side.forward
                self._add_target(
                    moves,
                    sign,
                    row,
                    col,
                    forward_row,
                    col,
                    captures_only,
                )
                if _crossed_river(side, row):
                    for dc in (-1, 1):
                        self._add_target(
                            moves,
                            sign,
                            row,
                            col,
                            row,
                            col + dc,
                            captures_only,
                        )

            else:  # 将/帅
                for dr, dc in _ORTHOGONAL:
                    target_row, target_col = row + dr, col + dc
                    if not _in_palace(side, target_row, target_col):
                        continue
                    self._add_target(
                        moves,
                        sign,
                        row,
                        col,
                        target_row,
                        target_col,
                        captures_only,
                    )
                # 飞将：同列且中间无子时，可“吃”对方将/帅。
                opponent_king_index = self._king_index.get(side.opponent)
                if opponent_king_index is not None:
                    king_row, king_col = divmod(
                        opponent_king_index, BOARD_COLS
                    )
                    if king_col == col:
                        top, bottom = sorted((row, king_row))
                        if all(
                            cells[r * BOARD_COLS + col] == 0
                            for r in range(top + 1, bottom)
                        ):
                            moves.append(
                                (
                                    index,
                                    opponent_king_index,
                                    cells[opponent_king_index],
                                )
                            )
        return moves

    def legal_moves(
        self,
        side: Side,
        captures_only: bool = False,
    ) -> list[tuple[int, int, int]]:
        """生成完全合法着法（排除送将）。"""
        result: list[tuple[int, int, int]] = []
        for move in self.pseudo_moves(side, captures_only=captures_only):
            captured = self.make(move)
            try:
                legal = not self.is_in_check(side)
            finally:
                self.unmake(move, captured)
            if legal:
                result.append(move)
        return result

    def has_legal_move(self, side: Side) -> bool:
        """短路判断是否存在合法着法。"""
        for move in self.pseudo_moves(side):
            captured = self.make(move)
            try:
                legal = not self.is_in_check(side)
            finally:
                self.unmake(move, captured)
            if legal:
                return True
        return False

    # ------------------------------------------------------------------
    # 将军检测
    # ------------------------------------------------------------------
    def is_in_check(self, side: Side) -> bool:
        """快速判断指定方是否被将军。

        只需检查能攻击到将/帅的兵种：兵/卒、马、车、炮与飞将。
        仕/士与相/象无法越过九宫/河界攻击对方将/帅。
        """
        king_index = self._king_index.get(side)
        if king_index is None:
            return True
        king_row, king_col = divmod(king_index, BOARD_COLS)
        enemy = side.opponent
        enemy_sign = _sign(enemy)
        cells = self.cells

        def enemy_at(row: int, col: int, kind: PieceKind) -> bool:
            if not (0 <= row < BOARD_ROWS and 0 <= col < BOARD_COLS):
                return False
            return cells[row * BOARD_COLS + col] == enemy_sign * int(kind)

        # 兵/卒：正面一步，或过河后的横向一步。
        if enemy_at(king_row - enemy.forward, king_col, PieceKind.PAWN):
            return True
        for dc in (-1, 1):
            if _crossed_river(enemy, king_row) and enemy_at(
                king_row, king_col + dc, PieceKind.PAWN
            ):
                return True

        # 马：反查八个马源，检查马腿。
        for dr, dc in _HORSE_STEPS:
            origin_row, origin_col = king_row + dr, king_col + dc
            if not enemy_at(origin_row, origin_col, PieceKind.HORSE):
                continue
            if abs(dr) == 2:
                leg_row, leg_col = king_row + dr // 2, king_col + dc
            else:
                leg_row, leg_col = king_row + dr, king_col + dc // 2
            if cells[leg_row * BOARD_COLS + leg_col] == 0:
                return True

        # 车/炮/将：沿四条射线扫描。
        for dr, dc in _ORTHOGONAL:
            row, col = king_row + dr, king_col + dc
            first_hit = False
            while 0 <= row < BOARD_ROWS and 0 <= col < BOARD_COLS:
                code = cells[row * BOARD_COLS + col]
                if code != 0:
                    same_side = (code > 0) == (side is Side.RED)
                    if not first_hit:
                        if not same_side:
                            kind = abs(code)
                            if kind == PieceKind.CHARIOT:
                                return True
                            if kind == PieceKind.KING:
                                return True
                        first_hit = True
                    else:
                        if (
                            not same_side
                            and abs(code) == PieceKind.CANNON
                        ):
                            return True
                        break
                row += dr
                col += dc

        return False

    # ------------------------------------------------------------------
    # 局面评估
    # ------------------------------------------------------------------
    def evaluate(self, side: Side) -> int:
        """从指定方视角评估当前局面。"""
        red_score = 0
        black_score = 0
        for index, code in enumerate(self.cells):
            if code == 0:
                continue
            row, col = divmod(index, BOARD_COLS)
            piece_side = Side.RED if code > 0 else Side.BLACK
            kind = PieceKind(abs(code))
            value = MATERIAL_VALUES[kind] + _positional_bonus(
                kind, row, col, piece_side
            )
            if piece_side is Side.RED:
                red_score += value
            else:
                black_score += value

        score = red_score - black_score
        return score if side is Side.RED else -score


class _SearchEngine:
    """一次搜索的私有状态。"""

    def __init__(
        self,
        position: _Position,
        config: SearchConfig,
        cancel_event: Optional[Event],
    ) -> None:
        self.position = position
        self.config = config
        self.cancel_event = cancel_event
        self.nodes = 0
        self.deadline = 0.0
        self.history = [0] * (BOARD_ROWS * BOARD_COLS * BOARD_ROWS * BOARD_COLS)

    # ------------------------------------------------------------------
    # 搜索
    # ------------------------------------------------------------------
    def run(self, side: Side) -> SearchResult:
        start = time.monotonic()
        self.deadline = start + max(0.01, self.config.time_limit)
        root_moves = self.position.legal_moves(side)
        if not root_moves:
            return SearchResult(
                move=None,
                score=-MATE_SCORE,
                depth=0,
                nodes=self.nodes,
                elapsed=time.monotonic() - start,
            )

        root_moves = self._order_moves(root_moves, None, 1)
        best_move = root_moves[0]
        best_score = -INFINITY
        completed_depth = 0
        root_scores: list[tuple[tuple[int, int, int], int]] = []
        previous_best: Optional[tuple[int, int, int]] = None

        for depth in range(1, self.config.max_depth + 1):
            if time.monotonic() >= self.deadline:
                break
            if self.cancel_event is not None and self.cancel_event.is_set():
                break

            ordered = self._order_moves(root_moves, previous_best, depth)
            alpha = -INFINITY
            iteration_best: Optional[tuple[int, int, int]] = None
            iteration_score = -INFINITY
            iteration_scores: list[tuple[tuple[int, int, int], int]] = []

            try:
                for move in ordered:
                    captured = self.position.make(move)
                    try:
                        score = -self._negamax(
                            depth - 1,
                            -INFINITY,
                            -alpha,
                            side.opponent,
                            1,
                        )
                    finally:
                        self.position.unmake(move, captured)
                    iteration_scores.append((move, score))
                    if score > iteration_score:
                        iteration_score = score
                        iteration_best = move
                    if score > alpha:
                        alpha = score
            except (_Timeout, _Cancelled):
                break

            completed_depth = depth
            if iteration_best is not None:
                best_move = iteration_best
                best_score = iteration_score
                previous_best = iteration_best
            root_scores = iteration_scores

            if abs(best_score) >= MATE_SCORE - _MAX_PLY:
                break

        if self.config.random_top_k > 0 and root_scores:
            ranked = sorted(root_scores, key=lambda item: item[1], reverse=True)
            top_score = ranked[0][1]
            candidates = [
                move
                for move, score in ranked[: self.config.random_top_k]
                if score >= top_score - 90
            ]
            if candidates:
                best_move = random.choice(candidates)

        return SearchResult(
            move=self._to_public_move(best_move),
            score=best_score,
            depth=completed_depth,
            nodes=self.nodes,
            elapsed=time.monotonic() - start,
        )

    def _to_public_move(self, move: tuple[int, int, int]) -> Move:
        from_index, to_index, captured = move
        from_row, from_col = divmod(from_index, BOARD_COLS)
        to_row, to_col = divmod(to_index, BOARD_COLS)
        return Move(
            from_row=from_row,
            from_col=from_col,
            to_row=to_row,
            to_col=to_col,
            captured=Piece.from_code(captured) if captured else None,
        )

    def _negamax(
        self,
        depth: int,
        alpha: int,
        beta: int,
        side: Side,
        ply: int,
    ) -> int:
        self._tick()
        if ply >= _MAX_PLY:
            return self.position.evaluate(side)

        if depth <= 0:
            if not self.position.has_legal_move(side):
                return -MATE_SCORE + ply
            return self._quiescence(
                alpha,
                beta,
                side,
                self.config.quiescence_depth,
                ply,
            )

        moves = self.position.legal_moves(side)
        if not moves:
            return -MATE_SCORE + ply

        moves = self._order_moves(moves, None, depth)
        best = -INFINITY
        for move in moves:
            captured = self.position.make(move)
            try:
                score = -self._negamax(
                    depth - 1,
                    -beta,
                    -alpha,
                    side.opponent,
                    ply + 1,
                )
            finally:
                self.position.unmake(move, captured)

            if score > best:
                best = score
            if best > alpha:
                alpha = best
            if alpha >= beta:
                if move[2] == 0:
                    self.history[move[0] * 90 + move[1]] += depth * depth
                break
        return best

    def _quiescence(
        self,
        alpha: int,
        beta: int,
        side: Side,
        depth: int,
        ply: int,
    ) -> int:
        self._tick()
        in_check = self.position.is_in_check(side)
        stand_pat = 0

        if in_check:
            moves = self.position.legal_moves(side)
            if not moves:
                return -MATE_SCORE + ply
            if depth <= 0:
                best = -INFINITY
                for move in moves:
                    captured = self.position.make(move)
                    try:
                        score = -self.position.evaluate(side.opponent)
                    finally:
                        self.position.unmake(move, captured)
                    if score > best:
                        best = score
                return best if best != -INFINITY else alpha
        else:
            stand_pat = self.position.evaluate(side)
            if stand_pat >= beta:
                return beta
            if stand_pat > alpha:
                alpha = stand_pat
            if depth <= 0:
                return alpha
            moves = self.position.legal_moves(side, captures_only=True)
            if not moves:
                return alpha

        moves = self._order_moves(moves, None, 1)
        best = -INFINITY
        for move in moves:
            if not in_check and move[2] != 0:
                # 吃子收益不足以弥补当前差距时剪枝。
                captured_kind = PieceKind(abs(move[2]))
                if stand_pat + MATERIAL_VALUES[captured_kind] + 200 < alpha:
                    continue
            captured = self.position.make(move)
            try:
                score = -self._quiescence(
                    -beta,
                    -alpha,
                    side.opponent,
                    depth - 1,
                    ply + 1,
                )
            finally:
                self.position.unmake(move, captured)
            if score > best:
                best = score
            if best > alpha:
                alpha = best
            if alpha >= beta:
                break
        return best if best != -INFINITY else alpha

    # ------------------------------------------------------------------
    # 辅助
    # ------------------------------------------------------------------
    def _tick(self) -> None:
        self.nodes += 1
        if self.nodes & 0xFF:
            return
        if self.cancel_event is not None and self.cancel_event.is_set():
            raise _Cancelled
        if time.monotonic() >= self.deadline:
            raise _Timeout
        if self.nodes >= self.config.node_limit:
            raise _Timeout

    def _order_moves(
        self,
        moves: list[tuple[int, int, int]],
        pv_move: Optional[tuple[int, int, int]],
        depth: int,
    ) -> list[tuple[int, int, int]]:
        del depth
        cells = self.position.cells

        def score(move: tuple[int, int, int]) -> int:
            from_index, to_index, captured = move
            if pv_move is not None and move == pv_move:
                return 10_000_000
            if captured != 0:
                attacker = abs(cells[from_index])
                return (
                    1_000_000
                    + MATERIAL_VALUES[PieceKind(abs(captured))] * 10
                    - MATERIAL_VALUES[PieceKind(attacker)]
                )
            return self.history[from_index * 90 + to_index]

        return sorted(moves, key=score, reverse=True)


class XiangqiAI:
    """中国象棋 AI 的对外入口；该类不依赖 Qt。"""

    def find_move(
        self,
        board: BoardLike,
        side: Side,
        difficulty: AIDifficulty = AIDifficulty.MEDIUM,
        cancel_event: Optional[Event] = None,
    ) -> Optional[Move]:
        """搜索并返回最佳着法；无合法着法或搜索被取消时返回 None。"""
        result = self.analyze(
            board,
            side,
            difficulty,
            cancel_event=cancel_event,
        )
        return result.move

    def analyze(
        self,
        board: BoardLike,
        side: Side,
        difficulty: AIDifficulty = AIDifficulty.MEDIUM,
        cancel_event: Optional[Event] = None,
        *,
        config_override: Optional[SearchConfig] = None,
    ) -> SearchResult:
        """搜索并返回完整结果；``config_override`` 供测试/提示使用。"""
        if cancel_event is not None and cancel_event.is_set():
            return SearchResult(move=None)
        config = config_override or DIFFICULTY_CONFIGS[difficulty]
        position = _Position(board)
        engine = _SearchEngine(position, config, cancel_event)
        return engine.run(side)


def search_best_move(
    board: BoardLike,
    side: Side,
    difficulty: AIDifficulty = AIDifficulty.MEDIUM,
    cancel_event: Optional[Event] = None,
    *,
    config_override: Optional[SearchConfig] = None,
) -> SearchResult:
    """函数式入口；与 :class:`XiangqiAI` 等价。"""
    return XiangqiAI().analyze(
        board,
        side,
        difficulty,
        cancel_event=cancel_event,
        config_override=config_override,
    )


def evaluate_board(board: BoardLike, side: Side) -> int:
    """从指定方视角评估局面（测试/调试用）。"""
    return _Position(board).evaluate(side)


def is_in_check_fast(board: BoardLike, side: Side) -> bool:
    """快速将军检测（与 shared.rules.is_in_check 结果一致，测试用）。"""
    return _Position(board).is_in_check(side)


__all__ = [
    "AIDifficulty",
    "SearchConfig",
    "DIFFICULTY_CONFIGS",
    "SearchResult",
    "XiangqiAI",
    "search_best_move",
    "evaluate_board",
    "is_in_check_fast",
    "MATE_SCORE",
    "MATERIAL_VALUES",
]
