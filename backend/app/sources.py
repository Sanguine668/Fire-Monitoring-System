"""视频源打开与网络源判定的公共逻辑。"""

from __future__ import annotations

import cv2

OPEN_TIMEOUT_MS = 5000
READ_TIMEOUT_MS = 5000
NETWORK_SCHEMES = ("http://", "https://", "rtsp://", "rtmp://", "rtmps://")


def is_network_source(source: str) -> bool:
    return source.strip().lower().startswith(NETWORK_SCHEMES)


def open_capture(
    source: str,
    open_timeout_ms: int = OPEN_TIMEOUT_MS,
    read_timeout_ms: int = READ_TIMEOUT_MS,
) -> cv2.VideoCapture:
    """打开视频源；网络源带超时，避免手机断流时线程长时间卡死。

    注意：OPEN/READ 超时属性必须在 open() 之前设置才会生效，
    因此这里先构造空的 VideoCapture、设好属性，再执行 open()。
    """

    cap = cv2.VideoCapture()
    if is_network_source(source):
        cap.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, float(open_timeout_ms))
        cap.set(cv2.CAP_PROP_READ_TIMEOUT_MSEC, float(read_timeout_ms))
    cap.open(source)
    return cap
