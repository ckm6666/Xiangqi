"""客户端与服务端共用的对局聊天（表情/评论）协议与校验。

设计要点（移植自 Gomoku 项目）：

* 不依赖任何 Qt，纯 Python，可在服务端与客户端共享同一套校验逻辑；
* 表情只能取自 :data:`EMOJI_PRESETS` 预设，评论是长度受限的短文本；
* 服务端只做校验与广播，不保存对局聊天历史：对话日志是客户端的临时
  界面日志；
* 限流参数（发言间隔、突发条数）放在本模块，客户端据此做本地冷却；
* 评论会去掉控制字符与格式字符（如零宽空格、方向覆写），避免日志被
  伪造或左右颠倒显示。
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from typing import Any, Mapping

from xiangqi.shared.errors import ProtocolError

CHAT_KIND_EMOJI = "emoji"
CHAT_KIND_TEXT = "text"
CHAT_KINDS = (CHAT_KIND_EMOJI, CHAT_KIND_TEXT)

# 可选表情预设（皇室战争式快捷表情）。
# 不变量：每个都是单个码位、类别 So、不含变体选择符 U+FE0F，
# 这样在 Windows 上能被 Segoe UI Emoji 直接渲染，且不会破坏单码位校验。
EMOJI_PRESETS: tuple[str, ...] = (
    "\U0001F44B",
    "\U0001F91D",
    "\U0001F604",
    "\U0001F525",
    "\U0001F605",
    "\U0001F44D",
    "\U0001F44E",
    "\U0001F62D",
    "\U0001F480",
    "\U0001F64F",
    "\U0001F914",
    "\U0001F389",
)

# 快捷评论预设（象棋场景同样适用）。
COMMENT_PRESETS: tuple[str, ...] = (
    "好棋！",
    "这步妙啊",
    "别急，慢慢来",
    "承让了",
    "手滑了",
    "再来一局",
    "你好，请多指教",
    "我快赢了！",
)

MAX_COMMENT_LENGTH = 60
MAX_EMOJI_LENGTH = 8
# 发送者昵称上限：昵称会显示在对话日志里，过长会挤爆日志面板。
MAX_SENDER_NAME_LENGTH = 32

# 客户端两次发言的最小间隔。
CHAT_INTERVAL_SECONDS = 0.8
# 服务端的限流窗口必须明显宽于客户端间隔：网络抖动会让按客户端
# 间隔发出的消息在服务端挤到一起，窗口太窄就会把守规矩的客户端
# 误判成"发言太快"。
CHAT_WINDOW_SECONDS = CHAT_INTERVAL_SECONDS * 2
# 一个限流窗口内允许的最大条数。
CHAT_BURST = 3


@dataclass(frozen=True)
class ChatMessage:
    """一条对局中的表情/评论消息。"""

    kind: str
    content: str
    sender_id: str
    sender_name: str
    sent_at_ms: int = 0


def _sanitize_comment(text: str) -> str:
    """去掉控制字符与格式字符，并把连续空白折叠成一个空格。

    控制字符（Cc，如换行、制表符）与格式字符（Cf，如零宽空格 U+200B、
    方向覆写 U+202E）会破坏对话日志的排版，甚至让日志看起来像是别人
    说的话。这里直接清洗而不是报错，避免用户因为一个看不见的字符
    就丢掉整条消息。
    """
    parts: list[str] = []
    for char in text:
        category = unicodedata.category(char)
        if category == "Cc":
            parts.append(" ")
        elif category == "Cf":
            continue
        else:
            parts.append(char)
    return " ".join("".join(parts).split())


def sanitize_comment(text: str) -> str:
    """公开的文本净化入口，供私聊等复用。"""
    return _sanitize_comment(text)


def normalize_chat_content(kind: str, content: object) -> str:
    """校验并规范化待发送的表情/评论；非法输入抛 ProtocolError。"""
    if kind not in CHAT_KINDS:
        raise ProtocolError("聊天消息类型非法")
    if not isinstance(content, str):
        raise ProtocolError("聊天内容必须是字符串")
    if kind == CHAT_KIND_EMOJI:
        if len(content) > MAX_EMOJI_LENGTH:
            raise ProtocolError("表情格式非法")
        if not is_emoji_preset(content):
            raise ProtocolError("不支持的表情")
        return content
    text = _sanitize_comment(content)
    if not text:
        raise ProtocolError("评论内容不能为空")
    if len(text) > MAX_COMMENT_LENGTH:
        raise ProtocolError("评论太长了")
    return text


def build_chat_payload(kind: str, content: object) -> dict[str, str]:
    """构造客户端 -> 服务端聊天 payload：``{"kind": ..., "content": ...}``。"""
    return {
        "kind": kind,
        "content": normalize_chat_content(kind, content),
    }


def parse_chat_message(payload: Mapping[str, Any]) -> ChatMessage:
    """校验并解析服务端下发的对局聊天消息。"""
    if not isinstance(payload, Mapping):
        raise ProtocolError("聊天消息必须是对象")

    kind = payload.get("kind")
    if not isinstance(kind, str) or kind not in CHAT_KINDS:
        raise ProtocolError("聊天消息类型非法")

    content = payload.get("content")
    if not isinstance(content, str) or not content:
        raise ProtocolError("聊天内容不能为空")
    if kind == CHAT_KIND_EMOJI:
        if not is_emoji_preset(content):
            raise ProtocolError("不支持的表情")
    elif len(content) > MAX_COMMENT_LENGTH:
        raise ProtocolError("评论太长了")

    sender_id = payload.get("sender_id")
    if not isinstance(sender_id, str) or not sender_id:
        raise ProtocolError("聊天消息缺少发送者")

    sender_name = payload.get("sender_name", "")
    if not isinstance(sender_name, str):
        sender_name = ""
    # 昵称会显示在日志里，过长或带控制字符都要收敛，避免刷屏与伪造。
    sender_name = _sanitize_comment(sender_name)[:MAX_SENDER_NAME_LENGTH]

    sent_at_ms = payload.get("sent_at_ms", 0)
    if (
        not isinstance(sent_at_ms, int)
        or isinstance(sent_at_ms, bool)
        or sent_at_ms < 0
    ):
        sent_at_ms = 0

    return ChatMessage(
        kind=kind,
        content=content,
        sender_id=sender_id,
        sender_name=sender_name,
        sent_at_ms=sent_at_ms,
    )


def is_emoji_preset(content: str) -> bool:
    """内容是否为受支持的表情。"""
    return content in EMOJI_PRESETS


__all__ = [
    "CHAT_KIND_EMOJI",
    "CHAT_KIND_TEXT",
    "CHAT_KINDS",
    "EMOJI_PRESETS",
    "COMMENT_PRESETS",
    "MAX_COMMENT_LENGTH",
    "MAX_EMOJI_LENGTH",
    "MAX_SENDER_NAME_LENGTH",
    "CHAT_INTERVAL_SECONDS",
    "CHAT_WINDOW_SECONDS",
    "CHAT_BURST",
    "ChatMessage",
    "sanitize_comment",
    "normalize_chat_content",
    "build_chat_payload",
    "parse_chat_message",
    "is_emoji_preset",
]
