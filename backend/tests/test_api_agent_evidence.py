"""证据抽屉接口与出图函数的回归测试。

图片函数用合成帧直接测试：不启动检测、不依赖真实视频源；
接口测试用假 Worker 注入注册表，验证 404/400 与 content-type。
"""
from __future__ import annotations

from types import SimpleNamespace

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from backend.app import evidence
from backend.app.main import app
from backend.app.tiling import tile_frame

CAMERA_ID = 999999


def _frame(width: int = 320, height: int = 240, value: int = 55) -> np.ndarray:
    return np.full((height, width, 3), value, dtype=np.uint8)


def _jpeg(frame: np.ndarray, quality: int = 80) -> bytes:
    ok, buffer = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
    assert ok
    return buffer.tobytes()


def _decode(data: bytes) -> np.ndarray:
    decoded = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
    assert decoded is not None
    return decoded


def _thumb() -> bytes:
    return _jpeg(cv2.resize(_frame(), (320, 180)), quality=60)


class _FakeWorker:
    """只实现证据接口真正读取的字段，模拟运行中的 DetectionWorker。"""

    def __init__(self) -> None:
        self.latest_raw_jpeg = _jpeg(_frame())
        self.latest_jpeg = self.latest_raw_jpeg
        self._last_objects = [
            {"type": "fire", "confidence": 0.78, "bbox": [40, 60, 80, 50]},
            {"type": "smoke", "confidence": 0.21, "bbox": [180, 90, 60, 40]},
        ]
        self._tile_objects = [
            {"type": "fire", "confidence": 0.66, "bbox": [44, 64, 60, 40]},
        ]
        self._last_verify = None
        self._last_trace = {
            "perception": {"active": True, "objects": 2, "top_confidence": 0.78},
            "farfield": {"active": True, "enabled": True, "tile_size": 640, "interval": 2, "held": 1},
            "temporal": {"smoke_streak": 0, "required": 3, "cooldown": 8},
            "verification": {"active": True, "triggered": False, "passed": None},
            "decision": {"status": "critical", "risk": 89, "alarm": False},
        }
        self._verify_stats = {
            "total": 13,
            "passed": 11,
            "blocked": 2,
            "last_ts": "2026-10-28 22:00:00",
            "last_passed": True,
            "last_confidence": 0.62,
        }
        self._evidence_frames = [
            {"ts": "22:10:01", "objects": 2, "smoke": 0.0, "jpeg": _thumb()},
            {"ts": "22:10:02", "objects": 3, "smoke": 0.42, "jpeg": _thumb()},
        ]
        self.engine = SimpleNamespace(smoke_streak=0, risk=89, status="critical")

    def settings_provider(self) -> dict:
        return {
            "fire_threshold": 0.4,
            "smoke_threshold": 0.4,
            "continuous_frames": 3,
            "alarm_cooldown": 8,
            "tiling_enabled": 1,
            "tile_size": 640,
            "tile_overlap": 0.2,
            "tile_interval": 2,
            "verify_enabled": 1,
            "verify_threshold": 0.25,
        }


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def fake_worker(client):
    worker = _FakeWorker()
    client.app.state.registry.workers[CAMERA_ID] = worker
    yield worker
    client.app.state.registry.workers.pop(CAMERA_ID, None)


# ── 纯图片函数 ────────────────────────────────────────────────

def test_render_detect_draws_boxes_and_header_on_real_frame() -> None:
    base = _frame()
    data = evidence.render_detect(base, [{"type": "fire", "confidence": 0.78, "bbox": [40, 60, 80, 50]}])
    assert data[:2] == b"\xff\xd8"
    decoded = _decode(data)
    assert decoded.shape[0] == base.shape[0] + 36  # 顶部说明条
    assert decoded.shape[1] >= base.shape[1]
    # 说明条里确实有文字像素，画面里确实画了框（与原纯色帧不同）
    assert float(decoded[:36].std()) > 4.0
    diff = cv2.absdiff(decoded[36:], base)
    assert int(diff.max()) > 80


def test_render_tiles_draws_grid_and_merged_boxes() -> None:
    base = _frame()
    tiles = tile_frame(base, 160, 0.2)
    assert len(tiles) == 6
    data = evidence.render_tiles(
        base,
        tiles,
        [{"type": "fire", "confidence": 0.66, "bbox": [44, 64, 60, 40]}],
        160,
        0.2,
    )
    decoded = _decode(data)
    assert decoded.shape[0] == base.shape[0] + 36
    assert decoded.shape[1] >= base.shape[1]
    diff = cv2.absdiff(decoded[36:, : base.shape[1]], base)
    assert int(diff.max()) > 60


def test_render_verify_marks_pass_and_block() -> None:
    base = _frame()
    passed = _decode(evidence.render_verify(base, {"passed": True, "confidence": 0.62, "threshold": 0.25}))
    blocked = _decode(evidence.render_verify(base, {"passed": False, "confidence": 0.10, "threshold": 0.25}))
    assert passed.shape[0] == base.shape[0] + 40
    assert blocked.shape[0] == base.shape[0] + 40
    # 左侧色条：通过偏绿（BGR 通道 1 最高），拦截偏红（通道 2 最高）
    assert int(np.argmax(passed[:40, :3].mean(axis=(0, 1)))) == 1
    assert int(np.argmax(blocked[:40, :3].mean(axis=(0, 1)))) == 2


def test_render_films_concatenates_labelled_frames() -> None:
    data = evidence.render_films([
        {"ts": "22:10:01", "objects": 2, "smoke": 0.0, "jpeg": _thumb()},
        {"ts": "22:10:02", "objects": 3, "smoke": 0.42, "jpeg": _thumb()},
    ])
    decoded = _decode(data)
    assert decoded.shape[1] > 320 * 2  # 两帧 + 间隔
    assert decoded.shape[0] == 180 + 26
    with pytest.raises(ValueError):
        evidence.render_films([])


# ── HTTP 接口 ────────────────────────────────────────────────

def test_meta_404_without_worker(client) -> None:
    response = client.get("/api/agents/evidence/meta?camera_id=999998")
    assert response.status_code == 404


def test_unknown_kind_400_wins_over_missing_worker(client) -> None:
    response = client.get("/api/agents/evidence?camera_id=999998&kind=bogus")
    assert response.status_code == 400


def test_unknown_kind_400_with_worker(client, fake_worker) -> None:
    response = client.get(f"/api/agents/evidence?camera_id={CAMERA_ID}&kind=bogus")
    assert response.status_code == 400


def test_meta_returns_five_sections(client, fake_worker) -> None:
    response = client.get(f"/api/agents/evidence/meta?camera_id={CAMERA_ID}")
    assert response.status_code == 200
    data = response.json()
    assert set(data) == {"camera_id", "perception", "farfield", "temporal", "verification", "decision"}
    assert data["perception"] == {"objects": 2, "top": 0.78}
    assert data["farfield"] == {"tiles": 1, "tile_size": 640, "overlap": 0.2, "held": 1, "active": True}
    assert data["temporal"]["streak"] == 0
    assert data["temporal"]["required"] == 3
    assert data["temporal"]["cooldown"] == 8
    assert [item["ts"] for item in data["temporal"]["frames"]] == ["22:10:01", "22:10:02"]
    assert data["verification"] == {"total": 13, "passed": 11, "blocked": 2, "last": None}
    assert data["decision"] == {"risk": 89, "status": "critical", "alarm": False}


def test_meta_reads_last_verification(client, fake_worker) -> None:
    fake_worker._last_verify = {
        "ts": "22:53:11",
        "crop": _jpeg(_frame(120, 90)),
        "bbox": [10, 10, 30, 30],
        "type": "fire",
        "confidence": 0.62,
        "passed": True,
        "threshold": 0.25,
    }
    data = client.get(f"/api/agents/evidence/meta?camera_id={CAMERA_ID}").json()
    assert data["verification"]["last"] == {
        "ts": "22:53:11",
        "passed": True,
        "confidence": 0.62,
        "threshold": 0.25,
        "type": "fire",
    }


def test_detect_endpoint_returns_jpeg(client, fake_worker) -> None:
    response = client.get(f"/api/agents/evidence?camera_id={CAMERA_ID}&kind=detect")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/jpeg"
    assert response.content[:2] == b"\xff\xd8"
    assert _decode(response.content) is not None


def test_tiles_endpoint_returns_jpeg(client, fake_worker) -> None:
    response = client.get(f"/api/agents/evidence?camera_id={CAMERA_ID}&kind=tiles")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/jpeg"
    assert len(response.content) > 1000


def test_verify_endpoint_404_until_verification_happens(client, fake_worker) -> None:
    missing = client.get(f"/api/agents/evidence?camera_id={CAMERA_ID}&kind=verify")
    assert missing.status_code == 404
    fake_worker._last_verify = {
        "ts": "22:53:11",
        "crop": _jpeg(_frame(200, 150)),
        "bbox": [10, 10, 30, 30],
        "type": "fire",
        "confidence": 0.62,
        "passed": True,
        "threshold": 0.25,
    }
    ready = client.get(f"/api/agents/evidence?camera_id={CAMERA_ID}&kind=verify")
    assert ready.status_code == 200
    assert ready.headers["content-type"] == "image/jpeg"
    assert ready.content[:2] == b"\xff\xd8"


def test_films_endpoint_404_without_frames_then_200(client, fake_worker) -> None:
    fake_worker._evidence_frames = []
    missing = client.get(f"/api/agents/evidence?camera_id={CAMERA_ID}&kind=films")
    assert missing.status_code == 404
    fake_worker._evidence_frames = [{"ts": "22:10:01", "objects": 2, "smoke": 0.0, "jpeg": _thumb()}]
    ready = client.get(f"/api/agents/evidence?camera_id={CAMERA_ID}&kind=films")
    assert ready.status_code == 200
    assert ready.headers["content-type"] == "image/jpeg"
