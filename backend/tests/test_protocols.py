"""Protocols: the description matcher, and the Protocols page (everything in force now, no personal data)."""
import os
import tempfile

os.environ["CANARY_DB"] = os.path.join(tempfile.mkdtemp(), "protocols.db")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from canary.assistant import protocol_match as ai_match  # noqa: E402
from canary.config import settings  # noqa: E402
from canary.domain import protocol_match, protocols  # noqa: E402
from canary.main import app  # noqa: E402
from tests.golden_capture import reset_demo  # noqa: E402

client = TestClient(app)


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    monkeypatch.setattr(settings, "mission_package", "odyssey1-mars")
    monkeypatch.setattr(settings, "live_space_weather", False)
    reset_demo(client)


def ids(text):
    return [m["id"] for m in protocol_match.match(text)["matches"]]


def test_a_synonym_finds_the_protocol():
    assert ids("he is having a fit and twitching")[0] == "seizure"
    assert ids("she cannot breathe, food stuck")[0] == "choke"
    assert ids("a lot of blood from his hand")[0] == "bleed"
    assert ids("something in my eye, I cannot see")[0] == "eye"


def test_shaking_and_not_responding_is_a_seizure_first_and_cpr_second():
    r = protocol_match.match("he is shaking and not responding")["matches"]
    assert [m["id"] for m in r][:2] == ["seizure", "cpr"]
    assert r[0]["matched"] == ["shaking"]


def test_several_words_add_up_and_are_listed():
    r = protocol_match.match("chest pain, sweating and short of breath")["matches"][0]
    assert r["id"] == "chest" and {"chest", "pain", "sweating"} <= set(r["matched"])
    assert r["score"] > protocol_match.match("chest pain")["matches"][0]["score"]


def test_light_typos_and_word_forms():
    assert ids("she is bleding badly")[0] == "bleed"
    assert ids("he stopped breathin")[0] == "cpr"
    assert ids("seizres")[0] == "seizure"
    assert ids("panicing and cryng")[0] == "crisis"
    assert ids("he was breathing fine") == []  # the word alone is not a clue


def test_a_phrase_needs_its_words_in_order():
    assert ids("not breathing")[0] == "cpr"
    assert "cpr" not in ids("breathing, not shaking")[:1]


def test_nothing_matches_falls_back_to_basic_life_support():
    r = protocol_match.match("my arm has a burn")
    assert r["matches"] == [] and r["fallback"]["id"] == "cpr"


def test_at_most_three_and_best_first():
    r = protocol_match.match("shaking, not breathing, bleeding, rash, radiation, panic")["matches"]
    assert len(r) == 3 and [m["score"] for m in r] == sorted((m["score"] for m in r), reverse=True)


def test_triage_is_never_suggested():
    assert "triage" not in ids("I do not know what is happening")


def test_endpoint_returns_matches_with_the_words():
    r = client.post("/api/protocols/match", json={"text": "he is shaking and not responding"})
    assert r.status_code == 200
    b = r.json()
    assert b["mode"] == "rules" and b["provider"] == "none" and b["matches"][0]["id"] == "seizure" and b["fallback"] is None


@pytest.mark.parametrize("text", ["", "   ", "\n\t"])
def test_empty_input_is_422(text):
    assert client.post("/api/protocols/match", json={"text": text}).status_code == 422


def test_missing_or_huge_text_is_422():
    assert client.post("/api/protocols/match", json={}).status_code == 422
    assert client.post("/api/protocols/match", json={"text": "a" * 501}).status_code == 422


def test_the_ai_slot_can_only_reorder_known_protocols(monkeypatch):
    class Fake:
        name, configured = "fake", True

        def __init__(self, answer):
            self.answer = answer

        def complete(self, req):
            from canary.assistant.providers import ProviderResult
            return ProviderResult(ok=True, answer=self.answer)

    monkeypatch.setattr(ai_match, "get_provider", lambda: Fake('["cpr", "made_up", "seizure"]'))
    r = ai_match.match("he is shaking and not responding")
    assert r["mode"] == "ai" and [m["id"] for m in r["matches"]] == ["cpr", "seizure"]
    monkeypatch.setattr(ai_match, "get_provider", lambda: Fake("not json"))
    assert ai_match.match("he is shaking")["mode"] == "rules"


def test_every_emergency_protocol_has_keywords():
    for pid, p in protocols.bank()["protocols"].items():
        if pid != "triage":
            assert p["keywords"]["strong"], pid


# ---------------------------------------------------------------- the Protocols page
def lib(step=None):
    if step is not None:
        client.put("/api/mission", json={"step": step})
    return client.get("/api/protocols/library").json()


def test_library_lists_emergency_and_operational_protocols():
    b = lib(0)
    got = {p["id"] for p in b["emergency"]} | {p["id"] for p in b["operational"]}
    assert {"cpr", "seizure", "rad", "eva", "dose", "care", "sickness", "regravity", "air", "delay"} <= got
    assert "triage" not in got
    for p in b["emergency"] + b["operational"]:
        assert p["when"] and p["steps"] and p["watch"], p["id"]


def test_storm_puts_radiation_and_eva_in_force():
    b = lib(3)  # day 152, particle storm
    f = {i["id"]: i for i in b["in_force"]}
    assert f["rad"]["level"] == 2 and f["eva"]["level"] == 2 and "suspended" in f["eva"]["reason"]
    assert "Shelter" in next(p for p in b["emergency"] if p["id"] == "rad")["live"][0]


def test_no_storm_eva_is_open_away_from_earth_and_pre_flight_has_nothing():
    b = lib(2)  # day 147, in transit, no storm
    f = {i["id"]: i for i in b["in_force"]}
    assert "rad" not in f and f["eva"]["level"] == 0
    assert lib(0)["in_force"] == []  # learning: nothing is in force yet


def test_launch_puts_space_sickness_in_force():
    assert "sickness" in {i["id"] for i in lib(1)["in_force"]}


def test_care_window_is_for_the_medical_team_only_and_never_names_anyone():
    client.put("/api/mission", json={"step": 4})
    tok = client.post("/api/crew/t/session", json={"pin": "1004"}).json()["token"]
    em = client.post("/api/emergencies", json={}).json()
    client.post(f"/api/emergencies/{em['id']}", json={"close": True, "outcome": "stable", "patient": "t", "protocol": "seizure"})
    med = {"Authorization": "Bearer " + client.post("/api/medical/session", json={"pin": "1961"}).json()["token"]}
    crew = client.get("/api/protocols/library", headers={"X-Canary-Viewer": tok}).json()
    anon = client.get("/api/protocols/library").json()
    doc = client.get("/api/protocols/library", headers=med).json()
    assert "care" not in {i["id"] for i in anon["in_force"]} and "care" not in {i["id"] for i in crew["in_force"]}
    mine = next(i for i in doc["in_force"] if i["id"] == "care")
    assert mine["audience"] == "medical team"
    blob = str(anon) + str(crew) + str(doc)
    for name in ("Tomás", "Tomas", "Helena"):
        assert name not in blob


def test_crew_overview_warnings_point_to_the_protocol():
    client.put("/api/mission", json={"step": 3})
    w = client.get("/api/crew/overview").json()["warnings"]
    assert w and w[0]["protocol"] == "rad"
