import json
import random

import pytest
from fastapi.testclient import TestClient
from horse_tinder import db
from horse_tinder.app import SESSION_COOKIE, create_app

HORSE_COUNT = len(json.loads(db.SEED_FILE.read_text()))


class FixedRandom(random.Random):
    """random() always returns `value`, so match outcomes are predictable."""

    def __init__(self, value: float):
        super().__init__(0)
        self.value = value

    def random(self) -> float:
        return self.value


def make_client(tmp_path, roll: float) -> TestClient:
    app = create_app(db_path=str(tmp_path / "test.db"), rng=FixedRandom(roll))
    return TestClient(app)


@pytest.fixture
def lucky(tmp_path):
    """Every like is a match."""
    with make_client(tmp_path, roll=0.999) as client:
        yield client


@pytest.fixture
def unlucky(tmp_path):
    """No like is ever a match."""
    with make_client(tmp_path, roll=0.0) as client:
        yield client


def test_health(lucky):
    assert lucky.get("/api/health").json() == {"status": "ok"}


def test_frontend_is_served(lucky):
    resp = lucky.get("/")
    assert resp.status_code == 200
    assert "Horse Tinder" in resp.text


def test_seed_photos_exist(lucky):
    for horse in json.loads(db.SEED_FILE.read_text()):
        assert lucky.get(f"/{horse['photo']}").status_code == 200, horse["slug"]


def test_session_cookie_is_issued_once(lucky):
    first = lucky.get("/api/horses")
    assert SESSION_COOKIE in first.cookies
    second = lucky.get("/api/horses")
    assert SESSION_COOKIE not in second.cookies


def test_horses_hide_pickiness(lucky):
    horse = lucky.get("/api/horses?limit=1").json()["horses"][0]
    assert "pickiness" not in horse
    assert isinstance(horse["interests"], list)
    assert horse["photo_license"]


def test_swiped_horse_is_not_shown_again(lucky):
    first = lucky.get("/api/horses?limit=1").json()["horses"][0]
    lucky.post("/api/swipes", json={"horse_id": first["id"], "liked": False})
    ids = [h["id"] for h in lucky.get("/api/horses?limit=20").json()["horses"]]
    assert first["id"] not in ids
    assert len(ids) == HORSE_COUNT - 1


def test_like_creates_match_and_opening_message(lucky):
    horse = lucky.get("/api/horses?limit=1").json()["horses"][0]
    resp = lucky.post("/api/swipes", json={"horse_id": horse["id"], "liked": True}).json()
    assert resp["matched"] is True
    assert resp["horse"]["id"] == horse["id"]

    matches = lucky.get("/api/matches").json()["matches"]
    assert [m["id"] for m in matches] == [horse["id"]]
    assert matches[0]["last_message"]

    msgs = lucky.get(f"/api/matches/{horse['id']}/messages").json()["messages"]
    assert len(msgs) == 1 and msgs[0]["from_horse"] is True


def test_pass_never_matches(lucky):
    horse = lucky.get("/api/horses?limit=1").json()["horses"][0]
    resp = lucky.post("/api/swipes", json={"horse_id": horse["id"], "liked": False}).json()
    assert resp == {"matched": False, "horse": None}
    assert lucky.get("/api/matches").json()["matches"] == []


def test_picky_horse_rejects_like(unlucky):
    horse = unlucky.get("/api/horses?limit=1").json()["horses"][0]
    resp = unlucky.post("/api/swipes", json={"horse_id": horse["id"], "liked": True}).json()
    assert resp["matched"] is False
    assert unlucky.get("/api/stats").json()["liked"] == 1


def test_double_swipe_conflicts(lucky):
    horse = lucky.get("/api/horses?limit=1").json()["horses"][0]
    body = {"horse_id": horse["id"], "liked": True}
    assert lucky.post("/api/swipes", json=body).status_code == 200
    assert lucky.post("/api/swipes", json=body).status_code == 409


def test_swipe_unknown_horse(lucky):
    assert lucky.post("/api/swipes", json={"horse_id": 99999, "liked": True}).status_code == 404


def test_chat_requires_match(unlucky):
    horse = unlucky.get("/api/horses?limit=1").json()["horses"][0]
    resp = unlucky.post(f"/api/matches/{horse['id']}/messages", json={"body": "hi"})
    assert resp.status_code == 404


def test_chat_gets_horse_reply(lucky):
    horse = lucky.get("/api/horses?limit=1").json()["horses"][0]
    lucky.post("/api/swipes", json={"horse_id": horse["id"], "liked": True})
    msgs = lucky.post(
        f"/api/matches/{horse['id']}/messages", json={"body": "  hey there  "}
    ).json()["messages"]
    assert [m["from_horse"] for m in msgs] == [True, False, True]
    assert msgs[1]["body"] == "hey there"


def test_empty_message_rejected(lucky):
    horse = lucky.get("/api/horses?limit=1").json()["horses"][0]
    lucky.post("/api/swipes", json={"horse_id": horse["id"], "liked": True})
    resp = lucky.post(f"/api/matches/{horse['id']}/messages", json={"body": ""})
    assert resp.status_code == 422


def test_users_are_isolated(tmp_path):
    with make_client(tmp_path, roll=0.999) as alice, make_client(tmp_path, roll=0.999) as bob:
        horse = alice.get("/api/horses?limit=1").json()["horses"][0]
        alice.post("/api/swipes", json={"horse_id": horse["id"], "liked": True})
        assert len(alice.get("/api/matches").json()["matches"]) == 1
        assert bob.get("/api/matches").json()["matches"] == []
        assert len(bob.get("/api/horses?limit=20").json()["horses"]) == HORSE_COUNT


def test_reset_clears_progress(lucky):
    for horse in lucky.get("/api/horses?limit=20").json()["horses"]:
        lucky.post("/api/swipes", json={"horse_id": horse["id"], "liked": True})
    assert lucky.get("/api/horses").json()["horses"] == []
    stats = lucky.get("/api/stats").json()
    assert stats == {
        "horses": HORSE_COUNT,
        "swiped": HORSE_COUNT,
        "liked": HORSE_COUNT,
        "matched": HORSE_COUNT,
    }

    lucky.post("/api/reset")
    assert len(lucky.get("/api/horses?limit=20").json()["horses"]) == HORSE_COUNT
    assert lucky.get("/api/matches").json()["matches"] == []


def test_reseed_is_idempotent(tmp_path):
    path = str(tmp_path / "seed.db")
    db.init(path)
    db.init(path)
    conn = db.connect(path)
    assert conn.execute("SELECT COUNT(*) FROM horses").fetchone()[0] == HORSE_COUNT
    conn.close()
