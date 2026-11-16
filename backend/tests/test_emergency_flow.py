"""Guided Response: the cabin-wide alarm and closing it with an outcome."""
import pytest
from fastapi.testclient import TestClient

from canary.main import app
from tests.support import crew_headers, reset_demo

client = TestClient(app)


@pytest.fixture(autouse=True)
def fresh():
    assert reset_demo(client).status_code == 200
    yield
    reset_demo(client)


def test_the_open_alarm_names_patient_and_protocol_until_closed():
    h = crew_headers(client, "h")
    e = client.post("/api/emergencies", json={}, headers=h).json()
    client.post(f"/api/emergencies/{e['id']}", json={"patient": "t", "protocol": "cpr"}, headers=h)
    opened = client.get("/api/emergencies/open").json()  # no sign-in: everyone on board sees it
    assert opened and opened[0]["id"] == e["id"] and opened[0]["patient"] and opened[0]["protocol"]
    assert client.post(f"/api/emergencies/{e['id']}", json={"close": True, "outcome": "stable"}, headers=h).status_code == 200
    assert not [x for x in client.get("/api/emergencies/open").json() if x["id"] == e["id"]]


def test_closing_needs_an_outcome():
    h = crew_headers(client, "h")
    e = client.post("/api/emergencies", json={}, headers=h).json()
    assert client.post(f"/api/emergencies/{e['id']}", json={"close": True}, headers=h).status_code == 422
    assert client.post(f"/api/emergencies/{e['id']}", json={"close": True, "outcome": "whatever"}, headers=h).status_code == 422
    assert client.post(f"/api/emergencies/{e['id']}", json={"close": True, "outcome": "needs evacuation review"}, headers=h).status_code == 200


def _counts(eid: int) -> tuple:
    from canary import db
    return (db.q("SELECT COUNT(*) n FROM care_events WHERE emergency_id=?", (eid,))[0]["n"],
            db.q("SELECT COUNT(*) n FROM medical_goals")[0]["n"],
            db.q("SELECT COUNT(*) n FROM messages WHERE kind='report'")[0]["n"])


def test_cancel_stops_the_alarm_without_goals_care_or_report():
    h = crew_headers(client, "h")
    e = client.post("/api/emergencies", json={}, headers=h).json()
    client.post(f"/api/emergencies/{e['id']}", json={"patient": "t", "protocol": "cpr", "text": "Patient: Tomás"}, headers=h)
    before = _counts(e["id"])
    r = client.post(f"/api/emergencies/{e['id']}", json={"cancel": True}, headers=h)
    assert r.status_code == 200
    body = r.json()
    assert body["outcome"] == "cancelled" and body["ended_at"]
    assert body["log"][-1][1] == "Cancelled without an outcome"
    assert not [x for x in client.get("/api/emergencies/open").json() if x["id"] == e["id"]]
    assert _counts(e["id"]) == before  # no care window, follow-up goals or Earth report


def test_cancel_after_close_changes_nothing_and_needs_sign_in():
    h = crew_headers(client, "h")
    e = client.post("/api/emergencies", json={}, headers=h).json()
    assert client.post(f"/api/emergencies/{e['id']}", json={"cancel": True}).status_code == 401
    assert client.post(f"/api/emergencies/{e['id']}", json={"close": True, "outcome": "stable"}, headers=h).status_code == 200
    r = client.post(f"/api/emergencies/{e['id']}", json={"cancel": True}, headers=h).json()
    assert r["outcome"] == "stable"
