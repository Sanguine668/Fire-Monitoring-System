from fastapi.testclient import TestClient

from backend.app.main import app


def test_api_flow() -> None:
    with TestClient(app) as client:
        assert client.get("/api/health").status_code == 200
        assert client.get("/api/settings").json()["fire_threshold"] == 0.5
        assert client.get("/api/cameras").json() == []

        r = client.post(
            "/api/cameras",
            json={"name": "演示源", "source_type": "file", "source": "C:/tmp/a.mp4"},
        )
        assert r.status_code == 200
        cid = r.json()["id"]
        assert any(c["id"] == cid for c in client.get("/api/cameras").json())
        assert client.post(f"/api/cameras/{cid}/toggle").json() == {"id": cid, "enabled": 0}
        assert client.delete(f"/api/cameras/{cid}").status_code == 200
