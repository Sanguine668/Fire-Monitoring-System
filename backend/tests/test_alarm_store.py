import json

from backend.app import alarm_store, db, snapshots


class FakeNotifier:
    def __init__(self):
        self.received = []

    def enqueue_alarm(self, alarm):
        self.received.append(alarm)


def _prepare():
    db.init_db()
    db.clear_alarms()
    db.clear_notifications()
    db.save_notify_config(1, "SCTkey", "", 5)


def test_first_alarm_saves_both_frames_and_boxes() -> None:
    _prepare()
    visible = [{"type": "fire", "confidence": 0.9, "bbox": [10, 20, 30, 40]}]
    record = alarm_store.persist_alarm(
        camera_id=4,
        camera_name="北门",
        alarm={"alarm_type": "fire", "level": "critical", "confidence": 0.9, "verified": True},
        visible=visible,
        frame_jpeg=b"\xff\xd8frame1\xff\xd9",
        frame_size=(640, 480),
    )
    assert record["is_new"] is True
    assert record["frame_size"] == "640x480"
    assert json.loads(record["boxes"])[0]["bbox"] == [10, 20, 30, 40]
    first = snapshots.resolve_frame(record["snapshot_first"])
    latest = snapshots.resolve_frame(record["snapshot_latest"])
    assert first is not None and latest is not None
    assert first.read_bytes() == b"\xff\xd8frame1\xff\xd9"


def test_merged_alarm_only_refreshes_latest() -> None:
    _prepare()
    alarm = {"alarm_type": "fire", "level": "critical", "confidence": 0.9}
    first = alarm_store.persist_alarm(4, "北门", alarm, [], b"\xff\xd8one\xff\xd9", (640, 480))
    merged = alarm_store.persist_alarm(
        4, "北门", {**alarm, "confidence": 0.95}, [], b"\xff\xd8two\xff\xd9", (640, 480)
    )
    assert merged["is_new"] is False
    assert merged["snapshot_first"] == first["snapshot_first"]
    assert snapshots.resolve_frame(first["snapshot_first"]).read_bytes() == b"\xff\xd8one\xff\xd9"
    assert snapshots.resolve_frame(merged["snapshot_latest"]).read_bytes() == b"\xff\xd8two\xff\xd9"


def test_notifier_only_gets_new_alarms() -> None:
    _prepare()
    notifier = FakeNotifier()
    alarm = {"alarm_type": "smoke", "level": "warning", "confidence": 0.5}
    alarm_store.persist_alarm(6, "西侧", alarm, [], b"\xff\xd8a\xff\xd9", (320, 240), notifier)
    alarm_store.persist_alarm(6, "西侧", alarm, [], b"\xff\xd8b\xff\xd9", (320, 240), notifier)
    assert len(notifier.received) == 1
    assert notifier.received[0]["camera_id"] == 6


def test_empty_frame_still_records_alarm() -> None:
    _prepare()
    record = alarm_store.persist_alarm(7, "南门", {"alarm_type": "fire", "level": "critical", "confidence": 0.7}, [], b"", (0, 0))
    assert record["id"] > 0
    assert not record.get("snapshot_first")
