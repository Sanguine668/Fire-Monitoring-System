"""视频源打开与网络源判定的公共逻辑。"""

from __future__ import annotations

import urllib.request
from typing import Any

import cv2
import numpy as np

OPEN_TIMEOUT_MS = 5000
READ_TIMEOUT_MS = 5000
NETWORK_SCHEMES = ("http://", "https://", "rtsp://", "rtmp://", "rtmps://")


def is_network_source(source: str) -> bool:
    return source.strip().lower().startswith(NETWORK_SCHEMES)


class SnapshotCapture:
    """把 IP Webcam 的 /shot.jpg 单帧接口包装成可 read() 的采集源。"""

    def __init__(self, url: str, timeout: float = 5.0) -> None:
        self.url = url
        self.timeout = timeout
        self._opened = False

    def isOpened(self) -> bool:  # noqa: N802 - 保持与 cv2.VideoCapture 一致
        return self._opened

    def open(self) -> bool:
        ok, _ = self.read()
        self._opened = ok
        return ok

    def read(self):
        try:
            req = urllib.request.Request(self.url, headers={"User-Agent": "FireGuard/1.0"})
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = resp.read()
            frame = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
            return frame is not None, frame
        except Exception:
            return False, None

    def set(self, *args: Any, **kwargs: Any) -> bool:
        return False

    def release(self) -> None:
        self._opened = False


def open_capture(
    source: str,
    open_timeout_ms: int = OPEN_TIMEOUT_MS,
    read_timeout_ms: int = READ_TIMEOUT_MS,
):
    """打开视频源；网络源带超时，避免手机断流时线程长时间卡死。

    注意：OPEN/READ 超时属性必须在 open() 之前设置才会生效，
    因此这里先构造空的 VideoCapture、设好属性，再执行 open()。
    """

    lower = source.strip().lower()
    if lower.startswith(("http://", "https://")) and "shot.jpg" in lower:
        cap = SnapshotCapture(source, timeout=read_timeout_ms / 1000)
        cap.open()
        return cap

    cap = cv2.VideoCapture()
    if is_network_source(source):
        cap.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, float(open_timeout_ms))
        cap.set(cv2.CAP_PROP_READ_TIMEOUT_MSEC, float(read_timeout_ms))
    cap.open(source)
    return cap
