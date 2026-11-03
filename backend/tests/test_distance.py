"""单目测距纯函数测试：无需 torch/cv2，可无头运行。"""

from __future__ import annotations

import math

import pytest

from backend.app.distance import estimate_distance

FRAME_W = 1920
FRAME_H = 1080
# 演示素材是手机视频，不做任何配置时必须回落到手机手持几何。
PHONE_DEFAULT = None
TOWER_PRESET = {"preset": "tower_telephoto"}


def _f_px(frame_w: int, hfov_deg: float) -> float:
    return (frame_w / 2.0) / math.tan(math.radians(hfov_deg) / 2.0)


def _round_m(raw: float) -> int:
    raw = min(20000.0, max(1.0, raw))
    return int(round(raw)) if raw < 100 else int(round(raw / 10.0) * 10)


def _size_estimate(frame_w: int, bbox_h: int, hfov_deg: float = 66.0, target_m: float = 25.0) -> int:
    """独立按尺寸法公式算期望值，避免测试直接复刻实现细节。"""
    return _round_m(_f_px(frame_w, hfov_deg) * target_m / bbox_h)


def _bbox(bottom_pct: float, height: int) -> list[int]:
    """构造一个框底落在画面 ``bottom_pct`` 处、指定高度的检测框。"""
    y_bottom = int(round(FRAME_H * bottom_pct))
    return [800, y_bottom - height, 240, height]


def test_no_geometry_falls_back_to_phone_default() -> None:
    result = estimate_distance([900, 600, 100, 80], FRAME_W, FRAME_H, None)
    assert result["source"] == "default"
    assert result["method"] in {"ground", "size"}
    assert result["size_px"] == 80
    assert result["ratio"] == pytest.approx(80 / FRAME_H)
    assert 1 <= result["meters"] <= 20000


@pytest.mark.parametrize(
    "geometry",
    [
        {},
        {"preset": None, "install_height_m": None, "pitch_deg": None, "hfov_deg": None},
        {"preset": "custom"},
        {"preset": "unknown_preset"},
    ],
)
def test_empty_or_unknown_geometry_uses_default_source(geometry) -> None:
    result = estimate_distance([900, 600, 100, 80], FRAME_W, FRAME_H, geometry)
    assert result["source"] == "default"


@pytest.mark.parametrize("geometry", [
    {"install_height_m": "abc", "pitch_deg": "abc", "hfov_deg": "abc"},
    {"install_height_m": -1.0, "pitch_deg": -1.0, "hfov_deg": 0.0},
    {"install_height_m": float("nan"), "pitch_deg": float("inf"), "hfov_deg": float("nan")},
])
def test_invalid_numeric_geometry_falls_back_to_default(geometry) -> None:
    result = estimate_distance([900, 600, 100, 80], FRAME_W, FRAME_H, geometry)
    assert result["source"] == "default"


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


def test_phone_default_close_big_box_is_under_20m() -> None:
    # 框高占画面 40%、框底在 95%：目标就在眼前，绝不能算成几百米。
    box_h = int(FRAME_H * 0.40)
    bbox = _bbox(0.95, box_h)
    result = estimate_distance(bbox, FRAME_W, FRAME_H, PHONE_DEFAULT)
    assert result["method"] == "ground"
    assert result["meters"] < 20
    assert result["band"] == "近"
    assert result["source"] == "default"


def test_phone_default_small_far_box_is_hundreds_of_metres() -> None:
    # 28 px 框、框底刚过画面中心：这是远景小目标，必须走尺寸法而不是地面法。
    bbox = [900, 532, 120, 28]  # 框底 560 px，刚过中心 540 px
    result = estimate_distance(bbox, FRAME_W, FRAME_H, PHONE_DEFAULT)
    assert result["method"] == "size"
    assert result["band"] == "远"
    assert 400 < result["meters"] < 1400
    assert result["meters"] == _size_estimate(FRAME_W, 28)


def test_tower_preset_small_box_still_yields_kilometres() -> None:
    # 塔杆长焦沿用旧的远景量级：28 px 目标仍是数公里，而不是几百米。
    bbox = [900, 532, 120, 28]
    result = estimate_distance(bbox, FRAME_W, FRAME_H, TOWER_PRESET)
    assert result["source"] == "preset"
    assert result["method"] == "size"
    assert result["meters"] >= 3000


def test_mid_frame_disagreement_takes_smaller_estimate() -> None:
    # 画面中部的 200 px 框：地面法约 5 m，尺寸法约 185 m，矛盾时取小的。
    bbox = _bbox(0.60, 200)
    result = estimate_distance(bbox, FRAME_W, FRAME_H, PHONE_DEFAULT)
    assert result["method"] == "ground"
    assert result["meters"] <= 10


def test_mid_frame_agreement_uses_ground_method() -> None:
    # 40 m 高、3° 俯角、60° 视场角：两法都约 470–520 m，一致时用地面法。
    geometry = {"install_height_m": 40.0, "pitch_deg": 3.0, "hfov_deg": 60.0}
    bbox = _bbox(0.55, 80)
    result = estimate_distance(bbox, FRAME_W, FRAME_H, geometry)
    assert result["method"] == "ground"
    assert result["source"] == "geometry"
    assert 400 <= result["meters"] <= 550


def test_upper_frame_box_uses_size_method() -> None:
    bbox = _bbox(0.45, 80)  # 框底正好落在画面上方 45% 边界
    result = estimate_distance(bbox, FRAME_W, FRAME_H, PHONE_DEFAULT)
    assert result["method"] == "size"
    assert result["meters"] == _size_estimate(FRAME_W, 80)


def test_horizon_rule_uses_size_method() -> None:
    # pitch=0 且框底贴近画面中心 -> pitch+theta <= 1°，地面交点不可靠。
    geometry = {"install_height_m": 1.5, "pitch_deg": 0.0, "hfov_deg": 66.0}
    bbox = [800, 505, 240, 40]  # 框底 545 px，中心下方 5 px
    result = estimate_distance(bbox, FRAME_W, FRAME_H, geometry)
    assert result["method"] == "size"
    assert result["meters"] == _size_estimate(FRAME_W, 40)


@pytest.mark.parametrize("bottom", [560, 648])
def test_fire_target_height_is_shorter_than_smoke(bottom: int) -> None:
    # 同一 28 px 框：火焰按 5 m、烟柱按 25 m 反演，火必须比烟近。
    bbox = [900, bottom - 28, 120, 28]
    fire = estimate_distance(bbox, FRAME_W, FRAME_H, PHONE_DEFAULT, alarm_type="fire")
    smoke = estimate_distance(bbox, FRAME_W, FRAME_H, PHONE_DEFAULT, alarm_type="smoke")
    assert fire["method"] == smoke["method"] == "size"
    assert fire["meters"] < smoke["meters"]
    assert smoke["meters"] == pytest.approx(_size_estimate(FRAME_W, 28), rel=0.01)
    assert fire["meters"] == pytest.approx(_size_estimate(FRAME_W, 28, target_m=5.0), rel=0.01)


@pytest.mark.parametrize(
    ("geometry", "expected_source"),
    [
        ({"install_height_m": 20.0, "pitch_deg": 5.0, "hfov_deg": 20.0}, "geometry"),
        ({"preset": "tower_telephoto"}, "preset"),
        ({"preset": "phone_mounted"}, "preset"),
        ({"preset": "tower_telephoto", "install_height_m": 20.0, "pitch_deg": 5.0, "hfov_deg": 20.0}, "geometry"),
        (None, "default"),
    ],
)
def test_source_reflects_geometry_priority(geometry, expected_source) -> None:
    result = estimate_distance([900, 600, 100, 80], FRAME_W, FRAME_H, geometry)
    assert result["source"] == expected_source


def test_explicit_numbers_override_preset_values() -> None:
    bbox = [900, 532, 120, 28]
    explicit = {
        "preset": "tower_telephoto",
        "install_height_m": 1.5,
        "pitch_deg": 12.0,
        "hfov_deg": 66.0,
    }
    overridden = estimate_distance(bbox, FRAME_W, FRAME_H, explicit)
    default = estimate_distance(bbox, FRAME_W, FRAME_H, PHONE_DEFAULT)
    assert overridden["source"] == "geometry"
    assert overridden["meters"] == default["meters"]
    assert overridden["meters"] < estimate_distance(bbox, FRAME_W, FRAME_H, TOWER_PRESET)["meters"]


def test_preset_changes_result_from_default_geometry() -> None:
    # 手机固定俯角 5° 比手持 12° 平，同一中部框的地面法距离更大。
    bbox = _bbox(0.60, 80)
    handheld = estimate_distance(bbox, FRAME_W, FRAME_H, PHONE_DEFAULT)
    mounted = estimate_distance(bbox, FRAME_W, FRAME_H, {"preset": "phone_mounted"})
    assert handheld["source"] == "default"
    assert mounted["source"] == "preset"
    assert mounted["meters"] > handheld["meters"]


def test_partial_explicit_field_overrides_preset() -> None:
    geometry = {"preset": "tower_telephoto", "hfov_deg": 66.0}
    result = estimate_distance([900, 532, 120, 28], FRAME_W, FRAME_H, geometry)
    assert result["source"] == "geometry"
    assert result["meters"] == _size_estimate(FRAME_W, 28)


def test_size_method_is_monotonic_with_box_height_far_field() -> None:
    meters = [
        estimate_distance(_bbox(0.45, h), FRAME_W, FRAME_H, PHONE_DEFAULT)["meters"]
        for h in (200, 80, 40, 28)
    ]
    assert meters == sorted(meters)
    assert len(set(meters)) == len(meters)
    assert meters[-1] >= 1000


def test_lower_close_box_is_nearer() -> None:
    lower = estimate_distance(_bbox(0.95, 80), FRAME_W, FRAME_H, PHONE_DEFAULT)
    higher = estimate_distance(_bbox(0.60, 80), FRAME_W, FRAME_H, PHONE_DEFAULT)
    assert lower["meters"] < higher["meters"]


def test_clamping_to_min_and_max() -> None:
    far = estimate_distance([0, 0, 80, 1], FRAME_W, FRAME_H, PHONE_DEFAULT)
    near = estimate_distance([0, 100, 80, 200000], FRAME_W, FRAME_H, PHONE_DEFAULT)
    assert far["meters"] == 20000
    assert near["meters"] == 1


def test_rounding_below_100m_is_whole_metres_above_is_tens() -> None:
    far = estimate_distance([900, 532, 120, 28], FRAME_W, FRAME_H, PHONE_DEFAULT)
    close = estimate_distance(_bbox(0.95, 432), FRAME_W, FRAME_H, PHONE_DEFAULT)
    assert far["meters"] == 1320
    assert far["meters"] % 10 == 0
    assert close["meters"] < 100
    assert close["meters"] == round(close["meters"])
