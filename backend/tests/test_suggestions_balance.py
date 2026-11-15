"""Suggestions balance the outside (place, storm, phase, delay) and the inside (the person's own state), rank by both,
learn a small weight from each person's own choices, and never expose another person's data."""
import os
import tempfile

os.environ["CANARY_DB"] = os.path.join(tempfile.mkdtemp(), "suggestions.db")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from canary import db  # noqa: E402
from canary.assistant import suggestions  # noqa: E402
from canary.config import settings  # noqa: E402
from canary.domain import protocols  # noqa: E402
from canary.main import app  # noqa: E402
from tests.golden_capture import reset_demo  # noqa: E402
from tests.support import GROUND, control_headers, crew_headers, empty, fresh as fresh_demo, medical_headers  # noqa: E402,F401

client = TestClient(app)


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    monkeypatch.setattr(settings, "mission_package", "odyssey1-mars")
    monkeypatch.setattr(settings, "live_space_weather", False)
    reset_demo(client)


def tok(cid, pin):
    return {"X-Canary-Viewer": client.post(f"/api/crew/{cid}/session", json={"pin": pin}).json()["token"]}


H, K = lambda: tok("h", "1001"), lambda: tok("k", "1002")  # noqa: E731


def items(cid="h", pin="1001"):
    return client.get(f"/api/suggestions/{cid}", headers=tok(cid, pin)).json()["items"]


def go(step):
    client.put("/api/mission", json={"step": step}, headers=control_headers(client))


def test_every_suggestion_carries_both_reasons_a_protocol_and_its_rank():
    go(3)
    for s in items():
        assert {"because_outside", "because_inside", "protocol", "rank"} <= set(s)
        assert s["because_outside"] or s["because_inside"], s["id"]
        assert set(s["rank"]) >= {"priority", "both", "learned", "score"}
        assert s["protocol"] is None or s["protocol"] in protocols.bank()["protocols"] or s["protocol"] in protocols.bank()["operational"]["protocols"]


def test_the_storm_puts_the_radiation_protocol_first_among_the_environmental_ones():
    go(3)
    s = {x["id"]: x for x in items()}
    assert s["storm"]["protocol"] == "rad" and "storm" in s["storm"]["because_outside"].lower()
    assert "mSv" in s["storm"]["because_inside"]  # the person's own career dose, the inside half
    go(2)
    assert "storm" not in {x["id"] for x in items()}


def test_launch_and_the_next_leg_bring_their_own_protocol():
    go(1)
    assert {x["id"]: x for x in items()}["firstdays"]["protocol"] == "sickness"
    go(2)
    assert {x["id"]: x for x in items()}["prepare"]["protocol"] == "regravity"


def test_ranking_favours_suggestions_that_speak_to_both_sides():
    both = {"id": "a", "priority": 60, "because_outside": "x", "because_inside": "y"}
    one = {"id": "b", "priority": 70, "because_outside": "", "because_inside": "y"}
    r = lambda s: suggestions.rank_of(s, {})["score"]  # noqa: E731
    assert r(both) == 60 + suggestions.BOTH_BONUS > r(one) == 70


def test_the_learned_weight_is_a_small_bounded_plain_count():
    w = suggestions.learned_weight
    assert w(0, 0) == 0 and w(1, 0) > 0 > w(0, 1)
    assert w(3, 0) > w(1, 0)  # more evidence, more weight
    assert abs(w(1000, 0)) <= suggestions.LEARN_MAX and abs(w(0, 1000)) <= suggestions.LEARN_MAX
    assert w(2, 2) == 0


def test_dismissing_hides_it_today_and_lowers_the_next_ranking():
    go(2)
    before = {x["id"]: x for x in items()}
    assert "social" in before
    r = client.post("/api/suggestions/h/social/dismiss", headers=H())
    assert r.status_code == 200 and "social" not in {x["id"] for x in r.json()["items"]}
    assert db.q("SELECT action FROM suggestion_feedback WHERE crew_id='h' AND sid='social'")[0]["action"] == "dismiss"
    f = suggestions.facts("h")
    c = {x["id"]: x for x in suggestions.candidates(f)}["social"]
    rk = suggestions.rank_of(c, suggestions.choices("h"))
    assert rk["learned"] < 0 and rk["dismissed"] == 1


def test_accepting_raises_the_weight_of_that_kind_of_suggestion():
    go(2)
    client.post("/api/suggestions/h/sleep/accept", headers=H())
    rk = suggestions.rank_of({"id": "sleep", "priority": 90, "because_outside": "", "because_inside": "y"}, suggestions.choices("h"))
    assert rk["learned"] > 0 and rk["accepted"] == 1


def test_one_persons_choices_never_move_another_persons_ranking():
    go(2)
    client.post("/api/suggestions/h/sleep/accept", headers=H())
    client.post("/api/suggestions/h/social/dismiss", headers=H())
    assert suggestions.choices("k") == {}
    for s in items("k", "1002"):
        assert s["rank"]["learned"] == 0 and s["rank"]["accepted"] == 0 and s["rank"]["dismissed"] == 0


def test_suggestions_and_choices_are_private():
    go(3)
    for path in ("/api/suggestions/h", "/api/suggestions/h/sleep/accept", "/api/suggestions/h/sleep/dismiss"):
        post = path.endswith(("accept", "dismiss"))
        for headers in (K(), {}):
            r = (client.post if post else client.get)(path, headers=headers)
            assert r.status_code == 403, (path, r.status_code)
    med = {"Authorization": "Bearer " + medical_headers(client)["Authorization"][7:]}
    assert client.get("/api/suggestions/h", headers=med).status_code == 403  # the medical team reads the medical console, not these


def test_a_persons_suggestions_cite_only_their_own_records():
    go(3)
    for cid, pin in (("h", "1001"), ("k", "1002"), ("a", "1003")):
        blob = str(items(cid, pin))
        for other in ("h", "k", "a", "t"):
            if other != cid:
                assert f"checkin:{other}:" not in blob and f"advice:{other}:" not in blob


def test_an_unknown_suggestion_cannot_be_dismissed():
    assert client.post("/api/suggestions/h/nope/dismiss", headers=H()).status_code == 404


def test_the_outside_lines_are_the_same_for_everyone_aboard():
    go(3)
    a = {x["id"]: x["because_outside"] for x in items("h", "1001")}
    b = {x["id"]: x["because_outside"] for x in items("k", "1002")}
    for sid in set(a) & set(b) & {"storm", "breathe"}:
        assert a[sid] == b[sid]
