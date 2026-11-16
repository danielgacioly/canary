"""Suggestions and goals: the all-clear gate, eligibility with reasons, one exercise target, general-guidance labels,
adherence before any advice outcome, and one definition of a kept day. Local and scripted only: no network, no API key."""
import os
import tempfile

os.environ.setdefault("CANARY_DB", os.path.join(tempfile.mkdtemp(), "test_wave_actions.db"))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from canary.assistant import suggestions  # noqa: E402
from canary.domain import advice, goals, mission  # noqa: E402
from canary.domain.catalog import PERSONAL_BY_ID  # noqa: E402
from canary.main import app  # noqa: E402
from tests.golden_capture import control_headers  # noqa: E402

client = TestClient(app)


@pytest.fixture(autouse=True)
def fresh():
    client.post("/api/demo/reset", headers=control_headers(client))
    client.put("/api/mission", json={"step": 2}, headers=control_headers(client))  # day 147: Helena has suggestions
    yield
    client.post("/api/demo/reset", headers=control_headers(client))


def test_an_all_clear_never_appears_while_an_alert_is_raised():
    f = suggestions.facts("h")
    out = suggestions.candidates({**f, "alert_level": 2, "care": None})
    assert all(not suggestions.ALL_CLEAR.search(" ".join([s["title"], s["why"], s["because_inside"]])) for s in out)


def test_a_rest_status_withholds_training_and_says_why():
    f = suggestions.facts("h")
    f2 = {**f, "duty": {"key": "rest", "label": "Rest"}}
    assert suggestions._withheld(f2, "exercise")
    skipped = []
    ids = [s["id"] for s in suggestions.candidates(f2, skipped)]
    assert not set(ids) & {"exercise", "bone"}
    assert all(s["reason"] for s in skipped)


def test_a_record_condition_withholds_only_the_matching_suggestion():
    f = suggestions.facts("h")
    f2 = {**f, "record": {"allergies": [], "conditions": ["Asthma"], "medications": []}}
    assert suggestions._withheld(f2, "exercise") is not None
    assert suggestions._withheld(f2, "hobby") is None


def test_the_goal_and_the_suggestions_read_one_exercise_target():
    f = suggestions.facts("h")
    level = f["risk"]["fatigue"]["level"]
    plan = goals.exercise_plan(f["location"], level)
    assert f["exercise_target"] == plan["minutes"]
    assert plan["minutes"] == round(plan["target"] * (100 - plan["pct"]) / 100)
    goal = goals._exercise_goal(PERSONAL_BY_ID["exercise"], f["location"], 2)
    assert f"about {goals.exercise_plan(f['location'], 2)['minutes']} min" in goal["title"]


def test_times_and_amounts_are_labelled_as_general_guidance():
    its = suggestions.candidates(suggestions.facts("h"))
    assert its and all(s["guidance"] in ("general", "personal") for s in its)
    assert all(s["guidance_note"] == suggestions.GENERAL_NOTE for s in its if s["guidance"] == "general")


def test_no_outcome_without_recorded_adherence(monkeypatch):
    row = {"crew_id": "zz", "goal_id": "sg_sleep", "indicator": "sleep", "risk": None, "start_day": 10, "check_day": 17, "start_bad": 1.0}
    monkeypatch.setattr(advice, "_bad", lambda crew, ind, day: 0.0)
    assert advice.outcome(row, 20) == "no_adherence"
    for d in range(10, 15):
        goals.set_done("zz", "sg_sleep", d, True)
    assert advice.outcome(row, 20) == "improved"


def test_a_kept_day_and_a_history_count_have_one_definition():
    assert goals.day_met({"done": ["a", "b", "c"], "total": 4})
    assert not goals.day_met({"done": ["a", "b"], "total": 4})
    assert not goals.day_met({"done": [], "total": 0})
    hist = goals._history("h", mission.state()["day"])
    assert all(v["count"] == len(v["done"]) for v in hist.values())
