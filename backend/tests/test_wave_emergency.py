"""Guided Response hardening: idempotent open, atomic close, care windows that wait for medical review, protocol metadata."""
from fastapi.testclient import TestClient

from canary.domain import care
from canary.main import app
from tests.support import crew_headers, medical_headers, reset_demo

client = TestClient(app)


def setup_function(_):
    assert reset_demo(client).status_code == 200


def test_the_same_token_gives_back_the_same_emergency():
    h = crew_headers(client, "h")
    a = client.post("/api/emergencies", json={"token": "open-1"}, headers=h).json()
    b = client.post("/api/emergencies", json={"token": "open-1"}, headers=h).json()
    assert a["id"] == b["id"]
    assert len([e for e in client.get("/api/emergencies", headers=h).json() if e["id"] == a["id"]]) == 1


def test_a_second_close_repeats_nothing():
    h = crew_headers(client, "h")
    e = client.post("/api/emergencies", json={"patient": "t", "protocol": "cpr"}, headers=h).json()
    client.post(f"/api/emergencies/{e['id']}", json={"close": True, "outcome": "stable"}, headers=h)
    before = len(client.get("/api/messages", headers=medical_headers(client, "g-fs1")).json())
    again = client.post(f"/api/emergencies/{e['id']}", json={"close": True, "outcome": "stable"}, headers=h).json()
    assert again["ended_at"] and sum(1 for _, text in again["log"] if text.startswith("Closed")) == 1
    assert len(client.get("/api/messages", headers=medical_headers(client, "g-fs1")).json()) == before


def test_a_closed_window_waits_for_medical_review_instead_of_ending():
    h = crew_headers(client, "h")
    e = client.post("/api/emergencies", json={"patient": "t", "protocol": "cpr"}, headers=h).json()
    client.post(f"/api/emergencies/{e['id']}", json={"close": True, "outcome": "stable"}, headers=h)
    row = care.status(e["id"], 0)
    late = row["until_day"] + 30
    waiting = care.active("t", late)
    assert waiting and waiting["status"] == "awaiting review" and waiting["sensitive_until"] >= late
    r = client.post(f"/api/medical/care-windows/{e['id']}/review", json={"resolution": "Checked, no restriction"},
                    headers=medical_headers(client, "g-fs1"))
    assert r.status_code == 200 and r.json()["status"] == "reviewed"
    assert care.active("t", late) is None


def test_every_protocol_says_it_is_illustrative_and_has_a_version():
    protocols = client.get("/api/protocols").json()["protocols"]
    assert protocols and all(p["version"] and p["status"] == "illustrative" and p["reviewer"] is None for p in protocols.values())
