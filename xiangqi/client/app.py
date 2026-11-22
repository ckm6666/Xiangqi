"""PySide6 桌面客户端初始化与启动入口。"""

from __future__ import annotations

import logging
import sys

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QApplication

from xiangqi.client.audio import initialize_audio
from xiangqi.client.config import AppConfig
from xiangqi.client.constants import (
    APP_NAME,
    APP_ORGANIZATION,
    APP_STORAGE_NAME,
    APP_VERSION,
)
from xiangqi.client.logging_setup import (
    initialize_logging,
    install_exception_hook,
)
from xiangqi.client.main_window import MainWindow
from xiangqi.client.theme_palette import (
    CINNABAR,
    GOLD,
    GOLD_DARK,
    INK_FAINT,
    PAPER_LIGHT,
    PIECE_BLACK_INK,
)
from xiangqi.client.ui_theme import (
    apply_app_theme,
    make_seal_pixmap,
    ui_assets_directory,
)
from xiangqi.client.voice import initialize_voice
from xiangqi.shared.errors import ConfigurationError


def create_app_icon() -> QIcon:
    """程序化生成水墨棋盘风格的应用图标。"""
    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

    painter.setPen(QPen(QColor(GOLD_DARK), 1.4))
    painter.setBrush(QColor(PAPER_LIGHT))
    painter.drawRoundedRect(QRectF(3.0, 3.0, 58.0, 58.0), 12.0, 12.0)
    painter.setPen(QPen(QColor(GOLD), 0.9))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawRoundedRect(QRectF(7.0, 7.0, 50.0, 50.0), 9.0, 9.0)

    painter.setPen(QPen(QColor(INK_FAINT), 0.8))
    for offset in (18.0, 32.0, 46.0):
        painter.drawLine(QPointF(12.0, offset), QPointF(52.0, offset))
        painter.drawLine(QPointF(offset, 12.0), QPointF(offset, 52.0))

    painter.setPen(QPen(QColor(CINNABAR), 0.9))
    painter.setBrush(QColor(CINNABAR))
    painter.drawEllipse(QPointF(26.0, 26.0), 9.0, 9.0)

    painter.setPen(QPen(QColor(PIECE_BLACK_INK), 0.9))
    painter.setBrush(QColor(PIECE_BLACK_INK))
    painter.drawEllipse(QPointF(40.0, 40.0), 9.0, 9.0)

    painter.setPen(QPen(QColor(PAPER_LIGHT), 0.8))
    painter.drawText(
        QRectF(17.0, 17.0, 18.0, 18.0),
        int(Qt.AlignmentFlag.AlignCenter),
        "帥",
    )
    painter.drawText(
        QRectF(31.0, 31.0, 18.0, 18.0),
        int(Qt.AlignmentFlag.AlignCenter),
        "將",
    )

    seal = make_seal_pixmap("象", 17, dpr=1.0)
    painter.drawPixmap(QPointF(43.0, 43.0), seal)
    painter.end()
    return QIcon(pixmap)


def main() -> int:
    """创建 QApplication、应用全局样式并启动主窗口。"""
    app = QApplication(sys.argv)

    # 应用元信息用于窗口标题、任务栏与 QStandardPaths 数据目录。
    app.setApplicationName(APP_STORAGE_NAME)
    app.setApplicationDisplayName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    app.setOrganizationName(APP_ORGANIZATION)

    # Fusion 风格可避免 Windows 原生主题干扰自定义 QSS 的圆角和配色。
    app.setStyle("Fusion")

    # 加载内置 OFL 字体并应用全局古风 QSS；失败时回退系统字体。
    theme_families = apply_app_theme(app)
    app.setWindowIcon(create_app_icon())

    # 配置只从环境变量读取非敏感项；坏配置不应阻止离线模式启动。
    config_error: Exception | None = None
    try:
        config = AppConfig.from_env()
    except ConfigurationError as exc:
        config = AppConfig()
        config_error = exc

    log_path = initialize_logging(config)
    install_exception_hook()
    logger = logging.getLogger("xiangqi.client.app")
    if config_error is not None:
        logger.warning("网络配置无效，回退到默认离线配置：%s", config_error)
    logger.info(
        "应用启动 version=%s env=%s online_configured=%s log=%s",
        APP_VERSION,
        config.environment,
        config.online_configured,
        log_path,
    )
    logger.info(
        "主题字体 families=%s body_fonts=%s assets=%s",
        theme_families,
        app.font().families(),
        ui_assets_directory(),
    )

    # 在窗口创建前初始化音频，让 QSettings/QStandardPaths 使用正确的应用元信息。
    audio_manager = initialize_audio()
    audio_manager.install_button_click_sounds(app)
    logger.info("音频初始化 available=%s", audio_manager.available)

    voice = initialize_voice()
    logger.info(
        "语音初始化 available=%s voice=%s",
        voice.available,
        voice.voice_name,
    )

    window = MainWindow(config=config)
    window.show()
    return app.exec()


__all__ = ["create_app_icon", "main"]
