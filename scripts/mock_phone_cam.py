"""本机模拟 IP Webcam 的 MJPEG 推流服务，用于在没有安卓手机时联调手机接入向导。

用法：
    ai\\.venv\\Scripts\\python scripts\\mock_phone_cam.py [视频文件] [端口]

启动后在向导第 3 步填入 `127.0.0.1:8080`（或本机局域网 IP:8080）即可走完整流程。
"""

from __future__ import annotations

import glob
import os
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import cv2


def pick_video() -> str:
    if len(sys.argv) > 1:
        return sys.argv[1]
    candidates = sorted(glob.glob("storage/uploads/*.mp4")) + sorted(glob.glob("storage/uploads/*.mov"))
    if not candidates:
        raise SystemExit("storage/uploads/ 下没有可用的 mp4/mov，请先上传演示视频或直接传入文件路径")
    return candidates[-1]


VIDEO = pick_video()
PORT = int(sys.argv[2]) if len(sys.argv) > 2 else 8080


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        print("%s - %s" % (self.address_string(), fmt % args), flush=True)

    def do_GET(self):
        if self.path.rstrip("/") not in ("/video", ""):
            self.send_error(404, "not found")
            return
        self.send_response(200)
        self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        cap = cv2.VideoCapture(VIDEO)
        try:
            while True:
                ok, frame = cap.read()
                if not ok:
                    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                    continue
                ok, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
                if not ok:
                    continue
                try:
                    self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + buf.tobytes() + b"\r\n")
                except (BrokenPipeError, ConnectionResetError):
                    break
                time.sleep(0.1)
        finally:
            cap.release()


if __name__ == "__main__":
    print("mock phone cam on 0.0.0.0:%d serving %s" % (PORT, os.path.abspath(VIDEO)), flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
