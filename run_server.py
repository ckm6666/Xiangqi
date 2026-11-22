"""联机服务端启动脚本。

优先使用 server/.venv 中的 Python；首次运行前请先安装服务端依赖：
    py -3 -m venv server\\.venv
    server\\.venv\\Scripts\\python.exe -m pip install -r server\\requirements-dev.txt

用法：
    python run_server.py                  # 前台运行，日志输出到当前终端
    python run_server.py --background     # 后台运行，不弹出控制台窗口
    python run_server.py --status         # 查看后台服务器状态
    python run_server.py --stop           # 停止后台服务器
    python run_server.py --host 0.0.0.0 --port 9000
    python run_server.py --reload         # 开发热重载（仅前台）

也可以直接双击 start_server.vbs，在后台静默启动。
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "server" / "data"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = "8765"
OWN_FLAGS = ("--background", "--status", "--stop")


def _say(message: str = "", *, error: bool = False) -> None:
    """pythonw.exe 没有控制台，打印时静默跳过而不是抛异常。"""
    stream = sys.stderr if error else sys.stdout
    if stream is None:
        return
    print(message, file=stream, flush=True)


def _option(argv: list[str], name: str, default: str) -> str:
    for index, arg in enumerate(argv):
        if arg == name and index + 1 < len(argv):
            return argv[index + 1]
        if arg.startswith(f"{name}="):
            return arg.split("=", 1)[1]
    return default


def _uvicorn_extra_args(argv: list[str]) -> list[str]:
    """保留 uvicorn 参数，去掉本脚本的开关与重复的 host/port。"""
    result: list[str] = []
    index = 0
    while index < len(argv):
        arg = argv[index]
        if arg in OWN_FLAGS:
            index += 1
        elif arg in ("--host", "--port"):
            index += 2
        elif arg.startswith("--host=") or arg.startswith("--port="):
            index += 1
        else:
            result.append(arg)
            index += 1
    return result


def _venv_python(*, windowless: bool = False) -> Path:
    if os.name == "nt":
        name = "pythonw.exe" if windowless else "python.exe"
        return ROOT / "server" / ".venv" / "Scripts" / name
    return ROOT / "server" / ".venv" / "bin" / "python"


def _probe_host(host: str) -> str:
    return "127.0.0.1" if host in ("", "0.0.0.0", "::") else host


def _health_url(host: str, port: str) -> str:
    return f"http://{_probe_host(host)}:{port}/api/v1/health"


def _health(host: str, port: str, timeout: float = 1.0) -> tuple[bool, str]:
    try:
        with urllib.request.urlopen(
            _health_url(host, port), timeout=timeout
        ) as response:
            body = response.read().decode("utf-8", "replace")
            return response.status == 200, body
    except Exception as exc:  # 连接拒绝、超时、端口没有服务等
        return False, str(exc)


def _pid_path(port: str) -> Path:
    return DATA_DIR / f"server-{port}.pid"


def _log_paths(port: str) -> tuple[Path, Path]:
    return (
        DATA_DIR / f"server-{port}.out.log",
        DATA_DIR / f"server-{port}.err.log",
    )


def _check_venv() -> bool:
    if _venv_python().exists():
        return True
    _say(
        "[!] 未找到 server/.venv。请先执行：\n"
        "    py -3 -m venv server\\.venv\n"
        "    server\\.venv\\Scripts\\python.exe -m pip install "
        "-r server\\requirements-dev.txt",
        error=True,
    )
    return False


def _uvicorn_command(
    python: Path,
    host: str,
    port: str,
    argv: list[str],
) -> list[str]:
    return [
        str(python),
        "-m",
        "uvicorn",
        "server.app.main:app",
        "--host",
        host,
        "--port",
        port,
        *_uvicorn_extra_args(argv),
    ]


def run_foreground(argv: list[str]) -> int:
    if not _check_venv():
        return 1
    host = _option(argv, "--host", DEFAULT_HOST)
    port = _option(argv, "--port", DEFAULT_PORT)
    cmd = _uvicorn_command(_venv_python(), host, port, argv)
    _say(f"$ {' '.join(cmd)}")
    return subprocess.call(cmd, cwd=str(ROOT))


def run_background(argv: list[str]) -> int:
    if "--reload" in argv:
        _say(
            "[!] --background 不支持 --reload，请在前台使用热重载。",
            error=True,
        )
        return 2
    host = _option(argv, "--host", DEFAULT_HOST)
    port = _option(argv, "--port", DEFAULT_PORT)
    running, _detail = _health(host, port)
    if running:
        _say(f"[OK] 服务器已在运行：{_health_url(host, port)}")
        return 0
    if not _check_venv():
        return 1
    python = _venv_python(windowless=True)
    if not python.exists():
        _say(f"[!] 未找到 {python}", error=True)
        return 1

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    out_log, err_log = _log_paths(port)
    pid_path = _pid_path(port)
    cmd = _uvicorn_command(python, host, port, argv)

    kwargs: dict[str, object] = {
        "cwd": str(ROOT),
        "stdin": subprocess.DEVNULL,
        "close_fds": True,
    }
    if os.name == "nt":
        # 完全脱离当前控制台，避免后台服务弹出窗口。
        kwargs["creationflags"] = (
            subprocess.DETACHED_PROCESS
            | subprocess.CREATE_NEW_PROCESS_GROUP
        )
    else:
        kwargs["start_new_session"] = True

    with open(out_log, "ab") as out, open(err_log, "ab") as err:
        process = subprocess.Popen(
            cmd,
            stdout=out,
            stderr=err,
            **kwargs,
        )
    pid_path.write_text(str(process.pid), encoding="utf-8")

    deadline = time.monotonic() + 8.0
    while time.monotonic() < deadline:
        if process.poll() is not None:
            break
        if _health(host, port, timeout=0.4)[0]:
            _say(f"[OK] 后台服务器已启动：PID {process.pid}")
            _say(f"     健康检查：{_health_url(host, port)}")
            _say(f"     日志：{out_log} / {err_log}")
            _say(f"     停止：python run_server.py --stop --port {port}")
            return 0
        time.sleep(0.2)

    if process.poll() is not None:
        pid_path.unlink(missing_ok=True)
        _say("[!] 后台服务器启动失败，请查看日志：", error=True)
        _say(f"     {err_log}", error=True)
        return 1

    _say(
        f"[OK] 后台服务器进程已启动（PID {process.pid}），"
        "健康检查稍后可用。"
    )
    _say(f"     日志：{out_log} / {err_log}")
    return 0


def _taskkill(pid: int) -> bool:
    if os.name != "nt":
        try:
            os.kill(pid, signal.SIGTERM)
            return True
        except OSError:
            return False
    # 只结束 python 进程，避免 PID 被复用时误杀其他程序。
    try:
        listing = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
            capture_output=True,
            text=True,
            timeout=5,
        ).stdout.lower()
    except Exception:
        return False
    if "python" not in listing:
        return False
    try:
        result = subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            capture_output=True,
            timeout=10,
        )
    except Exception:
        return False
    return result.returncode == 0


def run_stop(argv: list[str]) -> int:
    port = _option(argv, "--port", DEFAULT_PORT)
    pid_path = _pid_path(port)
    if not pid_path.exists():
        _say(
            "没有找到后台服务器的 PID 文件；"
            "如果服务器在前台运行，请在终端按 Ctrl+C。"
        )
        return 1
    try:
        pid = int(pid_path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        pid_path.unlink(missing_ok=True)
        _say("PID 文件无效，已清理。", error=True)
        return 1
    if not _taskkill(pid):
        pid_path.unlink(missing_ok=True)
        _say("后台服务器已不在运行，已清理 PID 文件。")
        return 0
    pid_path.unlink(missing_ok=True)
    _say(f"[OK] 已停止后台服务器（PID {pid}）。")
    return 0


def run_status(argv: list[str]) -> int:
    host = _option(argv, "--host", DEFAULT_HOST)
    port = _option(argv, "--port", DEFAULT_PORT)
    running, detail = _health(host, port)
    if not running:
        _say(f"[未运行] {_health_url(host, port)}（{detail}）")
        return 1
    pid_text = ""
    pid_path = _pid_path(port)
    if pid_path.exists():
        try:
            pid_text = (
                f"，PID {pid_path.read_text(encoding='utf-8').strip()}"
            )
        except OSError:
            pass
    _say(f"[运行中] {_health_url(host, port)}{pid_text}")
    _say(f"         健康检查：{detail}")
    out_log, err_log = _log_paths(port)
    _say(f"         日志：{out_log} / {err_log}")
    return 0


def main(argv: list[str]) -> int:
    if "--stop" in argv:
        return run_stop(argv)
    if "--status" in argv:
        return run_status(argv)
    if "--background" in argv:
        return run_background(argv)
    return run_foreground(argv)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
