"""Core behaviour: baseline alerts, the story, goals, the assistant guard and the API."""
import os
import tempfile

os.environ["CANARY_DB"] = os.path.join(tempfile.mkdtemp(), "test.db")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from canary.assistant import guard  # noqa: E402
from canary.domain import catalog, goals, health, mission  # noqa: E402
from canary.main import app  # noqa: E402

client = TestClient(app)


@pytest.fixture(autouse=True)
def fresh():
    client.post("/api/demo/reset")
    yield


def at(step):
    return client.put("/api/mission", json={"step": step}).json()


def test_no_alerts_while_learning_on_earth():
    ms = at(0)
    assert ms["learning"]
    for c in catalog.CREW:
        assert health.snapshot(c["id"], ms)["alerts"] == []


def test_space_sickness_only_for_tomas_on_day_2():
    ms = at(1)
    assert [a["id"] for a in health.snapshot("t", ms)["alerts"]][:1] == ["sickness"]
    for cid in ("h", "k", "a"):
        assert not any(a["id"] == "sickness" for a in health.snapshot(cid, ms)["alerts"])


def test_cross_signal_rule_catches_helena_on_day_147():
    s = health.snapshot("h", at(2))
    assert s["alerts"][0]["id"] == "behaviour"
    assert s["areas"]["mental"]["score"] < s["areas"]["physical"]["score"]
    assert any(g["id"] == "al_light" for g in goals.personal_today("h", mission.state(), s))


def test_storm_alerts_everyone_with_the_radiation_protocol():
    ms = at(3)
    for c in catalog.CREW:
        a = health.snapshot(c["id"], ms)["alerts"][0]
        assert a["id"] == "storm" and a["protocol"] == "rad"


def test_thresholds_change_levels():
    ms = at(2)
    strict = health.indicator("h", "sleep", ms, {"watch": 0.5, "act": 0.8})
    loose = health.indicator("h", "sleep", ms, {"watch": 4, "act": 5})
    assert strict["level"] >= loose["level"]


def test_checkin_overrides_and_completes_goal():
    at(2)
    r = client.post("/api/checkins", json={"crew_id": "h", "kind": "mood", "payload": {"mood": 5, "stress": 1}}).json()
    assert r["snapshot"]["indicators"]["mood"]["value"] > 4
    g = {x["id"]: x for x in client.get("/api/goals/h").json()["personal"]}
    assert g["mood"]["done"]


def test_xp_levels_are_monotonic():
    xs = [catalog.level_for(x)["level"] for x in range(0, 20000, 500)]
    assert xs == sorted(xs)


def test_leaderboard_ranks_everyone():
    at(2)
    lb = client.get("/api/leaderboard").json()
    assert [r["rank"] for r in lb["rows"]] == [1, 2, 3, 4]
    assert len(lb["team"]) == len(catalog.TEAM_GOALS)


@pytest.mark.parametrize("q,mode", [
    ("How many mg of melatonin should I take?", "refused"),
    ("Do I have cancer?", "refused"),
    ("Tomás is having a seizure", "emergency"),
    ("Why is my pulse high?", None),
])
def test_guard_precheck(q, mode):
    r = guard.precheck(q)
    assert (r or {}).get("mode") == mode


def test_guard_drops_uncited_claims():
    kept, dropped = guard.validate_claims(
        [{"text": "ok", "source_ids": ["a"]}, {"text": "made up", "source_ids": ["zzz"]}, {"text": "none", "source_ids": []}], ["a"])
    assert [k["text"] for k in kept] == ["ok"] and dropped == 2


def test_guard_flags_invented_numbers():
    assert guard.unknown_numbers("pulse 72, sleep 5.8", '{"hr": 72}') == ["5.8"]


def test_assistant_answers_grounded_without_a_provider():
    at(2)
    r = client.post("/api/assistant/ask", json={"crew_id": "h", "question": "Why is my sleep so bad?"}).json()
    assert r["provider"] == "none" and r["mode"] == "grounded"
    assert r["claims"] and all(c["source_ids"] for c in r["claims"])


def test_briefing_is_approved_then_queued():
    at(2)
    b = client.post("/api/briefings", json={"crew_id": "h"}).json()
    assert b["status"] == "draft" and "WHAT WORRIES" in b["text"]
    assert client.post(f"/api/briefings/{b['id']}/approve").json()["status"] == "queued"


def test_medical_endpoints_need_the_pin():
    assert client.get("/api/medical/overview").status_code == 401
    assert client.post("/api/medical/session", json={"pin": "0000"}).status_code == 401
    tok = client.post("/api/medical/session", json={"pin": "1961"}).json()["token"]
    assert client.get("/api/medical/overview", headers={"Authorization": f"Bearer {tok}"}).status_code == 200


def test_closing_an_emergency_creates_follow_up_goals_and_a_report():
    at(4)
    e = client.post("/api/emergencies", json={"responder": "k"}).json()
    client.post(f"/api/emergencies/{e['id']}", json={"protocol": "seizure", "patient": "t", "text": "Seizure stopped at 02:10"})
    client.post(f"/api/emergencies/{e['id']}", json={"close": True, "outcome": "stable"})
    titles = [g["title"] for g in client.get("/api/goals/t").json()["personal"] if g["by"] == "medical"]
    assert titles and any("Glucose" in t for t in titles)
    assert any(m["kind"] == "report" for m in client.get("/api/messages").json())
