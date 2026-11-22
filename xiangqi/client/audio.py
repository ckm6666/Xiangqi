"""程序化音频：运行时合成音效/背景音乐并统一管理播放。

音频素材完全由标准库合成，不依赖任何外部音频文件：

* 五类短音效（落子/开局/胜利/失败/平局）在首次运行时生成并写入缓存目录；
* 30 秒背景音乐同样生成，但耗时较长，放在后台线程中完成，避免阻塞启动；
* 播放使用 QtMultimedia 的 QSoundEffect；离屏/无音频环境自动禁用，保证测试可运行。

用户偏好（静音、BGM 音量、音效音量）通过 QSettings 持久化；两个窗口共享同一个
应用级 AudioManager。
"""

from __future__ import annotations

import io
import logging
import math
import os
import random
import sys
import tempfile
import threading
import wave
from array import array
from pathlib import Path
from typing import Final, Literal, Optional

from PySide6.QtCore import (
    QEvent,
    QEventLoop,
    QObject,
    QSettings,
    QStandardPaths,
    Qt,
    QTimer,
    QUrl,
    Signal,
)
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QAbstractButton

try:
    from PySide6.QtMultimedia import (
        QAudioDecoder,
        QAudioFormat,
        QAudioOutput,
        QMediaPlayer,
        QSoundEffect,
    )

    _QT_MULTIMEDIA_AVAILABLE: Final[bool] = True
except ImportError:  # pragma: no cover - 仅在缺少 QtMultimedia 的裁剪环境触发
    QAudioDecoder = None  # type: ignore[assignment]
    QAudioFormat = None  # type: ignore[assignment]
    QAudioOutput = None  # type: ignore[assignment]
    QMediaPlayer = None  # type: ignore[assignment]
    QSoundEffect = None  # type: ignore[assignment]
    _QT_MULTIMEDIA_AVAILABLE = False

logger = logging.getLogger(__name__)

SoundKind = Literal["move", "start", "win", "lose", "draw", "bgm"]

SAMPLE_RATE: Final[int] = 22050
SAMPLE_WIDTH: Final[int] = 2  # 16-bit PCM
CHANNELS: Final[int] = 1
AUDIO_CACHE_VERSION: Final[str] = "1"
BGM_DURATION_SECONDS: Final[float] = 30.0

DEFAULT_BGM_VOLUME: Final[int] = 35
DEFAULT_SFX_VOLUME: Final[int] = 70

SETTINGS_MUTED: Final[str] = "audio/muted"
SETTINGS_BGM_VOLUME: Final[str] = "audio/bgm_volume"
SETTINGS_SFX_VOLUME: Final[str] = "audio/sfx_volume"

SFX_KINDS: Final[tuple[str, ...]] = ("move", "start", "win", "lose", "draw")

# 用户提供的 MP3 素材；缺失时自动回退到程序化合成音效。
ASSET_BGM: Final[str] = "bgm.mp3"
ASSET_MOVE: Final[str] = "move.mp3"
ASSET_BUTTON: Final[str] = "button.mp3"
DECODED_CACHE_VERSION: Final[str] = "1"

_BGM_LOOP_BEATS: Final[float] = 48.0

# (起始拍, MIDI 音高, 振幅)，D 调五声音阶；48 拍 = 30 秒（96 BPM）。
_BGM_MELODY: Final[tuple[tuple[float, int, float], ...]] = (
    (0.0, 62, 0.45),
    (1.5, 66, 0.36),
    (3.0, 69, 0.40),
    (5.0, 71, 0.34),
    (6.5, 69, 0.38),
    (9.0, 66, 0.34),
    (11.0, 62, 0.40),
    (12.0, 71, 0.40),
    (13.5, 74, 0.46),
    (15.5, 71, 0.36),
    (18.0, 69, 0.40),
    (19.5, 66, 0.36),
    (21.0, 69, 0.40),
    (23.0, 71, 0.34),
    (24.0, 62, 0.42),
    (25.5, 66, 0.36),
    (27.0, 69, 0.40),
    (29.0, 71, 0.36),
    (30.5, 74, 0.44),
    (33.0, 71, 0.36),
    (35.0, 69, 0.38),
    (36.0, 66, 0.38),
    (37.5, 62, 0.36),
    (39.0, 66, 0.38),
    (41.0, 69, 0.42),
    (42.5, 66, 0.34),
    (44.0, 62, 0.42),
    (46.0, 74, 0.38),
)

_BGM_BASS: Final[tuple[tuple[float, int, float], ...]] = (
    (0.0, 50, 0.16),
    (6.0, 57, 0.12),
    (12.0, 50, 0.15),
    (18.0, 57, 0.12),
    (24.0, 50, 0.15),
    (30.0, 57, 0.12),
    (36.0, 50, 0.15),
    (42.0, 57, 0.12),
)


# ---------------------------------------------------------------------------
# 合成辅助
# ---------------------------------------------------------------------------
def _midi_to_hz(note: float) -> float:
    """MIDI 音高转频率；A4 = 69 = 440 Hz。"""
    return 440.0 * (2.0 ** ((note - 69.0) / 12.0))


def _add_sine_tone(
    buffer: list[float],
    *,
    start_sample: int,
    freq_hz: float,
    duration: float,
    amplitude: float,
    partials: tuple[tuple[float, float], ...] = ((1.0, 1.0),),
    decay: float = 3.0,
    attack: float = 0.004,
    release: float = 0.02,
    wrap: bool = False,
) -> None:
    """把一个带指数衰减包络的泛音音色叠加进缓冲区。"""
    total = len(buffer)
    if total <= 0:
        return
    note_samples = int(duration * SAMPLE_RATE)
    if note_samples <= 0:
        return

    attack_samples = max(1, int(attack * SAMPLE_RATE))
    release_samples = max(1, int(release * SAMPLE_RATE))

    for index in range(note_samples):
        time_s = index / SAMPLE_RATE
        envelope = math.exp(-decay * time_s)
        if index < attack_samples:
            envelope *= index / attack_samples
        remaining = note_samples - index
        if remaining < release_samples:
            envelope *= remaining / release_samples

        value = 0.0
        for multiplier, gain in partials:
            value += gain * math.sin(
                2.0 * math.pi * freq_hz * multiplier * time_s
            )
        sample = amplitude * envelope * value

        position = start_sample + index
        if wrap:
            buffer[position % total] += sample
        elif 0 <= position < total:
            buffer[position] += sample


def _add_pluck(
    buffer: list[float],
    *,
    start_sample: int,
    freq_hz: float,
    duration: float,
    amplitude: float,
    rng: random.Random,
    wrap: bool = True,
    feedback: float = 0.9965,
) -> None:
    """Karplus-Strong 拨弦音色，近似古筝/古琴的衰减弦音。"""
    total = len(buffer)
    if total <= 0:
        return
    note_samples = int(duration * SAMPLE_RATE)
    if note_samples <= 0:
        return

    period = max(2, int(round(SAMPLE_RATE / max(freq_hz, 20.0))))
    delay = [rng.uniform(-0.5, 0.5) for _ in range(period)]
    cursor = 0

    attack_samples = max(1, int(0.003 * SAMPLE_RATE))
    release_samples = max(1, int(0.04 * SAMPLE_RATE))

    for index in range(note_samples):
        current = delay[cursor]
        following = delay[(cursor + 1) % period]
        delay[cursor] = feedback * 0.5 * (current + following)
        cursor = (cursor + 1) % period

        envelope = 1.0
        if index < attack_samples:
            envelope *= index / attack_samples
        remaining = note_samples - index
        if remaining < release_samples:
            envelope *= remaining / release_samples
        sample = amplitude * envelope * current

        position = start_sample + index
        if wrap:
            buffer[position % total] += sample
        elif 0 <= position < total:
            buffer[position] += sample


def _pcm16_wav_bytes(samples: array, sample_rate: int) -> bytes:
    """把 16-bit 单声道 PCM 采样编码为 WAV 字节。"""
    pcm = array("h", samples)
    if sys.byteorder == "big":
        pcm.byteswap()

    output = io.BytesIO()
    with wave.open(output, "wb") as wav_file:
        wav_file.setnchannels(CHANNELS)
        wav_file.setsampwidth(SAMPLE_WIDTH)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(pcm.tobytes())
    return output.getvalue()


def _to_wav_bytes(samples: list[float], *, peak: float) -> bytes:
    """归一化浮点缓冲并编码为单声道 16-bit PCM WAV 字节。"""
    loudest = max((abs(value) for value in samples), default=0.0)
    scale = (peak / loudest) if loudest > 1e-9 else 0.0

    pcm = array(
        "h",
        (
            int(round(max(-1.0, min(1.0, value * scale)) * 32767))
            for value in samples
        ),
    )
    return _pcm16_wav_bytes(pcm, SAMPLE_RATE)


# ---------------------------------------------------------------------------
# 音效配方
# ---------------------------------------------------------------------------
def _render_move() -> bytes:
    """落子：短促木质/石质“啪”声。"""
    buffer = [0.0] * int(0.14 * SAMPLE_RATE)
    noise = random.Random(5817)
    burst_samples = int(0.010 * SAMPLE_RATE)
    for index in range(burst_samples):
        time_s = index / SAMPLE_RATE
        buffer[index] += (
            noise.uniform(-1.0, 1.0) * math.exp(-time_s / 0.0018) * 0.7
        )

    _add_sine_tone(
        buffer,
        start_sample=0,
        freq_hz=900.0,
        duration=0.11,
        amplitude=0.5,
        partials=((1.0, 1.0), (2.02, 0.25)),
        decay=38.0,
        attack=0.001,
        release=0.01,
    )
    _add_sine_tone(
        buffer,
        start_sample=0,
        freq_hz=230.0,
        duration=0.12,
        amplitude=0.35,
        decay=26.0,
        attack=0.002,
        release=0.012,
    )
    return _to_wav_bytes(buffer, peak=0.65)


def _render_start() -> bytes:
    """开局：D4–A4–D5 三音上行钟声。"""
    duration = 1.1
    buffer = [0.0] * int(duration * SAMPLE_RATE)
    notes = ((0.0, 62, 0.5), (0.09, 69, 0.45), (0.18, 74, 0.42))
    for offset, midi, amplitude in notes:
        _add_sine_tone(
            buffer,
            start_sample=int(offset * SAMPLE_RATE),
            freq_hz=_midi_to_hz(midi),
            duration=duration - offset,
            amplitude=amplitude,
            partials=((1.0, 1.0), (2.01, 0.35), (3.0, 0.12)),
            decay=3.4,
            attack=0.004,
            release=0.08,
        )
    return _to_wav_bytes(buffer, peak=0.6)


def _render_win() -> bytes:
    """胜利：D 调五声音阶上行琶音。"""
    duration = 1.8
    buffer = [0.0] * int(duration * SAMPLE_RATE)
    notes = (
        (0.0, 62, 0.50),
        (0.11, 66, 0.46),
        (0.22, 69, 0.48),
        (0.34, 71, 0.44),
        (0.47, 74, 0.55),
    )
    for index, (offset, midi, amplitude) in enumerate(notes):
        _add_pluck(
            buffer,
            start_sample=int(offset * SAMPLE_RATE),
            freq_hz=_midi_to_hz(midi),
            duration=1.25,
            amplitude=amplitude,
            rng=random.Random(9000 + index),
            wrap=False,
        )
    _add_sine_tone(
        buffer,
        start_sample=int(0.5 * SAMPLE_RATE),
        freq_hz=_midi_to_hz(74),
        duration=1.2,
        amplitude=0.18,
        partials=((1.0, 1.0), (2.0, 0.4), (4.0, 0.15)),
        decay=3.0,
        release=0.1,
    )
    return _to_wav_bytes(buffer, peak=0.65)


def _render_lose() -> bytes:
    """失败：柔和下行的低音短句，避免刺耳。"""
    duration = 1.9
    buffer = [0.0] * int(duration * SAMPLE_RATE)
    notes = ((0.0, 62, 0.40), (0.42, 57, 0.38), (0.84, 54, 0.36), (1.24, 50, 0.42))
    for offset, midi, amplitude in notes:
        _add_sine_tone(
            buffer,
            start_sample=int(offset * SAMPLE_RATE),
            freq_hz=_midi_to_hz(midi),
            duration=duration - offset,
            amplitude=amplitude,
            partials=((1.0, 1.0), (2.0, 0.2)),
            decay=2.2,
            attack=0.006,
            release=0.15,
        )
    _add_sine_tone(
        buffer,
        start_sample=0,
        freq_hz=_midi_to_hz(38),
        duration=duration,
        amplitude=0.12,
        decay=0.8,
        attack=0.05,
        release=0.2,
    )
    return _to_wav_bytes(buffer, peak=0.5)


def _render_draw() -> bytes:
    """平局：中性、安静的两音提示。"""
    duration = 1.1
    buffer = [0.0] * int(duration * SAMPLE_RATE)
    notes = ((0.0, 62, 0.36), (0.28, 57, 0.34))
    for offset, midi, amplitude in notes:
        _add_sine_tone(
            buffer,
            start_sample=int(offset * SAMPLE_RATE),
            freq_hz=_midi_to_hz(midi),
            duration=duration - offset,
            amplitude=amplitude,
            partials=((1.0, 1.0), (2.0, 0.18)),
            decay=2.6,
            attack=0.005,
            release=0.12,
        )
    return _to_wav_bytes(buffer, peak=0.5)


def _render_bgm(duration_seconds: float) -> bytes:
    """背景音乐：30 秒无缝循环的稀疏拨弦 + 低音铺底。"""
    total_samples = max(1, int(round(duration_seconds * SAMPLE_RATE)))
    buffer = [0.0] * total_samples
    scale = duration_seconds / BGM_DURATION_SECONDS

    for index, (beat, midi, amplitude) in enumerate(_BGM_MELODY):
        start = int(beat / _BGM_LOOP_BEATS * total_samples)
        note_duration = max(0.12, 2.2 * scale)
        _add_pluck(
            buffer,
            start_sample=start,
            freq_hz=_midi_to_hz(midi),
            duration=note_duration,
            amplitude=amplitude,
            rng=random.Random(4000 + index),
            wrap=True,
        )

    for index, (beat, midi, amplitude) in enumerate(_BGM_BASS):
        start = int(beat / _BGM_LOOP_BEATS * total_samples)
        note_duration = max(0.18, 3.2 * scale)
        _add_sine_tone(
            buffer,
            start_sample=start,
            freq_hz=_midi_to_hz(midi),
            duration=note_duration,
            amplitude=amplitude,
            partials=((1.0, 1.0), (2.0, 0.12)),
            decay=0.9,
            attack=0.02,
            release=0.2,
            wrap=True,
        )

    # 单次反馈延迟，增加空间感；先拷贝再叠加，避免无限反馈。
    delay_samples = max(1, int(0.28 * SAMPLE_RATE))
    if total_samples > delay_samples * 2:
        source = list(buffer)
        for index in range(total_samples):
            buffer[index] += 0.16 * source[
                (index - delay_samples) % total_samples
            ]

    return _to_wav_bytes(buffer, peak=0.5)


def synthesize_sound(
    kind: SoundKind, *, duration_seconds: Optional[float] = None
) -> bytes:
    """合成指定音效并返回 WAV 字节；BGM 可通过 duration_seconds 缩短（测试用）。"""
    if kind == "move":
        return _render_move()
    if kind == "start":
        return _render_start()
    if kind == "win":
        return _render_win()
    if kind == "lose":
        return _render_lose()
    if kind == "draw":
        return _render_draw()
    if kind == "bgm":
        return _render_bgm(
            duration_seconds if duration_seconds is not None else BGM_DURATION_SECONDS
        )
    raise ValueError(f"未知音频类型：{kind}")


# ---------------------------------------------------------------------------
# 外部 MP3 素材：解码为 WAV 供 QSoundEffect 低延迟播放
# ---------------------------------------------------------------------------
def _audio_buffer_mono_pcm16(buffer: object) -> Optional[tuple[array, int]]:
    """把 QAudioBuffer 的任意采样格式降混为单声道 16-bit PCM。"""
    if QAudioFormat is None:
        return None
    try:
        fmt = buffer.format()
        channels = max(1, int(fmt.channelCount()))
        sample_rate = int(fmt.sampleRate())
        raw = bytes(buffer.constData())
    except (RuntimeError, AttributeError):
        return None

    if sample_rate <= 0 or not raw:
        return None

    sample_format = fmt.sampleFormat()
    mono = array("h")

    if sample_format == QAudioFormat.SampleFormat.Float:
        values = array("f")
        values.frombytes(raw[: len(raw) - (len(raw) % 4)])
        if sys.byteorder == "big":
            values.byteswap()
        frame_count = len(values) // channels
        for frame in range(frame_count):
            base = frame * channels
            average = sum(values[base : base + channels]) / channels
            mono.append(
                max(-32768, min(32767, int(round(average * 32767.0))))
            )
    elif sample_format == QAudioFormat.SampleFormat.Int16:
        values = array("h")
        values.frombytes(raw[: len(raw) - (len(raw) % 2)])
        if sys.byteorder == "big":
            values.byteswap()
        frame_count = len(values) // channels
        for frame in range(frame_count):
            base = frame * channels
            mono.append(int(sum(values[base : base + channels]) / channels))
    elif sample_format == QAudioFormat.SampleFormat.Int32:
        values = array("i")
        values.frombytes(raw[: len(raw) - (len(raw) % 4)])
        if sys.byteorder == "big":
            values.byteswap()
        frame_count = len(values) // channels
        for frame in range(frame_count):
            base = frame * channels
            mono.append(
                int(sum(values[base : base + channels]) / channels) >> 16
            )
    elif sample_format == QAudioFormat.SampleFormat.UInt8:
        frame_count = len(raw) // channels
        for frame in range(frame_count):
            base = frame * channels
            average = int(sum(raw[base : base + channels]) / channels)
            mono.append((average - 128) << 8)
    else:
        return None

    return mono, sample_rate


def _trim_pcm16_silence(
    samples: array, sample_rate: int, threshold: int = 300
) -> array:
    """裁掉 MP3 编码器延迟带来的首尾静音，保留少量预卷/尾音。"""
    total = len(samples)
    if total == 0:
        return samples

    first = 0
    while first < total and abs(samples[first]) <= threshold:
        first += 1
    if first >= total:
        return samples

    last = total - 1
    while last > first and abs(samples[last]) <= threshold:
        last -= 1

    start = max(0, first - int(0.005 * sample_rate))
    end = min(total, last + 1 + int(0.03 * sample_rate))
    return samples[start:end]


def decode_audio_to_wav_bytes(source: Path) -> Optional[bytes]:
    """用 Qt 多媒体解码任意受支持音频（如 MP3）为单声道 16-bit WAV。

    解码结果会裁掉首尾静音，保持素材原有音量；在主线程通过局部事件循环
    等待解码完成，调用方应只在首次生成缓存时使用。
    """
    if (
        not _QT_MULTIMEDIA_AVAILABLE
        or QAudioDecoder is None
        or QGuiApplication.instance() is None
    ):
        return None

    source_path = Path(source)
    if not source_path.is_file():
        return None

    decoder = QAudioDecoder()
    decoder.setSource(QUrl.fromLocalFile(str(source_path)))
    fragments: list[tuple[array, int]] = []
    errors: list[str] = []
    state = {"timed_out": False}
    loop = QEventLoop()
    timeout = QTimer()
    timeout.setSingleShot(True)
    timeout.timeout.connect(
        lambda: (state.__setitem__("timed_out", True), loop.quit())
    )

    def collect_buffers() -> None:
        while decoder.bufferAvailable():
            buffer = decoder.read()
            if not buffer.isValid():
                continue
            converted = _audio_buffer_mono_pcm16(buffer)
            if converted is not None:
                fragments.append(converted)

    def on_error(*_args) -> None:
        errors.append(decoder.errorString() or "音频解码失败")
        loop.quit()

    decoder.bufferReady.connect(collect_buffers)
    decoder.finished.connect(loop.quit)
    decoder.error.connect(on_error)

    timeout.start(15_000)
    decoder.start()
    loop.exec()
    timeout.stop()
    try:
        decoder.stop()
    except RuntimeError:
        pass

    if state["timed_out"]:
        logger.warning("解码音频超时：%s", source_path)
        return None
    if errors:
        logger.warning("解码音频失败：%s（%s）", source_path, errors[0])
        return None
    if not fragments:
        return None

    sample_rate = fragments[0][1]
    merged = array("h")
    for fragment, rate in fragments:
        if rate == sample_rate:
            merged.extend(fragment)
    if not merged:
        return None

    merged = _trim_pcm16_silence(merged, sample_rate)
    if not merged:
        return None
    return _pcm16_wav_bytes(merged, sample_rate)


# ---------------------------------------------------------------------------
# 素材与缓存路径
# ---------------------------------------------------------------------------
def assets_directory() -> Path:
    """返回内置音频素材目录；兼容源码运行和 PyInstaller 单文件。"""
    if getattr(sys, "frozen", False):
        base = Path(
            getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent)
        )
        return base / "xiangqi" / "client" / "assets" / "audio"
    return Path(__file__).resolve().parent / "assets" / "audio"


def find_audio_asset(name: str) -> Optional[Path]:
    """查找内置素材；不存在时返回 None（调用方回退到合成音效）。"""
    path = assets_directory() / name
    return path if path.is_file() else None


def _decoded_cache_path(
    kind: str, source: Path, cache_dir: Optional[Path]
) -> Path:
    stat = source.stat()
    fingerprint = f"{stat.st_size:x}{int(stat.st_mtime_ns):x}"
    directory = (
        Path(cache_dir) if cache_dir is not None else default_cache_dir()
    )
    return (
        directory
        / f"{kind}_src{fingerprint}_v{DECODED_CACHE_VERSION}.wav"
    )


def _is_valid_mono_wav(path: Path) -> bool:
    try:
        with wave.open(str(path), "rb") as wav_file:
            return (
                wav_file.getnchannels() == 1
                and wav_file.getsampwidth() == SAMPLE_WIDTH
                and wav_file.getframerate() > 0
                and wav_file.getnframes() > 0
            )
    except (OSError, EOFError, wave.Error):
        return False


def ensure_decoded_wav(
    kind: str, source: Path, cache_dir: Optional[Path] = None
) -> Optional[Path]:
    """解码外部素材并缓存为 WAV；源文件或缓存变化时自动重建。"""
    source_path = Path(source)
    if not source_path.is_file():
        return None
    directory = (
        Path(cache_dir) if cache_dir is not None else default_cache_dir()
    )
    directory.mkdir(parents=True, exist_ok=True)
    path = _decoded_cache_path(kind, source_path, directory)
    if _is_valid_mono_wav(path):
        return path

    data = decode_audio_to_wav_bytes(source_path)
    if data is None:
        return None

    temporary = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_bytes(data)
        os.replace(temporary, path)
    except OSError:
        logger.warning("写入解码音频缓存失败，尝试复用已有文件：%s", path)
        try:
            temporary.unlink()
        except OSError:
            pass
        if not _is_valid_mono_wav(path):
            return None
    return path


# ---------------------------------------------------------------------------
# 合成音效缓存
# ---------------------------------------------------------------------------
def default_cache_dir() -> Path:
    """返回音频 WAV 缓存目录；无法定位时退回到临时目录。"""
    location = QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.CacheLocation
    )
    if not location:
        return Path(tempfile.mkdtemp(prefix="xiangqi_audio_"))
    return Path(location) / "audio"


def _cache_path(kind: str, cache_dir: Optional[Path]) -> Path:
    directory = Path(cache_dir) if cache_dir is not None else default_cache_dir()
    return directory / f"{kind}_v{AUDIO_CACHE_VERSION}.wav"


def _is_valid_wav(path: Path) -> bool:
    try:
        with wave.open(str(path), "rb") as wav_file:
            return (
                wav_file.getnchannels() == CHANNELS
                and wav_file.getsampwidth() == SAMPLE_WIDTH
                and wav_file.getframerate() == SAMPLE_RATE
                and wav_file.getnframes() > 0
            )
    except (OSError, EOFError, wave.Error):
        return False


def find_cached_wav(
    kind: SoundKind, cache_dir: Optional[Path] = None
) -> Optional[Path]:
    """已有合法缓存时返回路径，否则返回 None（不生成）。"""
    path = _cache_path(kind, cache_dir)
    return path if _is_valid_wav(path) else None


def ensure_cached_wav(
    kind: SoundKind, cache_dir: Optional[Path] = None
) -> Path:
    """确保缓存 WAV 存在并合法；缺失/损坏时重新合成（原子写入）。"""
    directory = Path(cache_dir) if cache_dir is not None else default_cache_dir()
    directory.mkdir(parents=True, exist_ok=True)
    path = _cache_path(kind, directory)
    if _is_valid_wav(path):
        return path

    data = synthesize_sound(kind)
    temporary = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_bytes(data)
        os.replace(temporary, path)
    except OSError:
        # 多进程同时生成时可能被另一实例抢先完成；复用合法文件即可。
        logger.warning("写入音频缓存失败，尝试复用已有文件：%s", path)
        try:
            temporary.unlink()
        except OSError:
            pass
        if not _is_valid_wav(path):
            raise
    return path


# ---------------------------------------------------------------------------
# 播放管理
# ---------------------------------------------------------------------------
def _audio_is_supported() -> bool:
    """判断当前环境是否允许创建真实音频设备。"""
    if not _QT_MULTIMEDIA_AVAILABLE or QSoundEffect is None:
        return False
    flag = os.environ.get("XIANGQI_DISABLE_AUDIO", "").strip().lower()
    if flag in {"1", "true", "yes", "on"}:
        return False
    app = QGuiApplication.instance()
    if app is None:
        return False
    platform = (app.platformName() or "").lower()
    return platform not in {"offscreen", "minimal"}


def _coerce_bool(value: object, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        text = value.strip().lower()
        if text in {"1", "true", "yes", "on"}:
            return True
        if text in {"0", "false", "no", "off"}:
            return False
    return default


def _coerce_volume(value: object, default: int) -> int:
    try:
        number = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default
    return max(0, min(100, number))


class AudioManager(QObject):
    """应用级音频管理器：音效池、循环 BGM、音量/静音与持久化。"""

    state_changed = Signal()
    _bgm_file_ready = Signal(str)

    def __init__(
        self,
        parent: Optional[QObject] = None,
        *,
        settings: Optional[QSettings] = None,
        enabled: Optional[bool] = None,
        cache_dir: Optional[Path] = None,
    ) -> None:
        super().__init__(parent)
        self._available = (
            _audio_is_supported() if enabled is None else bool(enabled)
        )
        self._settings = settings
        if self._available and self._settings is None:
            self._settings = QSettings()
        self._cache_dir = cache_dir
        self._shutting_down = False

        self._muted = False
        self._bgm_volume = DEFAULT_BGM_VOLUME
        self._sfx_volume = DEFAULT_SFX_VOLUME
        self._read_settings()

        self._effects: dict[str, list[QSoundEffect]] = {}
        self._sfx_pool_index = 0
        self._bgm_effect: Optional[QSoundEffect] = None
        self._bgm_player: Optional[QMediaPlayer] = None
        self._bgm_audio_output: Optional[QAudioOutput] = None
        self._bgm_thread: Optional[threading.Thread] = None
        self._bgm_fallback_started = False
        self._pending_oneshots: set[str] = set()
        self._error_logged: set[str] = set()
        self._click_filter: Optional[QObject] = None

        self._bgm_file_ready.connect(
            self._on_bgm_file_ready,
            Qt.ConnectionType.QueuedConnection,
        )

        if self._available:
            try:
                self._prepare_effects()
            except Exception:
                logger.exception("音频初始化失败，本次运行禁用声音")
                self._available = False
                self._stop_all()

    # ------------------------------------------------------------------
    # 只读状态
    # ------------------------------------------------------------------
    @property
    def available(self) -> bool:
        return self._available

    @property
    def muted(self) -> bool:
        return self._muted

    @property
    def bgm_volume(self) -> int:
        return self._bgm_volume

    @property
    def sfx_volume(self) -> int:
        return self._sfx_volume

    # ------------------------------------------------------------------
    # 播放
    # ------------------------------------------------------------------
    def play_start(self) -> None:
        self._play_effect("start")

    def play_move(self) -> None:
        self._play_effect("move")

    def play_win(self) -> None:
        self._play_effect("win")

    def play_lose(self) -> None:
        self._play_effect("lose")

    def play_draw(self) -> None:
        self._play_effect("draw")

    def play_button(self) -> None:
        """UI 按钮点击音效（任意 QAbstractButton 按下时由事件过滤器调用）。"""
        self._play_effect("button")

    def _play_effect(self, kind: str) -> None:
        if not self._available or self._shutting_down or self._muted:
            return
        effects = self._effects.get(kind)
        if not effects:
            return

        if len(effects) > 1:
            # 落子/按钮音效允许短时间重叠，用轮换池避免互相打断。
            effect = effects[self._sfx_pool_index % len(effects)]
            self._sfx_pool_index = (self._sfx_pool_index + 1) % len(effects)
        else:
            effect = effects[0]

        status = effect.status()
        if status == QSoundEffect.Status.Ready:
            effect.play()
        elif status == QSoundEffect.Status.Loading and kind != "move":
            # 首次加载尚未完成时，就绪后补播一次；落子音效跳过避免积压。
            self._pending_oneshots.add(kind)

    # ------------------------------------------------------------------
    # 设置
    # ------------------------------------------------------------------
    def set_muted(self, muted: bool) -> None:
        muted = bool(muted)
        if muted == self._muted:
            return
        self._muted = muted
        self._persist(SETTINGS_MUTED, muted)
        self._apply_volumes()
        self.state_changed.emit()

    def toggle_muted(self) -> None:
        self.set_muted(not self._muted)

    def set_bgm_volume(self, volume: int) -> None:
        volume = _coerce_volume(volume, DEFAULT_BGM_VOLUME)
        if volume == self._bgm_volume:
            return
        self._bgm_volume = volume
        self._persist(SETTINGS_BGM_VOLUME, volume)
        self._apply_volumes()
        self.state_changed.emit()

    def set_sfx_volume(self, volume: int) -> None:
        volume = _coerce_volume(volume, DEFAULT_SFX_VOLUME)
        if volume == self._sfx_volume:
            return
        self._sfx_volume = volume
        self._persist(SETTINGS_SFX_VOLUME, volume)
        self._apply_volumes()
        self.state_changed.emit()

    def _read_settings(self) -> None:
        if self._settings is None:
            return
        self._muted = _coerce_bool(
            self._settings.value(SETTINGS_MUTED, False), False
        )
        self._bgm_volume = _coerce_volume(
            self._settings.value(SETTINGS_BGM_VOLUME, DEFAULT_BGM_VOLUME),
            DEFAULT_BGM_VOLUME,
        )
        self._sfx_volume = _coerce_volume(
            self._settings.value(SETTINGS_SFX_VOLUME, DEFAULT_SFX_VOLUME),
            DEFAULT_SFX_VOLUME,
        )

    def _persist(self, key: str, value: object) -> None:
        if self._settings is None:
            return
        self._settings.setValue(key, value)
        self._settings.sync()

    # ------------------------------------------------------------------
    # 设备与资源
    # ------------------------------------------------------------------
    def _prepare_effects(self) -> None:
        effect_paths: dict[str, Path] = {}

        # 落子音效：优先使用用户提供的 MP3，解码失败则回退到合成音效。
        move_source = find_audio_asset(ASSET_MOVE)
        move_path = (
            self._decode_asset("move", move_source)
            if move_source is not None
            else None
        )
        if move_path is None:
            try:
                move_path = ensure_cached_wav("move", self._cache_dir)
            except Exception:
                logger.exception("生成落子音效失败，已跳过")
        if move_path is not None:
            effect_paths["move"] = move_path

        # 按钮点击音效：素材缺失时静默跳过（不影响其它音效）。
        button_source = find_audio_asset(ASSET_BUTTON)
        if button_source is not None:
            button_path = self._decode_asset("button", button_source)
            if button_path is not None:
                effect_paths["button"] = button_path

        for kind in ("start", "win", "lose", "draw"):
            try:
                effect_paths[kind] = ensure_cached_wav(kind, self._cache_dir)
            except Exception:
                logger.exception("生成音效 %s 失败，已跳过", kind)

        pool_sizes = {"move": 3, "button": 2}
        for kind, path in effect_paths.items():
            effects: list[QSoundEffect] = []
            for _ in range(pool_sizes.get(kind, 1)):
                effect = QSoundEffect(self)
                effect.setVolume(0.0)
                effect.setSource(QUrl.fromLocalFile(str(path)))
                effect.statusChanged.connect(
                    lambda *args, k=kind: self._on_effect_status_changed(k)
                )
                effects.append(effect)
            self._effects[kind] = effects

        self._apply_volumes()
        self._prepare_bgm()

    def _decode_asset(self, kind: str, source: Path) -> Optional[Path]:
        try:
            path = ensure_decoded_wav(kind, source, self._cache_dir)
        except Exception:
            logger.exception("解码音频素材失败：%s", source)
            return None
        if path is None:
            logger.warning(
                "无法将 %s 解码为 WAV，回退到合成音效", source.name
            )
        return path

    def _on_effect_status_changed(self, kind: str) -> None:
        effects = self._effects.get(kind)
        if not effects:
            return
        status = effects[0].status()
        if status == QSoundEffect.Status.Error:
            if kind not in self._error_logged:
                self._error_logged.add(kind)
                logger.warning("音效 %s 加载失败，已静默跳过", kind)
            return
        if (
            status == QSoundEffect.Status.Ready
            and kind in self._pending_oneshots
        ):
            self._pending_oneshots.discard(kind)
            if not self._shutting_down and not self._muted:
                effects[0].play()

    def _prepare_bgm(self) -> None:
        # 优先使用用户提供的 MP3 BGM（长音频适合流式播放和原生循环）。
        source = find_audio_asset(ASSET_BGM)
        if source is not None and self._start_file_bgm(source):
            return
        if not self._bgm_fallback_started:
            self._prepare_synth_bgm()

    def _start_file_bgm(self, source: Path) -> bool:
        if QMediaPlayer is None or QAudioOutput is None:
            return False
        try:
            output = QAudioOutput(self)
            player = QMediaPlayer(self)
            self._bgm_audio_output = output
            self._bgm_player = player
            player.setAudioOutput(output)
            player.setLoops(QMediaPlayer.Infinite.value)
            player.errorOccurred.connect(self._on_bgm_media_error)
            player.setSource(QUrl.fromLocalFile(str(source)))
            if self._bgm_fallback_started:
                return False
            self._apply_volumes()
            player.play()
        except Exception:
            logger.exception("启动文件 BGM 失败，回退到合成音乐")
            self._bgm_player = None
            self._bgm_audio_output = None
            return False
        logger.info("背景音乐使用文件素材：%s", source.name)
        return True

    def _on_bgm_media_error(
        self, error: object, error_string: str = ""
    ) -> None:
        if self._shutting_down:
            return
        if QMediaPlayer is not None and error == QMediaPlayer.Error.NoError:
            return
        logger.warning("文件 BGM 播放失败：%s", error_string or error)
        if self._bgm_fallback_started:
            return
        self._bgm_fallback_started = True
        player = self._bgm_player
        self._bgm_player = None
        self._bgm_audio_output = None
        if player is not None:
            try:
                player.stop()
            except RuntimeError:
                pass
        self._prepare_synth_bgm()

    def _prepare_synth_bgm(self) -> None:
        cached = find_cached_wav("bgm", self._cache_dir)
        if cached is not None:
            self._load_bgm(cached)
            return

        thread = threading.Thread(
            target=self._generate_bgm_file,
            name="xiangqi-bgm-synth",
            daemon=True,
        )
        self._bgm_thread = thread
        thread.start()

    def _generate_bgm_file(self) -> None:
        try:
            path = ensure_cached_wav("bgm", self._cache_dir)
        except Exception:
            logger.exception("生成背景音乐失败，本次运行无 BGM")
            return
        if self._shutting_down:
            return
        try:
            self._bgm_file_ready.emit(str(path))
        except RuntimeError:  # pragma: no cover - 退出过程中的竞态
            return

    def _on_bgm_file_ready(self, path: str) -> None:
        if self._shutting_down or not self._available:
            return
        try:
            self._load_bgm(Path(path))
        except Exception:
            logger.exception("加载背景音乐失败")

    def _load_bgm(self, path: Path) -> None:
        effect = QSoundEffect(self)
        effect.setLoopCount(QSoundEffect.Infinite.value)
        effect.setSource(QUrl.fromLocalFile(str(path)))
        effect.statusChanged.connect(self._on_bgm_status_changed)
        self._bgm_effect = effect
        self._apply_volumes()
        if effect.status() == QSoundEffect.Status.Ready:
            self._start_bgm()

    def _on_bgm_status_changed(self) -> None:
        if self._bgm_effect is None:
            return
        status = self._bgm_effect.status()
        if status == QSoundEffect.Status.Ready:
            self._apply_volumes()
            self._start_bgm()
        elif status == QSoundEffect.Status.Error:
            if "bgm" not in self._error_logged:
                self._error_logged.add("bgm")
                logger.warning("背景音乐加载失败，本次运行无 BGM")

    def _start_bgm(self) -> None:
        if self._shutting_down or not self._available:
            return
        if self._bgm_effect is not None:
            self._bgm_effect.play()

    def _apply_volumes(self) -> None:
        bgm_gain = 0.0 if self._muted else (self._bgm_volume / 100.0) ** 2
        sfx_gain = 0.0 if self._muted else (self._sfx_volume / 100.0) ** 2
        if self._bgm_player is not None and self._bgm_audio_output is not None:
            self._bgm_audio_output.setVolume(bgm_gain)
        if self._bgm_effect is not None:
            self._bgm_effect.setVolume(bgm_gain)
        for effects in self._effects.values():
            for effect in effects:
                effect.setVolume(sfx_gain)

    def _stop_all(self) -> None:
        for effects in self._effects.values():
            for effect in effects:
                try:
                    effect.stop()
                except RuntimeError:
                    pass
        if self._bgm_player is not None:
            try:
                self._bgm_player.stop()
            except RuntimeError:
                pass
        if self._bgm_effect is not None:
            try:
                self._bgm_effect.stop()
            except RuntimeError:
                pass

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------
    def shutdown(self) -> None:
        """停止全部声音；可安全重复调用。"""
        if self._shutting_down:
            return
        self._shutting_down = True
        self._pending_oneshots.clear()
        self._stop_all()

    # ------------------------------------------------------------------
    # UI 点击音效
    # ------------------------------------------------------------------
    def install_button_click_sounds(self, app: QObject) -> None:
        """安装应用级事件过滤器，让任意按钮点击都有音效。"""
        if not self._available or self._click_filter is not None:
            return
        self._click_filter = _ButtonClickFilter(self)
        app.installEventFilter(self._click_filter)


class _ButtonClickFilter(QObject):
    """在 QAbstractButton 被按下时播放 UI 点击音效。"""

    def __init__(
        self,
        manager: AudioManager,
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self._manager = manager

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if (
            event.type() == QEvent.Type.MouseButtonPress
            and isinstance(watched, QAbstractButton)
            and watched.isEnabled()
        ):
            self._manager.play_button()
        return False


# ---------------------------------------------------------------------------
# 单例
# ---------------------------------------------------------------------------
_manager: Optional[AudioManager] = None


def initialize_audio() -> AudioManager:
    """在 QApplication 就绪后创建应用级管理器并接管退出清理。"""
    global _manager
    if _manager is None:
        _manager = AudioManager()
        app = QGuiApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(_manager.shutdown)
    return _manager


def get_audio_manager() -> AudioManager:
    """懒获取应用级管理器；离屏/测试环境自动返回禁用实例。"""
    global _manager
    if _manager is None:
        _manager = AudioManager()
    return _manager


__all__ = [
    "ASSET_BGM",
    "ASSET_BUTTON",
    "ASSET_MOVE",
    "AudioManager",
    "AUDIO_CACHE_VERSION",
    "BGM_DURATION_SECONDS",
    "DEFAULT_BGM_VOLUME",
    "DEFAULT_SFX_VOLUME",
    "SETTINGS_BGM_VOLUME",
    "SETTINGS_MUTED",
    "SETTINGS_SFX_VOLUME",
    "SAMPLE_RATE",
    "SoundKind",
    "assets_directory",
    "decode_audio_to_wav_bytes",
    "default_cache_dir",
    "ensure_cached_wav",
    "ensure_decoded_wav",
    "find_audio_asset",
    "find_cached_wav",
    "get_audio_manager",
    "initialize_audio",
    "synthesize_sound",
]
