"""古风主题调色板。

纯 Python 常量，不依赖 Qt；绘制代码、QSS（字面值）与棋盘常量共用同一套色值。
色名沿用“纸、墨、朱砂、金、黛青、漆”等传统视觉语义。
"""

from __future__ import annotations

from typing import Final

# 宣纸
PAPER: Final[str] = "#F5EFE3"
PAPER_LIGHT: Final[str] = "#FBF7EE"
PAPER_DEEP: Final[str] = "#E9DFCE"
PAPER_MUTED: Final[str] = "#DCD0BC"

# 墨
INK: Final[str] = "#26221C"
INK_SOFT: Final[str] = "#4C463C"
INK_MUTED: Final[str] = "#756C5E"
INK_FAINT: Final[str] = "#A89C8B"

# 朱砂
CINNABAR: Final[str] = "#9E3B2E"
CINNABAR_DARK: Final[str] = "#7E2C22"
CINNABAR_LIGHT: Final[str] = "#B85546"

# 金
GOLD: Final[str] = "#B8934E"
GOLD_DARK: Final[str] = "#8E6C32"
GOLD_PALE: Final[str] = "#E3D1A9"

# 青绿与漆框
DAI_GREEN: Final[str] = "#5D6B63"
LACQUER_TOP: Final[str] = "#332C24"
LACQUER_BOTTOM: Final[str] = "#1E1A16"

# 禁用态
DISABLED_BG: Final[str] = "#EEE8DF"
DISABLED_TEXT: Final[str] = "#B3A898"

# 棋子（象牙色棋面 + 红/黑墨字）
PIECE_IVORY: Final[str] = "#F7EDDA"
PIECE_IVORY_DEEP: Final[str] = "#E4CFAC"
PIECE_RED_INK: Final[str] = "#A8382A"
PIECE_BLACK_INK: Final[str] = "#2A2620"

__all__ = [
    "CINNABAR",
    "CINNABAR_DARK",
    "CINNABAR_LIGHT",
    "DAI_GREEN",
    "DISABLED_BG",
    "DISABLED_TEXT",
    "GOLD",
    "GOLD_DARK",
    "GOLD_PALE",
    "INK",
    "INK_FAINT",
    "INK_MUTED",
    "INK_SOFT",
    "LACQUER_BOTTOM",
    "LACQUER_TOP",
    "PAPER",
    "PAPER_DEEP",
    "PAPER_LIGHT",
    "PAPER_MUTED",
    "PIECE_IVORY",
    "PIECE_IVORY_DEEP",
    "PIECE_RED_INK",
    "PIECE_BLACK_INK",
]
