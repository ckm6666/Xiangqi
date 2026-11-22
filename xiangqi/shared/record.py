"""棋谱数据结构与 JSON 序列化。

一局棋的棋谱包括模式、双方名称、完整着法序列、胜者与结束原因。联机
对局由服务端在 ``game_state`` 中附带完整着法，本地/人机对局直接读取
``GameModel.moves``，因此所有模式共用同一份 schema。

坐标与着法编码复用 :mod:`xiangqi.shared.protocol`，与联机协议保持一致。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Optional

from xiangqi.shared.errors import ProtocolError, RecordError
from xiangqi.shared.protocol import deserialize_move, serialize_move
from xiangqi.shared.rules import Move, Side

RECORD_VERSION = 1
RECORD_MODES = frozenset({"local", "ai", "online", "puzzle"})


@dataclass(frozen=True, slots=True)
class GameRecord:
    """一局棋的完整记录。"""

    record_id: str
    created_at: str
    mode: str
    moves: tuple[Move, ...]
    winner: Optional[Side]
    result_reason: str
    red_name: str = ""
    black_name: str = ""
    rated: bool = False
    metadata: Mapping[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        """序列化为 JSON 兼容字典。"""
        try:
            moves = [serialize_move(move) for move in self.moves]
        except ProtocolError as exc:  # 防御外部构造的非法着法
            raise RecordError(f"棋谱着法无效：{exc}") from exc
        return {
            "version": RECORD_VERSION,
            "record_id": self.record_id,
            "created_at": self.created_at,
            "mode": self.mode,
            "moves": moves,
            "winner": self.winner.value if self.winner is not None else None,
            "result_reason": self.result_reason,
            "red_name": self.red_name,
            "black_name": self.black_name,
            "rated": bool(self.rated),
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "GameRecord":
        """从字典载入棋谱；非法数据抛出 :class:`RecordError`。"""
        if not isinstance(data, Mapping):
            raise RecordError("棋谱必须是对象")
        version = data.get("version", RECORD_VERSION)
        if version != RECORD_VERSION:
            raise RecordError(f"不支持的棋谱版本：{version!r}")

        record_id = data.get("record_id")
        if not isinstance(record_id, str) or not record_id:
            raise RecordError("棋谱缺少 record_id")
        created_at = data.get("created_at", "")
        if not isinstance(created_at, str):
            raise RecordError("created_at 必须是字符串")

        mode = data.get("mode")
        if not isinstance(mode, str) or mode not in RECORD_MODES:
            raise RecordError(f"未知对局模式：{mode!r}")

        raw_moves = data.get("moves", [])
        if not isinstance(raw_moves, (list, tuple)):
            raise RecordError("moves 必须是数组")
        moves: list[Move] = []
        for index, raw_move in enumerate(raw_moves, start=1):
            try:
                move = deserialize_move(raw_move)
            except ProtocolError as exc:
                raise RecordError(f"第 {index} 手无效：{exc}") from exc
            if move is None:
                raise RecordError(f"第 {index} 手为空")
            moves.append(move)

        winner_raw = data.get("winner")
        if winner_raw is None:
            winner: Optional[Side] = None
        elif winner_raw in (Side.RED.value, Side.BLACK.value):
            winner = Side(str(winner_raw))
        else:
            raise RecordError(f"胜方无效：{winner_raw!r}")

        result_reason = data.get("result_reason", "")
        if not isinstance(result_reason, str):
            raise RecordError("result_reason 必须是字符串")

        red_name = data.get("red_name", "")
        black_name = data.get("black_name", "")
        if not isinstance(red_name, str) or not isinstance(black_name, str):
            raise RecordError("棋手名称必须是字符串")

        rated = data.get("rated", False)
        if not isinstance(rated, bool):
            raise RecordError("rated 必须是布尔值")

        metadata = data.get("metadata", {})
        if not isinstance(metadata, Mapping):
            raise RecordError("metadata 必须是对象")

        return cls(
            record_id=record_id,
            created_at=created_at,
            mode=mode,
            moves=tuple(moves),
            winner=winner,
            result_reason=result_reason,
            red_name=red_name,
            black_name=black_name,
            rated=rated,
            metadata=dict(metadata),
        )


__all__ = ["RECORD_VERSION", "RECORD_MODES", "GameRecord", "RecordError"]
