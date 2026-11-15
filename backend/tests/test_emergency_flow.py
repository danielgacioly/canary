"""Guided Response: the cabin-wide alarm, an outcome to close, and escalation that keeps it open."""
import pytest
from fastapi.testclient import TestClient

from canary.main import app
from tests.support import crew_headers, medical_headers, reset_demo

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
    assert client.post(f"/api/emergencies/{e['id']}", json={"close": True, "outcome": "resolved"}, headers=h).status_code == 200
    assert not [x for x in client.get("/api/emergencies/open").json() if x["id"] == e["id"]]


def test_closing_needs_an_outcome():
    h = crew_headers(client, "h")
    e = client.post("/api/emergencies", json={}, headers=h).json()
    assert client.post(f"/api/emergencies/{e['id']}", json={"close": True}, headers=h).status_code == 422
    assert client.post(f"/api/emergencies/{e['id']}", json={"close": True, "outcome": "whatever"}, headers=h).status_code == 422
    assert client.post(f"/api/emergencies/{e['id']}", json={"close": True, "outcome": "transferred to medical officer"}, headers=h).status_code == 200


def test_escalating_keeps_it_open_and_asks_the_flight_surgeon_for_a_pmc():
    h = crew_headers(client, "h")
    e = client.post("/api/emergencies", json={"patient": "t"}, headers=h).json()
    r = client.post(f"/api/emergencies/{e['id']}", json={"escalate": True}, headers=h).json()
    assert r["ended_at"] is None
    msgs = client.get("/api/messages", headers=medical_headers(client, "g-fs1")).json()
    pmc = [m for m in msgs if m["kind"] == "pmc"]
    assert pmc and pmc[0]["recipient"] == "g-fs1" and "private medical conference" in pmc[0]["text"].lower() or "PMC" in pmc[0]["text"]
    assert client.get("/api/emergencies/open").json()
