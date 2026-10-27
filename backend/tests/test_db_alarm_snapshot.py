from backend.app import db


def _fresh_alarm() -> dict:
    db.init_db()
    db.clear_alarms()
    return db.create_alarm(1, "测试源", "fire", "critical", 0.9, 1)


def test_create_alarm_marks_new_and_merged() -> None:
    db.init_db()
    db.clear_alarms()
    first = db.create_alarm(9, "源A", "smoke", "warning", 0.5, 0)
    assert first["is_new"] is True
    merged = db.create_alarm(9, "源A", "smoke", "warning", 0.6, 0)
    assert merged["is_new"] is False
    assert merged["id"] == first["id"]
    assert merged["count"] == 2


def test_update_alarm_snapshot_fields() -> None:
    alarm = _fresh_alarm()
    db.update_alarm_snapshot(
        alarm["id"],
        first="1/alarm_2_first.jpg",
        latest="1/alarm_2_latest.jpg",
        boxes='[{"type": "fire", "confidence": 0.9, "bbox": [1, 2, 3, 4]}]',
        frame_size="1280x720",
    )
    row = db.get_alarm(alarm["id"])
    assert row["snapshot_first"] == "1/alarm_2_first.jpg"
    assert row["snapshot_latest"] == "1/alarm_2_latest.jpg"
    assert row["frame_size"] == "1280x720"
    assert '"fire"' in row["boxes"]


def test_clear_alarms_returns_deleted_ids() -> None:
    alarm = _fresh_alarm()
    deleted = db.clear_alarms()
    assert any(item["id"] == alarm["id"] for item in deleted)
    assert db.get_alarm(alarm["id"]) is None


def test_notification_reserve_is_per_camera() -> None:
    db.init_db()
    db.clear_notifications()
    with db._conn() as c:  # 每日尝试计数独立于占位表，先清零再断言
        c.execute("DELETE FROM notify_daily")
    assert db.reserve_notification(5, 100, "fire", "标题A") is True
    assert db.reserve_notification(5, 101, "smoke", "标题B") is False
    assert db.reserve_notification(6, 102, "fire", "标题C") is True
    db.finish_notification(5, True, 0, "ok")
    records = {r["camera_id"]: r for r in db.list_notifications()}
    assert records[5]["ok"] == 1
    assert db.notifications_sent_today() == 0  # 占位不等于已发送，额度由 Notifier.handle 计
    db.bump_notify_daily()
    db.bump_notify_daily()
    assert db.notifications_sent_today() == 2
    assert db.clear_notifications() == 2
    assert db.notifications_sent_today() == 2  # 清占位表不影响每日计数
    assert db.reserve_notification(5, 103, "fire", "标题D") is True


def test_notify_config_roundtrip() -> None:
    db.init_db()
    db.save_notify_config(1, "SCTtestkey", "组长手机", 4)
    cfg = db.get_notify_config()
    assert cfg == {"enabled": 1, "sendkey": "SCTtestkey", "name": "组长手机", "daily_limit": 4}
