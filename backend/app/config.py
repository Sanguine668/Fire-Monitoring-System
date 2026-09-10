from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STORAGE = ROOT / "storage"
UPLOADS = STORAGE / "uploads"
SNAPSHOTS = STORAGE / "snapshots"
FRONTEND_DIST = ROOT / "frontend" / "dist"

DB_PATH = Path(os.environ.get("FIREGUARD_DB", str(STORAGE / "fireguard.db")))
MODEL_PATH = Path(os.environ.get("FIREGUARD_MODEL", str(ROOT / "ai" / "runs" / "fire26n" / "weights" / "best.pt")))
FRAME_QUALITY = int(os.environ.get("FIREGUARD_FRAME_QUALITY", "80"))
DEFAULT_FPS = 4.0
