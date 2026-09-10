from backend.app.alarm_engine import AlarmEngine


def test_smoke_warning_after_continuous_frames() -> None:
    engine = AlarmEngine()
    det = [{"type": "smoke", "confidence": 0.7, "bbox": [0, 0, 1, 1]}]
    alarm = None
    for i in range(3):
        _, _, alarm = engine.update(100.0 + i * 0.3, det, 0.5, 0.5, 3, 8)
    assert alarm is not None and alarm["alarm_type"] == "smoke" and alarm["level"] == "warning"
    # 冷却期内不重复告警
    _, _, alarm2 = engine.update(101.0, det, 0.5, 0.5, 3, 8)
    assert alarm2 is None


def test_fire_critical_immediate() -> None:
    engine = AlarmEngine()
    _, _, alarm = engine.update(
        1.0, [{"type": "fire", "confidence": 0.9, "bbox": [0, 0, 1, 1]}], 0.5, 0.5, 3, 8
    )
    assert alarm is not None and alarm["level"] == "critical"


def test_low_confidence_ignored() -> None:
    engine = AlarmEngine()
    _, _, alarm = engine.update(
        1.0, [{"type": "fire", "confidence": 0.1, "bbox": [0, 0, 1, 1]}], 0.5, 0.5, 3, 8
    )
    assert alarm is None
