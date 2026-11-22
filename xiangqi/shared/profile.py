"""玩家资料：排位称号、头像标识与战绩统计（纯 Python）。

称号只由排位分决定，排位分只在对局分胜负的排位赛中变化。本模块同时
被客户端（显示称号/胜率）和服务端（构建个人资料响应）复用，保证两端
使用同一套阈值。

头像分为两类：

* ``default:N``：客户端内置绘制的默认头像；
* ``custom``：玩家上传的 PNG，服务端以 BLOB 保存，客户端按昵称拉取。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

DEFAULT_AVATAR_IDS: tuple[str, ...] = tuple(
    f"default:{index}" for index in range(1, 7)
)
CUSTOM_AVATAR_ID = "custom"
MAX_AVATAR_BYTES = 512 * 1024


@dataclass(frozen=True, slots=True)
class TitleTier:
    """一个称号及其最低排位分。"""

    min_rating: int
    name: str


#: 从高到低排列；查找第一个 ``rating >= min_rating`` 的称号。
TITLE_TIERS: tuple[TitleTier, ...] = (
    TitleTier(2200, "棋圣"),
    TitleTier(2000, "特级大师"),
    TitleTier(1800, "大师"),
    TitleTier(1600, "棋师"),
    TitleTier(1400, "上品棋士"),
    TitleTier(1200, "棋士"),
    TitleTier(0, "棋童"),
)


def title_for_rating(rating: int) -> str:
    """返回指定排位分对应的称号。"""
    value = max(0, int(rating))
    for tier in TITLE_TIERS:
        if value >= tier.min_rating:
            return tier.name
    return TITLE_TIERS[-1].name


def next_title(rating: int) -> Optional[TitleTier]:
    """返回比当前分数更高的下一个称号；已是最高称号时返回 None。"""
    value = max(0, int(rating))
    candidates = [
        tier for tier in TITLE_TIERS if tier.min_rating > value
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda tier: tier.min_rating)


def is_valid_avatar_id(avatar: object) -> bool:
    """头像标识是否为内置默认头像或自定义头像。"""
    return isinstance(avatar, str) and (
        avatar in DEFAULT_AVATAR_IDS or avatar == CUSTOM_AVATAR_ID
    )


@dataclass(frozen=True, slots=True)
class PlayerStats:
    """联机对局战绩；和棋单独统计，胜率按总对局数计算。"""

    wins: int = 0
    losses: int = 0
    draws: int = 0

    @property
    def games(self) -> int:
        return self.wins + self.losses + self.draws

    @property
    def win_rate(self) -> float:
        """胜率百分比（0-100），保留一位小数。"""
        if self.games <= 0:
            return 0.0
        return round(self.wins * 100.0 / self.games, 1)

    @property
    def record_text(self) -> str:
        return f"{self.wins}胜 {self.draws}和 {self.losses}负"


__all__ = [
    "CUSTOM_AVATAR_ID",
    "DEFAULT_AVATAR_IDS",
    "MAX_AVATAR_BYTES",
    "PlayerStats",
    "TITLE_TIERS",
    "TitleTier",
    "is_valid_avatar_id",
    "next_title",
    "title_for_rating",
]
