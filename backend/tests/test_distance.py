"""单目测距纯函数测试：无需 torch/cv2，可无头运行。"""

from __future__ import annotations

import math

import pytest

from backend.app.distance import estimate_distance

FRAME_W = 1920
FRAME_H = 1080
NEAR_GEOMETRY = {"install_height_m": 6.0, "pitch_deg": 15.0, "hfov_deg": 60.0}
LONG_RANGE_GEOMETRY = {"install_height_m": 20.0, "pitch_deg": 0.0, "hfov_deg": 20.0}


def _f_px(frame_w: int, hfov_deg: float) -> float:
    return (frame_w / 2.0) / math.tan(math.radians(hfov_deg) / 2.0)


def _size_estimate(frame_w: int, bbox_h: int) -> int:
    """独立按公式算尺寸法期望值，避免测试直接复刻实现细节。"""
    raw = _f_px(frame_w, 20.0) * 25.0 / bbox_h
    raw = min(20000.0, max(1.0, raw))
    return int(round(raw)) if raw < 100 else int(round(raw / 10.0) * 10)


def test_no_geometry_uses_assumed_defaults() -> None:
    result = estimate_distance([900, 600, 100, 80], FRAME_W, FRAME_H, None)
    assert result["method"] == "assumed"
    assert result["size_px"] == 80
    assert result["ratio"] == pytest.approx(80 / FRAME_H)
    assert 1 <= result["meters"] <= 20000


@pytest.mark.parametrize("missing", [None, {}, {"install_height_m": None, "pitch_deg": None, "hfov_deg": None}])
def test_partial_or_missing_geometry_is_assumed(missing) -> None:
    result = estimate_distance([900, 600, 100, 80], FRAME_W, FRAME_H, missing)
    assert result["method"] == "assumed"


@pytest.mark.parametrize(
    ("bbox_h", "band"),
    [
        (27, "超远"),
        (28, "远"),
        (39, "远"),
        (40, "中"),
        (99, "中"),
        (100, "近"),
        (160, "近"),
    ],
)
def test_band_thresholds(bbox_h: int, band: str) -> None:
    result = estimate_distance([100, 200, 120, bbox_h], FRAME_W, FRAME_H, None)
    assert result["size_px"] == bbox_h
    assert result["band"] == band


def test_ratio_is_bbox_height_over_frame_height() -> None:
    result = estimate_distance([0, 100, 200, 270], FRAME_W, FRAME_H, None)
    assert result["ratio"] == pytest.approx(0.25)


def test_geometry_method_and_nearer_box_has_smaller_distance() -> None:
    # 画面中越靠下的框离相机越近（同一地面平面）。
    lower = estimate_distance([900, 900, 100, 80], FRAME_W, FRAME_H, NEAR_GEOMETRY)
    higher = estimate_distance([900, 570, 100, 80], FRAME_W, FRAME_H, NEAR_GEOMETRY)
    assert lower["method"] == "geometry"
    assert higher["method"] == "geometry"
    assert lower["meters"] < higher["meters"]


def test_horizon_falls_back_to_size_method() -> None:
    # pitch=0 且框底在画面中心上方，pitch+theta <= 1°，只能走尺寸法。
    result = estimate_distance([900, 0, 100, 40], FRAME_W, FRAME_H, LONG_RANGE_GEOMETRY)
    assert result["method"] == "geometry"
    assert result["meters"] == _size_estimate(FRAME_W, 40) == 3400


TOWER_GEOMETRY = {"install_height_m": 20.0, "pitch_deg": 10.0, "hfov_deg": 20.0}


def test_ground_distance_is_used_when_trustworthy() -> None:
    # 20 m 塔杆、10° 俯角、20° 视场角：画面 80% 处的 120 px 目标走地面法，约 84 m。
    result = estimate_distance([800, 744, 240, 120], FRAME_W, FRAME_H, TOWER_GEOMETRY)
    assert result["method"] == "geometry"
    assert 2 <= result["meters"] <= 300
    assert 70 <= result["meters"] <= 100


def test_horizon_rule_falls_back_to_size_method() -> None:
    # 框底贴近画面中心（pitch+theta <= 1°）时地面法失效，改用尺寸法。
    # 框底 600 px（中心下方 60 px ≈ 0.63°），theta 与 pitch 之和 <= 1°。
    result = estimate_distance([900, 520, 100, 80], FRAME_W, FRAME_H, LONG_RANGE_GEOMETRY)
    assert result["meters"] == _size_estimate(FRAME_W, 80)


def test_size_method_is_monotonic_with_box_height_at_horizon() -> None:
    meters = [
        estimate_distance([900, 100, 100, h], FRAME_W, FRAME_H, LONG_RANGE_GEOMETRY)["meters"]
        for h in (200, 80, 40, 28)
    ]
    assert meters == sorted(meters)
    assert len(set(meters)) == len(meters)
    assert meters[-1] >= 4000


def test_clamping_to_min_and_max() -> None:
    # 贴地平线时尺寸法给出超大/超小原始值，最终必须落在 [1, 20000]。
    far = estimate_distance([0, 0, 80, 1], FRAME_W, FRAME_H, LONG_RANGE_GEOMETRY)
    near = estimate_distance([0, 100, 80, 200000], FRAME_W, FRAME_H, LONG_RANGE_GEOMETRY)
    assert far["meters"] == 20000
    assert near["meters"] == 1


def test_rounding_below_100m_is_whole_metres_above_is_tens() -> None:
    # 尺寸法 1701.4 m -> 1700；地面法约 83.8 m -> 84。
    horizon = estimate_distance([900, 0, 100, 80], FRAME_W, FRAME_H, LONG_RANGE_GEOMETRY)
    ground = estimate_distance([800, 744, 240, 120], FRAME_W, FRAME_H, TOWER_GEOMETRY)
    assert horizon["meters"] == 1700
    assert ground["meters"] % 10 != 0 or ground["meters"] < 100
    assert ground["meters"] == round(ground["meters"])
