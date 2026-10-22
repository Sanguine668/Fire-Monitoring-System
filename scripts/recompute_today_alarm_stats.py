"""按 alarms 表的实际记录重算今天的日统计，避免合并告警重复计数。"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app import db


def main() -> None:
    day = datetime.now().date().isoformat()
    with db._conn() as c:
        c.execute("DELETE FROM alarm_daily WHERE day=?", (day,))
        c.execute(
            """
            INSERT INTO alarm_daily(day, fire_count, smoke_count, handled_count, total_count)
            SELECT substr(created_at, 1, 10),
                   SUM(CASE WHEN alarm_type='fire' THEN 1 ELSE 0 END),
                   SUM(CASE WHEN alarm_type='smoke' THEN 1 ELSE 0 END),
                   SUM(CASE WHEN status='handled' THEN 1 ELSE 0 END),
                   COUNT(*)
            FROM alarms
            WHERE substr(created_at, 1, 10)=?
            GROUP BY 1
            """,
            (day,),
        )
        row = c.execute("SELECT * FROM alarm_daily WHERE day=?", (day,)).fetchone()
        print(dict(row) if row else {"day": day, "total": 0})


if __name__ == "__main__":
    main()
