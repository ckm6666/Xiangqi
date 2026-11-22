"""应用日志初始化。

日志写到 Windows 用户本地数据目录（QStandardPaths.AppLocalDataLocation）下的
``logs/xiangqi.log``，使用滚动文件，避免写入 exe 所在目录或泄露令牌。当前阶段
不记录账号/棋谱等敏感数据，只记录启动、会话错误和未捕获异常。
"""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QStandardPaths

from xiangqi.client.config import AppConfig

_LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
_HANDLER_MARK = "_xiangqi_logging_handler"
_LOG_MAX_BYTES = 1_000_000
_LOG_BACKUP_COUNT = 3


def _remove_previous_handlers(root: logging.Logger) -> None:
    """避免重复调用 initialize_logging 时叠加多个 handler。"""
    for handler in list(root.handlers):
        if getattr(handler, _HANDLER_MARK, False):
            root.removeHandler(handler)
            handler.close()


def initialize_logging(config: Optional[AppConfig] = None) -> Optional[Path]:
    """初始化滚动文件日志并返回日志路径；失败时不让应用崩溃。

    必须在 QApplication 创建且应用元信息设置后调用，这样 QStandardPaths
    才能定位到正确的 Xiangqi 数据目录。
    """
    config = config or AppConfig()
    level = getattr(logging, config.log_level, logging.INFO)
    root = logging.getLogger()
    _remove_previous_handlers(root)
    root.setLevel(level)

    base_dir = QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.AppLocalDataLocation
    )
    if not base_dir:
        # 极端环境下 QStandardPaths 可能为空；不回退到 exe 目录，改为不落盘。
        logging.getLogger(__name__).warning("无法定位本地应用数据目录，日志未落盘")
        return None

    log_path = Path(base_dir) / "logs" / "xiangqi.log"
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            log_path,
            maxBytes=_LOG_MAX_BYTES,
            backupCount=_LOG_BACKUP_COUNT,
            encoding="utf-8",
        )
        file_handler.setLevel(level)
        file_handler.setFormatter(logging.Formatter(_LOG_FORMAT))
        setattr(file_handler, _HANDLER_MARK, True)
        root.addHandler(file_handler)
    except OSError:
        logging.getLogger(__name__).exception("无法创建日志文件")
        return None

    # 源码运行时同时输出到控制台；--windowed 打包时 stderr 可能不可用。
    if sys.stderr is not None:
        stream_handler = logging.StreamHandler()
        stream_handler.setLevel(level)
        stream_handler.setFormatter(logging.Formatter(_LOG_FORMAT))
        setattr(stream_handler, _HANDLER_MARK, True)
        root.addHandler(stream_handler)

    return log_path


def install_exception_hook() -> None:
    """记录未捕获异常，避免带 GUI 的应用静默退出。"""

    def handle_exception(exc_type, exc_value, exc_traceback) -> None:
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return
        logging.getLogger("xiangqi").critical(
            "未捕获异常",
            exc_info=(exc_type, exc_value, exc_traceback),
        )

    sys.excepthook = handle_exception


__all__ = ["initialize_logging", "install_exception_hook"]
