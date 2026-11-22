"""联机成就目录（纯 Python）。

成就不落库，而是由服务端根据玩家累计战绩实时派生；这样调整成就阈值
无需数据库迁移。客户端只展示服务端返回的 ``earned`` 结果。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable


@dataclass(frozen=True, slots=True)
class Achievement:
    """一条成就定义。"""

    key: str
    name: str
    description: str
    requirement: Callable[[int, int, int, int, int], bool]


@dataclass(frozen=True, slots=True)
class AchievementState:
    """成就及其当前是否达成。"""

    key: str
    name: str
    description: str
    earned: bool


def _games(wins: int, losses: int, draws: int, best: int, rating: int) -> int:
    del best, rating
    return wins + losses + draws


ACHIEVEMENTS: tuple[Achievement, ...] = (
    Achievement(
        "first_game",
        "初涉楚河",
        "完成第一局联机对局",
        lambda w, l, d, best, rating: _games(w, l, d, best, rating) >= 1,
    ),
    Achievement(
        "first_win",
        "首战告捷",
        "赢得第一局联机对局",
        lambda w, l, d, best, rating: w >= 1,
    ),
    Achievement(
        "wins_10",
        "十战十胜",
        "累计赢得 10 局联机对局",
        lambda w, l, d, best, rating: w >= 10,
    ),
    Achievement(
        "wins_50",
        "百战不殆",
        "累计赢得 50 局联机对局",
        lambda w, l, d, best, rating: w >= 50,
    ),
    Achievement(
        "games_100",
        "百局磨剑",
        "累计完成 100 局联机对局",
        lambda w, l, d, best, rating: _games(w, l, d, best, rating) >= 100,
    ),
    Achievement(
        "streak_3",
        "连战连捷",
        "取得 3 连胜",
        lambda w, l, d, best, rating: best >= 3,
    ),
    Achievement(
        "streak_5",
        "势如破竹",
        "取得 5 连胜",
        lambda w, l, d, best, rating: best >= 5,
    ),
    Achievement(
        "rank_1500",
        "登堂入室",
        "排位分达到 1500",
        lambda w, l, d, best, rating: rating >= 1500,
    ),
    Achievement(
        "rank_1800",
        "国手风范",
        "排位分达到 1800",
        lambda w, l, d, best, rating: rating >= 1800,
    ),
)

_ACHIEVEMENT_KEYS = frozenset(item.key for item in ACHIEVEMENTS)


def normalize_achievement_keys(
    values: Iterable[object],
) -> tuple[str, ...]:
    """过滤未知成就并去重，保持输入顺序。"""
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if isinstance(value, str) and value in _ACHIEVEMENT_KEYS:
            if value not in seen:
                seen.add(value)
                result.append(value)
    return tuple(result)


def evaluate_achievements(
    *,
    wins: int = 0,
    losses: int = 0,
    draws: int = 0,
    best_streak: int = 0,
    rating: int = 1200,
) -> tuple[AchievementState, ...]:
    """按累计战绩计算全部成就的达成状态。"""
    return tuple(
        AchievementState(
            key=item.key,
            name=item.name,
            description=item.description,
            earned=bool(
                item.requirement(
                    max(0, int(wins)),
                    max(0, int(losses)),
                    max(0, int(draws)),
                    max(0, int(best_streak)),
                    max(0, int(rating)),
                )
            ),
        )
        for item in ACHIEVEMENTS
    )


__all__ = [
    "ACHIEVEMENTS",
    "Achievement",
    "AchievementState",
    "evaluate_achievements",
    "normalize_achievement_keys",
]
