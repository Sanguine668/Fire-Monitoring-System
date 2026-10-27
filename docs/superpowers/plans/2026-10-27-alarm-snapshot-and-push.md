# 告警画面留存与手机推送 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让每条告警留存"触发帧 + 最近帧"两张带检测框的画面，可经接口与前端查看；新增 Server酱 通道，在同一路视频源本轮首次告警时推送一次到手机微信。

**Architecture:** 检测线程在原有告警写入路径上多取一次已经画好框的 JPEG，交给新的 `snapshots` 模块落盘，路径与框坐标写回 `alarms` 表。推送走独立的 `Notifier` 后台线程与有界队列，去重靠 `alarm_notifications` 表的 `INSERT OR IGNORE` 原子占位，检测线程永不等待网络。

**Tech Stack:** Python 3.12 / FastAPI / SQLite / OpenCV / httpx（已安装 0.28.1）/ Vue 3 + Element Plus / Vite

## Global Constraints

- 后端代码放 `backend/app/`，测试放 `backend/tests/`；**所有命令都在仓库根目录 `E:\软件项目管理-火情监测系统` 执行**。
- Python 解释器统一用 `ai\.venv\Scripts\python.exe`；跑测试用 `ai\.venv\Scripts\python.exe -m pytest backend/tests -q`。
- **不新增任何第三方依赖**（httpx、psutil 已在 venv 中）。
- 检测结果数据结构沿用现有格式：`{"type": "fire"|"smoke", "confidence": float, "bbox": [x, y, w, h]}`，bbox 为左上角坐标加宽高的整数。
- 数据库路径由 `FIREGUARD_DB` 环境变量覆盖（测试通过 `backend/tests/conftest.py` 指向临时库）；快照目录新增 `FIREGUARD_SNAPSHOTS` 覆盖。
- 所有面向前端的文案、注释、提交信息用中文；提交信息格式 `类型(范围): 说明 - 蔡俊杰`。
- **SendKey 绝不写进代码、文档、日志或提交**；只存本机 SQLite，接口返回掩码。
- 前端没有测试框架：前端任务的验收 = `npm run build` 通过 + 全新 profile 的无头 Chrome 截图人工确认 + 关键 DOM 断言。
- 前端字号体系见 `frontend/src/styles/base.css`：新样式一律用 rem，不要写 px 字号。
- 现有 15 个后端测试必须保持全绿。

---

## File Structure

| 文件 | 职责 | 变更 |
| --- | --- | --- |
| `backend/app/config.py` | 路径常量 | 修改：`SNAPSHOTS` 支持环境变量覆盖 |
| `backend/app/snapshots.py` | 画面帧落盘、解析、清理（只碰文件系统） | 新建 |
| `backend/app/notify.py` | 消息渲染、Server酱 通道、去重推送线程 | 新建 |
| `backend/app/alarm_store.py` | 一次告警的完整留存：写库 + 存图 + 入队推送 | 新建 |
| `backend/app/db.py` | 数据访问 | 修改：新列迁移、快照更新、推送记录、通知配置 |
| `backend/app/worker.py` | 检测线程 | 修改：告警段落改调 `alarm_store.persist_alarm` |
| `backend/app/main.py` | FastAPI 应用 | 修改：画面接口、通知接口、lifespan 启停 Notifier |
| `backend/tests/conftest.py` | 测试环境变量 | 修改：增加 `FIREGUARD_SNAPSHOTS` |
| `backend/tests/test_db_alarm_snapshot.py` | 数据层测试 | 新建 |
| `backend/tests/test_snapshots.py` | 文件层测试 | 新建 |
| `backend/tests/test_alarm_store.py` | 留存编排测试 | 新建 |
| `backend/tests/test_notify.py` | 消息与推送测试 | 新建 |
| `backend/tests/test_api_alarm_media.py` | 画面接口测试 | 新建 |
| `backend/tests/test_api_notify.py` | 通知接口测试 | 新建 |
| `frontend/src/api/index.js` | 前端接口封装 | 修改：5 个新方法 + 1 个 URL 构造器 |
| `frontend/src/views/AlarmsView.vue` | 告警中心 | 修改：缩略图列、抽屉大图、框列表 |
| `frontend/src/views/SettingsView.vue` | 系统设置 | 修改：新增「告警推送」卡片 |

任务依赖：Task 1 → 2 → 3 →(4 可并行)→ 5 → 6 → 7 → 8。

---

### Task 1: 数据层——告警画面字段与推送记录表

**Files:**
- Modify: `backend/app/db.py`（`init_db` 迁移段、`create_alarm`、`clear_alarms`，新增若干函数）
- Test: `backend/tests/test_db_alarm_snapshot.py`

**Interfaces:**
- Consumes: 现有 `db._conn()`、`db.now_text()`
- Produces:
  - `db.create_alarm(...) -> dict`，返回值新增键 `is_new: bool`
  - `db.update_alarm_snapshot(alarm_id: int, *, first: str | None = None, latest: str | None = None, boxes: str | None = None, frame_size: str | None = None) -> None`
  - `db.get_alarm(alarm_id: int) -> dict | None`
  - `db.clear_alarms() -> list[dict]`（返回被删的 `{id, camera_id}` 列表，不再是计数）
  - `db.reserve_notification(camera_id: int, alarm_id: int, alarm_type: str, title: str) -> bool`
  - `db.finish_notification(camera_id: int, ok: bool, code: int | None, message: str) -> None`
  - `db.list_notifications() -> list[dict]`
  - `db.clear_notifications() -> int`
  - `db.notifications_sent_today() -> int`
  - `db.get_notify_config() -> dict`（键：`enabled`/`sendkey`/`name`/`daily_limit`）
  - `db.save_notify_config(enabled: int, sendkey: str, name: str, daily_limit: int) -> None`

- [ ] **Step 1: 写失败的测试**

新建 `backend/tests/test_db_alarm_snapshot.py`：

```python
from backend.app import db


def _fresh_alarm() -> dict:
    db.init_db()
    db.clear_alarms()
    return db.create_alarm(1, "测试源", "fire", "critical", 0.9, 1)


def test_create_alarm_marks_new_and_merged() -> None:
    db.init_db()
    db.clear_alarms()
    first = db.create_alarm(9, "源A", "smoke", "warning", 0.5, 0)
    assert first["is_new"] is True
    merged = db.create_alarm(9, "源A", "smoke", "warning", 0.6, 0)
    assert merged["is_new"] is False
    assert merged["id"] == first["id"]
    assert merged["count"] == 2


def test_update_alarm_snapshot_fields() -> None:
    alarm = _fresh_alarm()
    db.update_alarm_snapshot(
        alarm["id"],
        first="1/alarm_2_first.jpg",
        latest="1/alarm_2_latest.jpg",
        boxes='[{"type": "fire", "confidence": 0.9, "bbox": [1, 2, 3, 4]}]',
        frame_size="1280x720",
    )
    row = db.get_alarm(alarm["id"])
    assert row["snapshot_first"] == "1/alarm_2_first.jpg"
    assert row["snapshot_latest"] == "1/alarm_2_latest.jpg"
    assert row["frame_size"] == "1280x720"
    assert '"fire"' in row["boxes"]


def test_clear_alarms_returns_deleted_ids() -> None:
    alarm = _fresh_alarm()
    deleted = db.clear_alarms()
    assert any(item["id"] == alarm["id"] for item in deleted)
    assert db.get_alarm(alarm["id"]) is None


def test_notification_reserve_is_per_camera() -> None:
    db.init_db()
    db.clear_notifications()
    assert db.reserve_notification(5, 100, "fire", "标题A") is True
    assert db.reserve_notification(5, 101, "smoke", "标题B") is False
    assert db.reserve_notification(6, 102, "fire", "标题C") is True
    db.finish_notification(5, True, 0, "ok")
    records = {r["camera_id"]: r for r in db.list_notifications()}
    assert records[5]["ok"] == 1
    assert db.notifications_sent_today() == 2
    assert db.clear_notifications() == 2
    assert db.reserve_notification(5, 103, "fire", "标题D") is True


def test_notify_config_roundtrip() -> None:
    db.init_db()
    db.save_notify_config(1, "SCTtestkey", "组长手机", 4)
    cfg = db.get_notify_config()
    assert cfg == {"enabled": 1, "sendkey": "SCTtestkey", "name": "组长手机", "daily_limit": 4}
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `ai\.venv\Scripts\python.exe -m pytest backend/tests/test_db_alarm_snapshot.py -q`
Expected: FAIL，报 `AttributeError: module 'backend.app.db' has no attribute 'reserve_notification'`（或先报 `is_new` 的 KeyError）

- [ ] **Step 3: 实现**

在 `backend/app/db.py` 的 `init_db()` 中，把现有迁移段改成（在原 `if "verified" not in columns:` 之后追加）：

```python
        for column, decl in (
            ("snapshot_first", "TEXT"),
            ("snapshot_latest", "TEXT"),
            ("boxes", "TEXT"),
            ("frame_size", "TEXT"),
        ):
            if column not in columns:
                c.execute(f"ALTER TABLE alarms ADD COLUMN {column} {decl}")
```

并在同一次 `executescript` 的建表语句里追加新表：

```sql
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
```

在 `init_db()` 的 settings 默认值字典里追加四项：

```python
            "notify_enabled": "0",
            "notify_sendkey": "",
            "notify_name": "",
            "notify_daily_limit": "5",
```

把 `create_alarm` 的合并分支 `return merged` 改成 `return {**merged, "is_new": False}`，插入分支的 `return {...}` 里追加 `"is_new": True`。

把 `list_alarms` 之后追加：

```python
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


def notifications_sent_today() -> int:
    with _conn() as c:
        return c.execute(
            "SELECT COUNT(*) n FROM alarm_notifications WHERE created_at LIKE ?",
            (now_text()[:10] + "%",),
        ).fetchone()["n"]


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
```

- [ ] **Step 4: 运行测试，确认通过**

Run: `ai\.venv\Scripts\python.exe -m pytest backend/tests/test_db_alarm_snapshot.py -q`
Expected: `5 passed`

- [ ] **Step 5: 跑全量测试确认没破坏既有行为**

Run: `ai\.venv\Scripts\python.exe -m pytest backend/tests -q`
Expected: `20 passed`（原 15 + 新 5）

- [ ] **Step 6: 提交**

```powershell
git add backend/app/db.py backend/tests/test_db_alarm_snapshot.py
git commit -m "feat(alarm): 告警表新增画面字段与推送记录表 - 蔡俊杰"
```

---

### Task 2: 快照模块——落盘、解析、清理

**Files:**
- Modify: `backend/app/config.py:9`（`SNAPSHOTS` 支持覆盖）
- Modify: `backend/tests/conftest.py`
- Create: `backend/app/snapshots.py`
- Test: `backend/tests/test_snapshots.py`

**Interfaces:**
- Consumes: `config.SNAPSHOTS`
- Produces:
  - `snapshots.alarm_frame_path(camera_id: int, alarm_id: int, variant: str) -> Path`
  - `snapshots.store_frame(camera_id: int, alarm_id: int, variant: str, jpeg: bytes) -> str` —— 返回相对 `SNAPSHOTS` 的 posix 路径，如 `9/alarm_80_first.jpg`
  - `snapshots.resolve_frame(rel_path: str) -> Path | None` —— 空值/越界/不存在都返回 None
  - `snapshots.delete_alarm_frames(camera_id: int, alarm_id: int) -> int`
  - `snapshots.cleanup_old_frames(days: int = 7, now: float | None = None) -> int`

- [ ] **Step 1: 写失败的测试**

新建 `backend/tests/test_snapshots.py`：

```python
import time

from backend.app import snapshots
from backend.app.config import SNAPSHOTS


def test_store_and_resolve_roundtrip() -> None:
    rel = snapshots.store_frame(1, 42, "first", b"\xff\xd8fakejpeg\xff\xd9")
    assert rel == "1/alarm_42_first.jpg"
    path = snapshots.resolve_frame(rel)
    assert path is not None and path.is_file()
    assert path.read_bytes().startswith(b"\xff\xd8")


def test_store_rejects_unknown_variant() -> None:
    try:
        snapshots.store_frame(1, 42, "middle", b"x")
    except ValueError as exc:
        assert "variant" in str(exc)
    else:
        raise AssertionError("应当抛出 ValueError")


def test_resolve_rejects_escape_and_missing() -> None:
    assert snapshots.resolve_frame("") is None
    assert snapshots.resolve_frame("../../etc/passwd") is None
    assert snapshots.resolve_frame("1/alarm_9999_first.jpg") is None


def test_delete_alarm_frames() -> None:
    snapshots.store_frame(7, 500, "first", b"a")
    snapshots.store_frame(7, 500, "latest", b"b")
    assert snapshots.delete_alarm_frames(7, 500) == 2
    assert snapshots.resolve_frame("7/alarm_500_first.jpg") is None


def test_cleanup_old_frames_removes_only_expired() -> None:
    old_rel = snapshots.store_frame(8, 600, "first", b"old")
    new_rel = snapshots.store_frame(8, 601, "first", b"new")
    old_path = SNAPSHOTS / old_rel
    stale = time.time() - 8 * 86400
    import os

    os.utime(old_path, (stale, stale))
    removed = snapshots.cleanup_old_frames(days=7)
    assert removed >= 1
    assert snapshots.resolve_frame(old_rel) is None
    assert snapshots.resolve_frame(new_rel) is not None
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `ai\.venv\Scripts\python.exe -m pytest backend/tests/test_snapshots.py -q`
Expected: FAIL，`ModuleNotFoundError: No module named 'backend.app.snapshots'`

- [ ] **Step 3: 实现**

`backend/app/config.py` 第 9 行改为：

```python
SNAPSHOTS = Path(os.environ.get("FIREGUARD_SNAPSHOTS", str(STORAGE / "snapshots")))
```

`backend/tests/conftest.py` 追加一行（放在 `os.environ["FIREGUARD_DB"]` 之后）：

```python
os.environ["FIREGUARD_SNAPSHOTS"] = str(Path(tmp) / "snapshots")
```

新建 `backend/app/snapshots.py`：

```python
"""告警画面帧的文件操作：只负责落盘、解析与清理，不碰数据库。"""

from __future__ import annotations

import time
from pathlib import Path

from .config import SNAPSHOTS

VARIANTS = ("first", "latest")


def alarm_frame_path(camera_id: int, alarm_id: int, variant: str) -> Path:
    if variant not in VARIANTS:
        raise ValueError(f"unknown variant: {variant}")
    return SNAPSHOTS / str(int(camera_id)) / f"alarm_{int(alarm_id)}_{variant}.jpg"


def store_frame(camera_id: int, alarm_id: int, variant: str, jpeg: bytes) -> str:
    """写入画面帧，返回相对 SNAPSHOTS 的路径，用于存库。"""
    path = alarm_frame_path(camera_id, alarm_id, variant)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(jpeg)
    return path.relative_to(SNAPSHOTS).as_posix()


def resolve_frame(rel_path: str) -> Path | None:
    """把库里存的相对路径还原成磁盘路径；越界或不存在都返回 None。"""
    if not rel_path:
        return None
    root = SNAPSHOTS.resolve()
    candidate = (root / rel_path).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    return candidate if candidate.is_file() else None


def delete_alarm_frames(camera_id: int, alarm_id: int) -> int:
    removed = 0
    for variant in VARIANTS:
        path = alarm_frame_path(camera_id, alarm_id, variant)
        if path.is_file():
            try:
                path.unlink()
                removed += 1
            except OSError:
                continue
    return removed


def cleanup_old_frames(days: int = 7, now: float | None = None) -> int:
    """删除超过保留期的画面帧，并顺手清掉空目录。"""
    if not SNAPSHOTS.is_dir():
        return 0
    cutoff = (now if now is not None else time.time()) - days * 86400
    removed = 0
    for path in SNAPSHOTS.glob("*/*.jpg"):
        try:
            if path.stat().st_mtime < cutoff:
                path.unlink()
                removed += 1
        except OSError:
            continue
    for folder in SNAPSHOTS.iterdir():
        if folder.is_dir() and not any(folder.iterdir()):
            try:
                folder.rmdir()
            except OSError:
                continue
    return removed
```

- [ ] **Step 4: 运行测试，确认通过**

Run: `ai\.venv\Scripts\python.exe -m pytest backend/tests/test_snapshots.py -q`
Expected: `5 passed`

- [ ] **Step 5: 提交**

```powershell
git add backend/app/snapshots.py backend/app/config.py backend/tests/conftest.py backend/tests/test_snapshots.py
git commit -m "feat(snapshot): 新增告警画面帧落盘与清理模块 - 蔡俊杰"
```

---

### Task 3: 告警画面接口

**Files:**
- Modify: `backend/app/main.py`（导入区、`/api/alarms` 路由段）
- Test: `backend/tests/test_api_alarm_media.py`

**Interfaces:**
- Consumes: `db.get_alarm`、`db.clear_alarms`（Task 1）、`snapshots.resolve_frame`、`snapshots.delete_alarm_frames`（Task 2）
- Produces:
  - `GET /api/alarms/{alarm_id}` → 告警字典，`boxes` 已解析为列表
  - `GET /api/alarms/{alarm_id}/frame?variant=first|latest` → `image/jpeg`，缺失 404
  - `DELETE /api/alarms` 返回 `{"ok": true, "deleted": <int>}`（行为不变，同时删图）

- [ ] **Step 1: 写失败的测试**

新建 `backend/tests/test_api_alarm_media.py`：

```python
import json

from fastapi.testclient import TestClient

from backend.app import db, snapshots
from backend.app.main import app


def _make_alarm_with_frames() -> int:
    db.init_db()
    db.clear_alarms()
    alarm = db.create_alarm(3, "接口测试源", "fire", "critical", 0.88, 1)
    first = snapshots.store_frame(3, alarm["id"], "first", b"\xff\xd8first\xff\xd9")
    latest = snapshots.store_frame(3, alarm["id"], "latest", b"\xff\xd8latest\xff\xd9")
    db.update_alarm_snapshot(
        alarm["id"],
        first=first,
        latest=latest,
        boxes=json.dumps([{"type": "fire", "confidence": 0.88, "bbox": [1, 2, 3, 4]}]),
        frame_size="640x480",
    )
    return alarm["id"]


def test_alarm_detail_parses_boxes() -> None:
    alarm_id = _make_alarm_with_frames()
    with TestClient(app) as client:
        data = client.get(f"/api/alarms/{alarm_id}").json()
    assert data["camera_name"] == "接口测试源"
    assert data["boxes"][0]["type"] == "fire"
    assert data["boxes"][0]["bbox"] == [1, 2, 3, 4]
    assert data["frame_size"] == "640x480"


def test_alarm_frame_variants() -> None:
    alarm_id = _make_alarm_with_frames()
    with TestClient(app) as client:
        first = client.get(f"/api/alarms/{alarm_id}/frame?variant=first")
        latest = client.get(f"/api/alarms/{alarm_id}/frame?variant=latest")
        bad = client.get(f"/api/alarms/{alarm_id}/frame?variant=middle")
    assert first.status_code == 200
    assert first.headers["content-type"] == "image/jpeg"
    assert first.content == b"\xff\xd8first\xff\xd9"
    assert latest.content == b"\xff\xd8latest\xff\xd9"
    assert bad.status_code == 400


def test_alarm_frame_missing_returns_404() -> None:
    db.init_db()
    db.clear_alarms()
    alarm = db.create_alarm(3, "无图源", "smoke", "warning", 0.5, 0)
    with TestClient(app) as client:
        assert client.get(f"/api/alarms/{alarm['id']}/frame").status_code == 404
        assert client.get("/api/alarms/999999").status_code == 404


def test_clear_alarms_removes_frames() -> None:
    alarm_id = _make_alarm_with_frames()
    with TestClient(app) as client:
        result = client.delete("/api/alarms").json()
    assert result["deleted"] >= 1
    assert snapshots.resolve_frame(f"3/alarm_{alarm_id}_first.jpg") is None
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `ai\.venv\Scripts\python.exe -m pytest backend/tests/test_api_alarm_media.py -q`
Expected: FAIL，`test_alarm_detail_parses_boxes` 报 404 或 `boxes` 是字符串

- [ ] **Step 3: 实现**

`backend/app/main.py` 顶部导入区补三行：

```python
import json

from fastapi.responses import FileResponse, Response

from . import snapshots
```

（`json` 放在 `import asyncio` 之后；`Response` 原本就从 `fastapi.responses` 导入，改成一起导入 `FileResponse`；`from . import db` 下方加 `from . import snapshots`。）

把 `clear_alarms` 路由改为：

```python
    @app.delete("/api/alarms")
    def clear_alarms() -> dict[str, Any]:
        deleted = db.clear_alarms()
        for item in deleted:
            snapshots.delete_alarm_frames(int(item["camera_id"]), int(item["id"]))
        return {"ok": True, "deleted": len(deleted)}
```

在 `list_alarms` 路由之后、`/api/model` 之前插入两个路由：

```python
    @app.get("/api/alarms/{alarm_id}")
    def alarm_detail(alarm_id: int) -> dict[str, Any]:
        row = db.get_alarm(alarm_id)
        if not row:
            raise HTTPException(404, "alarm not found")
        raw = row.get("boxes") or ""
        try:
            row["boxes"] = json.loads(raw) if raw else []
        except ValueError:
            row["boxes"] = []
        return row

    @app.get("/api/alarms/{alarm_id}/frame")
    def alarm_frame(alarm_id: int, variant: str = "first"):
        """返回告警对应的画面帧；variant=first 是触发瞬间，latest 是最近一次。"""
        if variant not in snapshots.VARIANTS:
            raise HTTPException(400, "variant must be first or latest")
        row = db.get_alarm(alarm_id)
        if not row:
            raise HTTPException(404, "alarm not found")
        path = snapshots.resolve_frame(row.get(f"snapshot_{variant}") or "")
        if path is None:
            raise HTTPException(404, "frame not found")
        return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "no-cache"})
```

- [ ] **Step 4: 运行测试，确认通过**

Run: `ai\.venv\Scripts\python.exe -m pytest backend/tests/test_api_alarm_media.py -q`
Expected: `4 passed`

- [ ] **Step 5: 提交**

```powershell
git add backend/app/main.py backend/tests/test_api_alarm_media.py
git commit -m "feat(api): 新增告警详情与画面帧接口 - 蔡俊杰"
```

---

### Task 4: 通知模块——消息渲染与 Server酱 通道

**Files:**
- Create: `backend/app/notify.py`
- Test: `backend/tests/test_notify.py`

**Interfaces:**
- Consumes: `db.get_notify_config`、`db.reserve_notification`、`db.finish_notification`、`db.notifications_sent_today`（Task 1）
- Produces:
  - `notify.code_label(type: str) -> str`
  - `notify.render_message(alarm: dict, base_url: str = "") -> tuple[str, str]` —— 返回 `(title, desp)`
  - `notify.ServerChanChannel(sendkey: str).send(title: str, desp: str) -> dict` —— 返回 `{"ok": bool, "code": int|None, "message": str}`
  - `notify.Notifier(base_url_provider=None, channel_factory=None)`：`threading.Thread` 子类，方法 `enqueue_alarm(alarm: dict) -> None`、`handle(alarm: dict) -> bool`、`stop() -> None`；属性 `last_skip: str`

- [ ] **Step 1: 写失败的测试**

新建 `backend/tests/test_notify.py`：

```python
import json

from backend.app import db, notify
from backend.app.notify import Notifier, ServerChanChannel, render_message


class FakeChannel:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def send(self, title, desp):
        self.calls.append((title, desp))
        return self.result


def _alarm(**over) -> dict:
    base = {
        "id": 12,
        "camera_id": 3,
        "camera_name": "东门摄像头",
        "alarm_type": "fire",
        "level": "critical",
        "confidence": 0.876,
        "count": 5,
        "created_at": "2026-10-27 20:05:51",
    }
    base.update(over)
    return base


def test_render_message_strips_newlines_from_title() -> None:
    title, desp = render_message(_alarm(camera_name="东门\n摄像头"))
    assert "\n" not in title
    assert title == "【火情监测】东门 摄像头 明火告警"
    assert "东门 摄像头" in desp
    assert "87.6%" in desp
    assert "5 次" in desp


def test_render_message_includes_frame_url_when_base_given() -> None:
    _, desp = render_message(_alarm(), base_url="http://192.168.1.5:8000")
    assert "http://192.168.1.5:8000/api/alarms/12/frame?variant=first" in desp


def test_render_message_notes_missing_base_url() -> None:
    _, desp = render_message(_alarm(), base_url="")
    assert "/api/alarms/12/frame" not in desp
    assert "局域网" in desp


def test_notifier_skips_when_disabled() -> None:
    db.init_db()
    db.clear_notifications()
    db.save_notify_config(0, "SCTkey", "", 5)
    channel = FakeChannel({"ok": True, "code": 0, "message": ""})
    n = Notifier(channel_factory=lambda key: channel)
    assert n.handle(_alarm()) is False
    assert channel.calls == []
    assert "未启用" in n.last_skip


def test_notifier_skips_without_sendkey() -> None:
    db.init_db()
    db.clear_notifications()
    db.save_notify_config(1, "", "", 5)
    n = Notifier(channel_factory=lambda key: FakeChannel({"ok": True, "code": 0, "message": ""}))
    assert n.handle(_alarm()) is False
    assert "SendKey" in n.last_skip


def test_notifier_pushes_once_per_camera() -> None:
    db.init_db()
    db.clear_notifications()
    db.save_notify_config(1, "SCTkey", "组长手机", 5)
    channel = FakeChannel({"ok": True, "code": 0, "message": ""})
    n = Notifier(channel_factory=lambda key: channel)
    assert n.handle(_alarm()) is True
    assert n.handle(_alarm(id=13, alarm_type="smoke")) is False
    assert len(channel.calls) == 1
    assert db.list_notifications()[0]["ok"] == 1


def test_notifier_respects_daily_limit() -> None:
    db.init_db()
    db.clear_notifications()
    db.save_notify_config(1, "SCTkey", "", 1)
    channel = FakeChannel({"ok": True, "code": 0, "message": ""})
    n = Notifier(channel_factory=lambda key: channel)
    assert n.handle(_alarm(camera_id=1)) is True
    assert n.handle(_alarm(camera_id=2)) is False
    assert "上限" in n.last_skip


def test_notifier_records_failure_and_keeps_slot() -> None:
    db.init_db()
    db.clear_notifications()
    db.save_notify_config(1, "SCTkey", "", 5)
    channel = FakeChannel({"ok": False, "code": 40001, "message": "bad key"})
    n = Notifier(channel_factory=lambda key: channel)
    assert n.handle(_alarm()) is False
    row = db.list_notifications()[0]
    assert row["ok"] == 0 and row["code"] == 40001
    assert n.handle(_alarm(id=14)) is False  # 占位仍在，不重试


def test_serverchan_channel_posts_form(monkeypatch) -> None:
    captured = {}

    class FakeResp:
        status_code = 200

        def json(self):
            return {"code": 0, "message": "", "data": {"error": "SUCCESS"}}

    def fake_post(url, data=None, timeout=None):
        captured["url"] = url
        captured["data"] = data
        return FakeResp()

    monkeypatch.setattr(notify.httpx, "post", fake_post)
    result = ServerChanChannel("SCTabc").send("标题", "正文")
    assert captured["url"] == "https://sctapi.ftqq.com/SCTabc.send"
    assert captured["data"] == {"title": "标题", "desp": "正文"}
    assert result["ok"] is True


def test_serverchan_channel_handles_429(monkeypatch) -> None:
    class FakeResp:
        status_code = 429

        def json(self):
            return {}

    monkeypatch.setattr(notify.httpx, "post", lambda *a, **k: FakeResp())
    result = ServerChanChannel("SCTabc").send("标题", "正文")
    assert result["ok"] is False
    assert result["code"] == 429
    assert "限流" in result["message"]


def test_serverchan_channel_handles_network_error(monkeypatch) -> None:
    def boom(*a, **k):
        raise notify.httpx.ConnectError("connection refused")

    monkeypatch.setattr(notify.httpx, "post", boom)
    result = ServerChanChannel("SCTabc").send("标题", "正文")
    assert result["ok"] is False
    assert "网络" in result["message"]
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `ai\.venv\Scripts\python.exe -m pytest backend/tests/test_notify.py -q`
Expected: FAIL，`ModuleNotFoundError: No module named 'backend.app.notify'`

- [ ] **Step 3: 实现**

新建 `backend/app/notify.py`：

```python
"""告警推送：消息渲染、Server酱 通道与去重发送线程。"""

from __future__ import annotations

import queue
import threading
from typing import Any, Callable

import httpx

from . import db

SERVERCHAN_URL = "https://sctapi.ftqq.com/{key}.send"
SEND_TIMEOUT = 10.0
TYPE_LABEL = {"fire": "明火", "smoke": "烟雾"}
LEVEL_LABEL = {"critical": "严重", "warning": "预警"}


def code_label(alarm_type: str) -> str:
    return TYPE_LABEL.get(alarm_type, alarm_type or "未知")


def _clean(text: str) -> str:
    """Server酱 的 title 不允许换行，统一压成单行。"""
    return " ".join(str(text).split())


def render_message(alarm: dict[str, Any], base_url: str = "") -> tuple[str, str]:
    kind = code_label(alarm.get("alarm_type", ""))
    level = LEVEL_LABEL.get(alarm.get("level", ""), alarm.get("level", ""))
    camera = _clean(alarm.get("camera_name") or "") or "未知视频源"
    title = _clean(f"【火情监测】{camera} {kind}告警")
    confidence = float(alarm.get("confidence") or 0) * 100
    count = int(alarm.get("count") or 1)
    created = alarm.get("created_at") or ""
    lines = [
        f"### {kind}告警 · {level}",
        "",
        f"- **监控源**：{camera}",
        f"- **时间**：{created}",
        f"- **置信度**：{confidence:.1f}%",
        f"- **累计次数**：{count} 次",
        "",
    ]
    if base_url:
        frame_url = f"{base_url}/api/alarms/{alarm.get('id')}/frame?variant=first"
        lines.append(f"![告警画面]({frame_url})")
        lines.append("")
        lines.append(f"> 打开系统查看：[{base_url}]({base_url}/#/alarms)")
    else:
        lines.append("> 未获取到局域网地址，画面请在系统内查看。")
    return title, "\n".join(lines)


class ServerChanChannel:
    """Server酱 Turbo 通道；只做一次 HTTP 请求，异常一律转成结果字典。"""

    def __init__(self, sendkey: str) -> None:
        self.sendkey = sendkey

    def send(self, title: str, desp: str) -> dict[str, Any]:
        url = SERVERCHAN_URL.format(key=self.sendkey)
        try:
            resp = httpx.post(url, data={"title": title, "desp": desp}, timeout=SEND_TIMEOUT)
        except httpx.HTTPError as exc:
            return {"ok": False, "code": None, "message": f"网络错误：{exc}"}
        if resp.status_code == 429:
            return {"ok": False, "code": 429, "message": "调用过于频繁，已被限流（429）"}
        if resp.status_code != 200:
            return {"ok": False, "code": resp.status_code, "message": f"HTTP {resp.status_code}"}
        try:
            payload = resp.json()
        except ValueError:
            return {"ok": False, "code": None, "message": "返回内容不是 JSON"}
        code = int(payload.get("code", -1))
        message = str(payload.get("message") or (payload.get("data") or {}).get("error") or "")
        return {"ok": code == 0, "code": code, "message": message}


class Notifier(threading.Thread):
    """后台推送线程：检测线程只入队，网络请求全部在这里发生。"""

    def __init__(
        self,
        base_url_provider: Callable[[], str] | None = None,
        channel_factory: Callable[[str], Any] | None = None,
    ) -> None:
        super().__init__(daemon=True, name="fireguard-notifier")
        self._queue: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=32)
        self._stop_event = threading.Event()
        self._base_url_provider = base_url_provider or (lambda: "")
        self._channel_factory = channel_factory or (lambda key: ServerChanChannel(key))
        self.last_skip = ""

    def enqueue_alarm(self, alarm: dict[str, Any]) -> None:
        try:
            self._queue.put_nowait(alarm)
        except queue.Full:
            self.last_skip = "推送队列已满，本条已丢弃"

    def handle(self, alarm: dict[str, Any]) -> bool:
        cfg = db.get_notify_config()
        if not cfg["enabled"]:
            self.last_skip = "推送未启用"
            return False
        if not cfg["sendkey"]:
            self.last_skip = "未配置 SendKey"
            return False
        if db.notifications_sent_today() >= int(cfg["daily_limit"]):
            self.last_skip = f"已达每日上限 {cfg['daily_limit']} 条"
            return False
        title, desp = render_message(alarm, self._base_url_provider())
        if not db.reserve_notification(
            int(alarm["camera_id"]), int(alarm["id"]), str(alarm.get("alarm_type", "")), title
        ):
            self.last_skip = "该视频源本轮已推送过"
            return False
        result = self._channel_factory(cfg["sendkey"]).send(title, desp)
        db.finish_notification(
            int(alarm["camera_id"]), bool(result["ok"]), result.get("code"), result.get("message", "")
        )
        self.last_skip = "" if result["ok"] else f"发送失败：{result.get('message', '')}"
        return bool(result["ok"])

    def run(self) -> None:
        while not self._stop_event.is_set():
            try:
                alarm = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                self.handle(alarm)
            except Exception as exc:  # noqa: BLE001
                self.last_skip = f"推送异常：{exc}"

    def stop(self) -> None:
        self._stop_event.set()
```

- [ ] **Step 4: 运行测试，确认通过**

Run: `ai\.venv\Scripts\python.exe -m pytest backend/tests/test_notify.py -q`
Expected: `11 passed`

- [ ] **Step 5: 提交**

```powershell
git add backend/app/notify.py backend/tests/test_notify.py
git commit -m "feat(notify): 新增 Server酱 推送通道与按视频源去重 - 蔡俊杰"
```

---

### Task 5: 告警留存编排——写库、存图、入队

**Files:**
- Create: `backend/app/alarm_store.py`
- Test: `backend/tests/test_alarm_store.py`

**Interfaces:**
- Consumes: `db.create_alarm`、`db.update_alarm_snapshot`（Task 1）、`snapshots.store_frame`（Task 2）
- Produces:
  - `alarm_store.persist_alarm(camera_id: int, camera_name: str, alarm: dict, visible: list[dict], frame_jpeg: bytes, frame_size: tuple[int, int], notifier=None) -> dict`
  - 返回的值 = `db.create_alarm` 的字典 + `snapshot_first`/`snapshot_latest`/`boxes`，并新增键 `pushed: bool`
  - 只有 `is_new` 为真且 `notifier` 不为 None 时调用 `notifier.enqueue_alarm(record)`

- [ ] **Step 1: 写失败的测试**

新建 `backend/tests/test_alarm_store.py`：

```python
import json

from backend.app import alarm_store, db, snapshots


class FakeNotifier:
    def __init__(self):
        self.received = []

    def enqueue_alarm(self, alarm):
        self.received.append(alarm)


def _prepare():
    db.init_db()
    db.clear_alarms()
    db.clear_notifications()
    db.save_notify_config(1, "SCTkey", "", 5)


def test_first_alarm_saves_both_frames_and_boxes() -> None:
    _prepare()
    visible = [{"type": "fire", "confidence": 0.9, "bbox": [10, 20, 30, 40]}]
    record = alarm_store.persist_alarm(
        camera_id=4,
        camera_name="北门",
        alarm={"alarm_type": "fire", "level": "critical", "confidence": 0.9, "verified": True},
        visible=visible,
        frame_jpeg=b"\xff\xd8frame1\xff\xd9",
        frame_size=(640, 480),
    )
    assert record["is_new"] is True
    assert record["frame_size"] == "640x480"
    assert json.loads(record["boxes"])[0]["bbox"] == [10, 20, 30, 40]
    first = snapshots.resolve_frame(record["snapshot_first"])
    latest = snapshots.resolve_frame(record["snapshot_latest"])
    assert first is not None and latest is not None
    assert first.read_bytes() == b"\xff\xd8frame1\xff\xd9"


def test_merged_alarm_only_refreshes_latest() -> None:
    _prepare()
    alarm = {"alarm_type": "fire", "level": "critical", "confidence": 0.9}
    first = alarm_store.persist_alarm(4, "北门", alarm, [], b"\xff\xd8one\xff\xd9", (640, 480))
    merged = alarm_store.persist_alarm(
        4, "北门", {**alarm, "confidence": 0.95}, [], b"\xff\xd8two\xff\xd9", (640, 480)
    )
    assert merged["is_new"] is False
    assert merged["snapshot_first"] == first["snapshot_first"]
    assert snapshots.resolve_frame(first["snapshot_first"]).read_bytes() == b"\xff\xd8one\xff\xd9"
    assert snapshots.resolve_frame(merged["snapshot_latest"]).read_bytes() == b"\xff\xd8two\xff\xd9"


def test_notifier_only_gets_new_alarms() -> None:
    _prepare()
    notifier = FakeNotifier()
    alarm = {"alarm_type": "smoke", "level": "warning", "confidence": 0.5}
    alarm_store.persist_alarm(6, "西侧", alarm, [], b"\xff\xd8a\xff\xd9", (320, 240), notifier)
    alarm_store.persist_alarm(6, "西侧", alarm, [], b"\xff\xd8b\xff\xd9", (320, 240), notifier)
    assert len(notifier.received) == 1
    assert notifier.received[0]["camera_id"] == 6


def test_empty_frame_still_records_alarm() -> None:
    _prepare()
    record = alarm_store.persist_alarm(7, "南门", {"alarm_type": "fire", "level": "critical", "confidence": 0.7}, [], b"", (0, 0))
    assert record["id"] > 0
    assert not record.get("snapshot_first")
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `ai\.venv\Scripts\python.exe -m pytest backend/tests/test_alarm_store.py -q`
Expected: FAIL，`ModuleNotFoundError: No module named 'backend.app.alarm_store'`

- [ ] **Step 3: 实现**

新建 `backend/app/alarm_store.py`：

```python
"""一次告警的完整留存：写库、存两张画面帧、交给推送线程。"""

from __future__ import annotations

import json
from typing import Any

from . import db, snapshots


def persist_alarm(
    camera_id: int,
    camera_name: str,
    alarm: dict[str, Any],
    visible: list[dict[str, Any]],
    frame_jpeg: bytes,
    frame_size: tuple[int, int],
    notifier: Any | None = None,
) -> dict[str, Any]:
    record = db.create_alarm(
        camera_id,
        camera_name,
        alarm["alarm_type"],
        alarm["level"],
        alarm["confidence"],
        1 if alarm.get("verified") else 0,
    )
    is_new = bool(record.get("is_new"))
    alarm_id = int(record["id"])
    if frame_jpeg:
        if is_new:
            record["snapshot_first"] = snapshots.store_frame(camera_id, alarm_id, "first", frame_jpeg)
        record["snapshot_latest"] = snapshots.store_frame(camera_id, alarm_id, "latest", frame_jpeg)
        record["boxes"] = json.dumps(visible, ensure_ascii=False)
        width, height = frame_size
        db.update_alarm_snapshot(
            alarm_id,
            first=record.get("snapshot_first") if is_new else None,
            latest=record["snapshot_latest"],
            boxes=record["boxes"],
            frame_size=f"{int(width)}x{int(height)}",
        )
        record["frame_size"] = f"{int(width)}x{int(height)}"
    record["pushed"] = False
    if is_new and notifier is not None:
        notifier.enqueue_alarm(record)
        record["pushed"] = True
    return record
```

- [ ] **Step 4: 运行测试，确认通过**

Run: `ai\.venv\Scripts\python.exe -m pytest backend/tests/test_alarm_store.py -q`
Expected: `4 passed`

- [ ] **Step 5: 提交**

```powershell
git add backend/app/alarm_store.py backend/tests/test_alarm_store.py
git commit -m "feat(alarm): 新增告警留存编排（写库+存图+推送入队） - 蔡俊杰"
```

---

### Task 6: 接线——worker 采集画面、lifespan 启停推送线程

**Files:**
- Modify: `backend/app/worker.py`（构造参数、告警段落）
- Modify: `backend/app/main.py`（`CameraRegistry`、`lifespan`）
- Modify: `backend/app/config.py`（新增 `PUBLIC_BASE`）
- Test: `backend/tests/test_api_notify.py` 暂不涉及；本任务靠既有测试不回归 + Step 5 的手工验证

**Interfaces:**
- Consumes: `alarm_store.persist_alarm`（Task 5）、`notify.Notifier`（Task 4）、`snapshots.cleanup_old_frames`（Task 2）
- Produces:
  - `DetectionWorker(camera, detector, ws, settings_provider, notifier=None)`
  - `CameraRegistry.notifier` 属性
  - `app.state.notifier`
  - `config.PUBLIC_BASE`（`FIREGUARD_PUBLIC_BASE` 环境变量，默认空串）

- [ ] **Step 1: 先确认现有测试仍全绿（基线）**

Run: `ai\.venv\Scripts\python.exe -m pytest backend/tests -q`
Expected: `44 passed`（原 15 + Task1 5 + Task2 5 + Task3 4 + Task4 11 + Task5 4）

- [ ] **Step 2: 改 `backend/app/config.py`**

在文件末尾追加：

```python
# 推送消息里引用的系统对外地址；留空则按本机局域网 IP + 8000 端口自动推断
PUBLIC_BASE = os.environ.get("FIREGUARD_PUBLIC_BASE", "")
```

- [ ] **Step 3: 改 `backend/app/worker.py`**

导入区把 `from . import db` 改为：

```python
from . import alarm_store, db
```

`__init__` 签名增加参数（放在 `settings_provider` 之后，保持向后兼容）：

```python
    def __init__(
        self,
        camera: dict[str, Any],
        detector,
        ws: WsManager,
        settings_provider: Callable[[], dict[str, Any]],
        notifier: Any | None = None,
    ) -> None:
```

`__init__` 内 `self.settings_provider = settings_provider` 之后补一行：

```python
        self.notifier = notifier
```

把告警段落（原 `if alarm is not None:` 那一块，从 `record = db.create_alarm(` 到 `self._send({"event": "alarm", "alarm": record})`）整体替换为：

```python
                if alarm is not None:
                    record = alarm_store.persist_alarm(
                        camera_id=self.camera_id,
                        camera_name=self.camera["name"],
                        alarm=alarm,
                        visible=visible,
                        frame_jpeg=self.latest_jpeg or b"",
                        frame_size=(frame.shape[1], frame.shape[0]),
                        notifier=self.notifier,
                    )
                    record["agents"] = trace
                    self._send({"event": "alarm", "alarm": record})
```

- [ ] **Step 4: 改 `backend/app/main.py` 的 `CameraRegistry` 与 `lifespan`**

导入区补：

```python
from . import alarm_store  # 若未用到可不加；worker 内部已导入
from . import snapshots
from . import notify
from .config import MODEL_PATH, PUBLIC_BASE, UPLOADS
```

`CameraRegistry.__init__` 增加：

```python
        self.notifier: notify.Notifier | None = None
```

`start_camera` 里的构造改为：

```python
        w = DetectionWorker(camera, self.detector, self.ws, db.get_settings, notifier=self.notifier)
```

`lifespan` 改为（完整替换原函数体）：

```python
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        db.init_db()
        if not MODEL_PATH.is_file():
            raise RuntimeError(f"模型不存在: {MODEL_PATH}，请先完成 AI 训练")
        snapshots.cleanup_old_frames(days=7)
        notifier = notify.Notifier(base_url_provider=_public_base_url)
        notifier.start()
        registry = CameraRegistry()
        registry.notifier = notifier
        registry.detector = YoloDetector(str(MODEL_PATH))
        registry.ws.set_loop(asyncio.get_running_loop())
        app.state.registry = registry
        app.state.notifier = notifier
        for camera in db.list_cameras():
            registry.start_camera(camera)
        yield
        for w in list(registry.workers.values()):
            w.stop()
        notifier.stop()
```

在 `create_app()` 之前（模块级）新增两个辅助函数：

```python
def _preferred_lan_ip() -> str:
    """挑选最可能被手机访问到的本机 IPv4，优先 192.168 网段。"""
    import socket

    import psutil

    addresses: list[str] = []
    for _name, addrs in psutil.net_if_addrs().items():
        for addr in addrs:
            if addr.family != socket.AF_INET:
                continue
            ip = addr.address
            if ip.startswith("127.") or ip.startswith("169.254."):
                continue
            addresses.append(ip)
    if not addresses:
        return ""
    addresses.sort(key=lambda ip: {"192": 0, "10": 1, "172": 2}.get(ip.split(".")[0], 3))
    return addresses[0]


def _public_base_url() -> str:
    """推送消息里使用的系统地址；配置了 FIREGUARD_PUBLIC_BASE 时优先用它。"""
    if PUBLIC_BASE:
        return PUBLIC_BASE.rstrip("/")
    ip = _preferred_lan_ip()
    return f"http://{ip}:8000" if ip else ""
```

- [ ] **Step 5: 手工冒烟验证（不开摄像头，只确认启动与清理正常）**

```powershell
ai\.venv\Scripts\python.exe -c "from backend.app.main import app; print('app ok', len(app.routes))"
```
Expected: 打印 `app ok <数字>`，无异常

- [ ] **Step 6: 跑全量测试**

Run: `ai\.venv\Scripts\python.exe -m pytest backend/tests -q`
Expected: 全部通过，`0 failed`

- [ ] **Step 7: 提交**

```powershell
git add backend/app/worker.py backend/app/main.py backend/app/config.py
git commit -m "feat(alarm): worker 留存告警画面并接入推送线程 - 蔡俊杰"
```

---

### Task 7: 通知配置接口

**Files:**
- Modify: `backend/app/main.py`（新增 `NotifyPayload`、`NotifyTestPayload` 与 4 个路由）
- Test: `backend/tests/test_api_notify.py`

**Interfaces:**
- Consumes: `db.get_notify_config`、`db.save_notify_config`、`db.list_notifications`、`db.clear_notifications`、`notify.ServerChanChannel`、`notify.render_message`
- Produces:
  - `GET /api/notify` → `{enabled, sendkey_masked, name, daily_limit, configured, sent_today, records, last_skip}`
  - `PUT /api/notify` → 保存后的同一结构（含掩码）
  - `POST /api/notify/test` → `{ok, code, message}`
  - `POST /api/notify/reset` → `{ok: true, cleared: <int>}`

- [ ] **Step 1: 写失败的测试**

新建 `backend/tests/test_api_notify.py`：

```python
from fastapi.testclient import TestClient

from backend.app import db, notify
from backend.app.main import app


def _reset() -> None:
    db.init_db()
    db.clear_notifications()
    db.save_notify_config(0, "", "", 5)


def test_get_notify_masks_sendkey() -> None:
    _reset()
    db.save_notify_config(1, "SCTabcdefgh1234", "组长手机", 5)
    with TestClient(app) as client:
        data = client.get("/api/notify").json()
    assert data["enabled"] == 1
    assert data["name"] == "组长手机"
    assert data["sendkey_masked"] == "****1234"
    assert "SCTabcdefgh1234" not in str(data)
    assert data["configured"] is True


def test_put_notify_keeps_existing_key_when_masked() -> None:
    _reset()
    db.save_notify_config(1, "SCTrealvalue9999", "手机A", 5)
    with TestClient(app) as client:
        client.put("/api/notify", json={"enabled": 1, "sendkey": "****9999", "name": "手机B", "daily_limit": 3})
    cfg = db.get_notify_config()
    assert cfg["sendkey"] == "SCTrealvalue9999"
    assert cfg["name"] == "手机B"
    assert cfg["daily_limit"] == 3


def test_notify_test_endpoint_uses_channel(monkeypatch) -> None:
    _reset()
    db.save_notify_config(1, "SCTkeyforTest0001", "手机A", 5)
    sent = {}

    def fake_send(self, title, desp):
        sent["title"] = title
        sent["desp"] = desp
        return {"ok": True, "code": 0, "message": "SUCCESS"}

    monkeypatch.setattr(notify.ServerChanChannel, "send", fake_send)
    with TestClient(app) as client:
        result = client.post("/api/notify/test", json={}).json()
    assert result["ok"] is True
    assert "推送测试" in sent["title"]
    assert "手机A" in sent["desp"]


def test_notify_test_without_key_returns_error() -> None:
    _reset()
    with TestClient(app) as client:
        result = client.post("/api/notify/test", json={}).json()
    assert result["ok"] is False
    assert "SendKey" in result["message"]


def test_notify_reset_clears_records() -> None:
    _reset()
    db.reserve_notification(2, 20, "fire", "标题")
    with TestClient(app) as client:
        assert len(client.get("/api/notify").json()["records"]) == 1
        assert client.post("/api/notify/reset").json()["cleared"] == 1
        assert client.get("/api/notify").json()["records"] == []
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `ai\.venv\Scripts\python.exe -m pytest backend/tests/test_api_notify.py -q`
Expected: FAIL，`404`（路由不存在）

- [ ] **Step 3: 实现**

`backend/app/main.py` 的 pydantic 模型区（`AckGroupPayload` 之后）新增：

```python
class NotifyPayload(BaseModel):
    enabled: int = Field(default=0, ge=0, le=1)
    sendkey: str = ""
    name: str = ""
    daily_limit: int = Field(default=5, ge=1, le=1000)


class NotifyTestPayload(BaseModel):
    sendkey: str = ""
```

`create_app()` 内、`/api/settings` 路由之前新增：

```python
    def _mask_key(key: str) -> str:
        return f"****{key[-4:]}" if len(key) > 4 else ("****" if key else "")

    def _notify_view() -> dict[str, Any]:
        cfg = db.get_notify_config()
        notifier = getattr(app.state, "notifier", None)
        return {
            "enabled": cfg["enabled"],
            "sendkey_masked": _mask_key(cfg["sendkey"]),
            "name": cfg["name"],
            "daily_limit": cfg["daily_limit"],
            "configured": bool(cfg["sendkey"]),
            "sent_today": db.notifications_sent_today(),
            "records": db.list_notifications(),
            "last_skip": getattr(notifier, "last_skip", "") if notifier else "",
        }

    @app.get("/api/notify")
    def notify_config() -> dict[str, Any]:
        return _notify_view()

    @app.put("/api/notify")
    def save_notify(payload: NotifyPayload) -> dict[str, Any]:
        current = db.get_notify_config()
        sendkey = payload.sendkey.strip()
        if "****" in sendkey:  # 前端回传的是掩码，保留原值
            sendkey = current["sendkey"]
        db.save_notify_config(payload.enabled, sendkey, payload.name.strip(), payload.daily_limit)
        return _notify_view()

    @app.post("/api/notify/test")
    def notify_test(payload: NotifyTestPayload) -> dict[str, Any]:
        cfg = db.get_notify_config()
        sendkey = payload.sendkey.strip() or cfg["sendkey"]
        if not sendkey:
            return {"ok": False, "code": None, "message": "未配置 SendKey，请先填写并保存"}
        title = "【火情监测】推送测试"
        desp = (
            "### 推送测试\n\n"
            f"- **接收人**：{cfg['name'] or '未命名'}\n"
            "- **说明**：收到这条说明告警推送配置正确。\n"
        )
        return notify.ServerChanChannel(sendkey).send(title, desp)

    @app.post("/api/notify/reset")
    def notify_reset() -> dict[str, Any]:
        return {"ok": True, "cleared": db.clear_notifications()}
```

- [ ] **Step 4: 运行测试，确认通过**

Run: `ai\.venv\Scripts\python.exe -m pytest backend/tests/test_api_notify.py -q`
Expected: `5 passed`

- [ ] **Step 5: 提交**

```powershell
git add backend/app/main.py backend/tests/test_api_notify.py
git commit -m "feat(api): 新增告警推送配置、测试与重置接口 - 蔡俊杰"
```

---

### Task 8: 前端——告警中心展示画面帧与检测框

**Files:**
- Modify: `frontend/src/api/index.js`
- Modify: `frontend/src/views/AlarmsView.vue`

**Interfaces:**
- Consumes: `GET /api/alarms/{id}`、`GET /api/alarms/{id}/frame`（Task 3）
- Produces:
  - `api.alarmDetail(id)`、`alarmFrameUrl(id, variant)`（供本任务与后续任务使用）

- [ ] **Step 1: 扩展前端接口层**

`frontend/src/api/index.js` 的 `api` 对象里，在 `clearAlarms` 之后加两行：

```js
  alarmDetail: (id) => request(`/api/alarms/${id}`),
```

文件末尾追加：

```js
export const alarmFrameUrl = (alarmId, variant = 'first') => `/api/alarms/${alarmId}/frame?variant=${variant}`
```

- [ ] **Step 2: `AlarmsView.vue` 脚本部分改造**

导入区改为：

```js
import { alarmFrameUrl, api } from '../api'
```

（原来只导入 `api`；本行替换原来的 `import { api } from '../api'`。）

在 `busyKey` 之后新增三个状态：

```js
const frameVariant = ref('first')
const frameError = ref(false)
const detailBoxes = ref([])
```

`displayRows` 的合并逻辑里补首帧归属（未处理分组时，代表行的 id 可能不是最早那条，首帧要记最早的 id）：

- 在 `if (!exist) { groups.set(key, {...}) }` 的对象里补两个字段：

```js
        firstSnapshotId: row.snapshot_first ? row.id : null,
```

- 在 `if ((row.created_at || '') > (exist.latestAt || ''))` 分支里，给 `exist` 补：

```js
      exist.snapshot_latest = row.snapshot_latest
```

- 在 `return filteredRows.value.map(...)` 那一支（未处理以外）改为：

```js
    return filteredRows.value.map((row) => ({
      ...row,
      count: 1,
      firstAt: row.created_at,
      latestAt: row.created_at,
      firstSnapshotId: row.snapshot_first ? row.id : null
    }))
```

把 `openDetail` 替换为（拉取详情以拿到框坐标）：

```js
async function openDetail(row) {
  detail.value = row
  detailBoxes.value = []
  frameVariant.value = 'first'
  frameError.value = false
  detailVisible.value = true
  try {
    const data = await api.alarmDetail(row.id)
    detailBoxes.value = Array.isArray(data.boxes) ? data.boxes : []
  } catch {
    detailBoxes.value = []
  }
}
```

新增三个计算属性/辅助函数（放在 `openDetail` 之后）：

```js
const firstFrameId = computed(() => detail.value?.firstSnapshotId || null)
const latestFrameId = computed(() => detail.value?.id || null)
const currentFrameId = computed(() =>
  frameVariant.value === 'first' ? firstFrameId.value : latestFrameId.value
)
const frameUrl = computed(() =>
  currentFrameId.value && !frameError.value ? alarmFrameUrl(currentFrameId.value, frameVariant.value) : ''
)
const hasAnyFrame = computed(() => Boolean(firstFrameId.value || detail.value?.snapshot_latest))

function switchVariant(value) {
  frameVariant.value = value
  frameError.value = false
}
```

- [ ] **Step 3: `AlarmsView.vue` 模板部分——表格缩略图列**

在「最近出现」列之后插入缩略图列（严重告警表格与预警表格各一处，两处代码相同）：

```html
                <el-table-column label="画面" width="96">
                  <template #default="{ row }">
                    <el-image
                      v-if="row.snapshot_latest"
                      :src="alarmFrameUrl(row.id, 'latest')"
                      fit="cover"
                      class="thumb"
                      :preview-src-list="[alarmFrameUrl(row.id, 'latest')]"
                      preview-teleported
                    />
                    <span v-else class="muted">—</span>
                  </template>
                </el-table-column>
```

- [ ] **Step 4: `AlarmsView.vue` 模板部分——抽屉改成画面优先**

把 `<el-drawer v-model="detailVisible" title="告警详情" size="420px">` 改为 `size="560px"`，并在 `<el-descriptions>` 之前插入：

```html
      <div v-if="detail" class="frame-panel">
        <div class="frame-head">
          <el-radio-group :model-value="frameVariant" size="small" @update:model-value="switchVariant">
            <el-radio-button value="first" :disabled="!firstFrameId">触发帧</el-radio-button>
            <el-radio-button value="latest" :disabled="!latestFrameId">最近帧</el-radio-button>
          </el-radio-group>
          <span class="frame-time">{{ detail.latestAt || detail.created_at }}</span>
        </div>
        <img v-if="frameUrl" :src="frameUrl" class="frame-img" alt="告警画面" @error="frameError = true" />
        <div v-else class="frame-empty">
          {{ hasAnyFrame ? '画面读取失败（文件可能已被清理）' : '该告警产生于功能上线前，无画面留存' }}
        </div>
        <div v-if="detailBoxes.length" class="box-list">
          <div class="box-title">检测结果（{{ detailBoxes.length }}）</div>
          <div v-for="(item, index) in detailBoxes" :key="index" class="box-row">
            <el-tag :type="item.type === 'fire' ? 'danger' : 'warning'" size="small" effect="plain">
              {{ item.type === 'fire' ? '明火' : '烟雾' }}
            </el-tag>
            <span class="box-conf">{{ (item.confidence * 100).toFixed(1) }}%</span>
            <span class="box-coord">框 x{{ item.bbox[0] }} y{{ item.bbox[1] }} w{{ item.bbox[2] }} h{{ item.bbox[3] }}</span>
          </div>
        </div>
      </div>
```

- [ ] **Step 5: `AlarmsView.vue` 样式补充**

在 `<style scoped>` 里追加：

```css
.thumb { width: 3.5rem; height: 2.25rem; border-radius: 4px; cursor: zoom-in; }
.frame-panel { margin-bottom: 1rem; }
.frame-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 0.5rem; }
.frame-time { color: #9aa2b0; font-size: 0.875rem; }
.frame-img { width: 100%; border-radius: 6px; background: #0f141c; display: block; }
.frame-empty {
  height: 8rem; display: flex; align-items: center; justify-content: center;
  background: #f3f5f8; color: #9aa2b0; border-radius: 6px; font-size: 0.875rem; text-align: center; padding: 0 1rem;
}
.box-list { margin-top: 0.75rem; }
.box-title { font-size: 0.875rem; color: #4b5563; margin-bottom: 0.375rem; }
.box-row { display: flex; align-items: center; gap: 0.5rem; padding: 0.25rem 0; font-size: 0.875rem; }
.box-conf { color: #1f2d3d; font-weight: 600; }
.box-coord { color: #9aa2b0; }
```

- [ ] **Step 6: 构建并验证**

```powershell
cd frontend
npm run build
```
Expected: `✓ built in ...`，无 error

```powershell
cd ..
$chrome = "C:\Program Files\Google\Chrome\Application\chrome.exe"
$prof = Join-Path $env:TEMP ("fg-verify-" + [guid]::NewGuid().ToString('N').Substring(0,8))
& $chrome --headless=new --disable-gpu --hide-scrollbars --user-data-dir="$prof" --window-size=1600,1000 --virtual-time-budget=12000 --screenshot="storage\verify_alarms.png" "http://127.0.0.1:8000/#/alarms" 2>&1 | Out-Null
Remove-Item $prof -Recurse -Force -ErrorAction SilentlyContinue
```
Expected: 生成 `storage\verify_alarms.png`；用图片查看工具打开，确认**表格出现"画面"列**（新告警有缩略图，历史告警显示"—"）

再用浏览器人工点一次「详情」，确认抽屉里有画面、能切换「触发帧/最近帧」、下方列出检测结果。若此刻还没有带图的新告警，先跳到 Task 10 的端到端验证再回看。

- [ ] **Step 7: 提交**

```powershell
git add frontend/src/api/index.js frontend/src/views/AlarmsView.vue
git commit -m "feat(alarm-ui): 告警中心展示画面帧与检测框 - 蔡俊杰"
```

---

### Task 9: 前端——系统设置新增「告警推送」卡片

**Files:**
- Modify: `frontend/src/api/index.js`
- Modify: `frontend/src/views/SettingsView.vue`

**Interfaces:**
- Consumes: `GET/PUT /api/notify`、`POST /api/notify/test`、`POST /api/notify/reset`（Task 7）
- Produces: 设置页可视化配置与推送记录

- [ ] **Step 1: 扩展 `frontend/src/api/index.js`**

`api` 对象里 `saveSettings` 之后追加（注意给上一行补逗号）：

```js
  notifyConfig: () => request('/api/notify'),
  saveNotify: (payload) => request('/api/notify', { method: 'PUT', body: JSON.stringify(payload) }),
  testNotify: (payload = {}) => request('/api/notify/test', { method: 'POST', body: JSON.stringify(payload) }),
  resetNotify: () => request('/api/notify/reset', { method: 'POST' })
```

- [ ] **Step 2: `SettingsView.vue` 脚本部分**

导入区不变。在 `saving` 之后新增状态与逻辑：

```js
const notify = ref({ enabled: 0, sendkey_masked: '', name: '', daily_limit: 5, configured: false, sent_today: 0, records: [], last_skip: '' })
const notifyForm = ref({ enabled: 0, sendkey: '', name: '', daily_limit: 5 })
const notifySaving = ref(false)
const testing = ref(false)

async function loadNotify() {
  try {
    const data = await api.notifyConfig()
    notify.value = data
    notifyForm.value = {
      enabled: data.enabled,
      sendkey: data.sendkey_masked,
      name: data.name,
      daily_limit: data.daily_limit
    }
  } catch (error) {
    ElMessage.error(`读取推送配置失败：${error.message}`)
  }
}

async function saveNotify() {
  notifySaving.value = true
  try {
    const data = await api.saveNotify(notifyForm.value)
    notify.value = data
    notifyForm.value = {
      enabled: data.enabled,
      sendkey: data.sendkey_masked,
      name: data.name,
      daily_limit: data.daily_limit
    }
    ElMessage.success('推送配置已保存')
  } catch (error) {
    ElMessage.error(`保存失败：${error.message}`)
  } finally {
    notifySaving.value = false
  }
}

async function testNotify() {
  testing.value = true
  try {
    const result = await api.testNotify({})
    if (result.ok) ElMessage.success('测试通知已发送，请查看微信')
    else ElMessage.error(`发送失败：${result.message || '未知原因'}（code=${result.code}）`)
    await loadNotify()
  } catch (error) {
    ElMessage.error(`测试失败：${error.message}`)
  } finally {
    testing.value = false
  }
}

async function resetNotify() {
  try {
    await ElMessageBox.confirm('重置后，各视频源在本次运行中可再次收到推送。确定重置？', '重置推送记录', { type: 'warning' })
    const result = await api.resetNotify()
    ElMessage.success(`已重置 ${result.cleared} 条推送记录`)
    await loadNotify()
  } catch (error) {
    if (error !== 'cancel') ElMessage.error(`重置失败：${error.message || error}`)
  }
}
```

`import` 行改为 `import { ElMessage, ElMessageBox } from 'element-plus'`；`onMounted(load)` 改为：

```js
onMounted(() => {
  load()
  loadNotify()
})
```

- [ ] **Step 3: `SettingsView.vue` 模板部分**

在最后一个 `</el-form>` 之后、`</el-card>` 之前插入：

```html
    <el-divider />
    <div class="section-title">告警推送</div>
    <el-alert
      type="warning"
      :closable="false"
      class="tips"
      title="采用 Server酱 推送到微信：免费版每天 5 条，按视频源去重（同一路本次运行只推第一条）。修改配置后需点保存生效。"
    />
    <el-form label-width="180px" style="max-width: 760px">
      <el-form-item label="启用推送">
        <el-switch v-model="notifyForm.enabled" :active-value="1" :inactive-value="0" />
        <span class="switch-hint">当前状态：{{ notify.enabled ? '已启用' : '未启用' }}</span>
      </el-form-item>
      <el-form-item label="SendKey">
        <el-input v-model="notifyForm.sendkey" placeholder="在 sct.ftqq.com 微信扫码后获取" show-password />
        <div class="switch-hint is-wide">
          已配置：{{ notify.configured ? '是' : '否' }}；输入框显示的是掩码，不改动则保留原 Key。
        </div>
      </el-form-item>
      <el-form-item label="接收人备注">
        <el-input v-model="notifyForm.name" placeholder="如：组长手机" />
      </el-form-item>
      <el-form-item label="每日上限">
        <el-input-number v-model="notifyForm.daily_limit" :min="1" :max="1000" />
        <span class="switch-hint">今日已发送 {{ notify.sent_today }} 条</span>
      </el-form-item>
      <el-form-item>
        <el-button type="primary" :loading="notifySaving" @click="saveNotify">保存推送配置</el-button>
        <el-button :loading="testing" @click="testNotify">发送测试通知</el-button>
        <el-button @click="resetNotify">重置推送记录</el-button>
      </el-form-item>
      <el-form-item v-if="notify.last_skip" label="最近一次跳过原因">
        <span class="switch-hint is-wide">{{ notify.last_skip }}</span>
      </el-form-item>
    </el-form>
    <div class="section-title">推送记录</div>
    <el-table :data="notify.records" size="small" empty-text="本轮尚未推送任何视频源">
      <el-table-column prop="created_at" label="时间" width="200" />
      <el-table-column prop="title" label="标题" min-width="280" show-overflow-tooltip />
      <el-table-column label="结果" width="120">
        <template #default="{ row }">
          <el-tag :type="row.ok ? 'success' : 'danger'" size="small" effect="plain">
            {{ row.ok ? '成功' : '失败' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="message" label="返回信息" min-width="180" show-overflow-tooltip />
    </el-table>
```

- [ ] **Step 4: 构建并验证**

```powershell
cd frontend
npm run build
```
Expected: `✓ built in ...`

```powershell
cd ..
$chrome = "C:\Program Files\Google\Chrome\Application\chrome.exe"
$prof = Join-Path $env:TEMP ("fg-verify-" + [guid]::NewGuid().ToString('N').Substring(0,8))
& $chrome --headless=new --disable-gpu --hide-scrollbars --user-data-dir="$prof" --window-size=1600,1000 --virtual-time-budget=12000 --screenshot="storage\verify_settings.png" "http://127.0.0.1:8000/#/settings" 2>&1 | Out-Null
Remove-Item $prof -Recurse -Force -ErrorAction SilentlyContinue
```
Expected: `storage\verify_settings.png` 里能看到「告警推送」区块与「推送记录」表格

- [ ] **Step 5: 提交**

```powershell
git add frontend/src/api/index.js frontend/src/views/SettingsView.vue
git commit -m "feat(settings): 设置页新增告警推送配置与记录 - 蔡俊杰"
```

---

### Task 10: 端到端验证与文档

**Files:**
- Modify: `README.md`（接口清单行、演示章节）
- Modify: `docs/demo-checklist.md`（演示顺序补推送环节）
- Test: 手工端到端（真实推送）

**Interfaces:**
- Consumes: 前 9 个任务的全部产出
- Produces: 可演示的完整功能 + 文档

- [ ] **Step 1: 重启后端让新代码生效**

```powershell
# 先停掉旧进程（若在后台任务里则用工具停），再启动
$env:FIREGUARD_DEVICE='0'
ai\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --host 0.0.0.0 --port 8000
```
Expected: 日志出现 `Application startup complete.`，无异常

- [ ] **Step 2: 配置并保存推送**

浏览器打开 <http://127.0.0.1:8000/#/settings>，「告警推送」里填 SendKey、接收人备注「组长手机」，打开「启用推送」，点保存。

- [ ] **Step 3: 点「发送测试通知」验证通道**

Expected: 页面提示「测试通知已发送」，微信收到；推送记录表格出现一条「成功」。

- [ ] **Step 4: 触发真实告警，验证三件事**

1. 打开 <http://127.0.0.1:8000/#/monitor> 让 demo_fire 等视频源跑起来；
2. 等到告警中心出现新告警；
3. 逐项确认：
   - 告警中心表格出现缩略图，点「详情」能看到大图与检测框列表；
   - 微信收到该视频源的告警推送，**且再等 1 分钟同一路不再重复推送**；
   - 推送消息里的画面链接在手机上（同一 WiFi）能打开。

- [ ] **Step 5: 验证去重与重置**

在设置页点「重置推送记录」，等待同一路视频源再次告警，确认微信又收到一条。
Expected: 重置后可以再次推送，说明占位已清空。

- [ ] **Step 6: 更新文档**

`README.md` 的「主要接口」行补上新接口；在「演示清单」相关段落补推送说明（一段话即可）：

```markdown
- 告警画面：每条告警留存「触发帧 + 最近帧」两张带检测框的画面，告警中心表格显示缩略图，详情抽屉可切换查看并列出检测框，接口 `GET /api/alarms/{id}/frame?variant=first|latest`；快照保留 7 天。
- 手机推送：系统设置「告警推送」里填 Server酱 SendKey 并启用，同一路视频源本次运行只推第一条，可在页面重置；接口 `GET/PUT /api/notify`、`POST /api/notify/test`、`POST /api/notify/reset`。
```

`docs/demo-checklist.md` 的演示顺序里插入一步：

```markdown
4.5 手机推送：设置页填 SendKey 并启用 → 点「发送测试通知」确认微信收到 → 等待真实告警推送一次 → 说明按视频源去重与每日额度限制。
```

- [ ] **Step 7: 跑最后一次全量测试**

Run: `ai\.venv\Scripts\python.exe -m pytest backend/tests -q`
Expected: 全部通过，`0 failed`

- [ ] **Step 8: 提交**

```powershell
git add README.md docs/demo-checklist.md
git commit -m "docs(demo): 补充告警画面与手机推送的演示说明 - 蔡俊杰"
```

---

## Self-Review

**1. Spec coverage**

| 设计文档要求 | 对应任务 |
| --- | --- |
| 采集触发帧 + 最近帧、存框坐标 JSON | Task 5（`persist_alarm`） |
| 快照目录与 7 天清理 | Task 2 |
| alarms 表新增 4 列 + 推送记录表 | Task 1 |
| 画面接口 `/api/alarms/{id}/frame`、详情接口 | Task 3 |
| 告警中心缩略图 + 抽屉大图 + 首帧/最近帧切换 + 框列表 | Task 8 |
| 历史告警无图占位文案 | Task 8 Step 4（`frame-empty`） |
| 清空告警时删图 | Task 3 |
| 按视频源去重（`INSERT OR IGNORE`） | Task 1 + Task 4 |
| 独立线程 + 有界队列，检测线程不等待网络 | Task 4 + Task 6 |
| 每日上限保护 | Task 4（`handle` 内检查） |
| 消息格式（标题去换行、Markdown、局域网画面链接） | Task 4（`render_message`） |
| 单接收人配置项 4 个 | Task 1 + Task 7 |
| 设置页推送卡片、测试、重置、记录 | Task 9 |
| SendKey 掩码与不外泄 | Task 7（`_mask_key`）+ Global Constraints |
| 失败占位不重试、原因可见 | Task 4（`handle`）+ Task 7（`last_skip`/`records`） |
| 测试方式 | 各任务 TDD 步骤 + Task 10 端到端 |

无遗漏。

**2. Placeholder scan**

已通读全文，未出现 TBD/TODO/「稍后补充」；每个代码步骤都带完整实现，每个验证步骤都带可执行命令与预期输出。

**3. Type consistency**

- `snapshots.store_frame(...) -> str` 在 Task 2 定义，Task 5 按返回值写入 `record["snapshot_first"]/["snapshot_latest"]`，Task 3 用 `db.get_alarm(...).get(f"snapshot_{variant}")` 读取，字段名一致。
- `db.create_alarm` 新增 `is_new`（Task 1），Task 5 用 `record.get("is_new")` 判断，Task 4 不依赖。
- `Notifier.handle` 返回 `bool`，Task 6/7 不直接调用；`last_skip` 由 Task 7 的 `_notify_view()` 读取，属性名一致。
- `ServerChanChannel.send` 返回 `{"ok","code","message"}`，Task 7 的接口原样透传，前端 Task 9 读取 `result.ok/message/code`，一致。
- `alarmFrameUrl(alarmId, variant)` 在 Task 8 定义并被模板与本任务 `:src` 使用，签名一致。
- `notify.get_notify_config()` 的键 `enabled/sendkey/name/daily_limit` 与 Task 7 的 `_notify_view()`、Task 4 的 `handle` 完全一致。

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-10-27-alarm-snapshot-and-push.md`.
