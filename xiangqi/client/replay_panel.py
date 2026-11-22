"""棋谱复盘页：历史对局列表 + 只读棋盘 + 逐手播放。

左侧列出本地保存的棋谱，右侧棋盘按手数回放；支持上一手/下一手、拖动
进度条与自动播放。对局结束后主窗口自动写入棋谱。
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from xiangqi.client.board_view import BoardView
from xiangqi.client.board_widget import BoardWidget
from xiangqi.client.records import LocalRecordStore
from xiangqi.client.replay import ReplayTimeline
from xiangqi.client.ui_theme import GAME_BACKDROP_SPEC, InkBackdrop
from xiangqi.shared.record import GameRecord
from xiangqi.shared.rules import EndReason

PLAY_INTERVAL_MS = 850
MODE_LABELS = {
    "local": "本地双人",
    "ai": "人机对战",
    "online": "联机对战",
    "puzzle": "残局挑战",
}


def _mode_label(mode: str) -> str:
    return MODE_LABELS.get(mode, mode or "对局")


def _reason_label(reason: str) -> str:
    if not reason:
        return ""
    try:
        return EndReason(reason).label
    except ValueError:
        return reason


def _record_summary(record: GameRecord) -> str:
    if record.winner is None:
        result = "和棋"
    else:
        result = f"{record.winner.label}胜"
    reason = _reason_label(record.result_reason)
    if reason:
        result += f" · {reason}"
    return result


class ReplayPanel(InkBackdrop):
    """棋谱复盘页。"""

    back_requested = Signal()

    def __init__(
        self,
        record_store: Optional[LocalRecordStore] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent, spec=GAME_BACKDROP_SPEC)
        self.setObjectName("replayPanel")
        self._store = record_store or LocalRecordStore()
        self._records: tuple[GameRecord, ...] = ()
        self._current: Optional[GameRecord] = None
        self._timeline: Optional[ReplayTimeline] = None

        self._play_timer = QTimer(self)
        self._play_timer.setInterval(PLAY_INTERVAL_MS)
        self._play_timer.timeout.connect(self._on_play_tick)

        self._build_ui()
        self._set_empty_state("自动加载最近的棋谱…")

    # ------------------------------------------------------------------
    # 获取
    # ------------------------------------------------------------------
    @property
    def record_store(self) -> LocalRecordStore:
        return self._store

    @property
    def records(self) -> tuple[GameRecord, ...]:
        return self._records

    @property
    def current_record(self) -> Optional[GameRecord]:
        return self._current

    @property
    def timeline(self) -> Optional[ReplayTimeline]:
        return self._timeline

    @property
    def is_playing(self) -> bool:
        return self._play_timer.isActive()

    # ------------------------------------------------------------------
    # 界面
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(10)

        header = QHBoxLayout()
        header.setContentsMargins(2, 0, 2, 0)
        title = QLabel("棋谱复盘", self)
        title.setObjectName("replayTitle")
        subtitle = QLabel("逐手回看历史对局", self)
        subtitle.setObjectName("brandSubtitle")
        title_box = QVBoxLayout()
        title_box.setContentsMargins(0, 0, 0, 0)
        title_box.setSpacing(0)
        title_box.addWidget(title)
        title_box.addWidget(subtitle)

        self.back_button = QPushButton("返回主菜单", self)
        self.back_button.setObjectName("menuBackButton")
        self.back_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.back_button.setMinimumHeight(34)
        self.back_button.clicked.connect(self._on_back)

        header.addLayout(title_box)
        header.addStretch(1)
        header.addWidget(self.back_button)
        root.addLayout(header)

        content = QHBoxLayout()
        content.setSpacing(12)

        sidebar = QFrame(self)
        sidebar.setObjectName("replaySidebar")
        sidebar.setAttribute(
            Qt.WidgetAttribute.WA_StyledBackground, True
        )
        sidebar.setFixedWidth(236)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(12, 10, 12, 10)
        sidebar_layout.setSpacing(6)
        list_title = QLabel("历史对局", sidebar)
        list_title.setObjectName("sectionTitle")
        self.count_label = QLabel("", sidebar)
        self.count_label.setObjectName("hintLabel")
        self.record_list = QListWidget(sidebar)
        self.record_list.setObjectName("replayList")
        self.record_list.setAlternatingRowColors(True)
        self.record_list.currentRowChanged.connect(
            self._on_row_changed
        )
        sidebar_layout.addWidget(list_title)
        sidebar_layout.addWidget(self.count_label)
        sidebar_layout.addWidget(self.record_list, 1)

        board_side = QVBoxLayout()
        board_side.setSpacing(8)
        self.board = BoardWidget(BoardView.empty(), self)
        self.board.setMinimumSize(220, 220)
        self.board.set_interaction_enabled(False)
        board_side.addWidget(self.board, 1)

        self.summary_label = QLabel("", self)
        self.summary_label.setObjectName("replaySummary")
        self.summary_label.setWordWrap(True)
        board_side.addWidget(self.summary_label)

        slider_row = QHBoxLayout()
        slider_row.setSpacing(10)
        self.slider = QSlider(Qt.Orientation.Horizontal, self)
        self.slider.setObjectName("replaySlider")
        self.slider.setRange(0, 0)
        self.slider.valueChanged.connect(self._on_slider_changed)
        self.frame_label = QLabel("第 0 / 0 手", self)
        self.frame_label.setObjectName("replayFrame")
        self.frame_label.setMinimumWidth(94)
        self.frame_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        slider_row.addWidget(self.slider, 1)
        slider_row.addWidget(self.frame_label)
        board_side.addLayout(slider_row)

        controls = QHBoxLayout()
        controls.setSpacing(8)
        self.prev_button = QPushButton("上一手", self)
        self.prev_button.setObjectName("undoButton")
        self.prev_button.setMinimumHeight(34)
        self.prev_button.clicked.connect(lambda: self._step(-1))
        self.play_button = QPushButton("自动播放", self)
        self.play_button.setObjectName("restartButton")
        self.play_button.setMinimumHeight(34)
        self.play_button.clicked.connect(self._toggle_play)
        self.next_button = QPushButton("下一手", self)
        self.next_button.setObjectName("undoButton")
        self.next_button.setMinimumHeight(34)
        self.next_button.clicked.connect(lambda: self._step(1))
        controls.addWidget(self.prev_button)
        controls.addWidget(self.play_button)
        controls.addWidget(self.next_button)
        controls.addStretch(1)
        board_side.addLayout(controls)

        content.addWidget(sidebar)
        content.addLayout(board_side, 1)
        root.addLayout(content, 1)

    # ------------------------------------------------------------------
    # 数据
    # ------------------------------------------------------------------
    def refresh(self) -> None:
        """重新读取本地棋谱并保持/恢复选择。"""
        self._stop_play()
        previous_id = (
            self._current.record_id if self._current is not None else ""
        )
        self._records = self._store.list_recent(200)
        self.record_list.blockSignals(True)
        self.record_list.clear()
        selected_row = -1
        for index, record in enumerate(self._records):
            item = QListWidgetItem(self._format_item(record))
            item.setData(Qt.ItemDataRole.UserRole, record.record_id)
            item.setSizeHint(QSize(210, 54))
            item.setToolTip(
                f"{record.red_name or '红方'} 对 "
                f"{record.black_name or '黑方'}\n"
                f"{_mode_label(record.mode)} · "
                f"{_record_summary(record)} · {len(record.moves)} 手"
            )
            self.record_list.addItem(item)
            if record.record_id == previous_id:
                selected_row = index
        self.record_list.blockSignals(False)
        self.count_label.setText(f"最近 {len(self._records)} 局")

        if not self._records:
            self._current = None
            self._timeline = None
            self._set_empty_state("暂无棋谱，完成一局后会自动记录")
            return
        if selected_row < 0:
            selected_row = 0
        self.record_list.setCurrentRow(selected_row)
        self._load_record(selected_row)

    @staticmethod
    def _format_item(record: GameRecord) -> str:
        timestamp = record.created_at[:16].replace("T", " ")
        names = (
            f"{record.red_name or '红方'} 对 "
            f"{record.black_name or '黑方'}"
        )
        return (
            f"{timestamp} · {_mode_label(record.mode)}\n"
            f"{names} · {_record_summary(record)}"
        )

    def _on_row_changed(self, row: int) -> None:
        if 0 <= row < len(self._records):
            self._load_record(row)

    def _load_record(self, index: int) -> None:
        self._stop_play()
        record = self._records[index]
        self._current = record
        self._timeline = ReplayTimeline(record.moves)
        self.slider.setRange(0, len(record.moves))
        self.summary_label.setText(
            f"{_mode_label(record.mode)} · "
            f"{record.red_name or '红方'} 对 "
            f"{record.black_name or '黑方'} · "
            f"{_record_summary(record)}"
        )
        self._apply_index(0)

    def _set_empty_state(self, message: str) -> None:
        self.slider.setRange(0, 0)
        self.slider.setValue(0)
        self.frame_label.setText("第 0 / 0 手")
        self.summary_label.setText(message)
        self.board.set_view(BoardView.empty())
        self.prev_button.setEnabled(False)
        self.next_button.setEnabled(False)
        self.play_button.setEnabled(False)
        self.play_button.setText("自动播放")

    # ------------------------------------------------------------------
    # 回放控制
    # ------------------------------------------------------------------
    def _apply_index(self, index: int) -> None:
        timeline = self._timeline
        if timeline is None:
            return
        position = timeline.seek(index)
        self.slider.blockSignals(True)
        self.slider.setValue(position)
        self.slider.blockSignals(False)
        try:
            frame = timeline.frame(position)
        except ValueError as exc:
            self.summary_label.setText(f"棋谱损坏：{exc}")
            self.prev_button.setEnabled(False)
            self.next_button.setEnabled(False)
            self.play_button.setEnabled(False)
            return
        self.board.set_view(frame)
        self.frame_label.setText(
            f"第 {position} / {timeline.length} 手"
        )
        self.prev_button.setEnabled(position > 0)
        self.next_button.setEnabled(position < timeline.length)
        self.play_button.setEnabled(timeline.length > 0)
        if position >= timeline.length:
            self._stop_play()

    def _step(self, delta: int) -> None:
        if self._timeline is None:
            return
        self._stop_play()
        self._apply_index(self._timeline.index + delta)

    def _on_slider_changed(self, value: int) -> None:
        if self._timeline is None:
            return
        self._stop_play()
        self._apply_index(value)

    def _toggle_play(self) -> None:
        if self._play_timer.isActive():
            self._stop_play()
            return
        timeline = self._timeline
        if timeline is None or timeline.length == 0:
            return
        if timeline.at_end:
            self._apply_index(0)
        self.play_button.setText("暂停播放")
        self._play_timer.start()

    def _on_play_tick(self) -> None:
        timeline = self._timeline
        if timeline is None or timeline.at_end:
            self._stop_play()
            return
        self._apply_index(timeline.index + 1)

    def _stop_play(self) -> None:
        if self._play_timer.isActive():
            self._play_timer.stop()
        self.play_button.setText("自动播放")

    def _on_back(self) -> None:
        self._stop_play()
        self.back_requested.emit()

    def hideEvent(self, event) -> None:  # noqa: N802 - Qt 接口
        self._stop_play()
        super().hideEvent(event)


__all__ = ["MODE_LABELS", "PLAY_INTERVAL_MS", "ReplayPanel"]
