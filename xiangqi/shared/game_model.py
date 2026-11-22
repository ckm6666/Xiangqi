"""中国象棋对局状态模型（纯 Python，不依赖 Qt）。

规则位于 :mod:`xiangqi.shared.rules`；本模块维护一局棋的棋盘、行棋方、
走子历史、终局状态与本地悔棋/重置语义。联机房间、时钟和服务器裁决由
未来的 OnlineSession/服务端提供。
"""

from __future__ import annotations

from typing import Mapping, Optional, Sequence

from xiangqi.shared.rules import (
    BOARD_COLS,
    BOARD_ROWS,
    Board,
    Cell,
    EndReason,
    Move,
    Piece,
    PieceKind,
    Side,
    Square,
    evaluate_status,
    initial_board,
    is_in_check,
    is_legal_move,
    legal_moves_from,
)


class GameModel:
    """一局中国象棋的状态与规则。

    红方先行；将死与困毙都判对方获胜；当前版本不裁决长将/重复局面。
    """

    def __init__(
        self,
        pieces: Optional[Mapping[Square, Piece]] = None,
        side_to_move: Side = Side.RED,
    ) -> None:
        if pieces is None:
            board = initial_board()
        else:
            board = self._board_from_setup(pieces)
        # 内部使用二维列表方便落子/悔棋；对外属性返回不可变快照。
        self._board: list[list[Cell]] = [list(row) for row in board]
        self._side_to_move: Side = side_to_move
        self._moves: list[Move] = []
        self._winner: Optional[Side] = None
        self._end_reason: Optional[EndReason] = None

    @classmethod
    def initial(cls) -> "GameModel":
        """返回标准初始局面，红方先行。"""
        return cls()

    @classmethod
    def from_setup(
        cls,
        pieces: Mapping[Square, Piece],
        side_to_move: Side,
    ) -> "GameModel":
        """从任意合法摆子创建局面（残局/测试用）。

        只校验坐标、棋子类型与每方恰好一个将/帅，不要求局面本身合法。
        """
        return cls(pieces=pieces, side_to_move=side_to_move)

    @classmethod
    def from_moves(cls, moves: Sequence[Move]) -> "GameModel":
        """从完整走子历史重建模型。

        历史非法或对局结束后仍有后续走子时抛出 ``ValueError``，错误信息
        包含 1 起始的手数，调用方应把它当作数据损坏处理。
        """
        model = cls.initial()
        for index, move in enumerate(moves, start=1):
            if not isinstance(move, Move):
                raise ValueError(f"第 {index} 手不是 Move 对象")
            applied = model.apply_move(
                move.from_row,
                move.from_col,
                move.to_row,
                move.to_col,
            )
            if applied is None:
                raise ValueError(f"第 {index} 手在当前局面下非法")
        return model

    # ------------------------------------------------------------------
    # 只读状态：界面/会话层读取这些属性，不直接改动内部数据
    # ------------------------------------------------------------------
    @property
    def board(self) -> Board:
        """返回只读形式的棋盘快照。"""
        return tuple(tuple(row) for row in self._board)

    @property
    def side_to_move(self) -> Side:
        """当前应当行棋的一方。"""
        return self._side_to_move

    @property
    def current_side(self) -> Side:
        """``side_to_move`` 的别名，便于界面代码阅读。"""
        return self._side_to_move

    @property
    def moves(self) -> tuple[Move, ...]:
        """按时间顺序排列的全部着法。"""
        return tuple(self._moves)

    @property
    def move_count(self) -> int:
        """已经行走的手数。"""
        return len(self._moves)

    @property
    def last_move(self) -> Optional[Move]:
        """最后一手；开局时为 None。"""
        return self._moves[-1] if self._moves else None

    @property
    def winner(self) -> Optional[Side]:
        """胜方；对局未结束时为 None。"""
        return self._winner

    @property
    def end_reason(self) -> Optional[EndReason]:
        """结束原因；对局未结束时为 None。"""
        return self._end_reason

    @property
    def is_check(self) -> bool:
        """当前行棋方是否正被将军。"""
        return is_in_check(self._board, self._side_to_move)

    @property
    def is_checkmate(self) -> bool:
        """当前是否以将死结束。"""
        return self._end_reason is EndReason.CHECKMATE

    @property
    def is_stalemate(self) -> bool:
        """当前是否以困毙结束。"""
        return self._end_reason is EndReason.STALEMATE

    @property
    def is_game_over(self) -> bool:
        """对局是否已经结束。"""
        return self._winner is not None or self._end_reason is not None

    # ------------------------------------------------------------------
    # 规则操作
    # ------------------------------------------------------------------
    def legal_moves_from(self, row: int, col: int) -> tuple[Move, ...]:
        """返回指定棋子的合法着法；终局时返回空。"""
        if self.is_game_over:
            return ()
        return legal_moves_from(self._board, row, col)

    def all_legal_moves(self) -> tuple[Move, ...]:
        """返回当前行棋方的全部合法着法；终局时返回空。"""
        if self.is_game_over:
            return ()
        moves: list[Move] = []
        for row in range(BOARD_ROWS):
            for col in range(BOARD_COLS):
                piece = self._board[row][col]
                if piece is None or piece.side is not self._side_to_move:
                    continue
                moves.extend(legal_moves_from(self._board, row, col))
        return tuple(moves)

    def is_legal_move(
        self,
        from_row: int,
        from_col: int,
        to_row: int,
        to_col: int,
    ) -> bool:
        """判断当前行棋方的一手棋是否合法。"""
        return (
            not self.is_game_over
            and is_legal_move(
                self._board,
                self._side_to_move,
                from_row,
                from_col,
                to_row,
                to_col,
            )
        )

    def apply_move(
        self,
        from_row: int,
        from_col: int,
        to_row: int,
        to_col: int,
    ) -> Optional[Move]:
        """行走一手棋。

        返回：
            成功时返回带被吃子的 Move；越界、非本方棋子、非法着法或
            对局已结束时返回 None。
        """
        if self.is_game_over:
            return None
        if not self.is_legal_move(from_row, from_col, to_row, to_col):
            return None

        piece = self._board[from_row][from_col]
        captured = self._board[to_row][to_col]
        assert piece is not None  # is_legal_move 已保证
        move = Move(
            from_row=from_row,
            from_col=from_col,
            to_row=to_row,
            to_col=to_col,
            captured=captured,
        )

        self._board[from_row][from_col] = None
        self._board[to_row][to_col] = piece
        self._moves.append(move)
        self._side_to_move = self._side_to_move.opponent

        winner, reason = evaluate_status(self._board, self._side_to_move)
        self._winner = winner
        self._end_reason = reason
        return move

    def resign(self, side: Side) -> bool:
        """指定方认输；对局已结束时返回 False。"""
        if self.is_game_over:
            return False
        self._winner = side.opponent
        self._end_reason = EndReason.RESIGN
        return True

    def undo(self) -> bool:
        """撤销最后一手并清除终局状态。

        本地模式使用单步悔棋；联机模式必须由服务器与对手授权，不能直接
        复用该语义。
        """
        if not self._moves:
            return False

        last_move = self._moves[-1]
        moved_piece = self._board[last_move.to_row][last_move.to_col]
        if moved_piece is None:
            return False

        self._board[last_move.from_row][last_move.from_col] = moved_piece
        self._board[last_move.to_row][last_move.to_col] = last_move.captured
        self._moves.pop()
        self._side_to_move = moved_piece.side
        self._winner = None
        self._end_reason = None
        return True

    def reset(self) -> None:
        """恢复标准初始局面并重新由红方先行。"""
        self._board = [list(row) for row in initial_board()]
        self._side_to_move = Side.RED
        self._moves.clear()
        self._winner = None
        self._end_reason = None

    # ------------------------------------------------------------------
    # 内部校验
    # ------------------------------------------------------------------
    @staticmethod
    def _board_from_setup(pieces: Mapping[Square, Piece]) -> Board:
        """校验摆子映射并转换为二维快照。"""
        rows: list[list[Cell]] = [[None for _ in range(BOARD_COLS)] for _ in range(BOARD_ROWS)]
        king_counts: dict[Side, int] = {Side.RED: 0, Side.BLACK: 0}

        for square, piece in pieces.items():
            if (
                not isinstance(square, tuple)
                or len(square) != 2
                or not all(isinstance(value, int) for value in square)
            ):
                raise ValueError(f"非法坐标：{square!r}")
            row, col = square
            if not (0 <= row < BOARD_ROWS and 0 <= col < BOARD_COLS):
                raise ValueError(f"坐标越界：{(row, col)}")
            if not isinstance(piece, Piece):
                raise ValueError(f"坐标 {(row, col)} 上的值不是 Piece")
            rows[row][col] = piece
            if piece.kind is PieceKind.KING:
                king_counts[piece.side] += 1

        for side, count in king_counts.items():
            if count != 1:
                raise ValueError(f"{side.label}必须恰好有一个将/帅，实际为 {count}")
        return tuple(tuple(row) for row in rows)


__all__ = ["GameModel"]
