"""古风界面主题：资源路径、字体、宣纸背景、印章与自绘控件。

设计约定：
* QSS 只负责颜色/字体/状态，不引用图片 URL；所有画作、纸纹、印章、云纹
  均通过 QPainter 绘制，避免 PyInstaller / 工作目录导致的资源路径问题。
* 所有带 DPR 的位图按 ``devicePixelRatioF`` 渲染并缓存，缩放时重建。
* 素材缺失时静默降级为纯宣纸底色，界面仍可正常使用。
"""

from __future__ import annotations

import logging
import os
import random
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Optional

from PySide6.QtCore import QPointF, QRect, QRectF, QSize, Qt
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QFontDatabase,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QRadialGradient,
)
from PySide6.QtWidgets import QApplication, QFrame, QWidget

from xiangqi.client.styles import APP_STYLE
from xiangqi.client.theme_palette import (
    CINNABAR,
    CINNABAR_DARK,
    GOLD,
    GOLD_PALE,
    INK,
    INK_MUTED,
    INK_SOFT,
    PAPER,
    PAPER_DEEP,
    PAPER_LIGHT,
    PAPER_MUTED,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 素材与字体
# ---------------------------------------------------------------------------
ASSET_MENU_BACKDROP = "menu_landscape.jpg"
ASSET_GAME_SCROLL = "game_scroll.jpg"
ASSET_RESULT_BACKDROP = "result_landscape.jpg"
ASSET_PLUM = "plum.jpg"
ASSET_BAMBOO = "bamboo.jpg"
ASSET_ONLINE_BACKDROP = "online_landscape.jpg"

FONT_MA_SHAN_ZHENG_FILE = "MaShanZheng-Regular.ttf"
FONT_ZCOOL_XIAOWEI_FILE = "ZCOOLXiaoWei-Regular.ttf"
DISPLAY_FONT_FAMILY = "Ma Shan Zheng"
BODY_FONT_FAMILY = "ZCOOL XiaoWei"


def assets_root() -> Path:
    """返回客户端素材根目录；兼容源码与 PyInstaller 单文件。"""
    if getattr(sys, "frozen", False):
        base = Path(
            getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent)
        )
        return base / "xiangqi" / "client" / "assets"
    return Path(__file__).resolve().parent / "assets"


def ui_assets_directory() -> Path:
    return assets_root() / "ui"


def fonts_directory() -> Path:
    return assets_root() / "fonts"


def find_ui_asset(name: str) -> Optional[Path]:
    path = ui_assets_directory() / name
    return path if path.is_file() else None


def find_font_asset(name: str) -> Optional[Path]:
    path = fonts_directory() / name
    return path if path.is_file() else None


def load_theme_fonts() -> tuple[str, ...]:
    """加载内置的 OFL 字体并返回实际 family 名；失败时返回已加载部分。"""
    if QApplication.instance() is None:
        return ()
    families: list[str] = []
    canonical = {
        FONT_MA_SHAN_ZHENG_FILE: DISPLAY_FONT_FAMILY,
        FONT_ZCOOL_XIAOWEI_FILE: BODY_FONT_FAMILY,
    }
    for filename in (FONT_MA_SHAN_ZHENG_FILE, FONT_ZCOOL_XIAOWEI_FILE):
        path = find_font_asset(filename)
        if path is None:
            logger.warning("主题字体缺失：%s", filename)
            continue
        font_id = QFontDatabase.addApplicationFont(str(path))
        if font_id < 0:
            logger.warning("主题字体加载失败：%s", path)
            continue
        actual = QFontDatabase.applicationFontFamilies(font_id)
        # 部分中文字体在系统里会注册多个别名；优先保证 canonical 名称存在。
        for family in (canonical[filename], *actual):
            if family and family not in families:
                families.append(family)
    return tuple(families)


def _ensure_system_classical_fonts() -> None:
    """在 Windows 上显式加载仿宋/楷体。

    这两款系统字体对“回”等字形的呈现比 ZCOOL XiaoWei 的显示字形更清楚；
    只加载本机文件，不随项目分发。非 Windows 或文件缺失时由回退链处理。
    """
    if sys.platform != "win32":
        return
    fonts_dir = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
    for filename in ("simfang.ttf", "simkai.ttf"):
        path = fonts_dir / filename
        if path.is_file():
            QFontDatabase.addApplicationFont(str(path))


def apply_app_theme(app: QApplication) -> tuple[str, ...]:
    """加载主题字体、设置全局字体与 QSS；返回内置主题字体的 family。"""
    _ensure_system_classical_fonts()
    families = load_theme_fonts()
    # 正文字体优先使用仿宋/楷体（古雅且小字号清晰），ZCOOL XiaoWei 作为
    # 项目内置的跨环境回退，保证无中文系统字体时仍有 CJK 覆盖。
    font = QFont()
    font.setFamilies(
        [
            "FangSong",
            "KaiTi",
            "Microsoft YaHei UI",
            "ZCOOL XiaoWei",
            "Microsoft YaHei",
            "Segoe UI",
        ]
    )
    font.setPointSize(10)
    app.setFont(font)
    app.setStyleSheet(APP_STYLE)
    return families


# 棋面汉字优先使用楷体/仿宋，Ma Shan Zheng 仅作最后的书法回退；小字号
# 下书法字体的辨识度不足，不适合作为棋子主字体。
PIECE_FONT_FAMILIES: Final[tuple[str, ...]] = (
    "KaiTi",
    "STKaiti",
    "FangSong",
    "ZCOOL XiaoWei",
    "Ma Shan Zheng",
    "Microsoft YaHei UI",
    "Microsoft YaHei",
)


def make_piece_font(pixel_size: int) -> QFont:
    """创建用于棋子汉字的字体。"""
    font = QFont()
    font.setFamilies(list(PIECE_FONT_FAMILIES))
    font.setPixelSize(max(1, int(pixel_size)))
    font.setWeight(QFont.Weight.DemiBold)
    return font


# ---------------------------------------------------------------------------
# 背景规格
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class BackdropSpec:
    """描述一页的水墨背景构图。"""

    image: Optional[str] = None
    image_opacity: float = 0.55
    source_crop: tuple[float, float, float, float] = (0.0, 0.0, 1.0, 1.0)
    focus: tuple[float, float] = (0.5, 0.5)
    band: Optional[str] = None
    band_opacity: float = 0.45
    band_scale: float = 1.15
    band_crop: tuple[float, float, float, float] = (0.0, 0.0, 1.0, 1.0)
    band_height_ratio: float = 0.26
    wash_alpha: int = 72
    tint: Optional[str] = None
    tint_alpha: int = 0
    texture: bool = True
    vignette: bool = True
    frame: bool = True
    frame_inset: int = 12


MENU_BACKDROP_SPEC = BackdropSpec(
    image=ASSET_MENU_BACKDROP,
    image_opacity=0.78,
    source_crop=(0.025, 0.025, 0.95, 0.95),
    focus=(0.5, 0.42),
    wash_alpha=66,
    frame=True,
    frame_inset=12,
)

GAME_BACKDROP_SPEC = BackdropSpec(
    band=ASSET_GAME_SCROLL,
    band_opacity=0.42,
    band_scale=1.12,
    band_crop=(0.30, 0.0, 0.70, 1.0),
    band_height_ratio=0.24,
    wash_alpha=34,
    frame=False,
)

ONLINE_BACKDROP_SPEC = BackdropSpec(
    image=ASSET_ONLINE_BACKDROP,
    image_opacity=0.62,
    source_crop=(0.17, 0.10, 0.66, 0.82),
    focus=(0.5, 0.42),
    wash_alpha=86,
    frame=True,
    frame_inset=12,
)

# ---------------------------------------------------------------------------
# 位图缓存与基础绘制
# ---------------------------------------------------------------------------
_pixmap_cache: dict[str, QPixmap] = {}
_texture_cache: dict[float, QPixmap] = {}
_seal_cache: dict[tuple[str, int, str, float], QPixmap] = {}
_divider_cache: dict[tuple[int, int, float], QPixmap] = {}
_sound_icon_cache: dict[tuple[bool, int, float], QPixmap] = {}
_missing_logged: set[str] = set()


def _c(color: str, alpha: int = 255) -> QColor:
    """按十六进制色名创建带透明度的 QColor。"""
    result = QColor(color)
    result.setAlpha(max(0, min(255, int(alpha))))
    return result


def _load_ui_pixmap(name: str) -> QPixmap:
    cached = _pixmap_cache.get(name)
    if cached is not None:
        return cached
    path = find_ui_asset(name)
    if path is None:
        if name not in _missing_logged:
            _missing_logged.add(name)
            logger.warning("UI 素材缺失：%s", name)
        pixmap = QPixmap()
    else:
        pixmap = QPixmap(str(path))
        if pixmap.isNull():
            logger.warning("UI 素材无法读取：%s", path)
    _pixmap_cache[name] = pixmap
    return pixmap


def _crop_pixmap(
    pixmap: QPixmap, crop: tuple[float, float, float, float]
) -> QPixmap:
    if pixmap.isNull():
        return pixmap
    left, top, width, height = crop
    left = max(0.0, min(1.0, left))
    top = max(0.0, min(1.0, top))
    width = max(0.01, min(1.0 - left, width))
    height = max(0.01, min(1.0 - top, height))
    rect = QRect(
        round(left * pixmap.width()),
        round(top * pixmap.height()),
        max(1, round(width * pixmap.width())),
        max(1, round(height * pixmap.height())),
    )
    return pixmap.copy(rect)


def _draw_cover(
    painter: QPainter,
    target: QRectF,
    pixmap: QPixmap,
    focus: tuple[float, float],
    opacity: float,
    mode: QPainter.CompositionMode = (
        QPainter.CompositionMode.CompositionMode_SourceOver
    ),
) -> None:
    if pixmap.isNull() or opacity <= 0:
        return
    scale = max(
        target.width() / max(1, pixmap.width()),
        target.height() / max(1, pixmap.height()),
    )
    draw_w = pixmap.width() * scale
    draw_h = pixmap.height() * scale
    x = target.left() - (draw_w - target.width()) * focus[0]
    y = target.top() - (draw_h - target.height()) * focus[1]

    painter.save()
    painter.setOpacity(opacity)
    painter.setCompositionMode(mode)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
    painter.drawPixmap(
        QRectF(x, y, draw_w, draw_h), pixmap, QRectF(pixmap.rect())
    )
    painter.restore()


def _paint_paper_base(painter: QPainter, width: float, height: float) -> None:
    gradient = QLinearGradient(0.0, 0.0, 0.0, height)
    gradient.setColorAt(0.0, QColor(PAPER_LIGHT))
    gradient.setColorAt(0.46, QColor(PAPER))
    gradient.setColorAt(1.0, QColor(PAPER_DEEP))
    painter.fillRect(QRectF(0.0, 0.0, width, height), QBrush(gradient))


def paper_texture_tile(dpr: float = 1.0) -> QPixmap:
    """生成可平铺的宣纸纤维纹理（确定性、按 DPR 缓存）。"""
    key = round(max(1.0, dpr), 2)
    cached = _texture_cache.get(key)
    if cached is not None:
        return cached

    size = 180
    pixmap = QPixmap(round(size * key), round(size * key))
    pixmap.setDevicePixelRatio(key)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

    rng = random.Random(0x6C4D)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    for _ in range(90):
        x = rng.uniform(0, size)
        y = rng.uniform(0, size)
        length = rng.uniform(4, 20)
        slope = rng.uniform(-1.0, 1.0)
        color = QColor(90, 70, 45, rng.randint(5, 15))
        painter.setPen(QPen(color, 0.6))
        painter.drawLine(QPointF(x, y), QPointF(x + length, y + slope))

    painter.setPen(Qt.PenStyle.NoPen)
    for _ in range(150):
        x = rng.uniform(0, size)
        y = rng.uniform(0, size)
        color = QColor(80, 62, 40, rng.randint(3, 9))
        painter.setBrush(color)
        painter.drawRect(QRectF(x, y, 1.0, 1.0))

    for _ in range(4):
        x = rng.uniform(0, size)
        y = rng.uniform(0, size)
        radius = rng.uniform(18, 42)
        stain = QRadialGradient(QPointF(x, y), radius)
        stain.setColorAt(0.0, QColor(120, 95, 60, 4))
        stain.setColorAt(1.0, QColor(120, 95, 60, 0))
        painter.setBrush(QBrush(stain))
        painter.drawEllipse(QPointF(x, y), radius, radius * 0.7)

    painter.end()
    _texture_cache[key] = pixmap
    return pixmap


def _paint_texture(
    painter: QPainter, width: float, height: float, dpr: float
) -> None:
    tile = paper_texture_tile(dpr)
    painter.drawTiledPixmap(QRectF(0, 0, width, height), tile, QPointF(0, 0))


def make_seal_pixmap(
    text: str,
    size: int,
    *,
    variant: str = "seal",
    dpr: float = 1.0,
) -> QPixmap:
    """生成朱砂印章位图（白文方印 + 轻微做旧）。"""
    key = (text, size, variant, round(max(1.0, dpr), 2))
    cached = _seal_cache.get(key)
    if cached is not None:
        return cached

    pixmap = QPixmap(round(size * dpr), round(size * dpr))
    pixmap.setDevicePixelRatio(dpr)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

    rect = QRectF(0.8, 0.8, size - 1.6, size - 1.6)
    radius = max(1.5, size * 0.10)
    painter.setPen(QPen(QColor(CINNABAR_DARK), max(0.8, size * 0.025)))
    painter.setBrush(QColor(CINNABAR))
    painter.drawRoundedRect(rect, radius, radius)

    inner = rect.adjusted(size * 0.09, size * 0.09, -size * 0.09, -size * 0.09)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.setPen(QPen(QColor(PAPER_LIGHT), max(0.7, size * 0.022)))
    painter.drawRect(inner)

    font = QFont(DISPLAY_FONT_FAMILY)
    font.setPixelSize(max(8, int(size * 0.58)))
    font.setWeight(QFont.Weight.Normal)
    painter.setFont(font)
    painter.setPen(QColor(PAPER_LIGHT))
    painter.drawText(
        QRectF(0.0, -size * 0.02, size, size),
        int(Qt.AlignmentFlag.AlignCenter),
        text,
    )

    # 做旧斑点：只改变红色/纸色，保持小尺寸下清晰。
    rng = random.Random(0x5EA1 + size + len(text))
    painter.setPen(Qt.PenStyle.NoPen)
    for _ in range(max(6, size // 5)):
        x = rng.uniform(2.0, size - 2.0)
        y = rng.uniform(2.0, size - 2.0)
        if rng.random() < 0.55:
            painter.setBrush(_c(CINNABAR_DARK, rng.randint(18, 45)))
        else:
            painter.setBrush(_c(PAPER_LIGHT, rng.randint(12, 30)))
        radius = rng.uniform(0.4, 1.1)
        painter.drawEllipse(QPointF(x, y), radius, radius)

    painter.end()
    _seal_cache[key] = pixmap
    return pixmap


def make_ink_divider(
    width: int, height: int = 16, *, dpr: float = 1.0
) -> QPixmap:
    """生成一笔淡墨分隔线，中心缀一枚小金菱。"""
    key = (width, height, round(max(1.0, dpr), 2))
    cached = _divider_cache.get(key)
    if cached is not None:
        return cached

    pixmap = QPixmap(round(width * dpr), round(height * dpr))
    pixmap.setDevicePixelRatio(dpr)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

    gradient = QLinearGradient(0.0, 0.0, width, 0.0)
    gradient.setColorAt(0.0, _c(INK_SOFT, 0))
    gradient.setColorAt(0.5, _c(INK_SOFT, 150))
    gradient.setColorAt(1.0, _c(INK_SOFT, 0))
    painter.setPen(QPen(QBrush(gradient), 1.1))
    y = height / 2.0
    painter.drawLine(QPointF(6.0, y), QPointF(width - 6.0, y))

    center = width / 2.0
    diamond = QPainterPath(QPointF(center, y - 3.8))
    diamond.lineTo(QPointF(center + 3.8, y))
    diamond.lineTo(QPointF(center, y + 3.8))
    diamond.lineTo(QPointF(center - 3.8, y))
    diamond.closeSubpath()
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(_c(GOLD, 210))
    painter.drawPath(diamond)

    painter.end()
    _divider_cache[key] = pixmap
    return pixmap


def _fade_top_pixmap(
    source: QPixmap,
    target_width: int,
    target_height: int,
    dpr: float,
    fade_ratio: float = 0.58,
) -> QPixmap:
    """把横幅缩放后用透明度遮罩让上缘淡入纸面。"""
    width = max(1, int(target_width))
    height = max(1, int(target_height))
    pixmap = QPixmap(round(width * dpr), round(height * dpr))
    pixmap.setDevicePixelRatio(dpr)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
    painter.drawPixmap(
        QRectF(0, 0, width, height), source, QRectF(source.rect())
    )
    painter.setCompositionMode(
        QPainter.CompositionMode.CompositionMode_DestinationIn
    )
    fade = QLinearGradient(0.0, 0.0, 0.0, height)
    fade.setColorAt(0.0, _c("#FFFFFF", 0))
    fade.setColorAt(max(0.05, min(1.0, fade_ratio)), _c("#FFFFFF", 255))
    fade.setColorAt(1.0, _c("#FFFFFF", 255))
    painter.fillRect(QRectF(0, 0, width, height), QBrush(fade))
    painter.end()
    return pixmap


def _feathered_pixmap(
    source: QPixmap,
    target_width: int,
    target_height: int,
    dpr: float,
    *,
    feather_left: float = 0.0,
    feather_right: float = 0.0,
    feather_top: float = 0.0,
) -> QPixmap:
    """把画作缩放到目标尺寸并羽化指定边缘，避免矩形贴片感。"""
    width = max(1, int(target_width))
    height = max(1, int(target_height))
    pixmap = QPixmap(round(width * dpr), round(height * dpr))
    pixmap.setDevicePixelRatio(dpr)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
    painter.drawPixmap(
        QRectF(0, 0, width, height), source, QRectF(source.rect())
    )
    painter.setCompositionMode(
        QPainter.CompositionMode.CompositionMode_DestinationIn
    )

    if feather_left > 0:
        gradient = QLinearGradient(0.0, 0.0, feather_left, 0.0)
        gradient.setColorAt(0.0, _c("#FFFFFF", 0))
        gradient.setColorAt(1.0, _c("#FFFFFF", 255))
        painter.fillRect(
            QRectF(0.0, 0.0, feather_left, height), QBrush(gradient)
        )
    if feather_right > 0:
        gradient = QLinearGradient(
            width - feather_right, 0.0, width, 0.0
        )
        gradient.setColorAt(0.0, _c("#FFFFFF", 255))
        gradient.setColorAt(1.0, _c("#FFFFFF", 0))
        painter.fillRect(
            QRectF(
                width - feather_right, 0.0, feather_right, height
            ),
            QBrush(gradient),
        )
    if feather_top > 0:
        gradient = QLinearGradient(0.0, 0.0, 0.0, feather_top)
        gradient.setColorAt(0.0, _c("#FFFFFF", 0))
        gradient.setColorAt(1.0, _c("#FFFFFF", 255))
        painter.fillRect(
            QRectF(0.0, 0.0, width, feather_top), QBrush(gradient)
        )

    painter.end()
    return pixmap


def make_sound_icon(
    muted: bool, size: int = 18, *, dpr: float = 1.0
) -> QPixmap:
    """水墨风格的声音图标；静音时以朱砂斜线标记。"""
    key = (bool(muted), size, round(max(1.0, dpr), 2))
    cached = _sound_icon_cache.get(key)
    if cached is not None:
        return cached

    pixmap = QPixmap(round(size * dpr), round(size * dpr))
    pixmap.setDevicePixelRatio(dpr)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

    ink = QColor(INK_SOFT)
    body = QPainterPath(QPointF(size * 0.16, size * 0.38))
    body.lineTo(size * 0.34, size * 0.38)
    body.lineTo(size * 0.56, size * 0.18)
    body.lineTo(size * 0.56, size * 0.82)
    body.lineTo(size * 0.34, size * 0.62)
    body.lineTo(size * 0.16, size * 0.62)
    body.closeSubpath()
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(ink)
    painter.drawPath(body)

    if not muted:
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(ink, max(1.0, size * 0.075)))
        painter.drawArc(
            QRectF(size * 0.52, size * 0.28, size * 0.30, size * 0.44),
            -60 * 16,
            120 * 16,
        )
        painter.drawArc(
            QRectF(size * 0.62, size * 0.16, size * 0.40, size * 0.68),
            -55 * 16,
            110 * 16,
        )
    else:
        painter.setPen(
            QPen(
                QColor(CINNABAR),
                max(1.4, size * 0.10),
                Qt.PenStyle.SolidLine,
                Qt.PenCapStyle.RoundCap,
            )
        )
        painter.drawLine(
            QPointF(size * 0.70, size * 0.28),
            QPointF(size * 0.90, size * 0.72),
        )
        painter.drawLine(
            QPointF(size * 0.90, size * 0.28),
            QPointF(size * 0.70, size * 0.72),
        )

    painter.end()
    _sound_icon_cache[key] = pixmap
    return pixmap


def paint_corner_ornament(
    painter: QPainter,
    rect: QRectF,
    corner: str,
    color: QColor,
    *,
    size: float = 14.0,
    inset: float = 4.0,
) -> None:
    """在矩形四角绘制简洁的“回纹”角饰。"""
    if size <= 2:
        return
    path = QPainterPath()
    path.moveTo(0.0, size * 0.45)
    path.lineTo(size * 0.45, size * 0.45)
    path.lineTo(size * 0.45, 0.0)
    path.moveTo(0.0, size * 0.82)
    path.lineTo(size * 0.82, size * 0.82)
    path.lineTo(size * 0.82, 0.0)

    painter.save()
    if corner in ("tl", "bl"):
        x = rect.left() + inset
    else:
        x = rect.right() - inset - size
    if corner in ("tl", "tr"):
        y = rect.top() + inset
    else:
        y = rect.bottom() - inset - size

    painter.translate(x, y)
    if corner in ("tr", "br"):
        painter.translate(size, 0.0)
        painter.scale(-1.0, 1.0)
    if corner in ("bl", "br"):
        painter.translate(0.0, size)
        painter.scale(1.0, -1.0)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.setPen(QPen(color, max(0.8, size * 0.055)))
    painter.drawPath(path)
    painter.restore()


# ---------------------------------------------------------------------------
# 页面背景
# ---------------------------------------------------------------------------
def render_backdrop(
    size: QSize, dpr: float, spec: BackdropSpec
) -> QPixmap:
    """按规格渲染一页完整背景（宣纸 + 水墨 + 纹理 + 边框）。"""
    width = max(1, size.width())
    height = max(1, size.height())
    dpr = max(1.0, dpr)

    pixmap = QPixmap(round(width * dpr), round(height * dpr))
    pixmap.setDevicePixelRatio(dpr)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

    _paint_paper_base(painter, width, height)

    if spec.image:
        source = _crop_pixmap(
            _load_ui_pixmap(spec.image), spec.source_crop
        )
        _draw_cover(
            painter,
            QRectF(0, 0, width, height),
            source,
            spec.focus,
            spec.image_opacity,
            QPainter.CompositionMode.CompositionMode_Multiply,
        )

    if spec.band:
        band = _crop_pixmap(
            _load_ui_pixmap(spec.band), spec.band_crop
        )
        if not band.isNull():
            target_w = width * spec.band_scale
            target_h = target_w * band.height() / max(1, band.width())
            max_h = height * spec.band_height_ratio
            if target_h > max_h:
                scale = max_h / target_h
                target_w *= scale
                target_h *= scale
            left = (width - target_w) / 2.0
            top = height - target_h
            masked_band = _fade_top_pixmap(
                band,
                int(round(target_w)),
                int(round(target_h)),
                dpr,
                0.58,
            )
            painter.save()
            painter.setOpacity(spec.band_opacity)
            painter.setCompositionMode(
                QPainter.CompositionMode.CompositionMode_Multiply
            )
            painter.drawPixmap(
                QRectF(left, top, target_w, target_h),
                masked_band,
                QRectF(masked_band.rect()),
            )
            painter.restore()

    if spec.tint and spec.tint_alpha > 0:
        tint = QColor(spec.tint)
        tint.setAlpha(spec.tint_alpha)
        painter.fillRect(QRectF(0, 0, width, height), tint)

    if spec.wash_alpha > 0:
        wash = QColor(PAPER)
        wash.setAlpha(spec.wash_alpha)
        painter.fillRect(QRectF(0, 0, width, height), wash)

    if spec.texture:
        _paint_texture(painter, width, height, dpr)

    if spec.vignette:
        radius = max(width, height) * 0.72
        vignette = QRadialGradient(
            QPointF(width * 0.5, height * 0.42), radius
        )
        vignette.setColorAt(0.0, _c(INK, 0))
        vignette.setColorAt(0.55, _c(INK, 0))
        vignette.setColorAt(1.0, _c(INK, 24))
        painter.fillRect(QRectF(0, 0, width, height), QBrush(vignette))

    if spec.frame:
        inset = float(spec.frame_inset)
        outer = QRectF(inset, inset, width - inset * 2, height - inset * 2)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(_c(GOLD, 155), 1.2))
        painter.drawRect(outer)
        inner = outer.adjusted(4.0, 4.0, -4.0, -4.0)
        painter.setPen(QPen(_c(INK, 55), 0.9))
        painter.drawRect(inner)
        gold = _c(GOLD, 120)
        paint_corner_ornament(painter, outer, "tl", gold, size=16, inset=0)
        paint_corner_ornament(painter, outer, "tr", gold, size=16, inset=0)
        paint_corner_ornament(painter, outer, "bl", gold, size=16, inset=0)
        paint_corner_ornament(painter, outer, "br", gold, size=16, inset=0)

    painter.end()
    return pixmap


def render_result_backdrop(
    size: QSize, dpr: float, kind: str
) -> QPixmap:
    """渲染终局弹窗背景：胜利/失败/平局各有不同色调与角饰。"""
    width = max(1, size.width())
    height = max(1, size.height())
    dpr = max(1.0, dpr)

    pixmap = QPixmap(round(width * dpr), round(height * dpr))
    pixmap.setDevicePixelRatio(dpr)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

    _paint_paper_base(painter, width, height)

    landscape = _crop_pixmap(
        _load_ui_pixmap(ASSET_RESULT_BACKDROP), (0.05, 0.06, 0.90, 0.90)
    )
    _draw_cover(
        painter,
        QRectF(0, 0, width, height),
        landscape,
        (0.5, 0.44),
        0.72,
        QPainter.CompositionMode.CompositionMode_Multiply,
    )

    tint_color = {
        "win": "GOLD",
        "lose": "DAI_GREEN",
        "draw": "INK_MUTED",
    }.get(kind, "INK_MUTED")
    tint_map = {
        "GOLD": GOLD,
        "DAI_GREEN": "#5D6B63",
        "INK_MUTED": INK_MUTED,
    }
    tint = QColor(tint_map[tint_color])
    tint.setAlpha({"win": 30, "lose": 28, "draw": 10}.get(kind, 10))
    painter.fillRect(QRectF(0, 0, width, height), tint)

    wash = QColor(PAPER)
    wash.setAlpha(86)
    painter.fillRect(QRectF(0, 0, width, height), wash)

    def draw_corner_art(
        asset: str, anchor_right: bool, opacity: float
    ) -> None:
        art = _crop_pixmap(
            _load_ui_pixmap(asset), (0.02, 0.045, 0.96, 0.91)
        )
        if art.isNull() or opacity <= 0:
            return
        target_h = height * 0.62
        scale = target_h / max(1, art.height())
        target_w = art.width() * scale
        x = (width - target_w - 4.0) if anchor_right else 4.0
        y = height - target_h + 8.0
        feather = target_w * 0.48
        feathered = _feathered_pixmap(
            art,
            int(round(target_w)),
            int(round(target_h)),
            dpr,
            feather_left=feather if anchor_right else 0.0,
            feather_right=0.0 if anchor_right else feather,
            feather_top=target_h * 0.24,
        )
        painter.save()
        painter.setOpacity(opacity)
        painter.setCompositionMode(
            QPainter.CompositionMode.CompositionMode_Multiply
        )
        painter.drawPixmap(
            QRectF(x, y, target_w, target_h),
            feathered,
            QRectF(feathered.rect()),
        )
        painter.restore()

    if kind == "win":
        draw_corner_art(ASSET_PLUM, True, 0.48)
    elif kind == "lose":
        draw_corner_art(ASSET_BAMBOO, False, 0.48)
    else:
        draw_corner_art(ASSET_PLUM, True, 0.16)
        draw_corner_art(ASSET_BAMBOO, False, 0.16)

    # 中央再铺一层纸张，保证标题/说明文字对比度。
    center_wash = QRadialGradient(
        QPointF(width * 0.5, height * 0.48), max(width, height) * 0.56
    )
    c1 = QColor(PAPER)
    c1.setAlpha(120)
    c2 = QColor(PAPER)
    c2.setAlpha(0)
    center_wash.setColorAt(0.0, c1)
    center_wash.setColorAt(1.0, c2)
    painter.fillRect(QRectF(0, 0, width, height), QBrush(center_wash))

    _paint_texture(painter, width, height, dpr)

    vignette = QRadialGradient(
        QPointF(width * 0.5, height * 0.45), max(width, height) * 0.75
    )
    vignette.setColorAt(0.0, _c(INK, 0))
    vignette.setColorAt(0.55, _c(INK, 0))
    vignette.setColorAt(1.0, _c(INK, 26))
    painter.fillRect(QRectF(0, 0, width, height), QBrush(vignette))

    inset = 12.0
    outer = QRectF(inset, inset, width - inset * 2, height - inset * 2)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.setPen(QPen(_c(GOLD, 170), 1.3))
    painter.drawRect(outer)
    inner = outer.adjusted(4.0, 4.0, -4.0, -4.0)
    painter.setPen(QPen(_c(INK, 70), 0.9))
    painter.drawRect(inner)
    gold = _c(GOLD, 130)
    for corner in ("tl", "tr", "bl", "br"):
        paint_corner_ornament(painter, outer, corner, gold, size=20, inset=0)

    painter.end()
    return pixmap


class InkBackdrop(QWidget):
    """以水墨宣纸为背景的页面容器。"""

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        *,
        spec: BackdropSpec = MENU_BACKDROP_SPEC,
    ) -> None:
        super().__init__(parent)
        self._spec = spec
        self._cache: Optional[QPixmap] = None
        self._cache_key: Optional[tuple[int, int, float, BackdropSpec]] = None
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self.setAutoFillBackground(False)

    def set_spec(self, spec: BackdropSpec) -> None:
        if spec == self._spec:
            return
        self._spec = spec
        self._cache = None
        self._cache_key = None
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt 接口
        del event
        width = self.width()
        height = self.height()
        if width <= 0 or height <= 0:
            return
        dpr = max(1.0, self.devicePixelRatioF())
        key = (width, height, round(dpr, 3), self._spec)
        if self._cache is None or self._cache_key != key:
            self._cache = render_backdrop(QSize(width, height), dpr, self._spec)
            self._cache_key = key
        painter = QPainter(self)
        painter.drawPixmap(
            QRectF(0, 0, width, height),
            self._cache,
            QRectF(self._cache.rect()),
        )
        painter.end()


class RicePaperCard(QFrame):
    """自绘宣纸卡片：双线墨框、金线、回纹角与朱砂印。"""

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        *,
        seal_text: Optional[str] = "弈",
        shadow: bool = True,
        corner_motifs: bool = True,
        opaque: bool = False,
    ) -> None:
        super().__init__(parent)
        self._seal_text = seal_text
        self._shadow = shadow
        self._corner_motifs = corner_motifs
        self._opaque = opaque
        self._seal_cache: Optional[QPixmap] = None
        self._seal_key: Optional[tuple[int, float]] = None
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt 接口
        del event
        width = float(self.width())
        height = float(self.height())
        if width <= 4 or height <= 4:
            return
        dpr = max(1.0, self.devicePixelRatioF())

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

        card = QRectF(4.0, 5.0, width - 8.0, height - 10.0)
        radius = 10.0

        if self._shadow:
            for offset, alpha in ((3.0, 26), (6.0, 16), (9.0, 8)):
                shadow_rect = card.adjusted(-1.0, offset * 0.4, 1.0, offset)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(30, 22, 12, alpha))
                painter.drawRoundedRect(
                    shadow_rect, radius + 1.0, radius + 1.0
                )

        path = QPainterPath()
        path.addRoundedRect(card, radius, radius)
        painter.setClipPath(path)

        # 半透明时让背景（主菜单的水墨底）透出来；浮层面板悬在任意内容
        # 之上，必须完全不透明，否则底下的文字会透上来。
        painter.fillRect(
            card,
            QColor(255, 252, 244, 255 if self._opaque else 230),
        )
        _paint_texture(painter, width, height, dpr)

        painter.setClipping(False)

        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(INK), 1.25))
        painter.drawRoundedRect(card, radius, radius)

        inner = card.adjusted(7.0, 7.0, -7.0, -7.0)
        painter.setPen(QPen(_c(GOLD, 150), 0.9))
        painter.drawRoundedRect(inner, radius - 3.0, radius - 3.0)

        if self._corner_motifs:
            gold = _c(GOLD, 95)
            for corner in ("tl", "tr", "bl", "br"):
                paint_corner_ornament(
                    painter, inner, corner, gold, size=16, inset=6
                )

        if self._seal_text:
            key = (int(width), round(dpr, 3))
            if self._seal_cache is None or self._seal_key != key:
                self._seal_cache = make_seal_pixmap(
                    self._seal_text, 36, dpr=dpr
                )
                self._seal_key = key
            seal_w = self._seal_cache.width() / dpr
            seal_h = self._seal_cache.height() / dpr
            painter.drawPixmap(
                QRectF(width - seal_w - 16.0, 14.0, seal_w, seal_h),
                self._seal_cache,
                QRectF(self._seal_cache.rect()),
            )

        painter.end()


__all__ = [
    "ASSET_BAMBOO",
    "ASSET_GAME_SCROLL",
    "ASSET_MENU_BACKDROP",
    "ASSET_ONLINE_BACKDROP",
    "ASSET_PLUM",
    "ASSET_RESULT_BACKDROP",
    "BODY_FONT_FAMILY",
    "BackdropSpec",
    "DISPLAY_FONT_FAMILY",
    "GAME_BACKDROP_SPEC",
    "InkBackdrop",
    "MENU_BACKDROP_SPEC",
    "ONLINE_BACKDROP_SPEC",
    "RicePaperCard",
    "apply_app_theme",
    "assets_root",
    "find_font_asset",
    "find_ui_asset",
    "fonts_directory",
    "load_theme_fonts",
    "make_ink_divider",
    "make_piece_font",
    "make_seal_pixmap",
    "make_sound_icon",
    "PIECE_FONT_FAMILIES",
    "paint_corner_ornament",
    "paper_texture_tile",
    "render_backdrop",
    "render_result_backdrop",
    "ui_assets_directory",
]
