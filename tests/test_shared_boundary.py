"""领域层边界测试：shared 不得依赖 Qt 或客户端。"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SHARED = ROOT / "xiangqi" / "shared"
FORBIDDEN_IMPORT = re.compile(
    r"^\s*(?:from|import)\s+(?:PySide6|xiangqi\.client)\b",
    re.MULTILINE,
)


class SharedBoundaryTests(unittest.TestCase):
    """扫描源码，防止 shared 引入 UI/网络依赖。"""

    def test_shared_does_not_import_qt_or_client(self) -> None:
        offenders: list[str] = []
        for path in sorted(SHARED.rglob("*.py")):
            source = path.read_text(encoding="utf-8")
            if FORBIDDEN_IMPORT.search(source):
                offenders.append(str(path.relative_to(ROOT)))
        self.assertEqual(offenders, [])

    def test_shared_package_exists(self) -> None:
        self.assertTrue((SHARED / "rules.py").is_file())
        self.assertTrue((SHARED / "game_model.py").is_file())


if __name__ == "__main__":
    unittest.main()
