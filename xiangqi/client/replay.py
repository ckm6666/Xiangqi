"""棋谱复盘时间轴。

把 ``GameRecord.moves`` 转换为逐手的只读 ``BoardView`` 帧：游标前进/后退
时从初始局面重放着法，最终交给棋盘控件绘制。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from xiangqi.client.board_view import BoardView
from xiangqi.shared.game_model import GameModel
from xiangqi.shared.rules import Move


@dataclass
class ReplayTimeline:
    """按手数前进/后退的只读游标。"""

    moves: tuple[Move, ...]
    index: int = 0

    @property
    def length(self) -> int:
        return len(self.moves)

    @property
    def at_start(self) -> bool:
        return self.index <= 0

    @property
    def at_end(self) -> bool:
        return self.index >= self.length

    @property
    def current_move(self) -> Optional[Move]:
        """当前已经走过的最后一手；起点为 None。"""
        if 0 < self.index <= self.length:
            return self.moves[self.index - 1]
        return None

    def reset(self) -> None:
        self.index = 0

    def step(self, delta: int) -> int:
        """向前/向后移动游标并返回新位置。"""
        self.index = max(0, min(self.length, self.index + int(delta)))
        return self.index

    def seek(self, index: int) -> int:
        """跳到指定手数并返回实际位置。"""
        self.index = max(0, min(self.length, int(index)))
        return self.index

    def model_at(self, index: Optional[int] = None) -> GameModel:
        """返回第 ``index`` 手之后的模型（0 表示初始局面）。"""
        position = self.index if index is None else max(
            0, min(self.length, int(index))
        )
        model = GameModel.initial()
        for move_number, move in enumerate(
            self.moves[:position], start=1
        ):
            applied = model.apply_move(
                move.from_row,
                move.from_col,
                move.to_row,
                move.to_col,
            )
            if applied is None:
                raise ValueError(f"第 {move_number} 手在当前局面下非法")
        return model

    def frame(self, index: Optional[int] = None) -> BoardView:
        """返回第 ``index`` 手之后的棋盘只读快照。"""
        return BoardView.from_model(self.model_at(index))


__all__ = ["ReplayTimeline"]
