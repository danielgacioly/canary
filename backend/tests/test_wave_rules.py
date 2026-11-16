"""Rules and data, one focused test per fix (RULE-01, 02, 04, 05, 06, 07, 08, 09, 10, DATA-01, 05, 06, 08).

The pure ones call the rule function directly with plain dicts. The ones that need stored data load the demo package
once through tests/support.py, like the other tests.
"""
import os
import tempfile

os.environ.setdefault("CANARY_DB", os.path.join(tempfile.mkdtemp(), "wave_rules.db"))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from canary.config import settings  # noqa: E402
from canary.domain import assumptions as A  # noqa: E402
from canary.domain import catalog, goals, health, mission, plan, reference, risk, telemetry  # noqa: E402
from canary.main import app  # noqa: E402
from tests import golden_capture as gc  # noqa: E402
from tests.support import GROUND, control_headers, crew_headers, empty, fresh as fresh_demo  # noqa: E402

client = TestClient(app)


@pytest.fixture
def demo(monkeypatch):
    monkeypatch.setattr(settings, "live_space_weather", False)
    fresh_demo(client)
    yield
    fresh_demo(client)


def test_every_assumption_is_unreviewed_until_a_reviewer_signs_it():
    rows = A.table()
    assert rows and all(r["validation_status"] == "heuristic, unreviewed" and r["reviewer"] is None for r in rows)
    assert A.review_summary()["unreviewed"] == A.review_summary()["total"] == len(rows)


def test_a_baseline_records_the_policy_version_and_its_coverage(demo):
    crew = gc.CREW_IDS[0]
    b = health.baselines(crew)["sleep"]
    assert b["policy"]["version"] == A.value("baseline.policy_version")
    assert b["policy"]["min_days"] == catalog.INDICATORS["sleep"].get("min_baseline", A.value("baseline.min_points"))
    assert b["policy"]["coverage_days"] >= b["n"] or b["from"] == "learning"


def test_bp_and_pulse_explain_each_other_only_in_the_expected_direction_and_position():
    def ind(delta, level, position):
        return {"delta": delta, "level": level, "value": 100, "context": {"position": position} if position else {}}

    standing = {"sbp": ind(-12, 1, "standing"), "dbp": ind(-5, 0, "standing"), "hr": ind(14, 1, None)}
    assert health.regravity_pattern(standing)
    assert not health.regravity_pattern({**standing, "hr": ind(-14, 1, None)})  # pulse lower: not the pattern
    assert not health.regravity_pattern({**standing, "sbp": ind(-12, 1, "seated"), "dbp": ind(-5, 0, "seated")})  # seated reading


def test_a_duration_text_is_generated_from_the_measured_days():
    assert health.duration_words(14) == "two weeks"
    assert health.duration_words(9) == "9 days"
    assert health.duration_words(3) == "three days"


def test_a_chronic_out_of_range_exam_still_flags_a_new_worsening(monkeypatch):
    from canary.domain import telemetry as tel
    recent = {d: 1.0 for d in range(80, 100)}  # the person's own level before this exam: 1.0
    monkeypatch.setattr(tel, "day_values", lambda crew, ind, d0, d1: {d: v for d, v in recent.items() if d0 <= d <= d1})
    assert risk._worsening("c", "lym", 100, 0.5, 0.9, None) is not None  # 50 % further below the recent level
    assert risk._worsening("c", "lym", 100, 0.95, 0.9, None) is None  # still out, but not moving


def test_derived_evidence_adds_points_but_is_not_an_independent_signal(monkeypatch):
    monkeypatch.setattr(risk, "_day_ms", lambda day: {"day": day, "location": "earth", "learning": False, "storm": None})
    derived = [{"key": "bone", "points": 2.0, "derived": True}, {"key": "dose", "points": 2.0, "derived": True}]
    monkeypatch.setitem(risk.GATHER, "immune", lambda crew, ms, tok: derived)
    e = risk._g_eval("immune", "derived-only", 7, None, ("t",))
    assert e["score"] >= risk.SPECS["immune"]["cuts"][2] and e["level"] < 2  # two derived signals never make level 2


def test_history_reads_the_place_the_screen_shows_today(monkeypatch):
    from canary.domain import mission
    monkeypatch.setattr(plan, "location_at", lambda d: "transit")
    monkeypatch.setattr(mission, "_get", lambda: {"location": "moon"})
    assert goals._place_on(5, 5) == "moon"  # today: the crew's override
    assert goals._place_on(4, 5) == "transit"  # another day: the plan


def test_check_ins_and_storms_still_speak_while_the_baseline_is_learned(monkeypatch):
    monkeypatch.setattr(health, "storm_info", lambda crew, ms: None)
    monkeypatch.setattr(health, "latest_checkin", lambda crew, kind, day, window=7: {"distortion": True, "day": day} if kind == "amsler" else None)
    monkeypatch.setattr(goals, "_log", lambda crew: {(0, "mood"): (True, None)})
    ms = {"day": 0, "location": "earth", "learning": True, "storm": None}
    al = health._alerts("c", ms, {})
    assert [a["id"] for a in al] == ["amsler"]


def test_an_organ_colour_includes_the_alerts_that_belong_to_it(monkeypatch):
    monkeypatch.setattr(health, "latest_checkin", lambda *a, **k: None)
    monkeypatch.setattr(health, "dose", lambda ms, crew: {"career_pct_of_limit": 0, "career_msv": 0})
    monkeypatch.setattr(health, "storm_info", lambda crew, ms: None)
    monkeypatch.setattr(health.data, "storms_following", lambda *a, **k: [])
    inds = {i: {"level": 0, "population": {"status": "in"}, "standard": None, "status": "ok"} for i in catalog.INDICATORS}
    ms = {"day": 3, "location": "earth", "learning": False, "storm": None}
    s = health.systems("c", ms, inds, [], [{"sys": "brain", "level": 1, "data": False}])
    assert s["brain"]["level"] == 1 and s["brain"]["status"] == "Watch"


def test_a_query_before_the_first_reading_never_returns_a_future_value(demo):
    crew = gc.CREW_IDS[0]
    days = sorted(telemetry.day_values(crew, "sleep", -10**6, 10**6))
    first = days[0]
    before = telemetry.series_points(crew, "sleep", first - 1, 3)
    assert all(p["value"] is None for p in before)
    assert telemetry.observation(crew, "sleep", first - 1)["value"] is None


def test_each_trend_value_carries_the_origin_of_its_reading(demo):
    crew = gc.CREW_IDS[0]
    last = max(telemetry.day_values(crew, "sleep", -10**6, 10**6))
    pts = telemetry.series_points(crew, "sleep", last, 5)
    valued = [p for p in pts if p["value"] is not None]
    assert valued and all(p["origin"] for p in valued)
    assert all(p["origin"] is None for p in pts if p["value"] is None)


def test_a_person_who_is_neither_f_nor_m_takes_the_widest_range():
    other = reference.check("water", None, 1.7)  # F 1.6, M 2.0: widest low is 1.6, so 1.7 is in range
    assert other["low"] == 1.6 and other["status"] == "in" and other["sex_policy"]
    assert reference.check("grip", "M", 20)["status"] == "out"  # a man has his own range (27)
    assert reference.check("grip", None, 20)["low"] == 16  # no sex: the widest, so 20 kg is in range


def test_a_new_person_in_a_seat_inherits_no_baseline_exam_or_checkin_of_the_one_before(monkeypatch):
    """DATA-01: after a reset, registering someone in a seat the demo used (h) starts from nothing."""
    monkeypatch.setattr(settings, "live_space_weather", False)
    fresh_demo(client)
    old = crew_headers(client, "h")
    assert client.post("/api/checkins", headers=old, json={"crew_id": "h", "kind": "mood", "payload": {"mood": 4, "stress": 2}}).status_code == 200
    assert client.get("/api/checkins/h", headers=old).json()["recent"]  # the demo person has a check-in
    assert client.get("/api/crew/h", headers=old).json()["blood"]["timepoints"]  # and exams
    empty(client)
    newcomer = {"seat": "h", "name": "Ines Almeida", "role": "Commander", "home": "Somewhere", "pin": "4001", "dob": "1990-04-10",
                "sex": "Female", "nationality": "Portuguese", "languages": ["Portuguese"], "agency": "Test agency", "flights": 0,
                "days_in_space": 0, "height_cm": 170, "weight_kg": 68, "blood_type": "A+", "skin_type": "III", "handedness": "Right", "eva": "surface"}
    mission_form = {"callsign": "Test 1", "name": "Test mission", "launch_date": "2036-03-01", "preset": "mars", "dose_waiver": True}
    r = client.post("/api/control/register", headers=control_headers(client), json={"crew": [newcomer], "mission": mission_form, "ground": GROUND})
    assert r.status_code == 200
    new = {"Authorization": "Bearer " + gc._token(client, "/api/crew/h/session", "4001")}
    assert client.get("/api/checkins/h", headers=new).json()["recent"] == []
    crew = client.get("/api/crew/h", headers=new).json()
    assert crew["blood"]["timepoints"] == [] and crew["blood"]["analytes"] == {}
    snap = health.snapshot("h", mission.state())
    assert snap["indicators"] and all(i["baseline"] is None for i in snap["indicators"].values())


def test_medical_can_list_observation_ids_for_a_correction_and_nobody_else_can(demo):
    """The 'Correct a value' form: recent readings with their ids, no photos or free text, medical team only."""
    med = gc.medical_headers(client)
    rows = client.get("/api/medical/observations/h?indicator=hr&limit=5", headers=med).json()
    assert 0 < len(rows) <= 5 and all(r["indicator"] == "hr" and set(r) == {"id", "indicator", "day", "value", "unit", "origin"} for r in rows)
    assert rows == sorted(rows, key=lambda r: -r["day"])
    assert client.get("/api/medical/observations/h", headers=crew_headers(client, "h")).status_code == 401
    assert client.get("/api/medical/observations/nobody", headers=med).status_code == 404
