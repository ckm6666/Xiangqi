"""测试替身：离屏环境使用的静音音频管理器。"""

from __future__ import annotations

from threading import Event
from typing import Optional

from PySide6.QtCore import QObject, QTimer, Signal

from xiangqi.client.transport import Transport
from xiangqi.shared.rules import Board, Side


class FakeVoiceAnnouncer:
    """记录“将军/吃/绝杀”播报顺序的语音替身。"""

    def __init__(self) -> None:
        self.available = True
        self.voice_name = "Fake"
        self.spoken: list[str] = []

    def say(self, kind: str) -> None:
        self.spoken.append(kind)

    def shutdown(self) -> None:
        pass


class FakeAuthApi(QObject):
    """记录登录/注册调用并允许测试注入结果的认证替身。"""

    authenticated = Signal(str, str, int)
    failed = Signal(str)

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self.calls: list[tuple[str, str, str, str]] = []

    def login(
        self,
        base_url: str,
        nickname: str,
        password: str,
    ) -> None:
        self.calls.append(("login", base_url, nickname, password))

    def register(
        self,
        base_url: str,
        nickname: str,
        password: str,
    ) -> None:
        self.calls.append(
            ("register", base_url, nickname, password)
        )

    def succeed(
        self,
        token: str = "token",
        nickname: str = "棋友",
        rating: int = 1200,
    ) -> None:
        self.authenticated.emit(token, nickname, rating)

    def fail(self, message: str = "登录失败") -> None:
        self.failed.emit(message)


class FakeAudioManager(QObject):
    """与 AudioManager 接口兼容的静音替身。"""

    state_changed = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.available = False
        self.muted = False
        self.bgm_volume = 60
        self.sfx_volume = 80
        self.played: list[str] = []

    def play_start(self) -> None:
        self.played.append("start")

    def play_move(self) -> None:
        self.played.append("move")

    def play_win(self) -> None:
        self.played.append("win")

    def play_lose(self) -> None:
        self.played.append("lose")

    def play_draw(self) -> None:
        self.played.append("draw")

    def play_button(self) -> None:
        self.played.append("button")

    def set_muted(self, muted: bool) -> None:
        self.muted = bool(muted)
        self.state_changed.emit()

    def toggle_muted(self) -> None:
        self.set_muted(not self.muted)

    def set_bgm_volume(self, volume: int) -> None:
        self.bgm_volume = int(volume)
        self.state_changed.emit()

    def set_sfx_volume(self, volume: int) -> None:
        self.sfx_volume = int(volume)
        self.state_changed.emit()

    def install_button_click_sounds(self, app: QObject) -> None:
        del app


class FakeAIWorker(QObject):
    """与 AIWorker 信号兼容的确定性替身。"""

    move_ready = Signal(int, int, int, int, int)
    search_failed = Signal(int, str)
    finished = Signal()

    def __init__(
        self,
        request_id: int,
        board: Board,
        side: Side,
        difficulty: object,
        cancel_event: Event,
        *,
        move: Optional[tuple[int, int, int, int]] = None,
        fail: Optional[str] = None,
        delay_ms: int = 0,
    ) -> None:
        super().__init__()
        self.request_id = request_id
        self.board = board
        self.side = side
        self.difficulty = difficulty
        self.cancel_event = cancel_event
        self.fail = fail
        self.delay_ms = delay_ms
        self.cancelled = False
        self._running = False
        if move is None:
            move = (6, 0, 5, 0) if side is Side.RED else (3, 0, 4, 0)
        self.move = move

    def start(self) -> None:
        self._running = True
        QTimer.singleShot(self.delay_ms, self._emit)

    def cancel(self) -> None:
        self.cancelled = True
        self.cancel_event.set()

    def wait(self, milliseconds: int = 0) -> bool:
        del milliseconds
        self._running = False
        return True

    def terminate(self) -> None:
        self._running = False

    def isRunning(self) -> bool:  # noqa: N802 - Qt 风格接口
        return self._running

    def _emit(self) -> None:
        self._running = False
        if self.cancel_event.is_set():
            self.finished.emit()
            return
        if self.fail is not None:
            self.search_failed.emit(self.request_id, self.fail)
        elif self.move is not None:
            self.move_ready.emit(self.request_id, *self.move)
        self.finished.emit()


class FakeTransport(Transport):
    """记录发送消息、可注入服务器事件的传输替身。"""

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self.opened: list[str] = []
        self.sent: list[object] = []
        self.closed = False

    def open(self, url: str) -> None:
        self.opened.append(url)

    def send_message(self, message: object) -> None:
        self.sent.append(message)

    def close(self) -> None:
        self.closed = True

    def simulate_connected(self) -> None:
        self.connected.emit()

    def simulate_disconnected(self) -> None:
        self.disconnected.emit()

    def server_send(self, message: object) -> None:
        self.message_received.emit(message)


__all__ = [
    "FakeAudioManager",
    "FakeAIWorker",
    "FakeTransport",
    "FakeVoiceAnnouncer",
    "FakeAuthApi",
]
