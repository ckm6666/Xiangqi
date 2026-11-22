"""好友私聊的共享校验与消息模型。

私聊只允许好友之间发送，正文复用对局聊天的净化规则；历史由服务端
SQLite 持久化，客户端按消息 id 去重合并实时推送与历史记录。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from xiangqi.shared.chat import sanitize_comment

#: 单条私聊消息的最大字符数。
MAX_DIRECT_MESSAGE_LENGTH = 200


class SocialError(ValueError):
    """好友/私聊数据非法。"""


def normalize_direct_message(content: object) -> str:
    """净化并校验私聊正文；非法时抛出 :class:`SocialError`。"""
    if not isinstance(content, str):
        raise SocialError("消息格式非法")
    text = sanitize_comment(content)
    if not text:
        raise SocialError("消息不能为空")
    if len(text) > MAX_DIRECT_MESSAGE_LENGTH:
        raise SocialError(
            f"消息不能超过 {MAX_DIRECT_MESSAGE_LENGTH} 个字符"
        )
    return text


@dataclass(frozen=True)
class DirectMessage:
    """一条服务端下发的私聊消息。"""

    id: str
    sender_id: str
    sender_name: str
    recipient_id: str
    content: str
    sent_at_ms: int = 0


def parse_direct_message(payload: Any) -> DirectMessage:
    """解析服务端推送的私聊消息负载。"""
    if not isinstance(payload, Mapping):
        raise SocialError("私聊消息必须是对象")

    message_id = payload.get("id")
    sender_id = payload.get("sender_id")
    sender_name = payload.get("sender_name")
    recipient_id = payload.get("recipient_id")
    content = payload.get("content")
    sent_at_ms = payload.get("sent_at_ms", 0)

    if not isinstance(message_id, str) or not message_id:
        raise SocialError("私聊消息缺少 id")
    if not isinstance(sender_id, str) or not sender_id:
        raise SocialError("私聊消息缺少发送者")
    if not isinstance(sender_name, str) or not sender_name:
        raise SocialError("私聊消息缺少发送者名称")
    if not isinstance(recipient_id, str) or not recipient_id:
        raise SocialError("私聊消息缺少接收者")
    if not isinstance(content, str) or not content:
        raise SocialError("私聊消息正文为空")
    if len(content) > MAX_DIRECT_MESSAGE_LENGTH:
        raise SocialError("私聊消息过长")
    if not isinstance(sent_at_ms, int) or isinstance(sent_at_ms, bool):
        sent_at_ms = 0

    return DirectMessage(
        id=message_id,
        sender_id=sender_id,
        sender_name=sender_name[:32],
        recipient_id=recipient_id,
        content=content,
        sent_at_ms=sent_at_ms,
    )


__all__ = [
    "MAX_DIRECT_MESSAGE_LENGTH",
    "SocialError",
    "normalize_direct_message",
    "DirectMessage",
    "parse_direct_message",
]
