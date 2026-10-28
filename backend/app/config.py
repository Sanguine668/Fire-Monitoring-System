from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STORAGE = ROOT / "storage"
UPLOADS = STORAGE / "uploads"
SNAPSHOTS = Path(os.environ.get("FIREGUARD_SNAPSHOTS", str(STORAGE / "snapshots")))
FRONTEND_DIST = ROOT / "frontend" / "dist"

DB_PATH = Path(os.environ.get("FIREGUARD_DB", str(STORAGE / "fireguard.db")))
_MODEL_CANDIDATES = [
    ROOT / "weights" / "fire26n-v2-best.pt",
    ROOT / "ai" / "runs" / "fire26n-v2" / "weights" / "best.pt",
]
_DEFAULT_MODEL = next((path for path in _MODEL_CANDIDATES if path.is_file()), _MODEL_CANDIDATES[0])
MODEL_PATH = Path(os.environ.get("FIREGUARD_MODEL", str(_DEFAULT_MODEL)))
FRAME_QUALITY = int(os.environ.get("FIREGUARD_FRAME_QUALITY", "80"))
DEFAULT_FPS = 4.0

# 推送消息里引用的系统对外地址；留空则按本机局域网 IP + 8000 端口自动推断
PUBLIC_BASE = os.environ.get("FIREGUARD_PUBLIC_BASE", "")
