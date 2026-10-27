import time

from backend.app import snapshots
from backend.app.config import SNAPSHOTS


def test_store_and_resolve_roundtrip() -> None:
    rel = snapshots.store_frame(1, 42, "first", b"\xff\xd8fakejpeg\xff\xd9")
    assert rel == "1/alarm_42_first.jpg"
    path = snapshots.resolve_frame(rel)
    assert path is not None and path.is_file()
    assert path.read_bytes().startswith(b"\xff\xd8")


def test_store_rejects_unknown_variant() -> None:
    try:
        snapshots.store_frame(1, 42, "middle", b"x")
    except ValueError as exc:
        assert "variant" in str(exc)
    else:
        raise AssertionError("应当抛出 ValueError")


def test_resolve_rejects_escape_and_missing() -> None:
    assert snapshots.resolve_frame("") is None
    assert snapshots.resolve_frame("../../etc/passwd") is None
    assert snapshots.resolve_frame("1/alarm_9999_first.jpg") is None


def test_delete_alarm_frames() -> None:
    snapshots.store_frame(7, 500, "first", b"a")
    snapshots.store_frame(7, 500, "latest", b"b")
    assert snapshots.delete_alarm_frames(7, 500) == 2
    assert snapshots.resolve_frame("7/alarm_500_first.jpg") is None


def test_cleanup_old_frames_removes_only_expired() -> None:
    old_rel = snapshots.store_frame(8, 600, "first", b"old")
    new_rel = snapshots.store_frame(8, 601, "first", b"new")
    old_path = SNAPSHOTS / old_rel
    stale = time.time() - 8 * 86400
    import os

    os.utime(old_path, (stale, stale))
    removed = snapshots.cleanup_old_frames(days=7)
    assert removed >= 1
    assert snapshots.resolve_frame(old_rel) is None
    assert snapshots.resolve_frame(new_rel) is not None
