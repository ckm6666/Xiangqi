"""Qt 测试环境：离屏平台与单例 QApplication。"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("XIANGQI_DISABLE_VOICE", "1")

_APP = None


def ensure_qt_app():
    """创建或复用进程内唯一的 QApplication。"""
    global _APP
    if _APP is None:
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance()
        if app is None:
            app = QApplication([])
        app.setApplicationName("Xiangqi")
        app.setOrganizationName("Xiangqi")
        _APP = app
    return _APP
