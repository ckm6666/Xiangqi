"""联机服务端开发启动脚本。

优先使用 server/.venv 中的 Python；首次运行前请先安装服务端依赖：

    py -3 -m venv server\\.venv
    server\\.venv\\Scripts\\python.exe -m pip install -r server\\requirements-dev.txt

用法：
    python run_server.py              # 127.0.0.1:8765
    python run_server.py --reload     # 开发热重载
    python run_server.py --host 0.0.0.0 --port 9000
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def _venv_python() -> Path:
    if os.name == "nt":
        return ROOT / "server" / ".venv" / "Scripts" / "python.exe"
    return ROOT / "server" / ".venv" / "bin" / "python"


def main(argv: list[str]) -> int:
    python = _venv_python()
    if not python.exists():
        print(
            "[!] 未找到 server/.venv。请先执行：\n"
            "    py -3 -m venv server\\.venv\n"
            "    server\\.venv\\Scripts\\python.exe -m pip install "
            "-r server\\requirements-dev.txt",
            file=sys.stderr,
        )
        return 1

    cmd = [
        str(python),
        "-m",
        "uvicorn",
        "server.app.main:app",
        "--host",
        "127.0.0.1",
        "--port",
        "8765",
    ]
    # 允许透传 --host/--port/--reload 等参数。
    cmd.extend(argv)
    print(f"$ {' '.join(cmd)}")
    return subprocess.call(cmd, cwd=str(ROOT))


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
