"""为演示补齐最近 7 天告警趋势（明确为演示数据，全部标记为已处理）。"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app import db  # noqa: E402


def main() -> None:
    db.init_db()
    now = datetime.now()
    with db._conn() as c:
        existing = c.execute(
            "SELECT COUNT(*) n FROM alarm_daily WHERE day < ?",
            (now.date().isoformat(),),
        ).fetchone()["n"]
        if existing:
            print("已有历史日统计，跳过演示数据")
            return

        cameras = [dict(r) for r in c.execute("SELECT id,name FROM cameras ORDER BY id").fetchall()]
        if not cameras:
            cameras = [{"id": 1, "name": "演示视频源"}]

        # 7 天：前 6 天为历史，今天补 2 条已处理演示记录
        counts = [4, 6, 3, 8, 5, 7, 2]
        inserted = 0
        for offset, count in enumerate(counts):
            day = now.date() - timedelta(days=6 - offset)
            for i in range(count):
                kind = "fire" if (offset + i) % 3 == 0 else "smoke"
                level = "critical" if kind == "fire" else "warning"
                camera = cameras[(offset + i) % len(cameras)]
                created = f"{day.isoformat()} {8 + (i * 37) // 60:02d}:{(i * 37) % 60:02d}:00"
                confidence = round(0.56 + ((offset * 3 + i) % 34) / 100, 3)
                c.execute(
                    "INSERT INTO alarms(camera_id,camera_name,alarm_type,level,confidence,"
                    "created_at,status,count,verified,updated_at)"
                    " VALUES(?,?,?,?,?,?,'handled',1,1,?)",
                    (camera["id"], camera["name"], kind, level, confidence, created, created),
                )
                db._bump_daily(c, day.isoformat(), kind, handled=1)
                inserted += 1
    print(f"已插入 {inserted} 条演示历史告警，覆盖最近 7 天")


if __name__ == "__main__":
    main()
