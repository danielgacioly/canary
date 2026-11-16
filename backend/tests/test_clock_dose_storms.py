"""Phase 3: the engine knows no demo. The mission day comes from the clock, a storm is a space event, the dose comes from
dosimeters (and the plan where there are none), the goal history starts where the person's log starts."""
import datetime as dt
import os
import tempfile

os.environ["CANARY_DB"] = os.path.join(tempfile.mkdtemp(), "phase3.db")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from canary import db  # noqa: E402
from canary.config import settings  # noqa: E402
from canary.domain import advice, data, dose, goals, health, live, mission, notify, plan, registry, risk  # noqa: E402
from canary.main import app  # noqa: E402
from tests.golden_capture import reset_demo  # noqa: E402
from tests.support import GROUND, control_headers, crew_headers, empty, fresh as fresh_demo, medical_headers  # noqa: E402,F401

client = TestClient(app)
LAUNCH = dt.date(2035, 6, 1)


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    monkeypatch.setattr(settings, "mission_package", "odyssey1-mars")
    monkeypatch.setattr(settings, "live_space_weather", False)
    reset_demo(client)
    yield
    reset_demo(client)


def ctl():
    return control_headers(client)


def me(cid="h", pin="1001"):
    return {"Authorization": "Bearer " + client.post(f"/api/crew/{cid}/session", json={"pin": pin}).json()["token"]}


def medical():
    return medical_headers(client)


def day(d):
    return client.put("/api/mission", json={"day": d}, headers=control_headers(client)).json()


def empty_database(monkeypatch):
    """No package at all: the app starts empty (no measurements, no scenes), then Mission Control registers the demo crew."""
    monkeypatch.setattr(settings, "mission_package", "")
    assert reset_demo(client).status_code == 200
    form = data.demo_form()
    assert client.post("/api/control/register", headers=ctl(), json={"crew": form["crew"], "mission": form["mission"], "ground": form["ground"]}).status_code == 200


# ---------------------------------------------------------------- clock
def test_the_demo_starts_on_the_package_date_and_a_scene_jump_sets_the_simulated_date():
    ms = client.get("/api/mission").json()
    assert ms["day"] == -30 and ms["clock"] == {"mode": "simulated", "date": "2035-05-02", "time": "12:00"} and not ms["custom_day"]
    ms = client.put("/api/mission", json={"step": 3}, headers=control_headers(client)).json()
    assert ms["day"] == 152 and ms["step"] == 3 and ms["storm"] == "sep" and not ms["custom_day"]
    assert ms["clock"]["date"] == (LAUNCH + dt.timedelta(days=152)).isoformat() and ms["clock"]["mode"] == "simulated"
    assert ms["story"]["day"] == 152 and ms["steps"] == 6 and ms["suggested_user"] == "h"
    assert db.get_setting("mission")["scene"] == 3


def test_a_scene_jump_clears_the_place_the_crew_had_chosen():
    client.put("/api/mission", json={"step": 3, "location": "earth"}, headers=control_headers(client))  # step first, then the override
    assert client.get("/api/mission").json()["location_override"] is True
    ms = client.put("/api/mission", json={"step": 4}, headers=control_headers(client)).json()
    assert ms["location"] == "transit" and ms["location_override"] is False


def test_set_day_moves_the_date_and_forgets_the_scene():
    client.put("/api/mission", json={"step": 3}, headers=control_headers(client))
    ms = day(10)
    assert ms["day"] == 10 and ms["custom_day"] and ms["clock"]["date"] == (LAUNCH + dt.timedelta(days=10)).isoformat()
    assert db.get_setting("mission")["scene"] is None
    assert client.put("/api/mission", json={"clear_day": True}, headers=control_headers(client)).json()["clock"]["mode"] == "real"


def test_with_the_launch_date_yesterday_the_real_date_gives_day_one(monkeypatch):
    now = dt.datetime(2040, 3, 5, 14, 5, tzinfo=dt.timezone.utc)
    monkeypatch.setattr(mission, "_now", lambda: now)
    monkeypatch.setattr(registry, "launch_date", lambda: (now.date() - dt.timedelta(days=1)).isoformat())
    r = client.put("/api/control/clock", json={"real": True}, headers=ctl())
    assert r.status_code == 200
    ms = client.get("/api/mission").json()
    assert ms["day"] == 1 and ms["clock"] == {"mode": "real", "date": "2040-03-05", "time": "14:05"}
    assert mission.mission_time() == "14:05"  # goals use this time, not a constant


def test_the_control_clock_sets_a_simulated_date_and_time():
    r = client.put("/api/control/clock", json={"date": "2035-07-01", "time": "08:30"}, headers=ctl())
    assert r.status_code == 200
    ms = r.json()
    assert ms["day"] == 30 and ms["clock"] == {"mode": "simulated", "date": "2035-07-01", "time": "08:30"} and ms["custom_day"]
    assert mission.mission_time() == "08:30"
    ms = client.put("/api/control/clock", json={"date": "2035-07-02"}, headers=ctl()).json()
    assert ms["clock"]["time"] == "08:30"  # the time is kept when only the date is sent


@pytest.mark.parametrize("body,field", [({}, "date"), ({"date": "2035-13-45"}, "date"), ({"date": "tomorrow"}, "date"),
                                        ({"date": 20350601}, "date"), ({"date": "1800-01-01"}, "date"),
                                        ({"date": "2035-06-01", "time": "25:00"}, "time"), ({"date": "2035-06-01", "time": 1200}, "time"),
                                        ({"real": "yes"}, "real")])
def test_the_control_clock_refuses_bad_input(body, field):
    before = client.get("/api/mission").json()["clock"]
    r = client.put("/api/control/clock", json=body, headers=ctl())
    assert r.status_code == 422 and r.json()["detail"][0]["field"] == field
    assert client.get("/api/mission").json()["clock"] == before


def test_the_control_clock_needs_the_control_session():
    assert client.put("/api/control/clock", json={"real": True}).status_code in (401, 403)
    assert client.put("/api/control/clock", json={"real": True}, headers=me()).status_code in (401, 403)


def test_a_day_change_runs_the_sync_once_per_day(monkeypatch):
    calls = []
    monkeypatch.setattr(advice, "sync_all", lambda d: calls.append(("advice", d)))
    monkeypatch.setattr(notify, "sync", lambda ms, ids=None: calls.append(("notify", ms["day"])))
    db.set_setting("last_synced_day", None)
    assert mission.sync_day() is True and calls == [("advice", -30), ("notify", -30)]
    assert mission.sync_day() is False and len(calls) == 2  # same day: nothing
    mission.set_day(5)
    assert mission.sync_day() is True and calls[2:] == [("advice", 5), ("notify", 5)]
    client.put("/api/control/clock", json={"date": "2035-06-11"}, headers=ctl())  # a clock change syncs at once
    assert calls[4:] == [("advice", 10), ("notify", 10)]
    client.put("/api/mission", json={"step": 3}, headers=control_headers(client))
    assert calls[6:] == [("advice", 152), ("notify", 152)]


def test_a_failing_sync_never_raises_from_the_background_helper(monkeypatch):
    def boom(_d):
        raise RuntimeError("no")
    monkeypatch.setattr(advice, "sync_all", boom)
    assert mission.safe_sync_day(force=True) is False


def test_the_app_starts_empty_without_scenes_and_the_story_calls_do_not_crash(monkeypatch):
    empty_database(monkeypatch)
    ms = client.get("/api/mission").json()
    assert ms["steps"] == 0 and ms["story"] is None and ms["suggested_user"] is None and ms["step"] == 0
    r = client.put("/api/mission", json={"step": 2}, headers=control_headers(client))
    assert r.status_code == 200 and r.json()["story"] is None
    assert client.get("/api/catalog").json()["story"] == []


def test_a_package_date_in_mission_csv_is_the_clock_start():
    assert db.get_setting("sim_date") == "2035-05-02" and data.mission_time() == "12:00"


# ---------------------------------------------------------------- storms are space events
def test_a_storm_event_turns_on_the_storm_the_radiation_evidence_and_the_immune_note_for_thirteen_days():
    X = 60
    assert day(X)["storm"] is None
    r = client.post("/api/control/space-events", headers=ctl(), json={
        "kind": "sep", "start_day": X, "locations": ["transit"], "extra_dose_msv": 12, "origin": "simulated", "source": "test"})
    assert r.status_code == 200
    eid = r.json()["id"]

    def look(d):
        ms = day(d)
        snap = health.snapshot("h", ms)
        rad = next(x for x in risk.evaluate("h", ms) if x["id"] == "radiation")
        immune = snap["systems"]["immune"]["note"]
        return ms, rad, immune

    ms, rad, immune = look(X - 1)
    assert ms["storm"] is None and immune != "Blood count due after the radiation storm."
    assert not any("storm is in progress" in e["text"] for e in rad["evidence"])
    ms, rad, immune = look(X)
    assert ms["storm"] == "sep"
    # the cabin dosimeter still reads its quiet rate that day: the shelter rule (measured rate above 3x the quiet rate) is not met,
    # so the event is a watch, and the text says why, from the event itself
    assert rad["level"] == 1 and any("No shelter ordered" in e["text"] and "source: test" in e["text"].lower().replace("source: test", "source: test") for e in rad["evidence"])
    assert any(a["id"] == "storm" for a in health.snapshot("h", ms)["alerts"])
    assert immune == "Blood count due after the radiation storm."
    ms, rad, immune = look(X + 1)  # the storm was one day long; the follow-up goes on
    assert ms["storm"] is None and immune == "Blood count due after the radiation storm."
    assert any("Blood count due after the radiation storm" in e["text"] for e in next(x for x in risk.evaluate("h", ms) if x["id"] == "immune")["evidence"])
    ms, rad, immune = look(X + 13)
    assert immune == "Blood count due after the radiation storm."
    ms, rad, immune = look(X + 14)
    assert immune != "Blood count due after the radiation storm."
    assert not any("Blood count due" in e["text"] for e in next(x for x in risk.evaluate("h", ms) if x["id"] == "immune")["evidence"])


def test_a_storm_at_another_place_does_not_hit_the_crew():
    client.post("/api/control/space-events", headers=ctl(), json={"kind": "sep", "start_day": 60, "locations": ["moon"], "extra_dose_msv": 12})
    assert day(60)["storm"] is None
    assert not health.snapshot("h", day(61))["systems"]["immune"]["note"]


def test_the_demo_storms_still_come_from_the_events_table():
    assert {e["id"]: (e["kind"], e["start_day"], e["locations"]) for e in data.events()} == {"replay-2024-05-10-sep": ("sep", 152, ["transit", "moon"]), "replay-2024-05-20-rad": ("mars", 222, ["mars"])}
    assert client.put("/api/mission", json={"step": 5}, headers=control_headers(client)).json()["storm"] == "mars"
    # the Mars surface storm adds no dose, so it calls for no blood count
    assert health.snapshot("h", mission.state())["systems"]["immune"]["note"] != "Blood count due after the radiation storm."
    assert data.storm_at(152, "transit") == "sep" and data.storm_at(152, "earth") is None and data.storm_at(153, "transit") is None


def test_space_weather_carries_the_active_event():
    client.put("/api/mission", json={"step": 3}, headers=control_headers(client))
    sw = client.get("/api/space-weather").json()
    assert sw["active"] and sw["headline"] == "Solar particle storm in progress"
    assert sw["event"] == {"id": "replay-2024-05-10-sep", "kind": "sep", "origin": "simulated", "source": "simulated", "live": False}
    client.put("/api/mission", json={"step": 0}, headers=control_headers(client))
    sw = client.get("/api/space-weather").json()
    assert not sw["active"] and sw["headline"] == "Calm" and "event" not in sw


# ---------------------------------------------------------------- live DONKI events (no network: a fake fetch)
def _real_clock(monkeypatch, launch_days_ago=20):
    now = dt.datetime(2040, 3, 5, 14, 5, tzinfo=dt.timezone.utc)
    monkeypatch.setattr(mission, "_now", lambda: now)
    monkeypatch.setattr(registry, "launch_date", lambda: (now.date() - dt.timedelta(days=launch_days_ago)).isoformat())
    client.put("/api/control/clock", json={"real": True}, headers=ctl())
    return now


def test_donki_events_become_space_events_on_their_mission_day(monkeypatch):
    now = _real_clock(monkeypatch)
    monkeypatch.setattr(settings, "live_space_weather", True)
    ask = []
    sep = [{"activityID": "2040-03-01T10:00:00-SEP-001", "eventTime": "2040-03-01T10:00Z"},   # day 16: in transit
           {"activityID": "2040-02-01T10:00:00-SEP-001", "eventTime": "2040-02-01T10:00Z"},   # day -13: on Earth, ignored
           {"activityID": "", "eventTime": "2040-03-02T10:00Z"}, {"eventTime": "2040-03-02T10:00Z"}, {"activityID": "x"}]  # odd rows

    def fetch(a, b):
        ask.append((a, b))
        return sep

    assert live.import_donki(fetch) == 1
    assert ask == [(now.date() - dt.timedelta(days=30), now.date())]
    e = data.event("donki:2040-03-01T10:00:00-SEP-001")
    assert (e["kind"], e["origin"], e["source"], e["start_day"], e["locations"]) == ("sep", "donki", "nasa:donki", 16, ["transit"])
    assert data.storm_at(16, "transit") == "sep" and data.storm_event(16, "transit")["id"] == e["id"]
    assert live.import_donki(fetch) == 0 and len([x for x in data.events() if x["origin"] == "donki"]) == 1  # deduplicated by id


def test_donki_import_does_nothing_offline_or_off_or_on_a_simulated_clock(monkeypatch):
    _real_clock(monkeypatch)
    n = len(data.events())

    def offline(a, b):
        raise OSError("no network")

    monkeypatch.setattr(settings, "live_space_weather", True)
    assert live.import_donki(offline) == 0
    assert live.import_donki(lambda a, b: "not a list") == 0
    monkeypatch.setattr(settings, "live_space_weather", False)
    assert live.import_donki(lambda a, b: [{"activityID": "a", "eventTime": "2040-03-01T10:00Z"}]) == 0
    monkeypatch.setattr(settings, "live_space_weather", True)
    client.put("/api/control/clock", json={"date": "2040-03-05"}, headers=ctl())  # a simulated clock: the replay owns the events
    assert live.import_donki(lambda a, b: [{"activityID": "a", "eventTime": "2040-03-01T10:00Z"}]) == 0
    assert len(data.events()) == n


# ---------------------------------------------------------------- dose
def rows(crew, values, origin="real"):
    return [{"crew_id": crew, "indicator": "dose_eq_rate", "value": v, "unit": "mSv/day", "day": d, "origin": origin,
             "method": "dosimeter", "source": "test:dosimeter"} for d, v in values.items()]


def test_the_dose_is_partial_when_only_some_days_have_a_dosimeter(monkeypatch):
    empty_database(monkeypatch)
    ms = day(4)  # rocket days 0..3, then transit
    assert plan.location_at(3) == "rocket" and plan.location_at(4) == "transit"
    e = dose.mission(None, 4)
    assert e["origin"] == "estimated" and e["measured_days"] == 0 and e["estimated_days"] == 5 and e["simulated"]
    assert e["msv"] == round(4 * 0.5 + 1.8, 1)  # four days in the rocket, today in transit: all from the plan
    data.add_observations(rows("cabin", {0: 1.0, 1: 2.0, 2: 3.0}))
    p = dose.mission(None, 4)
    assert (p["origin"], p["measured_days"], p["estimated_days"]) == ("partial", 3, 2)
    assert p["msv"] == round(1.0 + 2.0 + 3.0 + 0.5 + 1.8, 1) == 8.3  # three readings, day 3 from the plan, today's place rate
    d = health.dose(ms)
    assert (d["origin"], d["measured_days"], d["estimated_days"], d["mission_msv"], d["simulated"]) == ("partial", 3, 2, 8.3, True)
    assert d["rate_msv_day"] == 1.8
    data.add_observations(rows("cabin", {3: 4.0, 4: 5.0}))  # now every day has a reading
    full = health.dose(ms)
    assert (full["origin"], full["measured_days"], full["estimated_days"], full["mission_msv"]) == ("measured", 5, 0, 15.0)
    assert full["simulated"] is False  # all measured, none of them from a simulation


def test_a_measured_day_is_not_counted_twice_with_its_storm_and_an_estimated_day_adds_it(monkeypatch):
    empty_database(monkeypatch)
    client.post("/api/control/space-events", headers=ctl(), json={"kind": "sep", "start_day": 10, "locations": ["transit"], "extra_dose_msv": 20})
    assert dose.mission(None, 11)["msv"] == round(0.5 * 4 + 1.8 * 8 + 20, 1)  # days 0..3 rocket, 4..11 transit, the storm once
    data.add_observations(rows("cabin", {10: 21.8}))  # the dosimeter saw the storm: the reading holds it
    assert dose.mission(None, 11)["msv"] == round(0.5 * 4 + 1.8 * 6 + 21.8 + 1.8, 1)
    assert dose.curve(None, 11)[11] == dose.mission(None, 11)["msv"]
    assert dose.curve(None, 11)[20] == round(0.5 * 4 + 1.8 * 6 + 21.8 + 1.8 * 10, 1)  # later days: the plan


def test_a_personal_dosimeter_wins_over_the_cabin_for_that_person_only(monkeypatch):
    empty_database(monkeypatch)
    data.add_observations(rows("cabin", {0: 1.0, 1: 1.0, 2: 1.0}) + rows("h", {1: 9.0}))
    assert dose.mission(None, 2)["msv"] == 3.0 and dose.mission("k", 2)["msv"] == 3.0
    mine = dose.mission("h", 2)
    assert mine["msv"] == 11.0 and mine["personal"] is True and dose.mission(None, 2)["personal"] is False


def test_the_projection_uses_the_plan_after_today_and_names_the_day_the_limit_is_passed():
    p = dose.projection(None, 100, 0.0)
    assert p["cross_day"] == 513 and p["mission_msv"] == dose.mission(None, 100)["msv"]


def test_crew_wide_pages_never_show_a_personal_dosimeter_but_the_person_does():
    client.put("/api/mission", json={"step": 3}, headers=control_headers(client))
    paths = ["/api/crew/overview", "/api/mission/overview", "/api/plan/conditions", "/api/leaderboard", "/api/space-weather"]

    def crew_wide():
        out = {p: client.get(p, headers=ctl()).json() for p in paths}
        out["control"] = client.get("/api/control/overview", headers=ctl()).json()
        out["medical-list-dose"] = client.get("/api/crew", headers=medical()).json()["dose"]
        return out

    from tests import golden_capture as gc
    before = gc.normalise(crew_wide())
    own_before = client.get("/api/crew/h", headers=me()).json()
    cabin = data.daily("cabin", "dose_eq_rate", 0, 151)
    data.add_observations(rows("h", {d: round(v[0] + 0.1, 2) for d, v in cabin.items()}))  # 15 mSv more than the cabin read
    assert gc.normalise(crew_wide()) == before
    own = client.get("/api/crew/h", headers=me()).json()
    assert own["dose"]["mission_msv"] > own_before["dose"]["mission_msv"] + 10
    assert own["dose"]["origin"] == "measured" or own["dose"]["measured_days"] > 100
    rad = next(r for r in own["risks"] if r["id"] == "radiation")
    assert rad["dose"]["same_for_everyone"] is False
    as_medical = client.get("/api/crew/h", headers=medical()).json()
    assert as_medical["dose"]["mission_msv"] == own["dose"]["mission_msv"]
    other = client.get("/api/crew/k", headers=me("k", "1002")).json()  # nobody else sees it
    assert other["dose"]["mission_msv"] == own_before["dose"]["mission_msv"]


# ---------------------------------------------------------------- goals: the history starts where the log starts
def test_each_history_starts_on_the_persons_first_logged_day():
    assert not hasattr(goals, "HISTORY_START")
    assert {c: goals._start(c, 0) for c in "hkat"} == {c: -30 for c in "hkat"}
    assert min(goals._history("h", 100)) == -30


def test_a_person_with_no_log_starts_on_the_first_day_of_the_plan_and_completes_nothing():
    db.x("DELETE FROM goal_log")
    assert goals._start("h", 10) == plan.get()["legs"][0]["start"]
    p = goals.profile("h", 10)
    assert p["completion_7d"] == 0 and p["streak"] == 0 and p["goals_week"] == 0
    lb = goals.leaderboard(10)
    assert [r["completion_7d"] for r in lb["rows"]] == [0, 0, 0, 0]
    assert goals.crew_board(10)["crew_streak"] == 0


def test_completion_and_streak_count_only_from_the_persons_first_day():
    db.x("DELETE FROM goal_log")
    ids = goals.daily_goal_ids("transit")
    for d in (5, 6, 7, 8):
        for g in ids:
            goals.set_done("h", g, d, True)
    h = goals._history("h", 8)
    assert min(h) == 5 and goals._start("h", 8) == 5
    p = goals.profile("h", 8)
    assert p["completion_7d"] == 100 and p["streak"] == 4  # four days of history, all kept: not diluted by the days before
    assert [d for d, *_ in p["daily_done"]] == [5, 6, 7, 8]
    assert goals._start("h", 2) == 2  # a clock set before the first row shows today alone
    assert list(goals._history("h", 2)) == [2]


def test_a_goal_ticked_in_the_app_is_stored_with_the_mission_time(monkeypatch):
    monkeypatch.setattr(mission, "_now", lambda: dt.datetime(2040, 3, 5, 9, 41, tzinfo=dt.timezone.utc))
    client.put("/api/control/clock", json={"real": True}, headers=ctl())
    goals.set_done("h", "sleep_log", 3, True)
    assert db.q("SELECT done_at_time t FROM goal_log WHERE crew_id='h' AND day=3 AND goal_id='sleep_log'")[0]["t"] == "09:41"


def test_the_kind_of_event_says_what_it_is_and_only_known_kinds_are_accepted():
    r = client.post("/api/control/space-events", headers=ctl(), json={"kind": "storm", "start_day": 60, "locations": ["transit"]})
    assert r.status_code == 422 and r.json()["detail"] == [{"field": "event.kind", "message": "kind must be one of: sep, mars"}]
    client.post("/api/control/space-events", headers=ctl(), json={"id": "any-name", "kind": "mars", "start_day": 60, "locations": ["transit"]})
    assert data.storm_at(60, "transit") == "mars" and data.storm_event(60, "transit")["id"] == "any-name"


def test_the_immune_follow_up_follows_the_kind_of_storm_not_its_dose():
    def note(kind, d):
        client.post("/api/control/space-events", headers=ctl(), json={"id": "t-" + kind, "kind": kind, "start_day": 60, "locations": ["transit"], "extra_dose_msv": 0})
        return health.snapshot("h", day(d))["systems"]["immune"]["note"]
    assert note("mars", 62) != "Blood count due after the radiation storm."
    assert note("sep", 62) == "Blood count due after the radiation storm."
