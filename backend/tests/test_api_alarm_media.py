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
