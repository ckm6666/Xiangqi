"""客户端打包脚本。

依据 README「打包成 exe」一节，等价于执行：

    pyinstaller --noconfirm --clean Xiangqi.spec

产物为 dist/Xiangqi.exe（onefile + windowed）。

用法：
    python build.py            # 正常打包
    python build.py --fast     # 跳过 --clean（复用上次的缓存）
    python build.py --install  # 先安装 requirements-dev.txt 依赖再打包

附加参数会原样透传给 PyInstaller，例如：
    python build.py -- --windowed --debug
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SPEC = ROOT / "Xiangqi.spec"
APP_NAME = "Xiangqi"


def _run(cmd: list[str], **kwargs) -> int:
    print(f"$ {' '.join(cmd)}")
    return subprocess.call(cmd, cwd=str(ROOT), **kwargs)


def _ensure_pyinstaller() -> bool:
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print(
            "[!] 未检测到 PyInstaller，请先安装构建依赖：\n"
            "    pip install -r requirements-dev.txt",
            file=sys.stderr,
        )
        return False
    return True


def _install_deps() -> int:
    req = ROOT / "requirements-dev.txt"
    if not req.exists():
        print(f"[!] 缺少依赖清单：{req}", file=sys.stderr)
        return 1
    return _run([sys.executable, "-m", "pip", "install", "-r", str(req)])


def main(argv: list[str]) -> int:
    if not SPEC.exists():
        print(f"[!] 缺少 spec 文件：{SPEC}", file=sys.stderr)
        return 1

    if "--install" in argv:
        argv = [a for a in argv if a != "--install"]
        code = _install_deps()
        if code != 0:
            return code

    if not _ensure_pyinstaller():
        return 1

    cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm"]
    if "--fast" not in argv:
        cmd.append("--clean")
    argv = [a for a in argv if a != "--fast"]
    if "--" in argv:
        extra = argv[argv.index("--") + 1 :]
        argv = argv[: argv.index("--")]
        cmd.extend(extra)

    cmd.append(SPEC.name)

    code = _run(cmd)
    if code != 0:
        print("[!] 打包失败，请查看上方 PyInstaller 日志。", file=sys.stderr)
        return code

    exe = ROOT / "dist" / f"{APP_NAME}.exe"
    if exe.exists():
        size_mb = exe.stat().st_size / 1024 / 1024
        print(f"[OK] 打包完成：{exe}（约 {size_mb:.1f} MB）")
        print(
            "     分发时记得把 xiangqi/client/assets/THIRD_PARTY_NOTICES.md "
            "与字体目录中的 OFL 文本一并放到 exe 旁边。"
        )
    else:
        print(f"[OK] 打包结束，产物应位于 {ROOT / 'dist'}")
    return 0


if __name__ == "__main__":
    os.chdir(ROOT)
    raise SystemExit(main(sys.argv[1:]))
