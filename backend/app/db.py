from __future__ import annotations

import sqlite3
import time
from datetime import datetime, timedelta
from typing import Any

from .config import DB_PATH


def _conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=5)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=3000")
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _bump_daily(c: sqlite3.Connection, day: str, alarm_type: str, handled: int = 0) -> None:
    fire = 1 if alarm_type == "fire" else 0
    smoke = 1 if alarm_type == "smoke" else 0
    c.execute(
        """
        INSERT INTO alarm_daily(day, fire_count, smoke_count, handled_count, total_count)
        VALUES(?,?,?,?,1)
        ON CONFLICT(day) DO UPDATE SET
            fire_count=fire_count+excluded.fire_count,
            smoke_count=smoke_count+excluded.smoke_count,
            handled_count=handled_count+excluded.handled_count,
            total_count=total_count+1
        """,
        (day, fire, smoke, handled),
    )


def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _conn() as c:
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS cameras (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                location TEXT NOT NULL DEFAULT '',
                source_type TEXT NOT NULL,
                source TEXT NOT NULL,
                loop INTEGER NOT NULL DEFAULT 1,
                online INTEGER NOT NULL DEFAULT 0,
                enabled INTEGER NOT NULL DEFAULT 1,
                alerts_enabled INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS alarms (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                camera_id INTEGER NOT NULL,
                camera_name TEXT NOT NULL,
                alarm_type TEXT NOT NULL,
                level TEXT NOT NULL,
                confidence REAL NOT NULL,
                created_at TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'unhandled',
                count INTEGER NOT NULL DEFAULT 1,
                verified INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT
            );
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS alarm_daily (
                day TEXT PRIMARY KEY,
                fire_count INTEGER NOT NULL DEFAULT 0,
                smoke_count INTEGER NOT NULL DEFAULT 0,
                handled_count INTEGER NOT NULL DEFAULT 0,
                total_count INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS notify_daily (
                day TEXT PRIMARY KEY,
                count INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS alarm_notifications (
                camera_id INTEGER PRIMARY KEY,
                alarm_id INTEGER NOT NULL,
                alarm_type TEXT NOT NULL,
                title TEXT NOT NULL,
                ok INTEGER NOT NULL DEFAULT 0,
                code INTEGER,
                message TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            );
            """
        )
        for k, v in {
            "fire_threshold": "0.40",
            "smoke_threshold": "0.25",
            "continuous_frames": "3",
            "alarm_cooldown": "8",
            "tiling_enabled": "1",
            "tile_size": "640",
            "tile_overlap": "0.2",
            "tile_interval": "2",
            "verify_enabled": "1",
            "verify_threshold": "0.25",
            "notify_enabled": "0",
            "notify_sendkey": "",
            "notify_name": "",
            "notify_daily_limit": "5",
        }.items():
            c.execute("INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)", (k, v))
        current = {r["key"]: r["value"] for r in c.execute("SELECT * FROM settings").fetchall()}
        if current.get("fire_threshold") == "0.1" and current.get("smoke_threshold") == "0.1":
            c.execute("UPDATE settings SET value='0.40' WHERE key='fire_threshold'")
            c.execute("UPDATE settings SET value='0.45' WHERE key='smoke_threshold'")
        columns = {r["name"] for r in c.execute("PRAGMA table_info(alarms)").fetchall()}
        if "count" not in columns:
            c.execute("ALTER TABLE alarms ADD COLUMN count INTEGER NOT NULL DEFAULT 1")
        if "updated_at" not in columns:
            c.execute("ALTER TABLE alarms ADD COLUMN updated_at TEXT")
        if "verified" not in columns:
            c.execute("ALTER TABLE alarms ADD COLUMN verified INTEGER NOT NULL DEFAULT 0")
        for column, decl in (
            ("snapshot_first", "TEXT"),
            ("snapshot_latest", "TEXT"),
            ("boxes", "TEXT"),
            ("frame_size", "TEXT"),
        ):
            if column not in columns:
                c.execute(f"ALTER TABLE alarms ADD COLUMN {column} {decl}")
        camera_columns = {r["name"] for r in c.execute("PRAGMA table_info(cameras)").fetchall()}
        if "alerts_enabled" not in camera_columns:
            c.execute("ALTER TABLE cameras ADD COLUMN alerts_enabled INTEGER NOT NULL DEFAULT 1")
        for column, decl in (
            ("install_height_m", "REAL"),
            ("pitch_deg", "REAL"),
            ("hfov_deg", "REAL"),
            ("geometry_preset", "TEXT"),
        ):
            if column not in camera_columns:
                c.execute(f"ALTER TABLE cameras ADD COLUMN {column} {decl}")


def insert_camera(name: str, source_type: str, source: str, location: str = "", loop: int = 1) -> int:
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO cameras(name,location,source_type,source,loop,online,enabled,created_at)"
            " VALUES(?,?,?,?,?,0,1,?)",
            (name, location, source_type, source, loop, now_text()),
        )
        return int(cur.lastrowid)


def list_cameras() -> list[dict[str, Any]]:
    with _conn() as c:
        return [dict(r) for r in c.execute("SELECT * FROM cameras ORDER BY id").fetchall()]


def get_camera(camera_id: int) -> dict[str, Any] | None:
    with _conn() as c:
        row = c.execute("SELECT * FROM cameras WHERE id=?", (camera_id,)).fetchone()
        return dict(row) if row else None


def set_camera_enabled(camera_id: int, enabled: bool) -> None:
    with _conn() as c:
        c.execute("UPDATE cameras SET enabled=? WHERE id=?", (1 if enabled else 0, camera_id))


def set_camera_alerts(camera_id: int, enabled: bool) -> None:
    with _conn() as c:
        c.execute("UPDATE cameras SET alerts_enabled=? WHERE id=?", (1 if enabled else 0, camera_id))


def set_camera_geometry(
    camera_id: int,
    install_height_m: float | None,
    pitch_deg: float | None,
    hfov_deg: float | None,
    preset: str | None = None,
) -> None:
    """写入相机安装参数与几何预设；传 None 表示清除，检测端会回落到默认值。"""
    with _conn() as c:
        c.execute(
            "UPDATE cameras SET install_height_m=?, pitch_deg=?, hfov_deg=?, geometry_preset=?"
            " WHERE id=?",
            (install_height_m, pitch_deg, hfov_deg, preset, camera_id),
        )


def set_camera_online(camera_id: int, online: bool) -> None:
    with _conn() as c:
        c.execute("UPDATE cameras SET online=? WHERE id=?", (1 if online else 0, camera_id))


def delete_camera(camera_id: int) -> None:
    with _conn() as c:
        c.execute("DELETE FROM cameras WHERE id=?", (camera_id,))


def create_alarm(
    camera_id: int,
    camera_name: str,
    alarm_type: str,
    level: str,
    confidence: float,
    verified: int = 0,
) -> dict[str, Any]:
    """创建告警；若同一视频源+同一类型已有未处理告警，则合并更新并累计次数。"""
    with _conn() as c:
        created = now_text()
        exist = c.execute(
            "SELECT * FROM alarms WHERE camera_id=? AND alarm_type=? AND status='unhandled' ORDER BY id DESC LIMIT 1",
            (camera_id, alarm_type),
        ).fetchone()
        if exist:
            count = int(exist["count"] or 1) + 1
            c.execute(
                "UPDATE alarms SET confidence=?, created_at=?, updated_at=?, count=?,"
                " verified=CASE WHEN ?=1 THEN 1 ELSE verified END WHERE id=?",
                (round(confidence, 3), created, created, count, verified, exist["id"]),
            )
            merged = dict(exist)
            merged.update(
                {
                    "confidence": round(confidence, 3),
                    "created_at": created,
                    "updated_at": created,
                    "count": count,
                    "verified": 1 if verified or exist["verified"] else 0,
                }
            )
            return {**merged, "is_new": False}
        cur = c.execute(
            "INSERT INTO alarms(camera_id,camera_name,alarm_type,level,confidence,created_at,status,count,verified,updated_at)"
            " VALUES(?,?,?,?,?,?,'unhandled',1,?,?)",
            (camera_id, camera_name, alarm_type, level, confidence, created, verified, created),
        )
        _bump_daily(c, created[:10], alarm_type)
        return {
            "id": int(cur.lastrowid),
            "camera_id": camera_id,
            "camera_name": camera_name,
            "alarm_type": alarm_type,
            "level": level,
            "confidence": round(confidence, 3),
            "created_at": created,
            "updated_at": created,
            "count": 1,
            "verified": 1 if verified else 0,
            "status": "unhandled",
            "is_new": True,
        }


def list_alarms(limit: int = 100) -> list[dict[str, Any]]:
    with _conn() as c:
        return [dict(r) for r in c.execute("SELECT * FROM alarms ORDER BY id DESC LIMIT ?", (limit,)).fetchall()]


def get_alarm(alarm_id: int) -> dict[str, Any] | None:
    with _conn() as c:
        row = c.execute("SELECT * FROM alarms WHERE id=?", (alarm_id,)).fetchone()
        return dict(row) if row else None


def update_alarm_snapshot(
    alarm_id: int,
    *,
    first: str | None = None,
    latest: str | None = None,
    boxes: str | None = None,
    frame_size: str | None = None,
) -> None:
    """写入告警画面信息；first 只在新建告警时传，latest 每次合并都覆盖。"""
    sets: list[str] = []
    params: list[Any] = []
    if first:
        sets.append("snapshot_first=?")
        params.append(first)
    if latest:
        sets.append("snapshot_latest=?")
        params.append(latest)
    if boxes is not None:
        sets.append("boxes=?")
        params.append(boxes)
    if frame_size is not None:
        sets.append("frame_size=?")
        params.append(frame_size)
    if not sets:
        return
    params.append(alarm_id)
    with _conn() as c:
        c.execute(f"UPDATE alarms SET {', '.join(sets)} WHERE id=?", params)


def clear_alarms() -> list[dict[str, Any]]:
    with _conn() as c:
        rows = [dict(r) for r in c.execute("SELECT id, camera_id FROM alarms").fetchall()]
        c.execute("DELETE FROM alarms")
        return rows


def reserve_notification(camera_id: int, alarm_id: int, alarm_type: str, title: str) -> bool:
    """原子占位：该视频源本轮尚未推送过才返回 True。"""
    with _conn() as c:
        cur = c.execute(
            "INSERT OR IGNORE INTO alarm_notifications"
            "(camera_id,alarm_id,alarm_type,title,ok,created_at) VALUES(?,?,?,?,0,?)",
            (camera_id, alarm_id, alarm_type, title, now_text()),
        )
        return cur.rowcount > 0


def finish_notification(camera_id: int, ok: bool, code: int | None, message: str) -> None:
    with _conn() as c:
        c.execute(
            "UPDATE alarm_notifications SET ok=?, code=?, message=? WHERE camera_id=?",
            (1 if ok else 0, code, (message or "")[:500], camera_id),
        )


def list_notifications() -> list[dict[str, Any]]:
    with _conn() as c:
        return [dict(r) for r in c.execute(
            "SELECT * FROM alarm_notifications ORDER BY created_at DESC"
        ).fetchall()]


def clear_notifications() -> int:
    with _conn() as c:
        return c.execute("DELETE FROM alarm_notifications").rowcount


def release_notification(camera_id: int) -> int:
    """释放某路视频源的推送名额：告警被确认处理后，下次新告警可以再推一次。"""
    with _conn() as c:
        return c.execute("DELETE FROM alarm_notifications WHERE camera_id=?", (camera_id,)).rowcount


def bump_notify_daily() -> None:
    """每尝试推送一次就 +1；写在独立表里，重启清空 alarm_notifications 也不会归零。"""
    with _conn() as c:
        c.execute(
            """
            INSERT INTO notify_daily(day, count) VALUES(?, 1)
            ON CONFLICT(day) DO UPDATE SET count=count+1
            """,
            (now_text()[:10],),
        )


def notifications_sent_today() -> int:
    """今天已尝试推送的条数；读持久计数，重启不清零。"""
    with _conn() as c:
        row = c.execute("SELECT count FROM notify_daily WHERE day=?", (now_text()[:10],)).fetchone()
    return int(row["count"]) if row else 0


def get_notify_config() -> dict[str, Any]:
    with _conn() as c:
        rows = {r["key"]: r["value"] for r in c.execute(
            "SELECT * FROM settings WHERE key LIKE 'notify_%'"
        ).fetchall()}
    return {
        "enabled": 1 if rows.get("notify_enabled", "0") == "1" else 0,
        "sendkey": rows.get("notify_sendkey", ""),
        "name": rows.get("notify_name", ""),
        "daily_limit": int(rows.get("notify_daily_limit", "5") or 5),
    }


def save_notify_config(enabled: int, sendkey: str, name: str, daily_limit: int) -> None:
    with _conn() as c:
        for key, value in (
            ("notify_enabled", "1" if enabled else "0"),
            ("notify_sendkey", sendkey),
            ("notify_name", name),
            ("notify_daily_limit", str(daily_limit)),
        ):
            c.execute("INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)", (key, value))


def ack_alarm(alarm_id: int) -> bool:
    with _conn() as c:
        cur = c.execute("UPDATE alarms SET status='handled' WHERE id=? AND status='unhandled'", (alarm_id,))
        return cur.rowcount > 0


def ack_alarm_group(camera_id: int, alarm_type: str) -> int:
    """把同一视频源、同一类型的所有未处理告警一次性标记为已处理，返回处理条数。"""
    with _conn() as c:
        cur = c.execute(
            "UPDATE alarms SET status='handled' WHERE camera_id=? AND alarm_type=? AND status='unhandled'",
            (camera_id, alarm_type),
        )
        return cur.rowcount


_settings_cache: tuple[float, dict[str, float | int]] | None = None


def get_settings() -> dict[str, float | int]:
    global _settings_cache
    now = time.monotonic()
    if _settings_cache and now - _settings_cache[0] < 1.0:
        return dict(_settings_cache[1])
    with _conn() as c:
        values = {r["key"]: r["value"] for r in c.execute("SELECT * FROM settings").fetchall()}
    result = {
        "fire_threshold": float(values["fire_threshold"]),
        "smoke_threshold": float(values["smoke_threshold"]),
        "continuous_frames": int(values["continuous_frames"]),
        "alarm_cooldown": int(values["alarm_cooldown"]),
        "tiling_enabled": int(values.get("tiling_enabled", "1")),
        "tile_size": int(values.get("tile_size", "640")),
        "tile_overlap": float(values.get("tile_overlap", "0.2")),
        "tile_interval": int(values.get("tile_interval", "2")),
        "verify_enabled": int(values.get("verify_enabled", "1")),
        "verify_threshold": float(values.get("verify_threshold", "0.25")),
    }
    _settings_cache = (now, result)
    return dict(result)


def put_settings(values: dict[str, float | int]) -> dict[str, float | int]:
    global _settings_cache
    with _conn() as c:
        for k, v in values.items():
            c.execute("INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)", (k, str(v)))
    _settings_cache = None
    return {k: v for k, v in values.items()}


def dashboard_stats() -> dict[str, Any]:
    with _conn() as c:
        camera_count = c.execute("SELECT COUNT(*) n FROM cameras").fetchone()["n"]
        online_count = c.execute("SELECT COUNT(*) n FROM cameras WHERE online=1").fetchone()["n"]
        now = datetime.now()
        today = now.strftime("%Y-%m-%d") + "%"
        alarm_count = c.execute("SELECT COUNT(*) n FROM alarms WHERE created_at LIKE ?", (today,)).fetchone()["n"]
        unhandled = c.execute("SELECT COUNT(*) n FROM alarms WHERE status='unhandled'").fetchone()["n"]
        recent = [dict(r) for r in c.execute("SELECT * FROM alarms ORDER BY id DESC LIMIT 5").fetchall()]
        days = [now.date() - timedelta(days=i) for i in range(6, -1, -1)]
        daily = {
            row["day"]: dict(row)
            for row in c.execute(
                "SELECT * FROM alarm_daily WHERE day>=? ORDER BY day",
                (days[0].isoformat(),),
            ).fetchall()
        }
        trend = []
        for day in days:
            row = daily.get(day.isoformat(), {})
            trend.append({
                "date": day.isoformat(),
                "label": f"{day.month}/{day.day}",
                "fire": int(row.get("fire_count", 0)),
                "smoke": int(row.get("smoke_count", 0)),
                "handled": int(row.get("handled_count", 0)),
                "total": int(row.get("total_count", 0)),
            })
    return {
        "camera_count": camera_count,
        "online_count": online_count,
        "today_alarms": alarm_count,
        "unhandled": unhandled,
        "recent": recent,
        "trend": trend,
    }
