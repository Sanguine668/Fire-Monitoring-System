from backend.app import db


def test_init_and_crud() -> None:
    db.init_db()
    cid = db.insert_camera("测试源", "file", "C:/tmp/demo.mp4")
    assert db.get_camera(cid)["name"] == "测试源"
    db.set_camera_online(cid, True)
    assert db.get_camera(cid)["online"] == 1
    assert db.get_settings()["fire_threshold"] == 0.1
    db.delete_camera(cid)
