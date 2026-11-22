"""桌面客户端专用的应用、窗口与棋盘绘制常量。

棋盘规则常量（10×9 棋盘、九宫、河界）位于 :mod:`xiangqi.shared.rules`，
供客户端、AI 与未来服务端复用；本文件只放 PySide6 界面使用的尺寸、
颜色和绘制比例。
"""

from __future__ import annotations

from typing import Final

# ---------------------------------------------------------------------------
# 应用信息
# ---------------------------------------------------------------------------
APP_NAME: Final[str] = "中国象棋"
APP_TITLE: Final[str] = "中国象棋"
APP_VERSION: Final[str] = "0.7.0"
APP_ORGANIZATION: Final[str] = "Xiangqi"
APP_STORAGE_NAME: Final[str] = "Xiangqi"

# ---------------------------------------------------------------------------
# 窗口尺寸（逻辑像素，Qt 会在高 DPI 屏幕上自动缩放）
# ---------------------------------------------------------------------------
WINDOW_DEFAULT_WIDTH: Final[int] = 720
WINDOW_DEFAULT_HEIGHT: Final[int] = 860
WINDOW_MIN_WIDTH: Final[int] = 640
WINDOW_MIN_HEIGHT: Final[int] = 640
WINDOW_SCREEN_MARGIN: Final[int] = 32
BOARD_SUGGESTED_SIZE: Final[int] = 600
BOARD_MIN_SIZE: Final[int] = 260

# ---------------------------------------------------------------------------
# 棋盘绘制参数
#
# 以“格距 spacing”为基准单位：网格为 8×9 个格距，外框、边距和棋子
# 均按 spacing 的比例缩放，保证棋盘在任意窗口尺寸下保持比例。
# ---------------------------------------------------------------------------
BOARD_OUTER_PADDING: Final[float] = 12.0
BOARD_FRAME_SPACING_RATIO: Final[float] = 0.45
BOARD_GRID_MARGIN_SPACING_RATIO: Final[float] = 0.55
PIECE_RADIUS_RATIO: Final[float] = 0.42
PIECE_GLYPH_SIZE_RATIO: Final[float] = 1.02
CLICK_TOLERANCE_RATIO: Final[float] = 0.46
BOARD_SURFACE_CORNER_RATIO: Final[float] = 0.012
BOARD_CORNER_RADIUS_RATIO: Final[float] = 0.024
BOARD_GRAIN_LINE_COUNT: Final[int] = 14
RIVER_TEXT_SIZE_RATIO: Final[float] = 0.42

# ---------------------------------------------------------------------------
# 动效与语音时序
# ---------------------------------------------------------------------------
FRAME_INTERVAL_MS: Final[int] = 16
MOVE_ANIMATION_SECONDS: Final[float] = 0.28
# 人落子后先让动画完整播放，再启动 AI 搜索，避免搜索线程抢占 GIL
# 导致落子动画来不及重绘。
AI_START_DELAY_MS: Final[int] = int(MOVE_ANIMATION_SECONDS * 1000) + 150
MOVE_LIFT_SPACING_RATIO: Final[float] = 0.10
EFFECT_CAPTURE_SECONDS: Final[float] = 0.60
EFFECT_CHECK_SECONDS: Final[float] = 0.95
EFFECT_CHECKMATE_SECONDS: Final[float] = 1.55
RESULT_DIALOG_DELAY_MS: Final[int] = 120

# ---------------------------------------------------------------------------
# 棋盘配色（沿用 Gomoku 的暖木、深漆与金线）
# ---------------------------------------------------------------------------
WOOD_TOP_COLOR: Final[str] = "#E8C99B"
WOOD_MIDDLE_COLOR: Final[str] = "#D9B17B"
WOOD_BOTTOM_COLOR: Final[str] = "#C99A62"
WOOD_BORDER_COLOR: Final[str] = "#8A6336"
WOOD_GRAIN_COLOR: Final[str] = "#6B4526"
GRID_COLOR: Final[str] = "#5A4129"

BOARD_LACQUER_TOP: Final[str] = "#332C24"
BOARD_LACQUER_BOTTOM: Final[str] = "#1E1A16"
BOARD_FRAME_GOLD: Final[str] = "#B8934E"
BOARD_FRAME_INK: Final[str] = "#26221C"

LAST_MOVE_COLOR: Final[str] = "#C7442E"
SELECTION_COLOR: Final[str] = "#9E3B2E"
LEGAL_TARGET_COLOR: Final[str] = "#A8382A"
CHECK_COLOR: Final[str] = "#C0392B"
RIVER_TEXT_COLOR: Final[str] = "#6B5A42"
PIECE_SHADOW_COLOR: Final[str] = "#3A2A16"

__all__ = [
    "APP_NAME",
    "APP_TITLE",
    "APP_VERSION",
    "APP_ORGANIZATION",
    "APP_STORAGE_NAME",
    "WINDOW_DEFAULT_WIDTH",
    "WINDOW_DEFAULT_HEIGHT",
    "WINDOW_MIN_WIDTH",
    "WINDOW_MIN_HEIGHT",
    "WINDOW_SCREEN_MARGIN",
    "BOARD_SUGGESTED_SIZE",
    "BOARD_MIN_SIZE",
    "BOARD_OUTER_PADDING",
    "BOARD_FRAME_SPACING_RATIO",
    "BOARD_GRID_MARGIN_SPACING_RATIO",
    "PIECE_RADIUS_RATIO",
    "PIECE_GLYPH_SIZE_RATIO",
    "CLICK_TOLERANCE_RATIO",
    "BOARD_SURFACE_CORNER_RATIO",
    "BOARD_CORNER_RADIUS_RATIO",
    "BOARD_GRAIN_LINE_COUNT",
    "RIVER_TEXT_SIZE_RATIO",
    "FRAME_INTERVAL_MS",
    "MOVE_ANIMATION_SECONDS",
    "AI_START_DELAY_MS",
    "MOVE_LIFT_SPACING_RATIO",
    "EFFECT_CAPTURE_SECONDS",
    "EFFECT_CHECK_SECONDS",
    "EFFECT_CHECKMATE_SECONDS",
    "RESULT_DIALOG_DELAY_MS",
    "WOOD_TOP_COLOR",
    "WOOD_MIDDLE_COLOR",
    "WOOD_BOTTOM_COLOR",
    "WOOD_BORDER_COLOR",
    "WOOD_GRAIN_COLOR",
    "GRID_COLOR",
    "BOARD_LACQUER_TOP",
    "BOARD_LACQUER_BOTTOM",
    "BOARD_FRAME_GOLD",
    "BOARD_FRAME_INK",
    "LAST_MOVE_COLOR",
    "SELECTION_COLOR",
    "LEGAL_TARGET_COLOR",
    "CHECK_COLOR",
    "RIVER_TEXT_COLOR",
    "PIECE_SHADOW_COLOR",
]
