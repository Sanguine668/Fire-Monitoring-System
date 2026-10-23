"""组员一键安装：创建 Python 虚拟环境、安装依赖、构建前端、初始化演示数据。"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VENV = ROOT / "ai" / ".venv"
VENV_PYTHON = VENV / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")


def run(command: list[str], cwd: Path | None = None) -> None:
    print("> " + " ".join(command), flush=True)
    subprocess.run(command, cwd=cwd or ROOT, check=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cuda", action="store_true", help="安装 CUDA 12.8 版 torch（NVIDIA 显卡）")
    ap.add_argument("--skip-install", action="store_true")
    ap.add_argument("--skip-frontend", action="store_true")
    ap.add_argument("--with-history", action="store_true", help="初始化 7 天演示告警趋势")
    args = ap.parse_args()

    if not args.skip_install:
        if not VENV_PYTHON.exists():
            run([sys.executable, "-m", "venv", str(VENV)])
        run([str(VENV_PYTHON), "-m", "pip", "install", "--upgrade", "pip"])
        if args.cuda:
            run([
                str(VENV_PYTHON), "-m", "pip", "install", "torch", "torchvision",
                "--index-url", "https://download.pytorch.org/whl/cu128",
            ])
        run([str(VENV_PYTHON), "-m", "pip", "install", "-r", "requirements.txt"])

    if not args.skip_frontend:
        npm = shutil.which("npm") or "npm"
        run([npm, "install"], cwd=ROOT / "frontend")
        run([npm, "run", "build"], cwd=ROOT / "frontend")

    bootstrap_python = VENV_PYTHON if VENV_PYTHON.exists() else Path(sys.executable)
    command = [str(bootstrap_python), "scripts/bootstrap_demo.py"]
    if args.with_history:
        command.append("--with-history")
    run(command)

    print("\n安装完成。启动后端：")
    print("  $env:FIREGUARD_DEVICE='0'")
    print("  ai\\.venv\\Scripts\\python -m uvicorn backend.app.main:app --host 0.0.0.0 --port 8000")
    print("浏览器打开 http://127.0.0.1:8000")


if __name__ == "__main__":
    main()
