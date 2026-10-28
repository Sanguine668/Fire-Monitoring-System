from fastapi.testclient import TestClient

from backend.app import db
from backend.app.main import app


def test_camera_alerts_default_and_toggle() -> None:
    """新建视频源默认开启全屏告警，新路由可反复翻转该开关。"""
    db.init_db()
    with TestClient(app) as client:
        created = client.post(
            "/api/cameras",
            json={"name": "告警开关测试源", "source_type": "file", "source": "C:/tmp/alerts.mp4"},
        )
        assert created.status_code == 200
        camera_id = created.json()["id"]
        try:
            cameras = client.get("/api/cameras").json()
            camera = next(item for item in cameras if item["id"] == camera_id)
            assert camera["alerts_enabled"] == 1

            first = client.post(f"/api/cameras/{camera_id}/alerts")
            assert first.status_code == 200
            assert first.json() == {"id": camera_id, "alerts_enabled": 0}

            cameras = client.get("/api/cameras").json()
            camera = next(item for item in cameras if item["id"] == camera_id)
            assert camera["alerts_enabled"] == 0

            second = client.post(f"/api/cameras/{camera_id}/alerts")
            assert second.status_code == 200
            assert second.json() == {"id": camera_id, "alerts_enabled": 1}

            cameras = client.get("/api/cameras").json()
            camera = next(item for item in cameras if item["id"] == camera_id)
            assert camera["alerts_enabled"] == 1
        finally:
            client.delete(f"/api/cameras/{camera_id}")


def test_camera_alerts_unknown_camera_returns_404() -> None:
    db.init_db()
    with TestClient(app) as client:
        response = client.post("/api/cameras/999999/alerts")
        assert response.status_code == 404
