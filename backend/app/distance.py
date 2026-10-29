"""基于单目画面的距离估算：地面平面几何 + 目标尺寸反演。

纯函数模块，只依赖标准库，便于在无 torch/cv2 的环境里做单元测试。

公式（默认参数为远景长焦机位：20 m 高 / 10° 俯角 / 20° 视场角）::

    f_px      = (frame_w / 2) / tan(hfov_deg / 2)
    theta     = atan((y_bottom - frame_h / 2) / f_px)   # 正值在画面中心下方
    d_ground  = install_height_m / tan(pitch_deg + theta)
    d_size    = f_px * 25.0 / bbox_height_px            # 烟柱按 25 m 高假设

选择规则：

* ``pitch_deg + theta <= 1°``（目标贴近/高于地平线）→ 用 ``d_size``；
* 否则地面法结果落在 2–300 m 内 → 用 ``d_ground``（近处地面平面可信）；
* 其余情况 → 用 ``d_size``。

最终距离夹在 [1, 20000] m；100 m 以下取整米，100 m 及以上取整十米。
``method`` 只有在三个相机安装参数都真实提供时才为 ``geometry``，否则为
``assumed``（只要有参数缺失就说明用了默认值）。``band`` 依据实测框高，
不使用距离反推，阈值 28 / 40 / 100 px 来自平台的实测可靠下限。
"""

from __future__ import annotations

import math
from typing import Any

DEFAULT_INSTALL_HEIGHT_M = 20.0
DEFAULT_PITCH_DEG = 10.0
DEFAULT_HFOV_DEG = 20.0
ASSUMED_TARGET_HEIGHT_M = 25.0
GROUND_MIN_M = 2.0
GROUND_MAX_M = 300.0
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


def _resolve_geometry(geometry: dict[str, Any] | None) -> tuple[float, float, float, bool]:
    """返回 (安装高度, 俯角, 水平视场角, 是否使用默认值)。

    三个参数必须同时有效才视为真实几何；缺一个就用默认值并标记 assumed。
    """
    if isinstance(geometry, dict):
        try:
            install = float(geometry["install_height_m"])
            pitch = float(geometry["pitch_deg"])
            hfov = float(geometry["hfov_deg"])
        except (KeyError, TypeError, ValueError):
            pass
        else:
            if (
                math.isfinite(install)
                and math.isfinite(pitch)
                and math.isfinite(hfov)
                and install > 0
                and 0.0 <= pitch < 90.0
                and 0.0 < hfov < 180.0
            ):
                return install, pitch, hfov, False
    return DEFAULT_INSTALL_HEIGHT_M, DEFAULT_PITCH_DEG, DEFAULT_HFOV_DEG, True


def estimate_distance(
    bbox: list[int],
    frame_w: int,
    frame_h: int,
    geometry: dict[str, Any] | None,
) -> dict[str, Any]:
    """估算一个检测框到相机的距离（米）。

    ``bbox`` 为 YOLO 的 ``[x, y, w, h]``（像素）。返回::

        {"meters": int, "band": str, "size_px": int,
         "method": "geometry" | "assumed", "ratio": float}

    ``ratio`` 是框高 / 画面高，用于前端判断远近；不参与距离计算。
    """
    x, y, _w, box_h = (float(v) for v in bbox[:4])
    fw = max(1.0, float(frame_w))
    fh = max(1.0, float(frame_h))
    size_px = max(0, int(round(box_h)))
    ratio = box_h / fh

    install, pitch, hfov, assumed = _resolve_geometry(geometry)
    f_px = (fw / 2.0) / math.tan(math.radians(hfov) / 2.0)
    y_bottom = y + box_h
    theta = math.atan((y_bottom - fh / 2.0) / f_px)
    combined_deg = pitch + math.degrees(theta)

    d_size = f_px * ASSUMED_TARGET_HEIGHT_M / max(1.0, box_h)
    if combined_deg <= 1.0:
        # 目标贴近/高于地平线，地面交点不可靠，只能按目标尺寸反演。
        raw = d_size
    else:
        d_ground = install / math.tan(math.radians(pitch) + theta)
        raw = d_ground if GROUND_MIN_M <= d_ground <= GROUND_MAX_M else d_size

    if not math.isfinite(raw):
        raw = float(MAX_METERS)
    value = min(float(MAX_METERS), max(float(MIN_METERS), raw))
    meters = int(round(value)) if value < 100 else int(round(value / 10.0) * 10)
    meters = min(MAX_METERS, max(MIN_METERS, meters))

    return {
        "meters": meters,
        "band": _band(size_px),
        "size_px": size_px,
        "method": "assumed" if assumed else "geometry",
        "ratio": ratio,
    }
