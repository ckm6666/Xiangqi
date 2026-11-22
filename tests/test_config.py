"""AppConfig 环境变量解析测试。"""

from __future__ import annotations

import unittest

from xiangqi.client.config import AppConfig
from xiangqi.shared.errors import ConfigurationError


class AppConfigTests(unittest.TestCase):
    """XIANGQI_* 配置。"""

    def test_defaults_are_offline(self) -> None:
        config = AppConfig.from_env({})
        self.assertEqual(config.environment, "development")
        self.assertIsNone(config.api_base_url)
        self.assertIsNone(config.ws_base_url)
        self.assertEqual(config.request_timeout_seconds, 10.0)
        self.assertEqual(config.log_level, "INFO")
        self.assertFalse(config.online_configured)

    def test_valid_environment(self) -> None:
        config = AppConfig.from_env(
            {
                "XIANGQI_ENV": "production",
                "XIANGQI_API_BASE_URL": "https://example.com/api/",
                "XIANGQI_WS_BASE_URL": "wss://example.com/ws",
                "XIANGQI_REQUEST_TIMEOUT": "4.5",
                "XIANGQI_LOG_LEVEL": "debug",
            }
        )
        self.assertEqual(config.environment, "production")
        self.assertEqual(config.api_base_url, "https://example.com/api")
        self.assertEqual(config.ws_base_url, "wss://example.com/ws")
        self.assertEqual(config.request_timeout_seconds, 4.5)
        self.assertEqual(config.log_level, "DEBUG")
        self.assertTrue(config.online_configured)

    def test_only_one_url_is_not_online_configured(self) -> None:
        config = AppConfig.from_env(
            {"XIANGQI_API_BASE_URL": "http://localhost:8000"}
        )
        self.assertFalse(config.online_configured)

    def test_invalid_urls(self) -> None:
        for field in ("XIANGQI_API_BASE_URL", "XIANGQI_WS_BASE_URL"):
            with self.subTest(field=field):
                with self.assertRaises(ConfigurationError):
                    AppConfig.from_env({field: "ftp://example.com"})

    def test_invalid_log_level(self) -> None:
        with self.assertRaises(ConfigurationError):
            AppConfig.from_env({"XIANGQI_LOG_LEVEL": "TRACE"})

    def test_invalid_timeout(self) -> None:
        for value in ("0", "-1", "abc"):
            with self.subTest(value=value):
                with self.assertRaises(ConfigurationError):
                    AppConfig.from_env({"XIANGQI_REQUEST_TIMEOUT": value})

    def test_gomoku_prefix_is_ignored(self) -> None:
        config = AppConfig.from_env(
            {
                "GOMOKU_API_BASE_URL": "https://example.com",
                "GOMOKU_WS_BASE_URL": "wss://example.com",
            }
        )
        self.assertIsNone(config.api_base_url)
        self.assertIsNone(config.ws_base_url)


if __name__ == "__main__":
    unittest.main()
