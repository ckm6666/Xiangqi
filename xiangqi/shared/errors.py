"""跨层共享的异常类型。

客户端界面应把这些异常当作可恢复错误处理：配置错误回退到离线默认值，
协议错误记录日志后拒绝该消息，会话错误提示玩家但不阻塞棋盘操作。
"""

from __future__ import annotations


class XiangqiError(Exception):
    """中国象棋项目所有自定义异常的基类。"""


class ConfigurationError(XiangqiError):
    """环境变量或本地配置缺失、格式非法。"""


class ProtocolError(XiangqiError):
    """联机消息信封或载荷不符合协议。"""


class TransportError(XiangqiError):
    """WebSocket 连接或发送失败。"""


class SessionError(XiangqiError):
    """会话层无法完成请求（例如状态不一致）。"""


class RecordError(XiangqiError):
    """棋谱数据损坏或版本不受支持。"""


__all__ = [
    "XiangqiError",
    "ConfigurationError",
    "ProtocolError",
    "TransportError",
    "SessionError",
    "RecordError",
]
