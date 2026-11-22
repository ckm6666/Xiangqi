"""中文语音播报（QtTextToSpeech）。

Windows 上使用系统 SAPI/WinRT 中文语音播报“将军 / 吃 / 绝杀”。离屏测试
或显式设置 ``XIANGQI_DISABLE_VOICE`` / ``XIANGQI_DISABLE_AUDIO`` 时不创建
语音引擎；引擎不可用时静默降级，不影响游戏。
"""

from __future__ import annotations

import logging
import os
from typing import Optional

from PySide6.QtCore import QLocale, QObject
from PySide6.QtTextToSpeech import QTextToSpeech

from xiangqi.client.audio import get_audio_manager

logger = logging.getLogger(__name__)

VOICE_TEXTS: dict[str, str] = {
    "check": "将军",
    "capture": "吃",
    "checkmate": "绝杀",
}


def _voice_disabled() -> bool:
    if os.environ.get("XIANGQI_DISABLE_VOICE"):
        return True
    if os.environ.get("XIANGQI_DISABLE_AUDIO"):
        return True
    return os.environ.get("QT_QPA_PLATFORM", "").lower() == "offscreen"


class VoiceAnnouncer(QObject):
    """封装 QTextToSpeech；优先选择中文女声。"""

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._engine: Optional[QTextToSpeech] = None
        self._available = False
        self._voice_name = ""
        if _voice_disabled():
            return
        try:
            engine = QTextToSpeech(self)
            voices = engine.availableVoices()
            chinese = [
                voice
                for voice in voices
                if voice.locale().language() == QLocale.Language.Chinese
            ]
            if not chinese:
                logger.info("未找到中文语音，语音播报已禁用")
                engine.deleteLater()
                return
            preferred = next(
                (
                    voice
                    for voice in chinese
                    if "Huihui" in voice.name() or "Yaoyao" in voice.name()
                ),
                chinese[0],
            )
            engine.setVoice(preferred)
            engine.setLocale(preferred.locale())
            engine.setRate(0.0)
            engine.setVolume(0.9)
            self._engine = engine
            self._available = True
            self._voice_name = preferred.name()
        except Exception:
            logger.exception("初始化中文语音失败")

    @property
    def available(self) -> bool:
        return self._available

    @property
    def voice_name(self) -> str:
        return self._voice_name

    def say(self, kind: str) -> None:
        """播报指定事件；不可用或静音时静默返回。"""
        text = VOICE_TEXTS.get(kind)
        if not text or not self._available or self._engine is None:
            return
        try:
            manager = get_audio_manager()
            if manager.muted:
                return
            volume = max(0.0, min(1.0, manager.sfx_volume / 100.0))
            if volume <= 0.0:
                return
            self._engine.setVolume(volume)
            self._engine.say(text)
        except Exception:
            logger.exception("语音播报失败")

    def shutdown(self) -> None:
        if self._engine is not None:
            try:
                self._engine.stop()
            except RuntimeError:
                pass
            self._engine = None
        self._available = False


_announcer: Optional[VoiceAnnouncer] = None


def initialize_voice() -> VoiceAnnouncer:
    """创建应用级语音播报器，并在退出时停止。"""
    global _announcer
    if _announcer is None:
        _announcer = VoiceAnnouncer()
        from PySide6.QtCore import QCoreApplication

        app = QCoreApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(_announcer.shutdown)
    return _announcer


def get_voice_announcer() -> VoiceAnnouncer:
    """懒获取语音播报器；离屏/静音环境返回不可用实例。"""
    global _announcer
    if _announcer is None:
        _announcer = VoiceAnnouncer()
    return _announcer


__all__ = [
    "VOICE_TEXTS",
    "VoiceAnnouncer",
    "initialize_voice",
    "get_voice_announcer",
]
