"""Briefings: who may approve one, what state it must be in, and who may read it in the message feed (plan.md, schema.md §7).

Only the medical team approves a briefing. The astronaut it is about may read it once approved, but may not approve it; nobody
else, and nobody signed out, may approve or read it. Approving is idempotent: the second approval is refused and queues no second message to Earth.
"""
import os
import tempfile

os.environ["CANARY_DB"] = os.path.join(tempfile.mkdtemp(), "test_briefing_access.db")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from canary import db  # noqa: E402
from canary.main import app  # noqa: E402
from tests.golden_capture import PINS, control_headers, medical_headers, reset_demo  # noqa: E402

client = TestClient(app)


@pytest.fixture(autouse=True)
def fresh():
    reset_demo(client)
    client.put("/api/mission", json={"step": 2})
    yield
    reset_demo(client)


def as_(cid):
    r = client.post(f"/api/crew/{cid}/session", json={"pin": PINS[cid]})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def medical():
    return medical_headers(client)


def control():
    return control_headers(client)


def new_briefing(cid="h"):
    return client.post("/api/briefings", json={"crew_id": cid}, headers=as_(cid)).json()


def earth_briefings():
    return [m for m in db.q("SELECT * FROM messages WHERE kind='briefing'")]


def test_approve_without_a_token_is_refused():
    b = new_briefing()
    r = client.post(f"/api/briefings/{b['id']}/approve")
    assert r.status_code in (401, 403)
    assert b["status"] == "draft" and earth_briefings() == []


def test_another_crew_member_may_not_approve():
    b = new_briefing()
    r = client.post(f"/api/briefings/{b['id']}/approve", headers=as_("k"))
    assert r.status_code == 401  # signed in, but not the medical team: refused before the briefing is looked at
    assert earth_briefings() == []


def test_mission_control_may_not_approve():
    b = new_briefing()
    assert client.post(f"/api/briefings/{b['id']}/approve", headers=control()).status_code == 401
    assert earth_briefings() == []


def test_owner_may_not_approve_their_own_briefing():
    b = new_briefing()
    r = client.post(f"/api/briefings/{b['id']}/approve", headers=as_("h"))
    assert r.status_code == 401
    assert b["status"] == "draft" and earth_briefings() == []


def test_medical_team_may_approve():
    b = new_briefing()
    r = client.post(f"/api/briefings/{b['id']}/approve", headers=medical())
    assert r.status_code == 200 and r.json()["status"] == "queued"


def test_second_approval_is_idempotent_and_queues_nothing_more():
    b = new_briefing()
    assert client.post(f"/api/briefings/{b['id']}/approve", headers=medical()).status_code == 200
    again = client.post(f"/api/briefings/{b['id']}/approve", headers=medical())
    assert again.status_code == 200 and again.json()["status"] == "queued"
    assert len(earth_briefings()) == 1


def test_unknown_briefing_is_not_found():
    r = client.post("/api/briefings/999999/approve", headers=medical())
    assert r.status_code == 404


# ---------------------------------------------------------------- item 2: approved briefings are private in the message feed

def _approved_text():
    b = new_briefing()
    client.post(f"/api/briefings/{b['id']}/approve", headers=medical())
    rows = earth_briefings()
    assert len(rows) == 1
    return rows[0]["text"], b


def test_approved_briefing_is_not_public_in_the_message_feed():
    text, _ = _approved_text()
    first_line = text.splitlines()[0]
    assert first_line not in str(client.get("/api/messages").json())
    assert first_line not in str(client.get("/api/messages", headers=as_("k")).json())
    assert first_line not in str(client.get("/api/messages", headers=control()).json())


def test_medical_team_sees_the_approved_briefing_in_the_feed():
    text, _ = _approved_text()
    assert any(m["kind"] == "briefing" for m in client.get("/api/messages", headers=medical()).json())


def test_owner_sees_their_own_approved_briefing_in_the_feed():
    text, _ = _approved_text()
    feed = client.get("/api/messages", headers=as_("h")).json()
    assert [m["text"] for m in feed if m["kind"] == "briefing"] == [text]


def test_owner_sees_the_briefing_only_when_signed_in_as_them():
    _approved_text()
    assert not _briefings_in_feed(as_("k"))
    assert not _briefings_in_feed(control())
    assert client.get("/api/messages").status_code == 401  # signed out: no feed at all
    assert not _briefings_in_feed()


def _briefings_in_feed(headers=None) -> list:
    """The briefing messages a caller gets from the feed; an error answer (no sign-in, or not a person) gives none."""
    r = client.get("/api/messages", headers=headers or {})
    if r.status_code != 200:
        return []
    return [m for m in r.json() if m.get("kind") == "briefing"]
