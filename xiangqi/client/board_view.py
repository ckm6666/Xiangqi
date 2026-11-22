"""棋盘只读视图。

BoardWidget 不直接读取具体 GameModel，而是消费这个不可变快照。这样本地、
AI 以及未来的联机会话都可以把自己的状态投影成 BoardView，界面层无需
知道状态来自本地模型还是服务器快照。

``selected`` 与 ``legal_targets`` 只是界面叠加数据，不属于权威规则状态；
它们由 MainWindow 通过 :meth:`BoardView.with_selection` 填入。
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Iterable, Optional

from xiangqi.shared.rules import (
    Board,
    EndReason,
    Move,
    Side,
    Square,
    empty_board,
)

if TYPE_CHECKING:
    from xiangqi.shared.game_model import GameModel


@dataclass(frozen=True)
class BoardView:
    """棋盘绘制、选中提示与弹窗所需的只读状态快照。"""

    board: Board
    side_to_move: Side
    last_move: Optional[Move]
    is_check: bool
    winner: Optional[Side]
    end_reason: Optional[EndReason]
    is_game_over: bool
    move_count: int
    selected: Optional[Square] = None
    legal_targets: tuple[Square, ...] = ()

    @classmethod
    def from_model(cls, model: "GameModel") -> "BoardView":
        """从本地 GameModel 生成只读快照。"""
        return cls(
            board=model.board,
            side_to_move=model.side_to_move,
            last_move=model.last_move,
            is_check=model.is_check,
            winner=model.winner,
            end_reason=model.end_reason,
            is_game_over=model.is_game_over,
            move_count=model.move_count,
        )

    @classmethod
    def empty(cls) -> "BoardView":
        """返回空棋盘视图；供联机占位会话使用。"""
        return cls(
            board=empty_board(),
            side_to_move=Side.RED,
            last_move=None,
            is_check=False,
            winner=None,
            end_reason=None,
            is_game_over=False,
            move_count=0,
        )

    def with_selection(
        self,
        selected: Optional[Square],
        legal_targets: Iterable[Square] = (),
    ) -> "BoardView":
        """返回带选中高亮与合法目标的新快照。"""
        return replace(
            self,
            selected=selected,
            legal_targets=tuple(legal_targets),
        )


__all__ = ["BoardView"]
