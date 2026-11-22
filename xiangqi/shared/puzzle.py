"""残局数据结构（当前版本占位）。

后续版本将补充摆子、步数限制、提示与解法校验。
"""

from __future__ import annotations

from dataclasses import dataclass

from xiangqi.shared.errors import XiangqiError


class PuzzleError(XiangqiError):
    """残局数据不合法。"""


@dataclass(frozen=True, slots=True)
class Puzzle:
    """一道残局的基础元信息。"""

    puzzle_id: str
    title: str
    description: str = ""
    hint: str = ""


__all__ = ["Puzzle", "PuzzleError"]
