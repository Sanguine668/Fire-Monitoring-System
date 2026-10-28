"""告警推送：消息渲染、Server酱 通道与去重发送线程。"""

from __future__ import annotations

import queue
import threading
from typing import Any, Callable

import httpx

from . import db

SERVERCHAN_URL = "https://sctapi.ftqq.com/{key}.send"
SEND_TIMEOUT = 10.0
TYPE_LABEL = {"fire": "明火", "smoke": "烟雾"}
LEVEL_LABEL = {"critical": "严重", "warning": "预警"}


def code_label(alarm_type: str) -> str:
    return TYPE_LABEL.get(alarm_type, alarm_type or "未知")


def _clean(text: str) -> str:
    """Server酱 的 title 不允许换行，统一压成单行。"""
    return " ".join(str(text).split())


def render_message(alarm: dict[str, Any], base_url: str = "") -> tuple[str, str]:
    kind = code_label(alarm.get("alarm_type", ""))
    level = LEVEL_LABEL.get(alarm.get("level", ""), alarm.get("level", ""))
    camera = _clean(alarm.get("camera_name") or "") or "未知视频源"
    title = _clean(f"【火情监测】{camera} {kind}告警")
    confidence = float(alarm.get("confidence") or 0) * 100
    count = int(alarm.get("count") or 1)
    created = alarm.get("created_at") or ""
    lines = [
        f"### {kind}告警 · {level}",
        "",
        f"- **监控源**：{camera}",
        f"- **时间**：{created}",
        f"- **置信度**：{confidence:.1f}%",
        f"- **累计次数**：{count} 次",
        "",
    ]
    frame_available = bool(alarm.get("snapshot_first"))
    if base_url and frame_available:
        frame_url = f"{base_url}/api/alarms/{alarm.get('id')}/frame?variant=first"
        lines.append(f"![告警画面]({frame_url})")
        lines.append("")
        lines.append(f"> 打开系统查看：[{base_url}]({base_url}/#/alarms)")
    elif base_url:
        lines.append(f"> 本条告警未留存画面；打开系统查看：[{base_url}]({base_url}/#/alarms)")
    else:
        lines.append("> 未获取到局域网地址，画面请在系统内查看。")
    return title, "\n".join(lines)


class ServerChanChannel:
    """Server酱 Turbo 通道；只做一次 HTTP 请求，异常一律转成结果字典。"""

    def __init__(self, sendkey: str) -> None:
        self.sendkey = sendkey

    def send(self, title: str, desp: str) -> dict[str, Any]:
        """任何异常都转成结果字典，绝不让 /api/notify/test 或推送线程 500。"""
        try:
            url = SERVERCHAN_URL.format(key=self.sendkey)
            resp = httpx.post(url, data={"title": title, "desp": desp}, timeout=SEND_TIMEOUT)
            if resp.status_code == 429:
                return {"ok": False, "code": 429, "message": "调用过于频繁，已被限流（429）"}
            if resp.status_code != 200:
                return {"ok": False, "code": resp.status_code, "message": f"HTTP {resp.status_code}"}
            try:
                payload = resp.json()
            except ValueError:
                return {"ok": False, "code": None, "message": "返回内容不是 JSON"}
            code = int(payload.get("code", -1))
            message = str(payload.get("message") or (payload.get("data") or {}).get("error") or "")
            return {"ok": code == 0, "code": code, "message": message}
        except httpx.HTTPError as exc:
            return {"ok": False, "code": None, "message": f"网络错误：{exc}"}
        except Exception as exc:  # noqa: BLE001
            # InvalidURL（SendKey 含控制字符）、JSON 结构异常等都落到这里
            return {"ok": False, "code": None, "message": f"发送异常：{exc}"}


class Notifier(threading.Thread):
    """后台推送线程：检测线程只入队，网络请求全部在这里发生。"""

    def __init__(
        self,
        base_url_provider: Callable[[], str] | None = None,
        channel_factory: Callable[[str], Any] | None = None,
    ) -> None:
        super().__init__(daemon=True, name="fireguard-notifier")
        self._queue: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=32)
        self._stop_event = threading.Event()
        self._base_url_provider = base_url_provider or (lambda: "")
        self._channel_factory = channel_factory or (lambda key: ServerChanChannel(key))
        self.last_skip = ""

    def enqueue_alarm(self, alarm: dict[str, Any]) -> None:
        try:
            self._queue.put_nowait(alarm)
        except queue.Full:
            self.last_skip = "推送队列已满，本条已丢弃"

    def handle(self, alarm: dict[str, Any]) -> bool:
        cfg = db.get_notify_config()
        if not cfg["enabled"]:
            self.last_skip = "推送未启用"
            return False
        if not cfg["sendkey"]:
            self.last_skip = "未配置 SendKey"
            return False
        if db.notifications_sent_today() >= int(cfg["daily_limit"]):
            self.last_skip = f"已达每日上限 {cfg['daily_limit']} 条"
            return False
        title, desp = render_message(alarm, self._base_url_provider())
        if not db.reserve_notification(
            int(alarm["camera_id"]), int(alarm["id"]), str(alarm.get("alarm_type", "")), title
        ):
            self.last_skip = "该视频源本轮已推送过"
            return False
        db.bump_notify_daily()  # 占位成功后即计一次尝试：发送失败也算用掉额度
        try:
            result = self._channel_factory(cfg["sendkey"]).send(title, desp)
            db.finish_notification(
                int(alarm["camera_id"]), bool(result["ok"]), result.get("code"), result.get("message", "")
            )
        except Exception as exc:  # noqa: BLE001
            message = f"推送异常：{exc}"
            try:
                db.finish_notification(int(alarm["camera_id"]), False, None, message)
            except Exception:  # noqa: BLE001
                pass  # 记录失败也不能让异常冒到 run()，否则连 last_skip 都留不下
            self.last_skip = message
            return False
        self.last_skip = "" if result["ok"] else f"发送失败：{result.get('message', '')}"
        return bool(result["ok"])

    def run(self) -> None:
        while not self._stop_event.is_set():
            try:
                alarm = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                self.handle(alarm)
            except Exception as exc:  # noqa: BLE001
                self.last_skip = f"推送异常：{exc}"

    def stop(self) -> None:
        self._stop_event.set()
