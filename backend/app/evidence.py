"""证据图渲染：把 Worker 真实采集的帧画成可给检查人看的现场证据。

本模块是纯函数集合：输入 numpy 帧 / Worker 留档数据，输出 JPEG bytes，
不依赖 FastAPI 或数据库，方便在测试里用合成帧直接验证。
图片主体永远来自真实采集字节；文字条只负责说明，不会凭空生成画面。
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

JPEG_QUALITY = 82
_THUMB_QUALITY = 82

# PIL 用 RGB，OpenCV 用 BGR；这里只定义文字条配色
_BAR_BG_RGB = (26, 31, 39)
_BAR_FG_RGB = (238, 242, 246)
_BAR_ACCENT_RGB = (217, 126, 48)
_BAR_HEIGHT = 36
_BAR_FONT_SIZE = 18
_LABEL_HEIGHT = 26
_LABEL_FONT_SIZE = 13

# OpenCV 图层颜色（BGR）
_FIRE_COLOR = (56, 64, 232)
_SMOKE_COLOR = (40, 165, 250)
_TILE_COLOR = (220, 176, 60)
_MERGED_COLOR = (88, 196, 96)

_FONT_PATHS = (
    Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts" / "msyh.ttc",
    Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts" / "msyhbd.ttc",
    Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts" / "simhei.ttf",
    Path("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"),
    Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
)


@lru_cache(maxsize=8)
def _font(size: int) -> ImageFont.ImageFont:
    """优先用系统中文字体，缺失时退回 Pillow 默认字体（不阻断出图）。"""
    for path in _FONT_PATHS:
        try:
            if path.is_file():
                return ImageFont.truetype(str(path), size)
        except OSError:
            continue
    return ImageFont.load_default()


def _text_width(text: str, font: ImageFont.ImageFont) -> int:
    canvas = Image.new("L", (1, 1))
    try:
        return int(ImageDraw.Draw(canvas).textlength(text, font=font))
    except Exception:  # noqa: BLE001 - 默认字体可能不支持测量
        return int(len(text) * getattr(font, "size", 16) * 0.62)


def _banner(
    width: int,
    text: str,
    *,
    height: int = _BAR_HEIGHT,
    size: int = _BAR_FONT_SIZE,
    bg: tuple[int, int, int] = _BAR_BG_RGB,
    fg: tuple[int, int, int] = _BAR_FG_RGB,
    accent: tuple[int, int, int] | None = _BAR_ACCENT_RGB,
) -> np.ndarray:
    width = max(1, int(width))
    image = Image.new("RGB", (width, height), bg)
    draw = ImageDraw.Draw(image)
    if accent is not None:
        draw.rectangle([0, 0, 3, height], fill=accent)
    font = _font(size)
    x = 14
    try:
        box = draw.textbbox((x, 0), text, font=font)
        text_height = box[3] - box[1]
        y = (height - text_height) / 2 - box[1]
        draw.text((x, y), text, font=font, fill=fg)
    except Exception:  # noqa: BLE001 - 极端情况下退回固定基线
        draw.text((x, max(0, (height - size) // 2)), text, font=font, fill=fg)
    return cv2.cvtColor(np.array(image), cv2.COLOR_RGB2BGR)


def _as_bgr(frame: np.ndarray) -> np.ndarray:
    if frame.ndim == 2:
        return cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)
    return frame


def _with_header(
    frame: np.ndarray,
    text: str,
    *,
    height: int = _BAR_HEIGHT,
    size: int = _BAR_FONT_SIZE,
    bg: tuple[int, int, int] = _BAR_BG_RGB,
    accent: tuple[int, int, int] | None = _BAR_ACCENT_RGB,
) -> np.ndarray:
    """在图片顶部加说明条；说明文字比图片宽时向右补黑边，不裁掉原文。"""
    frame = _as_bgr(frame)
    banner_width = max(frame.shape[1], _text_width(text, _font(size)) + 28)
    banner = _banner(banner_width, text, height=height, size=size, bg=bg, accent=accent)
    if frame.shape[1] < banner_width:
        pad = np.zeros((frame.shape[0], banner_width - frame.shape[1], 3), dtype=np.uint8)
        frame = cv2.hconcat([frame, pad])
    return cv2.vconcat([banner, frame])


def encode_jpeg(frame: np.ndarray, quality: int = JPEG_QUALITY) -> bytes:
    ok, buffer = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), int(quality)])
    if not ok:
        raise ValueError("JPEG 编码失败")
    return buffer.tobytes()


def decode_jpeg(data: bytes | None) -> np.ndarray | None:
    if not data:
        return None
    buffer = np.frombuffer(data, dtype=np.uint8)
    if buffer.size == 0:
        return None
    return cv2.imdecode(buffer, cv2.IMREAD_COLOR)


def _label(canvas: np.ndarray, text: str, x: int, y: int, color: tuple[int, int, int]) -> None:
    """在检测框上方绘制小号标签，保证低置信度候选也看得清。"""
    font = cv2.FONT_HERSHEY_SIMPLEX
    scale, thickness = 0.38, 1
    (text_w, text_h), _base = cv2.getTextSize(text, font, scale, thickness)
    top = max(0, int(y) - text_h - 5)
    left = max(0, int(x))
    cv2.rectangle(canvas, (left, top), (left + text_w + 4, top + text_h + 5), color, -1)
    cv2.putText(canvas, text, (left + 2, top + text_h + 2), font, scale, (255, 255, 255), thickness, cv2.LINE_AA)


def render_detect(frame: np.ndarray, objects: list[dict[str, Any]]) -> bytes:
    """感知证据：原始帧 + 每个候选的 1px 细框（含低置信度候选）。"""
    canvas = _as_bgr(frame).copy()
    for item in objects:
        x, y, w, h = (int(round(float(value))) for value in item.get("bbox", [0, 0, 0, 0]))
        color = _FIRE_COLOR if item.get("type") == "fire" else _SMOKE_COLOR
        cv2.rectangle(canvas, (x, y), (x + w, y + h), color, 1)
        _label(canvas, f"{item.get('type', '?')} {float(item.get('confidence', 0.0)):.2f}", x, y, color)
    top = max((float(item.get("confidence", 0.0)) for item in objects), default=0.0)
    return encode_jpeg(_with_header(canvas, f"候选 {len(objects)} 个 · 最高 {top:.2f}"))


def render_tiles(
    frame: np.ndarray,
    tiles: list[Any],
    merged: list[dict[str, Any]],
    tile_size: int,
    overlap: float,
) -> bytes:
    """远场证据：原始帧 + 实际切片网格与编号 + 跨片合并后的绿色框。"""
    canvas = _as_bgr(frame).copy()
    for index, tile in enumerate(tiles, start=1):
        x, y = int(tile.x), int(tile.y)
        tile_h, tile_w = tile.image.shape[:2]
        cv2.rectangle(canvas, (x, y), (x + tile_w - 1, y + tile_h - 1), _TILE_COLOR, 1)
        label = f"T{index}"
        cv2.putText(canvas, label, (x + 6, y + 20), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (18, 22, 28), 2, cv2.LINE_AA)
        cv2.putText(canvas, label, (x + 6, y + 20), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)
    for item in merged:
        x, y, w, h = (int(round(float(value))) for value in item.get("bbox", [0, 0, 0, 0]))
        cv2.rectangle(canvas, (x, y), (x + w, y + h), _MERGED_COLOR, 2)
        _label(canvas, f"{item.get('type', '?')} {float(item.get('confidence', 0.0)):.2f}", x, y, _MERGED_COLOR)
    overlap_pct = round(float(overlap) * 100)
    header = f"瓦片 {int(tile_size)} · 重叠 {overlap_pct}% · {len(tiles)} 片 · 合并后 {len(merged)} 个"
    return encode_jpeg(_with_header(canvas, header))


def render_verify(image: np.ndarray, verify: dict[str, Any]) -> bytes:
    """复核证据：真实裁剪放大图 + 复核结论条（阈值、置信度、通过/拦截）。"""
    passed = bool(verify.get("passed"))
    confidence = float(verify.get("confidence") or 0.0)
    threshold = float(verify.get("threshold") or 0.0)
    relation = "≥" if passed else "<"
    verdict = "通过" if passed else "拦截"
    text = f"复核 {confidence:.2f} {relation} 阈值 {threshold:.2f} → {verdict}"
    bg = (26, 52, 36) if passed else (56, 27, 29)
    accent = (52, 168, 96) if passed else (214, 74, 74)
    return encode_jpeg(_with_header(image, text, height=40, size=19, bg=bg, accent=accent))


def render_films(frames: list[dict[str, Any]]) -> bytes:
    """时序证据：把最近留档的原始缩略图横向拼接，每帧标注时间与烟雾分。"""
    tiles: list[np.ndarray] = []
    for item in frames:
        image = decode_jpeg(item.get("jpeg"))
        if image is None:
            continue
        label = f"{item.get('ts') or ''} · 烟雾 {float(item.get('smoke') or 0.0):.2f}"
        tiles.append(_with_header(image, label, height=_LABEL_HEIGHT, size=_LABEL_FONT_SIZE))
    if not tiles:
        raise ValueError("没有可用的证据帧")
    height = min(tile.shape[0] for tile in tiles)
    normalized: list[np.ndarray] = []
    for tile in tiles:
        if tile.shape[0] != height:
            width = max(1, int(tile.shape[1] * height / tile.shape[0]))
            tile = cv2.resize(tile, (width, height), interpolation=cv2.INTER_AREA)
        normalized.append(tile)
    gap = np.full((height, 3, 3), (28, 33, 40), dtype=np.uint8)
    parts: list[np.ndarray] = []
    for index, tile in enumerate(normalized):
        if index:
            parts.append(gap)
        parts.append(tile)
    return encode_jpeg(cv2.hconcat(parts), quality=_THUMB_QUALITY)
