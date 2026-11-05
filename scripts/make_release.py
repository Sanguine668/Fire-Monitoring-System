"""打包"最小可完整运行"的源码包（用于上交）。

只收录运行必需的文件，剔除数据集、训练产物、文档图片、依赖目录与运行数据。

用法（仓库根目录）：
    python scripts/make_release.py
产出：
    release/FireGuard-AI-源码包/        （目录形式，便于检查）
    release/FireGuard-AI-源码包.zip     （上交用）
"""
from __future__ import annotations

import shutil
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT_ROOT = ROOT / "release"
PKG_NAME = "FireGuard-AI-源码包"
PKG = OUT_ROOT / PKG_NAME

# 逐项收录：目录 / 文件
INCLUDE_DIRS = [
    "backend",                  # 后端全部代码
    "frontend/src",             # 前端源码
    "frontend/dist",            # 前端构建产物（免去安装 Node 也能跑）
    "scripts",                  # 安装/引导/工具脚本
    "samples",                  # 演示视频（bootstrap 会用）
    "tests",                    # 若存在则一并带上
]
INCLUDE_FILES = [
    "requirements.txt",
    "README.md",
    "frontend/package.json",
    "frontend/package-lock.json",
    "frontend/vite.config.js",
    "frontend/index.html",
    "frontend/README.md",
]
# 权重：只带推理必需的（上一版留作回退），不带走 yolo26n.pt 等中间产物
INCLUDE_GLOBS = [
    "weights/fire26n-v2-far.pt",
    "weights/fire26n-v2-best.pt",
]

EXCLUDE_DIR_NAMES = {"__pycache__", "node_modules", ".venv", ".git", ".pytest_cache", ".vscode"}
EXCLUDE_SUFFIXES = {".pyc", ".pyo", ".log"}


def copy_tree(src: Path, dst: Path) -> int:
    count = 0
    for item in src.rglob("*"):
        if item.is_dir():
            continue
        rel = item.relative_to(src)
        if any(part in EXCLUDE_DIR_NAMES for part in rel.parts):
            continue
        if item.suffix.lower() in EXCLUDE_SUFFIXES:
            continue
        target = dst / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(item, target)
        count += 1
    return count


def build_files() -> dict[str, str]:
    return {
        "run.ps1": RUN_PS1,
        "run.bat": RUN_BAT,
        "运行说明.md": RUN_DOC,
        ".gitignore": "ai/.venv/\nstorage/\nfrontend/node_modules/\n__pycache__/\n*.pyc\nrelease/\n",
    }


RUN_PS1 = r"""# FireGuard AI 一键运行（Windows）
# 首次运行会自动创建虚拟环境、安装依赖、初始化演示数据；之后再运行直接启动。
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot

function Step($msg) { Write-Host "`n=== $msg ===" -ForegroundColor Cyan }
function Fail($msg) { Write-Host $msg -ForegroundColor Red; Read-Host '按回车退出'; exit 1 }

$venvPy = Join-Path $PSScriptRoot 'ai\.venv\Scripts\python.exe'

Step '检查 Python'
$pyCmd = Get-Command python -ErrorAction SilentlyContinue
if (-not $pyCmd) { $pyCmd = Get-Command py -ErrorAction SilentlyContinue }
if (-not $pyCmd) { Fail '未找到 Python。请安装 Python 3.12 并在安装时勾选 Add python.exe to PATH。' }
& $pyCmd.Source --version

if (-not (Test-Path -LiteralPath $venvPy)) {
    Step '首次运行：创建虚拟环境（约 10 秒）'
    & $pyCmd.Source -m venv (Join-Path $PSScriptRoot 'ai\.venv')
    if (-not (Test-Path -LiteralPath $venvPy)) { Fail '虚拟环境创建失败。' }

    Step '安装 PyTorch（约 2.5 GB，需联网，5-15 分钟）'
    & $venvPy -m pip install --upgrade pip
    & $venvPy -m pip install torch torchvision --index-url https://download.pytorch.org/whl/cu128
    if ($LASTEXITCODE -ne 0) {
        Write-Host 'CUDA 版安装失败，改用 CPU 版（速度较慢但可运行）' -ForegroundColor Yellow
        & $venvPy -m pip install torch torchvision
    }

    Step '安装其余依赖'
    & $venvPy -m pip install -r (Join-Path $PSScriptRoot 'requirements.txt')
}

if (-not (Test-Path -LiteralPath 'frontend\dist\index.html')) {
    Step '构建前端（需要 Node.js 20+）'
    if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
        Fail '缺少 frontend/dist 且未安装 Node.js。请安装 Node.js 20+ 后重试，或直接使用随包提供的 dist 目录。'
    }
    Push-Location frontend
    npm install
    npm run build
    Pop-Location
}

Step '初始化演示数据（视频源、演示视频、存储目录）'
& $venvPy scripts\bootstrap_demo.py

Step '启动服务'
$url = 'http://127.0.0.1:8000'
Write-Host "  访问地址： $url" -ForegroundColor Green
Write-Host '  手机访问：本机局域网 IP + :8000（同一 WiFi）' -ForegroundColor Green
Write-Host '  停止服务：在本窗口按 Ctrl+C' -ForegroundColor Green
Start-Sleep -Milliseconds 800
Start-Process $url
& $venvPy -m uvicorn backend.app.main:app --host 0.0.0.0 --port 8000
"""

RUN_BAT = r"""@echo off
chcp 65001 >nul
title FireGuard AI
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0run.ps1"
echo.
echo Server exited.
pause
"""

RUN_DOC = """# FireGuard AI 火情监测系统 — 运行说明

## 一、双击运行

直接双击 **`run.bat`**（或右键 `run.ps1` → 使用 PowerShell 运行）。

首次运行会自动完成：

1. 创建 `ai/.venv` 虚拟环境；
2. 安装 PyTorch（CUDA 12.8 版；装不上会自动退回 CPU 版）与其余依赖；
3. 检查 `frontend/dist`（本包已自带构建产物，无需再装前端依赖）；
4. 初始化演示数据（复制演示视频、创建 3 路演示视频源、生成 7 天演示告警）；
5. 启动服务并自动打开浏览器。

再次运行（已装好环境）会直接启动，约 **10 秒**可用。

## 二、访问地址

- 本机：<http://127.0.0.1:8000>
- 手机/局域网：`http://<本机局域网IP>:8000`（手机与电脑连同一 WiFi；页面「手机接入向导」会显示本机地址）
- 接口文档：<http://127.0.0.1:8000/docs>

## 三、环境要求

| 项 | 要求 | 说明 |
|---|---|---|
| 操作系统 | Windows 10/11 x64 | 已在 Windows 11 + Python 3.12.10 验证 |
| Python | 3.12（需在 PATH 中） | 安装时勾选 *Add python.exe to PATH* |
| Node.js | 20+（可选） | 仅当 `frontend/dist` 缺失时才需要构建前端 |
| NVIDIA 显卡 | 可选 | 有 GPU 时自动使用 CUDA；无 GPU 用 CPU 也能跑，帧率较低 |
| 磁盘 | 约 6 GB | PyTorch 约 2.5 GB + 依赖 + 模型 |

## 四、目录说明

```
backend/             FastAPI 后端（检测 worker、告警、推送、距离估算）
frontend/src|dist/   Vue3 前端源码与已构建产物
scripts/             一键安装引导、演示数据、评测与工具脚本
samples/             演示视频（安装时复制到 storage/uploads）
weights/             推理权重 fire26n-v2-far.pt（主）/ fire26n-v2-best.pt（回退）
requirements.txt     Python 依赖
run.bat / .ps1  一键启动
```

运行后新增（可随时删除，不影响源码）：

```
ai/.venv/            虚拟环境
storage/             数据库、上传视频、告警快照（含推送配置，属本机私有数据）
```

## 五、常见问题

**1. 提示"未找到 Python"**
安装 Python 3.12 时勾选 *Add python.exe to PATH*，重开一个命令行窗口再试。

**2. PyTorch 下载很慢**
可换国内镜像：`ai\\.venv\\Scripts\\python -m pip install torch torchvision -i https://pypi.tuna.tsinghua.edu.cn/simple`，
或先只装 CPU 版：`... torch torchvision --index-url https://download.pytorch.org/whl/cpu`。

**3. 页面打不开**
服务窗口是否还在运行？端口 8000 是否被占用（换端口：`ai\\.venv\\Scripts\\python -m uvicorn backend.app.main:app --port 8001`）。

**4. 视频源显示离线**
演示视频在 `storage/uploads/`；若被删除，重新运行一次 `run.bat` 或执行
`ai\\.venv\\Scripts\\python scripts\\bootstrap_demo.py` 会重新复制。

**5. 想清空演示告警**
页面「告警中心 → 清空」，或删除 `storage/fireguard.db` 后重启（会重新生成演示数据）。

**6. 手机推送如何配置**
「系统设置 → 告警推送」填自己的 Server酱 SendKey 并启用。**本包不含任何密钥**，不配置时检测、告警、画面留存等功能全部正常，仅不推送。

## 六、已验证的指标（答辩可引用）

- 远景烟雾（520 张 D-Fire 远景子集）：图级召回 **90.1%**、实例精确率 **82.5%**，误报图 40/520
- 明火图级召回 **95.1%**
- 最小可靠目标高度 **28 像素**；1080p+12 mm 镜头对应约 **3.7 km**，实际可用约 2.6 km
- 距离估算：手机默认（1.5 m 高/12° 俯角/66° 视场角），画面下 1/4 走地面几何，其余按目标像素尺寸反推
"""


def main() -> None:
    if OUT_ROOT.exists():
        shutil.rmtree(OUT_ROOT)
    PKG.mkdir(parents=True)

    total = 0
    print("打包最小可运行集：")
    for rel in INCLUDE_DIRS:
        src = ROOT / rel
        if not src.exists():
            print(f"  跳过（不存在）: {rel}")
            continue
        n = copy_tree(src, PKG / rel)
        total += n
        size = sum(p.stat().st_size for p in (PKG / rel).rglob("*") if p.is_file())
        print(f"  {rel:<18} {n:>4} 文件  {size / 1048576:8.1f} MB")

    for rel in INCLUDE_FILES:
        src = ROOT / rel
        if src.is_file():
            dst = PKG / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            total += 1
            print(f"  {rel:<18}   1 文件")

    for rel in INCLUDE_GLOBS:
        src = ROOT / rel
        if src.is_file():
            dst = PKG / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            total += 1
            print(f"  {rel:<18}   1 文件  {src.stat().st_size / 1048576:8.1f} MB")

    for name, content in build_files().items():
        # .ps1 必须带 BOM：Windows PowerShell 5.1 无 BOM 时会按 ANSI 解码，
        # 中文被误解后引号/大括号配对被破坏，脚本直接语法报错。
        enc = "utf-8-sig" if name.endswith(".ps1") else "utf-8"
        (PKG / name).write_text(content, encoding=enc)
        total += 1
        print(f"  {name:<18}   1 文件")

    # 占位目录，保证解压后结构完整
    for d in ("storage", "ai/runs", "datasets"):
        (PKG / d).mkdir(parents=True, exist_ok=True)

    zip_path = OUT_ROOT / f"{PKG_NAME}.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for item in PKG.rglob("*"):
            if item.is_file():
                zf.write(item, item.relative_to(OUT_ROOT))

    pkg_size = sum(p.stat().st_size for p in PKG.rglob("*") if p.is_file())
    print(f"\n共 {total} 个文件")
    print(f"目录：{PKG}  ({pkg_size / 1048576:.1f} MB)")
    print(f"压缩包：{zip_path}  ({zip_path.stat().st_size / 1048576:.1f} MB)")


if __name__ == "__main__":
    sys.exit(main())
