"""Qt 测试环境：离屏平台与单例 QApplication。"""

from __future__ import annotations

import os
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("XIANGQI_DISABLE_VOICE", "1")

_APP = None


def ensure_qt_app():
    """创建或复用进程内唯一的 QApplication。

    同时把 QSettings 重定向到临时 INI 文件，避免测试读到或写脏开发机
    上真实的用户偏好（例如“对话日志是否展开”）。
    """
    global _APP
    if _APP is None:
        from PySide6.QtCore import QSettings
        from PySide6.QtWidgets import QApplication

        settings_dir = os.path.join(
            tempfile.gettempdir(),
            f"xiangqi-test-settings-{os.getpid()}",
        )
        os.makedirs(settings_dir, exist_ok=True)
        QSettings.setDefaultFormat(QSettings.Format.IniFormat)
        QSettings.setPath(
            QSettings.Format.IniFormat,
            QSettings.Scope.UserScope,
            settings_dir,
        )
        app = QApplication.instance()
        if app is None:
            app = QApplication([])
        app.setApplicationName("Xiangqi")
        app.setOrganizationName("Xiangqi")
        _APP = app
    return _APP
