"""共用测试夹具：快速构造带双方将/帅的棋盘。"""

from __future__ import annotations

from typing import Mapping, Optional

from xiangqi.shared.game_model import GameModel
from xiangqi.shared.rules import (
    Board,
    Piece,
    PieceKind,
    Side,
    Square,
)

DEFAULT_RED_KING: Square = (9, 3)
DEFAULT_BLACK_KING: Square = (0, 5)


def piece(kind: PieceKind, side: Side) -> Piece:
    """创建棋子。"""
    return Piece(side=side, kind=kind)


def model_with(
    pieces: Optional[Mapping[Square, Piece]] = None,
    *,
    red_king: Optional[Square] = DEFAULT_RED_KING,
    black_king: Optional[Square] = DEFAULT_BLACK_KING,
    side: Side = Side.RED,
) -> GameModel:
    """构造指定摆子的模型；默认在九宫放入互不照面的双方将/帅。"""
    mapping: dict[Square, Piece] = {}
    if red_king is not None:
        mapping[red_king] = piece(PieceKind.KING, Side.RED)
    if black_king is not None:
        mapping[black_king] = piece(PieceKind.KING, Side.BLACK)
    if pieces:
        mapping.update(pieces)
    return GameModel.from_setup(mapping, side)


def board_with(
    pieces: Optional[Mapping[Square, Piece]] = None,
    *,
    red_king: Optional[Square] = DEFAULT_RED_KING,
    black_king: Optional[Square] = DEFAULT_BLACK_KING,
    side: Side = Side.RED,
) -> Board:
    """只返回摆子后的棋盘快照。"""
    return model_with(
        pieces,
        red_king=red_king,
        black_king=black_king,
        side=side,
    ).board
