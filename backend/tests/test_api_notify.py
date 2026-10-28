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
    with TestClient(app) as client:
        # lifespan 启动时会清空推送记录（每次启动视为新一轮），故占位必须在启动之后
        db.reserve_notification(2, 20, "fire", "标题")
        assert len(client.get("/api/notify").json()["records"]) == 1
        assert client.post("/api/notify/reset").json()["cleared"] == 1
        assert client.get("/api/notify").json()["records"] == []


def test_ack_releases_camera_push_slot() -> None:
    """确认处理某条告警后，该视频源的推送名额应被释放，下次新告警可再推。"""
    _reset()
    db.clear_alarms()
    alarm = db.create_alarm(5, "东门", "fire", "critical", 0.9, 1)
    with TestClient(app) as client:
        assert db.reserve_notification(5, alarm["id"], "fire", "标题") is True
        assert db.reserve_notification(5, alarm["id"] + 1, "fire", "标题2") is False

        assert client.post(f"/api/alarms/{alarm['id']}/ack").json()["ok"] is True

        # 名额已释放
        assert db.reserve_notification(5, alarm["id"] + 2, "fire", "标题3") is True


def test_ack_group_releases_camera_push_slot() -> None:
    _reset()
    db.clear_alarms()
    db.create_alarm(6, "西门", "smoke", "warning", 0.6, 0)
    with TestClient(app) as client:
        assert db.reserve_notification(6, 900, "smoke", "标题") is True
        assert client.post("/api/alarms/ack_group", json={"camera_id": 6, "alarm_type": "smoke"}).json()["handled"] == 1
        assert db.reserve_notification(6, 901, "smoke", "标题2") is True