"""头像绘制、本地图片读取与上传编码（Qt）。

默认头像由 QPainter 程序化生成，不依赖外部图片文件；自定义头像会先
裁剪为正方形并缩放，再编码成 PNG 上传给服务端。
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import (
    QBuffer,
    QByteArray,
    QIODevice,
    QRectF,
    QSize,
    Qt,
)
from PySide6.QtGui import (
    QColor,
    QFont,
    QImage,
    QImageReader,
    QLinearGradient,
    QPainter,
    QPen,
    QPixmap,
)

from xiangqi.client.ui_theme import DISPLAY_FONT_FAMILY
from xiangqi.shared.profile import DEFAULT_AVATAR_IDS

#: 每个默认头像的 (字, 底色, 字色, 描边色)。
AVATAR_STYLES: dict[str, tuple[str, str, str, str]] = {
    "default:1": ("帥", "#9E3B2E", "#FFF6E8", "#E3D1A9"),
    "default:2": ("將", "#2B2722", "#F1E4CC", "#B8934E"),
    "default:3": ("棋", "#B8934E", "#2B2722", "#F8F0DF"),
    "default:4": ("弈", "#3F5648", "#F7EFE2", "#C9B99F"),
    "default:5": ("兵", "#6B4526", "#F3E6D2", "#D9C2A0"),
    "default:6": ("象", "#3C4A5A", "#F4EFE4", "#AFC0D2"),
}

_AVATAR_CACHE: dict[tuple[str, int, float], QPixmap] = {}


def normalize_avatar_id(avatar_id: object) -> str:
    """把未知/缺失的头像标识回退到第一张默认头像。"""
    if isinstance(avatar_id, str) and avatar_id in AVATAR_STYLES:
        return avatar_id
    return DEFAULT_AVATAR_IDS[0]


def render_default_avatar(
    avatar_id: object,
    size: int,
    *,
    dpr: float = 1.0,
) -> QPixmap:
    """绘制圆形默认头像；按 (标识, 尺寸, DPR) 缓存。"""
    key_id = normalize_avatar_id(avatar_id)
    size = max(8, int(size))
    dpr = max(1.0, float(dpr))
    key = (key_id, size, round(dpr, 2))
    cached = _AVATAR_CACHE.get(key)
    if cached is not None:
        return cached

    glyph, background, foreground, ring = AVATAR_STYLES[key_id]
    pixmap = QPixmap(round(size * dpr), round(size * dpr))
    pixmap.setDevicePixelRatio(dpr)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

    margin = max(0.8, size * 0.025)
    rect = QRectF(margin, margin, size - margin * 2, size - margin * 2)
    gradient = QLinearGradient(rect.topLeft(), rect.bottomRight())
    base = QColor(background)
    gradient.setColorAt(0.0, base.lighter(116))
    gradient.setColorAt(1.0, base.darker(112))
    painter.setPen(QPen(QColor(ring), max(0.9, size * 0.028)))
    painter.setBrush(gradient)
    painter.drawEllipse(rect)

    inner = rect.adjusted(
        size * 0.065, size * 0.065, -size * 0.065, -size * 0.065
    )
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.setPen(QPen(QColor(foreground), max(0.6, size * 0.014)))
    painter.setOpacity(0.42)
    painter.drawEllipse(inner)
    painter.setOpacity(1.0)

    font = QFont(DISPLAY_FONT_FAMILY)
    font.setPixelSize(max(9, int(size * 0.52)))
    font.setWeight(QFont.Weight.Normal)
    painter.setFont(font)
    painter.setPen(QColor(foreground))
    painter.drawText(
        QRectF(0.0, -size * 0.015, size, size),
        int(Qt.AlignmentFlag.AlignCenter),
        glyph,
    )

    painter.end()
    _AVATAR_CACHE[key] = pixmap
    return pixmap


def _square_image(image: QImage, size: int, dpr: float) -> QImage:
    """居中裁剪为正方形并缩放到目标物理尺寸。"""
    width = image.width()
    height = image.height()
    if width <= 0 or height <= 0:
        raise ValueError("图片尺寸无效")
    side = min(width, height)
    x = (width - side) // 2
    y = (height - side) // 2
    cropped = image.copy(x, y, side, side)
    target = max(8, int(round(size * dpr)))
    if cropped.width() != target:
        cropped = cropped.scaled(
            QSize(target, target),
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
    return cropped


def pixmap_from_image(
    image: QImage,
    size: int,
    *,
    dpr: float = 1.0,
) -> QPixmap:
    """把任意 QImage 转为圆形裁切前的方形头像位图。"""
    dpr = max(1.0, float(dpr))
    square = _square_image(image, max(8, int(size)), dpr)
    pixmap = QPixmap.fromImage(square)
    pixmap.setDevicePixelRatio(dpr)
    return pixmap


def load_avatar_image(path: str) -> QImage:
    """读取本地图片并应用 EXIF 方向；失败抛出 ValueError。"""
    reader = QImageReader(path)
    reader.setAutoTransform(True)
    image = reader.read()
    if image.isNull():
        raise ValueError(reader.errorString() or "无法读取图片")
    return image


def encode_png_bytes(image: QImage, size: int = 256) -> bytes:
    """裁剪并缩放为 ``size`` 正方形 PNG 字节。"""
    square = _square_image(image, size, 1.0)
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    if not square.save(buffer, "PNG"):
        raise ValueError("无法把图片编码为 PNG")
    buffer.close()
    return bytes(data)


def pixmap_from_png_bytes(
    data: bytes,
    size: int,
    *,
    dpr: float = 1.0,
) -> Optional[QPixmap]:
    """从服务端返回的 PNG 字节生成头像位图；坏数据返回 None。"""
    image = QImage.fromData(data)
    if image.isNull():
        return None
    try:
        return pixmap_from_image(image, size, dpr=dpr)
    except ValueError:
        return None


def avatar_sequence(count: int = 0) -> tuple[str, ...]:
    """返回可轮换的默认头像顺序；供界面装饰使用。"""
    if count <= 0:
        return DEFAULT_AVATAR_IDS
    start = count % len(DEFAULT_AVATAR_IDS)
    return DEFAULT_AVATAR_IDS[start:] + DEFAULT_AVATAR_IDS[:start]


__all__ = [
    "AVATAR_STYLES",
    "avatar_sequence",
    "encode_png_bytes",
    "load_avatar_image",
    "normalize_avatar_id",
    "pixmap_from_image",
    "pixmap_from_png_bytes",
    "render_default_avatar",
]
