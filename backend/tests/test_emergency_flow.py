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
