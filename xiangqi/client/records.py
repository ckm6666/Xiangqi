"""本地棋谱存储（JSONL）。

每局结束追加一行 JSON；超过上限时重写文件只保留最近记录。损坏的行会
被跳过而不是让整个复盘页失败。文件默认位于 Qt 的应用数据目录
``.../Xiangqi/Xiangqi/records/games.jsonl``。
"""

from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QCoreApplication, QStandardPaths

from xiangqi.shared.errors import RecordError
from xiangqi.shared.record import GameRecord

logger = logging.getLogger(__name__)


def _default_records_directory() -> Path:
    """返回本地棋谱目录，优先使用 Qt 的应用数据路径。"""
    if QCoreApplication.instance() is not None:
        base = QStandardPaths.writableLocation(
            QStandardPaths.StandardLocation.AppLocalDataLocation
        )
        if base:
            return Path(base) / "records"
    local_app_data = os.environ.get("LOCALAPPDATA")
    root = Path(local_app_data) if local_app_data else Path.home() / ".local" / "share"
    return root / "Xiangqi" / "Xiangqi" / "records"


class LocalRecordStore:
    """线程安全的 JSONL 棋谱存储。"""

    def __init__(
        self,
        directory: Optional[Path] = None,
        max_records: int = 1000,
    ) -> None:
        self._directory = (
            Path(directory)
            if directory is not None
            else _default_records_directory()
        )
        self._max_records = max(1, int(max_records))
        self._lock = threading.Lock()

    @property
    def directory(self) -> Path:
        """棋谱目录。"""
        return self._directory

    @property
    def path(self) -> Path:
        """棋谱文件路径。"""
        return self._directory / "games.jsonl"

    @property
    def max_records(self) -> int:
        """最多保留的记录数。"""
        return self._max_records

    def append(self, record: GameRecord) -> None:
        """追加一局棋；写盘失败时记录日志，不影响对局流程。"""
        if not isinstance(record, GameRecord):
            raise TypeError("record 必须是 GameRecord")
        try:
            line = json.dumps(
                record.to_dict(), ensure_ascii=False, separators=(",", ":")
            )
        except (TypeError, ValueError, RecordError):
            logger.exception("棋谱序列化失败 record_id=%s", record.record_id)
            return
        with self._lock:
            try:
                self._directory.mkdir(parents=True, exist_ok=True)
                with self.path.open("a", encoding="utf-8") as handle:
                    handle.write(line)
                    handle.write("\n")
                records = self._read_records_unlocked()
                if len(records) > self._max_records:
                    self._write_records_unlocked(
                        records[-self._max_records :]
                    )
            except OSError:
                logger.exception("写入本地棋谱失败 path=%s", self.path)

    def list_recent(self, limit: int = 50) -> tuple[GameRecord, ...]:
        """返回最近的棋谱，最新在前。"""
        if limit <= 0:
            return ()
        with self._lock:
            records = self._read_records_unlocked()
        return tuple(reversed(records[-int(limit) :]))

    def load(self, record_id: str) -> Optional[GameRecord]:
        """按编号载入棋谱；不存在或损坏时返回 None。"""
        if not isinstance(record_id, str):
            return None
        with self._lock:
            records = self._read_records_unlocked()
        for record in reversed(records):
            if record.record_id == record_id:
                return record
        return None

    def count(self) -> int:
        """返回已保存棋谱数量。"""
        with self._lock:
            return len(self._read_records_unlocked())

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------
    def _read_records_unlocked(self) -> list[GameRecord]:
        if not self.path.exists():
            return []
        try:
            text = self.path.read_text(encoding="utf-8")
        except OSError:
            logger.exception("读取本地棋谱失败 path=%s", self.path)
            return []
        records: list[GameRecord] = []
        for line_number, line in enumerate(text.splitlines(), start=1):
            line = line.strip()
            if not line:
                continue
            try:
                raw = json.loads(line)
                records.append(GameRecord.from_dict(raw))
            except (json.JSONDecodeError, TypeError, RecordError):
                logger.warning(
                    "跳过损坏的棋谱行 path=%s line=%d",
                    self.path,
                    line_number,
                )
        return records

    def _write_records_unlocked(self, records: list[GameRecord]) -> None:
        temp_path = self.path.with_suffix(".jsonl.tmp")
        with temp_path.open("w", encoding="utf-8") as handle:
            for record in records:
                handle.write(
                    json.dumps(
                        record.to_dict(),
                        ensure_ascii=False,
                        separators=(",", ":"),
                    )
                )
                handle.write("\n")
        temp_path.replace(self.path)


__all__ = ["LocalRecordStore"]
