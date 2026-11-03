"""基于单目画面的距离估算：地面平面几何 + 目标尺寸反演。

纯函数模块，只依赖标准库，便于在无 torch/cv2 的环境里做单元测试。

几何参数按设备类型预设解析：**显式数值 > 预设 > 手机手持默认**。预设为
``(安装高度 m, 俯角 °, 水平视场角 °)``::

    phone_handheld   1.5, 12.0, 66.0   # 默认（演示素材就是手机视频）
    phone_mounted    1.5,  5.0, 66.0
    tower_telephoto 20.0,  5.0, 20.0
    custom           使用数据库里存着的三个数值

公式::

    f_px      = (frame_w / 2) / tan(hfov_deg / 2)
    theta     = atan((y_bottom - frame_h / 2) / f_px)   # 正值在画面中心下方
    d_ground  = install_height_m / tan(pitch_deg + theta)  # 仅 pitch+theta > 1° 时有效
    d_size    = f_px * target_height_m / bbox_height_px

目标高度假设：烟柱 25 m，火焰 5 m（火苗远低于烟柱，用 25 m 会把近处火情
放成几百米）。

选取规则（按顺序执行）::

* 近距离：框高占画面 >= 25% -> 取 ``d_ground``（无效则 ``d_size``），且结果
  不超过 ``d_ground * 1.5``；
* 远场：框底在画面上方 45% 区域、``pitch + theta <= 1°``，或框高 < 40 px
  （平台的实测远/超远档）-> 取 ``d_size``；
* 其余（画面中部）：地面法与尺寸法都有效且相差 2 倍以内 -> 取 ``d_ground``；
  相差超过 2 倍 -> 取较小值（避免把近处目标算成几百米）。

最终距离夹在 ``[1, 20000]`` m；100 m 以下取整米，100 m 及以上取整十米。
``method`` 表示用了哪种几何方法（``ground`` / ``size``），``source`` 表示几何
参数来源（``geometry`` / ``preset`` / ``default``）。``band`` 只依据实测框高，
阈值 28 / 40 / 100 px 来自平台的实测可靠下限。
"""

from __future__ import annotations

import math
from typing import Any

DEFAULT_PRESET = "phone_handheld"

# 预设名 -> (安装高度 m, 俯角 °, 水平视场角 °)。custom 不在这里：
# 它表示“只认数据库里存的数值”，缺失的字段回落到手机手持默认。
PRESETS: dict[str, tuple[float, float, float]] = {
    "phone_handheld": (1.5, 12.0, 66.0),
    "phone_mounted": (1.5, 5.0, 66.0),
    "tower_telephoto": (20.0, 5.0, 20.0),
}
PRESET_NAMES: tuple[str, ...] = (*PRESETS, "custom")

# 目标高度假设（米）：烟柱远高于火焰。
TARGET_HEIGHT_M: dict[str, float] = {"smoke": 25.0, "fire": 5.0}
DEFAULT_TARGET_HEIGHT_M = TARGET_HEIGHT_M["smoke"]

CLOSE_RATIO = 0.25  # 框高 / 画面高 >= 25% 视为近距离
CLOSE_MAX_FACTOR = 1.5  # 近距离结果不超过 d_ground * 1.5
FAR_BOTTOM_RATIO = 0.45  # 框底在画面上方 45% 区域视为远场
MIN_GROUND_ANGLE_DEG = 1.0  # pitch + theta 大于该值地面法才有效
FAR_BOX_PX = 40  # 低于该框高属于实测远/超远档，直接走尺寸法

MIN_METERS = 1
MAX_METERS = 20000


def _band(size_px: int) -> str:
    if size_px >= 100:
        return "近"
    if size_px >= 40:
        return "中"
    if size_px >= 28:
        return "远"
    return "超远"


def _as_number(
    value: Any,
    *,
    low: float,
    high: float,
    low_inclusive: bool = True,
) -> float | None:
    """把显式参数转成有限浮点数；非法值返回 None（交给预设/默认值兜底）。"""
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    if number < low or number > high:
        return None
    if not low_inclusive and number <= low:
        return None
    return number


def _resolve_geometry(
    geometry: dict[str, Any] | None,
) -> tuple[float, float, float, str]:
    """解析 (安装高度, 俯角, 水平视场角, 来源)。

    * 三个显式数值任意一个有效即视为 ``geometry``（逐字段覆盖预设）；
    * 否则有效预设给出 ``preset``；
    * 都没有则用 ``phone_handheld`` 默认，来源 ``default``。
    """
    preset_name: str | None = None
    explicit: dict[str, float | None] = {
        "install_height_m": None,
        "pitch_deg": None,
        "hfov_deg": None,
    }

    if isinstance(geometry, dict):
        raw_preset = geometry.get("preset")
        if isinstance(raw_preset, str) and raw_preset in PRESETS:
            preset_name = raw_preset
        explicit["install_height_m"] = _as_number(
            geometry.get("install_height_m"), low=0.0, high=1000.0, low_inclusive=False
        )
        explicit["pitch_deg"] = _as_number(
            geometry.get("pitch_deg"), low=0.0, high=89.0
        )
        explicit["hfov_deg"] = _as_number(
            geometry.get("hfov_deg"), low=0.0, high=180.0, low_inclusive=False
        )

    base = PRESETS[preset_name] if preset_name else PRESETS[DEFAULT_PRESET]
    values = [
        base[0] if explicit["install_height_m"] is None else explicit["install_height_m"],
        base[1] if explicit["pitch_deg"] is None else explicit["pitch_deg"],
        base[2] if explicit["hfov_deg"] is None else explicit["hfov_deg"],
    ]

    if any(value is not None for value in explicit.values()):
        source = "geometry"
    elif preset_name:
        source = "preset"
    else:
        source = "default"
    return float(values[0]), float(values[1]), float(values[2]), source


def _agree_within(a: float, b: float, factor: float = 2.0) -> bool:
    """两个距离估计是否相差不超过 factor 倍。"""
    smaller = min(a, b)
    if smaller <= 0:
        return False
    return max(a, b) <= factor * smaller


def estimate_distance(
    bbox: list[int],
    frame_w: int,
    frame_h: int,
    geometry: dict[str, Any] | None = None,
    *,
    alarm_type: str = "smoke",
) -> dict[str, Any]:
    """估算一个检测框到相机的距离（米）。

    ``bbox`` 为 YOLO 的 ``[x, y, w, h]``（像素）；``geometry`` 可带 ``preset`` 与
    三个显式数值；``alarm_type`` 取 ``fire`` / ``smoke``，决定目标高度假设
    （默认按烟柱 25 m）。返回::

        {"meters": int, "band": str, "size_px": int, "ratio": float,
         "method": "ground" | "size", "source": "geometry" | "preset" | "default"}

    ``ratio`` 是框高 / 画面高，用于前端判断远近；不参与距离计算。
    """
    x, y, _w, box_h = (float(v) for v in bbox[:4])
    fw = max(1.0, float(frame_w))
    fh = max(1.0, float(frame_h))
    size_px = max(0, int(round(box_h)))
    ratio = box_h / fh
    y_bottom = y + box_h

    install, pitch, hfov, source = _resolve_geometry(geometry)
    f_px = (fw / 2.0) / math.tan(math.radians(hfov) / 2.0)
    theta = math.atan((y_bottom - fh / 2.0) / f_px)
    combined_deg = pitch + math.degrees(theta)

    target_height = TARGET_HEIGHT_M.get(
        str(alarm_type or "").strip().lower(), DEFAULT_TARGET_HEIGHT_M
    )
    d_size = f_px * target_height / max(1.0, box_h)

    # 地面法只在交点落在相机前方且结果为正时有效。
    ground_valid = MIN_GROUND_ANGLE_DEG < combined_deg < 90.0
    d_ground = install / math.tan(math.radians(combined_deg)) if ground_valid else math.inf

    if ratio >= CLOSE_RATIO:
        # 大框 = 近处目标：地面平面最可信；地面法失效（贴地平线）才退回尺寸法。
        if ground_valid:
            method = "ground"
            raw = min(d_ground, d_ground * CLOSE_MAX_FACTOR)
        else:
            method = "size"
            raw = d_size
    elif (
        y_bottom <= fh * FAR_BOTTOM_RATIO
        or combined_deg <= MIN_GROUND_ANGLE_DEG
        or size_px < FAR_BOX_PX
    ):
        # 远场：框底靠近画面顶部/地平线，或框小到属于实测远档，尺寸法更可信。
        method = "size"
        raw = d_size
    elif ground_valid and _agree_within(d_ground, d_size):
        method = "ground"
        raw = d_ground
    else:
        # 画面中部且两种方法矛盾：取较小值，避免“近处火情算成几百米”。
        if ground_valid and d_ground < d_size:
            method = "ground"
            raw = d_ground
        else:
            method = "size"
            raw = d_size

    if not math.isfinite(raw):
        raw = float(MAX_METERS)
    value = min(float(MAX_METERS), max(float(MIN_METERS), raw))
    meters = int(round(value)) if value < 100 else int(round(value / 10.0) * 10)
    meters = min(MAX_METERS, max(MIN_METERS, meters))

    return {
        "meters": meters,
        "band": _band(size_px),
        "size_px": size_px,
        "ratio": ratio,
        "method": method,
        "source": source,
    }
