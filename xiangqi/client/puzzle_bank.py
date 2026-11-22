"""残局题库加载占位。"""

from __future__ import annotations

from xiangqi.shared.puzzle import Puzzle


def load_puzzle_bank() -> tuple[Puzzle, ...]:
    """载入内置残局；当前版本尚未提供题库。"""
    return ()


__all__ = ["load_puzzle_bank"]
