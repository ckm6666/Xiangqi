"""客户端运行配置。

当前单机/AI 功能不需要网络配置；这些字段为未来 OnlineSession 预留，
通过环境变量注入，不把服务器地址或任何密钥硬编码进 exe。配置中不包含
密码、access token 或 refresh token。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping, Optional
from urllib.parse import urlparse

from xiangqi.shared.errors import ConfigurationError

_VALID_LOG_LEVELS = {
    "CRITICAL",
    "ERROR",
    "WARNING",
    "INFO",
    "DEBUG",
}


def _optional_url(value: str, schemes: set[str], field: str) -> Optional[str]:
    """校验并规范化可选的 HTTP/WS 服务地址。"""
    value = value.strip()
    if not value:
        return None

    parsed = urlparse(value)
    if parsed.scheme not in schemes or not parsed.netloc:
        allowed = "/".join(sorted(schemes))
        raise ConfigurationError(f"{field} 必须是 {allowed} URL")
    return value.rstrip("/")


@dataclass(frozen=True)
class AppConfig:
    """应用运行时的非敏感配置。"""

    environment: str = "development"
    api_base_url: Optional[str] = None
    ws_base_url: Optional[str] = None
    request_timeout_seconds: float = 10.0
    log_level: str = "INFO"

    @property
    def online_configured(self) -> bool:
        """是否已同时配置 REST 与 WebSocket 地址。"""
        return bool(self.api_base_url and self.ws_base_url)

    @classmethod
    def from_env(
        cls, environ: Optional[Mapping[str, str]] = None
    ) -> "AppConfig":
        """从环境变量读取配置；不读取本地密钥文件。"""
        source = os.environ if environ is None else environ

        api_url = _optional_url(
            source.get("XIANGQI_API_BASE_URL", ""),
            {"https", "http"},
            "XIANGQI_API_BASE_URL",
        )
        ws_url = _optional_url(
            source.get("XIANGQI_WS_BASE_URL", ""),
            {"wss", "ws"},
            "XIANGQI_WS_BASE_URL",
        )

        log_level = source.get("XIANGQI_LOG_LEVEL", "INFO").strip().upper()
        if log_level not in _VALID_LOG_LEVELS:
            raise ConfigurationError(
                "XIANGQI_LOG_LEVEL 必须是 DEBUG/INFO/WARNING/ERROR/CRITICAL"
            )

        raw_timeout = source.get("XIANGQI_REQUEST_TIMEOUT", "10").strip()
        try:
            timeout = float(raw_timeout)
        except ValueError as exc:
            raise ConfigurationError(
                "XIANGQI_REQUEST_TIMEOUT 必须是正数"
            ) from exc
        if timeout <= 0:
            raise ConfigurationError("XIANGQI_REQUEST_TIMEOUT 必须大于 0")

        return cls(
            environment=source.get("XIANGQI_ENV", "development").strip()
            or "development",
            api_base_url=api_url,
            ws_base_url=ws_url,
            request_timeout_seconds=timeout,
            log_level=log_level,
        )


__all__ = ["AppConfig"]
