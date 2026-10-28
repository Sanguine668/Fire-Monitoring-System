import json

from backend.app import db, notify
from backend.app.notify import Notifier, ServerChanChannel, render_message


class FakeChannel:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def send(self, title, desp):
        self.calls.append((title, desp))
        return self.result


def _alarm(**over) -> dict:
    base = {
        "id": 12,
        "camera_id": 3,
        "camera_name": "东门摄像头",
        "alarm_type": "fire",
        "level": "critical",
        "confidence": 0.876,
        "count": 5,
        "created_at": "2026-10-27 20:05:51",
    }
    base.update(over)
    return base


def _prepare(enabled: int = 1, sendkey: str = "SCTkey", daily_limit: int = 5) -> None:
    db.init_db()
    db.clear_notifications()
    with db._conn() as c:  # 每日计数独立于 alarm_notifications，需按用例清零
        c.execute("DELETE FROM notify_daily")
    db.save_notify_config(enabled, sendkey, "", daily_limit)


def test_render_message_strips_newlines_from_title() -> None:
    title, desp = render_message(_alarm(camera_name="东门\n摄像头"))
    assert "\n" not in title
    assert title == "【火情监测】东门 摄像头 明火告警"
    assert "东门 摄像头" in desp
    assert "87.6%" in desp
    assert "5 次" in desp


def test_render_message_includes_frame_url_when_base_given() -> None:
    _, desp = render_message(_alarm(snapshot_first="3/12_first.jpg"), base_url="http://192.168.1.5:8000")
    assert "http://192.168.1.5:8000/api/alarms/12/frame?variant=first" in desp


def test_render_message_notes_missing_base_url() -> None:
    _, desp = render_message(_alarm(), base_url="")
    assert "/api/alarms/12/frame" not in desp
    assert "局域网" in desp


def test_notifier_skips_when_disabled() -> None:
    _prepare(enabled=0)
    channel = FakeChannel({"ok": True, "code": 0, "message": ""})
    n = Notifier(channel_factory=lambda key: channel)
    assert n.handle(_alarm()) is False
    assert channel.calls == []
    assert "未启用" in n.last_skip


def test_notifier_skips_without_sendkey() -> None:
    _prepare(sendkey="")
    n = Notifier(channel_factory=lambda key: FakeChannel({"ok": True, "code": 0, "message": ""}))
    assert n.handle(_alarm()) is False
    assert "SendKey" in n.last_skip


def test_notifier_pushes_once_per_camera() -> None:
    _prepare()
    channel = FakeChannel({"ok": True, "code": 0, "message": ""})
    n = Notifier(channel_factory=lambda key: channel)
    assert n.handle(_alarm()) is True
    assert n.handle(_alarm(id=13, alarm_type="smoke")) is False
    assert len(channel.calls) == 1
    assert db.list_notifications()[0]["ok"] == 1


def test_notifier_respects_daily_limit() -> None:
    _prepare(daily_limit=1)
    channel = FakeChannel({"ok": True, "code": 0, "message": ""})
    n = Notifier(channel_factory=lambda key: channel)
    assert n.handle(_alarm(camera_id=1)) is True
    assert n.handle(_alarm(camera_id=2)) is False
    assert "上限" in n.last_skip


def test_notify_daily_survives_restart() -> None:
    """重启只会清 alarm_notifications（本轮去重），每日额度必须还在。"""
    _prepare()
    channel = FakeChannel({"ok": True, "code": 0, "message": ""})
    n = Notifier(channel_factory=lambda key: channel)
    assert db.notifications_sent_today() == 0
    assert n.handle(_alarm()) is True
    assert db.notifications_sent_today() == 1
    db.clear_notifications()  # 等价于 main.py 启动时的那次清理
    assert db.notifications_sent_today() == 1


def test_notifier_counts_failed_send_as_attempt() -> None:
    _prepare(daily_limit=5)
    channel = FakeChannel({"ok": False, "code": 40001, "message": "bad key"})
    n = Notifier(channel_factory=lambda key: channel)
    assert n.handle(_alarm()) is False
    assert db.notifications_sent_today() == 1


def test_notifier_records_failure_and_keeps_slot() -> None:
    _prepare()
    channel = FakeChannel({"ok": False, "code": 40001, "message": "bad key"})
    n = Notifier(channel_factory=lambda key: channel)
    assert n.handle(_alarm()) is False
    row = db.list_notifications()[0]
    assert row["ok"] == 0 and row["code"] == 40001
    assert n.handle(_alarm(id=14)) is False  # 占位仍在，不重试


def test_notifier_records_channel_exception() -> None:
    """通道内部抛非 HTTP 异常时也要落一条失败记录，不能只在 run() 里静默吞掉。"""
    _prepare()

    class BoomChannel:
        def send(self, title, desp):
            raise RuntimeError("boom")

    n = Notifier(channel_factory=lambda key: BoomChannel())
    assert n.handle(_alarm()) is False
    row = db.list_notifications()[0]
    assert row["ok"] == 0
    assert "推送异常" in row["message"]
    assert "推送异常" in n.last_skip


def test_serverchan_channel_posts_form(monkeypatch) -> None:
    captured = {}

    class FakeResp:
        status_code = 200

        def json(self):
            return {"code": 0, "message": "", "data": {"error": "SUCCESS"}}

    def fake_post(url, data=None, timeout=None):
        captured["url"] = url
        captured["data"] = data
        return FakeResp()

    monkeypatch.setattr(notify.httpx, "post", fake_post)
    result = ServerChanChannel("SCTabc").send("标题", "正文")
    assert captured["url"] == "https://sctapi.ftqq.com/SCTabc.send"
    assert captured["data"] == {"title": "标题", "desp": "正文"}
    assert result["ok"] is True


def test_serverchan_channel_handles_429(monkeypatch) -> None:
    class FakeResp:
        status_code = 429

        def json(self):
            return {}

    monkeypatch.setattr(notify.httpx, "post", lambda *a, **k: FakeResp())
    result = ServerChanChannel("SCTabc").send("标题", "正文")
    assert result["ok"] is False
    assert result["code"] == 429
    assert "限流" in result["message"]


def test_serverchan_channel_handles_network_error(monkeypatch) -> None:
    def boom(*a, **k):
        raise notify.httpx.ConnectError("connection refused")

    monkeypatch.setattr(notify.httpx, "post", boom)
    result = ServerChanChannel("SCTabc").send("标题", "正文")
    assert result["ok"] is False
    assert "网络" in result["message"]


def test_serverchan_channel_wraps_non_http_errors(monkeypatch) -> None:
    """InvalidURL（SendKey 含控制字符）之类不是 HTTPError，也必须转成失败结果。"""

    def boom(*a, **k):
        raise ValueError("boom")

    monkeypatch.setattr(notify.httpx, "post", boom)
    result = ServerChanChannel("SCTabc").send("标题", "正文")
    assert result["ok"] is False
    assert result["code"] is None
    assert "异常" in result["message"]


def test_render_message_omits_image_without_snapshot() -> None:
    title, desp = render_message(_alarm(), base_url="http://192.168.1.5:8000")
    assert "/api/alarms/12/frame" not in desp
    assert "未留存画面" in desp
