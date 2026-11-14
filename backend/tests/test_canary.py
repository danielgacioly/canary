"""Core behaviour: baseline alerts, the story, goals, the assistant guard and the API."""
import json
import os
import tempfile
import time

os.environ["CANARY_DB"] = os.path.join(tempfile.mkdtemp(), "test.db")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from canary import auth, db  # noqa: E402
from canary.assistant import guard  # noqa: E402
from canary.domain import catalog, goals, health, mission  # noqa: E402
from canary.main import app  # noqa: E402

client = TestClient(app)


@pytest.fixture(autouse=True)
def fresh():
    client.post("/api/demo/reset")
    yield
    client.post("/api/demo/reset")


PINS = {"h": "1001", "k": "1002", "a": "1003", "t": "1004"}


def as_(cid):
    """Sign in with the default PIN and send the session token, as the web app does."""
    r = client.post(f"/api/crew/{cid}/session", json={"pin": PINS[cid]})
    assert r.status_code == 200
    return {"X-Canary-Viewer": r.json()["token"]}


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
    r = client.post("/api/checkins", json={"crew_id": "h", "kind": "mood", "payload": {"mood": 5, "stress": 1}}, headers=as_("h")).json()
    assert r["snapshot"]["indicators"]["mood"]["value"] > 4
    g = {x["id"]: x for x in client.get("/api/goals/h", headers=as_("h")).json()["personal"]}
    assert g["mood"]["done"]


def test_leaderboard_ranks_everyone():
    at(2)
    lb = client.get("/api/leaderboard").json()
    assert [r["rank"] for r in lb["rows"]] == [1, 2, 3, 4]
    assert len(lb["team"]) == len(catalog.TEAM_GOALS)
    goals_week = [r["goals_week"] for r in lb["rows"]]
    assert goals_week == sorted(goals_week, reverse=True)

    def keys(x):
        if isinstance(x, dict):
            for k, v in x.items():
                yield k
                yield from keys(v)
        elif isinstance(x, list):
            for v in x:
                yield from keys(v)
    for payload in (lb, client.get("/api/goals/h", headers=as_("h")).json()):
        assert not [k for k in keys(payload) if "xp" in k]


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
    r = client.post("/api/assistant/ask", json={"crew_id": "h", "question": "Why is my sleep so bad?"}, headers=as_("h")).json()
    assert r["provider"] == "none" and r["mode"] == "grounded"
    assert r["claims"] and all(c["source_ids"] for c in r["claims"])


def test_briefing_is_approved_then_queued():
    at(2)
    b = client.post("/api/briefings", json={"crew_id": "h"}, headers=as_("h")).json()
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
    titles = [g["title"] for g in client.get("/api/goals/t", headers=as_("t")).json()["personal"] if g["by"] == "medical"]
    assert titles and any("Glucose" in t for t in titles)
    assert any(m["kind"] == "report" for m in client.get("/api/messages").json())


def test_plan_drives_the_place_and_goals():
    client.post("/api/plan/preset", json={"preset": "iss"})
    ms = client.put("/api/mission", json={"day": 100}).json()
    assert ms["location"] == "iss" and ms["leg"]["label"].startswith("Expedition")
    titles = [g["title"] for g in client.get("/api/goals/h", headers=as_("h")).json()["personal"]]
    assert any("treadmill" in t for t in titles) and any("cupola" in t for t in titles)
    assert client.put("/api/mission", json={"day": 200}).json()["location"] == "earth"


def test_custom_plan_is_validated_and_used():
    bad = {"name": "x", "legs": [{"location": "earth", "start": 0, "end": 10}, {"location": "moon", "start": 5, "end": 20}]}
    assert client.put("/api/plan", json=bad).status_code == 400
    good = {"name": "Short hop", "legs": [{"location": "earth", "start": -30, "end": -1}, {"location": "rocket", "start": 0, "end": 2},
                                          {"location": "moon", "start": 3, "end": 40, "label": "Base camp"}]}
    assert client.put("/api/plan", json=good).status_code == 200
    ms = client.put("/api/mission", json={"day": 10}).json()
    assert ms["location"] == "moon" and ms["place"]["gravity"] == "1/6 g" and ms["leg"]["label"] == "Base camp"
    assert any(p["variant"] for p in client.get("/api/protocols").json()["protocols"]["rad"]["steps"])


def test_bone_loss_depends_on_gravity_in_the_plan():
    client.post("/api/plan/preset", json={"preset": "mars"})
    at(2)
    mars = health.indicator("t", "bone", mission.state())["value"]
    client.post("/api/plan/preset", json={"preset": "moon"})
    moon = health.indicator("t", "bone", mission.state())["value"]  # day 147 is back on Earth after a short trip
    assert mars < moon


def test_crew_overview_hides_private_health():
    at(2)
    o = client.get("/api/crew/overview").json()
    helena = next(p for p in o["people"] if p["id"] == "h")
    assert "ops" not in helena and "shared" not in helena and "fit" not in o
    text = str(o)
    for leak in ("indicators", "areas", "alerts", "score", "baseline", "Sleep, mood and focus", "'ops'", "Fit for", "Off critical"):
        assert leak not in text


def test_details_are_private_to_self_and_medical():
    at(2)
    assert client.get("/api/crew/h").status_code == 403
    assert client.get("/api/crew/h", headers=as_("k")).status_code == 403
    d = client.get("/api/crew/h", headers=as_("h")).json()
    assert d["access"] == "self" and d["ops"]["key"] == "rest"
    assert client.get("/api/goals/h", headers=as_("t")).status_code == 403
    assert client.put("/api/crew/h/sharing", json={"shared": True}, headers=as_("h")).status_code in (404, 405)


def test_profile_photo_is_set_by_the_astronaut_only():
    png = "data:image/png;base64,iVBORw0KGgo="
    assert client.put("/api/crew/h/photo", json={"data_url": png}, headers=as_("k")).status_code == 403
    assert client.put("/api/crew/h/photo", json={"data_url": "javascript:alert(1)"}, headers=as_("h")).status_code == 400
    assert client.put("/api/crew/h/photo", json={"data_url": png}, headers=as_("h")).json() == {"h": png}
    assert client.get("/api/crew/photos").json() == {"h": png}
    assert client.delete("/api/crew/h/photo", headers=as_("h")).json() == {}

def test_medical_team_sees_everyone_and_storm_is_a_crew_hazard():
    tok = client.post("/api/medical/session", json={"pin": "1961"}).json()["token"]
    med = {"Authorization": f"Bearer {tok}"}
    assert client.get("/api/crew/h", headers=med).json()["access"] == "medical"
    assert client.get("/api/crew").status_code == 401
    at(2)
    assert all("ops" in p for p in client.get("/api/crew", headers=med).json()["crew"])
    ov = client.get("/api/medical/overview", headers=med).json()["crew"]
    assert next(c for c in ov if c["id"] == "h")["ops"]["key"] == "rest"
    o = client.get("/api/crew/overview").json() if at(3) else None
    assert o["hazards"][0]["level"] == 2 and not o["eva_open"]


# ---------------------------------------------------------------- the mission clock before and after the plan
@pytest.mark.parametrize("day", [-60, -365, -31, 800, 2000])
def test_every_page_works_on_any_mission_day(day):
    assert client.put("/api/mission", json={"day": day}).json()["day"] == day
    for path in ("/api/crew/overview", "/api/leaderboard"):
        assert client.get(path).status_code == 200, path
    h = as_("h")
    for path in ("/api/crew/h", "/api/goals/h"):
        assert client.get(path, headers=h).status_code == 200, path


# ---------------------------------------------------------------- PINs and sessions
def test_wrong_pin_is_401_and_the_right_one_returns_a_token():
    assert client.post("/api/crew/h/session", json={"pin": "9999"}).status_code == 401
    r = client.post("/api/crew/h/session", json={"pin": "1001"}).json()
    assert r["crew_id"] == "h" and r["token"].startswith("h.") and r["expires_at"] > 0
    assert client.post("/api/crew/h/session", json={"pin": "12"}).status_code == 422  # exactly 4 digits
    assert client.post("/api/crew/zz/session", json={"pin": "1001"}).status_code == 404


def test_pin_attempts_are_rate_limited_per_person():
    for _ in range(5):
        assert client.post("/api/crew/h/session", json={"pin": "0000"}).status_code == 401
    assert client.post("/api/crew/h/session", json={"pin": "1001"}).status_code == 429  # even the right PIN waits
    assert client.post("/api/crew/k/session", json={"pin": "1002"}).status_code == 200


def test_a_plain_id_in_the_viewer_header_is_rejected():
    assert client.get("/api/goals/h", headers={"X-Canary-Viewer": "h"}).status_code == 403
    assert client.get("/api/crew/h", headers={"X-Canary-Viewer": "h"}).status_code == 403
    exp = int(time.time()) - 10  # a correctly signed but expired token
    assert client.get("/api/goals/h", headers={"X-Canary-Viewer": f"h.{exp}.{auth._sig('h', exp)}"}).status_code == 403
    assert client.get("/api/goals/h", headers={"X-Canary-Viewer": as_("h")["X-Canary-Viewer"] + "0"}).status_code == 403


def test_a_token_only_opens_its_own_space():
    assert client.get("/api/goals/h", headers=as_("h")).status_code == 200
    assert client.get("/api/goals/k", headers=as_("h")).status_code == 403


def test_changing_the_pin_replaces_the_old_one():
    h = as_("h")
    assert client.put("/api/crew/h/pin", json={"current": "1001", "new": "2468"}).status_code == 403  # no token
    assert client.put("/api/crew/h/pin", json={"current": "1001", "new": "2468"}, headers=as_("k")).status_code == 403
    assert client.put("/api/crew/h/pin", json={"current": "5555", "new": "2468"}, headers=h).status_code == 401
    assert client.put("/api/crew/h/pin", json={"current": "1001", "new": "12ab"}, headers=h).status_code == 422
    assert client.put("/api/crew/h/pin", json={"current": "1001", "new": "2468"}, headers=h).status_code == 200
    assert client.post("/api/crew/h/session", json={"pin": "1001"}).status_code == 401
    assert client.post("/api/crew/h/session", json={"pin": "2468"}).status_code == 200
    stored = json.dumps(db.get_setting("pins"))
    assert "2468" not in stored  # stored salted and hashed
    client.post("/api/demo/reset")
    assert client.post("/api/crew/h/session", json={"pin": "1001"}).status_code == 200  # reset restores defaults


def test_medical_pin_is_four_digits():
    assert client.post("/api/medical/session", json={"pin": "196"}).status_code == 422
    assert client.post("/api/medical/session", json={"pin": "1961"}).status_code == 200


# ---------------------------------------------------------------- mission setup
def test_setup_saves_the_plan_and_marks_it_done():
    assert client.get("/api/mission").json()["setup_done"] is True  # configured by the mission admin
    legs = [{"location": "earth", "start": -60, "end": -1, "label": "Training"},
            {"location": "rocket", "start": 0, "end": 4, "label": "Transfer"},
            {"location": "moon", "start": 5, "end": 34, "label": "Surface"}]
    bad = client.post("/api/setup", json={"name": "x", "legs": [legs[1], {**legs[2], "start": 3}]})
    assert bad.status_code == 400
    ms = client.post("/api/setup", json={"name": "Artemis", "legs": legs}).json()
    assert ms["setup_done"] and ms["plan_name"] == "Artemis" and ms["step"] == 0
    assert client.put("/api/mission", json={"day": 10}).json()["location"] == "moon"
    client.post("/api/demo/reset")
    ms = client.get("/api/mission").json()
    assert ms["setup_done"] is True and ms["plan_name"] == "Mars reference mission"  # reset restores the demo mission


def test_ridge_hazards_follow_place_and_storm():
    o = client.get("/api/crew/overview").json()  # pre-flight, on Earth
    assert [h["id"] for h in o["ridge"]] == ["R", "I", "D", "G", "E"] and all(h["level"] == 0 for h in o["ridge"])
    o = client.get("/api/crew/overview").json() if at(3) else None  # the replayed May 2024 storm, in transit
    r = {h["id"]: h for h in o["ridge"]}
    assert r["R"]["level"] == 2 and r["G"]["label"] == "High" and o["warnings"][0]["id"] == "storm"


def test_plan_conditions_project_the_dose():
    c = client.get("/api/plan/conditions").json()
    assert len(c["legs"]) == 4 and c["legs"][2]["location"] == "transit"
    doses = [v for _, v in c["dose"]["series"]]
    assert doses == sorted(doses) and c["dose"]["end_msv"] > c["dose"]["limit_msv"] * 0.5


def test_tests_page_saves_results_privately_and_completes_goals():
    at(2)
    h = as_("h")
    r = client.post("/api/checkins", json={"crew_id": "h", "kind": "sleep", "payload": {"bed": "23:00", "wake": "06:30", "quality": 4}}, headers=h).json()
    assert r["goal"] == "sleep" and r["summary"].startswith("7.5 h")
    assert client.post("/api/checkins", json={"crew_id": "h", "kind": "journal", "payload": {"lines": 3, "text": "secret"}}, headers=h).json()["goal"] == "journal"
    client.post("/api/checkins", json={"crew_id": "h", "kind": "wellbeing", "payload": {"answers": [2, 2, 0, 1]}}, headers=h)
    hist = client.get("/api/checkins/h", headers=h).json()
    latest = {t["id"]: t["latest"] for t in hist["tests"]}
    assert latest["sleep"]["payload"]["hours"] == 7.5 and latest["journal"]["payload"] == {"lines": 3}  # the text is never kept
    assert any(a["id"] == "wellbeing" for a in client.get("/api/crew/h", headers=h).json()["alerts"])
    assert client.get("/api/checkins/h", headers=as_("k")).status_code == 403
    assert client.post("/api/checkins", json={"crew_id": "h", "kind": "nope", "payload": {}}, headers=h).status_code == 422


def test_suggestions_are_personal_grounded_and_become_goals():
    at(2)  # day 147: Helena's sleep, mood and crew time are slipping
    h = as_("h")
    s = client.get("/api/suggestions/h", headers=h).json()
    ids = [x["id"] for x in s["items"]]
    assert s["mode"] == "rules" and "sleep" in ids and "social" in ids
    sleep = next(x for x in s["items"] if x["id"] == "sleep")
    assert "h against your normal" in sleep["why"] and sleep["sources"]
    assert client.get("/api/suggestions/h", headers=as_("k")).status_code == 403
    s = client.post("/api/suggestions/h/sleep/accept", headers=h).json()
    assert next(x for x in s["items"] if x["id"] == "sleep")["accepted"]
    g = client.get("/api/goals/h", headers=h).json()["personal"]
    assert any(x["id"] == "sg_sleep" and x["by"] == "suggestion" for x in g)


# ---------------------------------------------------------------- the observation table (DatasetSource)
def _gen(legs=None, real_dir=None):
    from canary.domain import plan as plan_mod, simdata
    legs = legs or plan_mod.PRESETS["mars"]["legs"]
    return simdata.Generator(legs, simdata.load_recipes(), real_dir)


def _mean(g, crew, ind, a, b):
    return sum(g.value(crew, ind, d) for d in range(a, b + 1)) / (b - a + 1)


def test_states_move_related_signals_together_only_for_helena():
    g = _gen()
    # fatigue: sleep falls while reaction time, sleepiness and workload rise, from days 100-130 to 140-153
    for ind, sign in (("sleep", -1), ("react", 1), ("kss", 1), ("tlx", 1), ("dsst", -1), ("mood", -1)):
        shift = (_mean(g, "h", ind, 140, 153) - _mean(g, "h", ind, 100, 130)) * sign
        sd = catalog.INDICATORS[ind]["sd"] if ind in catalog.INDICATORS else g.sd("h", ind)
        assert shift > 1.5 * sd, ind
        for other in ("k", "a", "t"):
            assert abs(_mean(g, other, ind, 140, 153) - _mean(g, other, ind, 100, 130)) < 0.8 * sd, (other, ind)


def test_real_csv_in_data_real_replaces_the_simulated_row(tmp_path):
    (tmp_path / "mine.csv").write_text("crew_id,day,indicator,value\nh,10,gluc,77\n")
    rows = {(r[0], r[1], r[2]): r for r in _gen(real_dir=tmp_path).observations()}
    r = rows[("h", 10, "gluc")]
    assert r[5] == "real" and r[3] == "77" and r[4] == "mg/dL" and r[6] == "manual"
    assert rows[("h", 12, "sleep")][5] == "simulated"


def test_panel_indicators_only_have_rows_on_collection_days_and_last_observation_has_an_age():
    from canary.domain import telemetry
    days = sorted(r["day"] for r in _rows_of("h", "cortisol"))
    assert len(days) > 15 and all((b - a) % 30 == 0 for a, b in zip(days, days[1:]))
    a = days[3]
    assert telemetry.last_observation("h", "cortisol", a)["age"] == 0
    mid = telemetry.last_observation("h", "cortisol", a + 11)
    assert mid["age"] == 11 and mid["day"] == a and mid["origin"] == "simulated" and mid["method"] == "blood"
    assert telemetry.SOURCE.value("h", "cortisol", a + 11) == telemetry.SOURCE.value("h", "cortisol", a)
    assert telemetry.last_observation("h", "cortisol", days[0] - 1) is None


def _rows_of(crew, ind):
    from canary.domain import simdata
    return [{"day": int(r["day"])} for r in simdata.read_csv(simdata.OBS_FILE) if r["crew_id"] == crew and r["indicator"] == ind]


def test_every_recipe_has_a_source_and_unsourced_ones_are_listed():
    from canary.domain import simdata
    rec = simdata.load_recipes()
    md = simdata.REPORT_FILE.read_text()
    for name, r in rec["indicators"].items():
        assert r["source"], name
        if not r["verified"]:
            assert r["source"] and f"`{name}`" in md.split("## Assumptions without a source")[1], name
    for name, sd in ((k, v) for k, v in rec["indicators"].items() if k in catalog.INDICATORS and k != "bone"):
        assert sd["sd"] == "catalog" and sd["baseline"] == {"kind": "catalog"}
    assert {"dsst", "span", "kss", "tlx", "hrv", "weight", "creatinine", "cortisol", "urine_calcium", "co2"} <= set(rec["indicators"])


def test_the_committed_file_is_what_the_generator_writes_and_is_small():
    from canary.domain import plan as plan_mod, simdata
    rec = simdata.load_recipes()
    rows = simdata.Generator(plan_mod.PRESETS["mars"]["legs"], rec, simdata.REAL_DIR).observations()
    assert simdata.OBS_FILE.read_text() == simdata.csv_text(rows), "run: python data/generate_dataset.py"
    assert simdata.REPORT_FILE.read_text() == simdata.report(rows, rec, plan_mod.PRESETS["mars"]["name"])
    assert simdata.OBS_FILE.stat().st_size < 10_000_000
    assert simdata.csv_text(rows) == simdata.csv_text(simdata.Generator(plan_mod.PRESETS["mars"]["legs"], rec, simdata.REAL_DIR).observations())


def test_osd569_rows_are_real_and_keep_the_original_label():
    from canary.domain import nasa, simdata
    rows = [r for r in simdata.read_csv(simdata.OBS_FILE) if r["origin"] == "real"]
    assert len(rows) == 4 * 7 * 7 and {r["source"] for r in rows} == {"nasa:osd569"}
    h_lym = {r["note"].split()[0]: float(r["value"]) for r in rows if r["crew_id"] == "h" and r["indicator"] == "lym"}
    assert [h_lym[t] for t in nasa.snapshot()["cbc"]["tp"]] == nasa.blood("C001")["lymphocytes"]
    assert set(h_lym) == {"L-92", "L-44", "L-3", "R+1", "R+45", "R+82", "R+194"}
    # pre-flight collections set the baseline of the simulated rows
    pre = [float(r["value"]) for r in rows if r["crew_id"] == "h" and r["indicator"] == "lym" and int(r["day"]) < 0]
    sim = [float(r["value"]) for r in simdata.read_csv(simdata.OBS_FILE)
           if r["crew_id"] == "h" and r["indicator"] == "lym" and r["origin"] == "simulated"]
    assert abs(sum(sim) / len(sim) - sum(pre) / len(pre)) < 600


def test_simdata_follows_the_plan_the_same_way_plan_does():
    from canary.domain import plan as plan_mod, simdata
    for key in ("mars", "iss", "moon"):
        client.post("/api/plan/preset", json={"preset": key})
        legs = plan_mod.get()["legs"]
        for d in range(-70, 800, 7):
            assert simdata.location_at(legs, d) == plan_mod.location_at(d)
            assert simdata.days_since_gravity_change(legs, d) == plan_mod.days_since_gravity_change(d)


def test_a_custom_plan_gets_its_own_table_and_value_never_breaks():
    from canary.domain import telemetry
    good = {"name": "Short hop", "legs": [{"location": "earth", "start": -30, "end": -1}, {"location": "rocket", "start": 0, "end": 2},
                                          {"location": "moon", "start": 3, "end": 40}]}
    assert client.put("/api/plan", json=good).status_code == 200
    assert telemetry.last_observation("h", "co2", 10) is None  # co2 belongs to "cabin"
    assert telemetry.last_observation("cabin", "co2", 10)["value"] > 1000
    for d in (-500, 0, 20, 40, 41, 3000):
        assert isinstance(telemetry.SOURCE.value("t", "hr", d), float)


# ---------------------------------------------------------------- Prompt 1: everything the person measures is an observation
def _day(d):
    return client.put("/api/mission", json={"day": d}).json()


def _checkin(cid, kind, payload):
    return client.post("/api/checkins", json={"crew_id": cid, "kind": kind, "payload": payload}, headers=as_(cid))


def test_a_pvt_checkin_shows_in_the_series_and_weighs_on_the_next_two_days():
    from canary.domain import telemetry
    _day(100)
    before = {d: telemetry.current("a", "react", d) for d in (100, 101, 102, 103)}
    assert _checkin("a", "pvt", {"ms": 600}).status_code == 200
    assert dict(telemetry.series("a", "react", 100, 5))[100] == 600
    assert dict(telemetry.series("a", "react", 102, 5))[100] == 600  # still there in later charts
    assert telemetry.current("a", "react", 100) == pytest.approx(before[100] + 0.6 * (600 - telemetry.SOURCE.value("a", "react", 100)))
    assert telemetry.current("a", "react", 101) > before[101] + 0.25 * 200
    assert telemetry.current("a", "react", 102) > before[102] + 0.15 * 200
    assert telemetry.current("a", "react", 103) == pytest.approx(before[103])


@pytest.mark.parametrize("kind,payload,ind,value", [("dsst", {"correct": 10}, "dsst", 10), ("span", {"span": 3}, "span", 3),
                                                    ("kss", {"level": 9}, "kss", 9), ("tlx", {"scores": {"a": 100, "b": 100}}, "tlx", 100)])
def test_cognitive_and_self_report_tests_feed_their_indicator(kind, payload, ind, value):
    _day(100)
    before = client.get("/api/crew/a", headers=as_("a")).json()["indicators"][ind]
    assert before["origin"] == "simulated" and before["age_days"] is None
    r = _checkin("a", kind, payload).json()["snapshot"]["indicators"][ind]
    assert r["origin"] == "user" and r["age_days"] == 0 and r["last_measured_day"] == 100
    assert r["value"] != before["value"] and r["bad"] > before["bad"]
    assert dict(client.get("/api/crew/a", headers=as_("a")).json()["trends"][ind])[100] == value
    _day(103)
    later = client.get("/api/crew/a", headers=as_("a")).json()["indicators"][ind]
    assert later["origin"] != "user" and later["age_days"] == 3


def test_crew_detail_has_the_four_new_indicators_with_origin_and_age():
    _day(100)
    d = client.get("/api/crew/h", headers=as_("h")).json()
    for ind in ("dsst", "span", "kss", "tlx"):
        i = d["indicators"][ind]
        assert {"value", "baseline", "level", "origin", "age_days"} <= set(i) and i["origin"] in ("simulated", "real", "user")
        assert ind in catalog.SYSTEMS["brain"]["indicators"] and catalog.INDICATOR_NOTES[ind]["verified"] is False


def test_story_alerts_are_unchanged_by_the_new_indicators():
    s = health.snapshot("h", at(2))
    assert s["alerts"][0]["id"] == "behaviour" and s["alerts"][0]["level"] == 2
    assert not any(a["id"].startswith("ind_") and a["id"][4:] in ("dsst", "span", "kss", "tlx") for a in s["alerts"])
    for cid in ("k", "a", "t"):
        assert not any(a["id"] == "behaviour" for a in health.snapshot(cid, mission.state())["alerts"])
    ms = _day(-30)
    assert all(health.snapshot(c["id"], ms)["alerts"] == [] for c in catalog.CREW)
    ms = at(1)
    assert [c["id"] for c in catalog.CREW if any(a["id"] == "sickness" for a in health.snapshot(c["id"], ms)["alerts"])] == ["t"]


def test_missing_mood_after_three_days_without_the_goal_and_gone_after_a_checkin():
    ms = _day(100)
    for d in (98, 99, 100):
        goals.set_done("a", "mood", d, False)
    ids = lambda: [a["id"] for a in health.snapshot("a", mission.state())["alerts"]]  # noqa: E731
    assert "missing_mood" in ids()
    a = next(x for x in health.snapshot("a", ms)["alerts"] if x["id"] == "missing_mood")
    assert a["level"] == 1 and a["sys"] == "brain" and "fault" not in a["why"].lower()
    assert health.snapshot("a", ms)["level"] == 0  # missing data is not a health risk
    assert _checkin("a", "mood", {"mood": 4, "stress": 2}).status_code == 200
    assert "missing_mood" not in ids()
    goals.set_done("a", "mood", 100, False)
    goals.set_done("a", "mood", 99, True)
    assert "missing_mood" not in ids()  # only three days in a row count
    ms = _day(-5)  # learning: no alerts at all
    for d in (-7, -6, -5):
        goals.set_done("a", "mood", d, False)
    assert health.snapshot("a", ms)["alerts"] == []


def test_vitals_outside_what_can_be_typed_are_refused():
    _day(100)
    for bad in ({"hr": 900}, {"hr": 5}, {"temp": 80}, {"spo2": 120}, {"bp": 0}, {"hr": "fast"}):
        r = _checkin("a", "vitals", bad)
        assert r.status_code == 400, bad
    assert _checkin("a", "vitals", {"hr": 62, "bp": 118, "temp": 36.6, "spo2": 98}).status_code == 200
    latest = {t["id"]: t["latest"] for t in client.get("/api/checkins/a", headers=as_("a")).json()["tests"]}
    assert latest["vitals"]["payload"]["hr"] == 62
    assert selftests_limits_are_not_clinical()


def selftests_limits_are_not_clinical():
    from canary.domain import selftests
    return selftests.VITALS_LIMITS_SOURCE["verified"] is False and "not clinical" in selftests.VITALS_LIMITS_SOURCE["source"]


# ---------------------------------------------------------------- Prompt 2: two references (population safety limit + personal baseline)
STORY_ALERTS = {  # scene step -> crew -> (alert id, level), as before the population ranges and the computed baseline
    1: {"t": [("sickness", 1)]},
    2: {"h": [("behaviour", 2), ("missing_mood", 1)], "k": [("ind_bone", 1)], "t": [("ind_bone", 1)]},
    3: {"h": [("storm", 2), ("behaviour", 2), ("missing_mood", 1), ("ind_bone", 1)], "k": [("storm", 2), ("ind_bone", 1)],
        "a": [("storm", 2)], "t": [("storm", 2), ("ind_bone", 1)]},
    4: {"h": [("behaviour", 2), ("missing_mood", 1), ("ind_bone", 1)], "k": [("ind_bone", 1)], "t": [("ind_bone", 1)]},
    5: {"h": [("storm", 2), ("regravity", 1), ("ind_bone", 1)], "k": [("storm", 2), ("regravity", 1), ("ind_grip", 1), ("ind_bone", 1)],
        "a": [("storm", 2), ("ind_hr", 2), ("ind_grip", 1), ("ind_bone", 1)], "t": [("storm", 2), ("ind_hr", 1), ("ind_bone", 1)]},
}


@pytest.mark.parametrize("step", range(6))
def test_story_scenes_keep_the_same_alerts(step):
    ms = at(step)
    for c in catalog.CREW:
        got = [(a["id"], a["level"]) for a in health.snapshot(c["id"], ms)["alerts"]]
        assert got == STORY_ALERTS.get(step, {}).get(c["id"], []), (step, c["id"])


def test_a_critical_reading_is_level_two_even_while_learning():
    ms = _day(-30)
    assert ms["learning"]
    assert _checkin("a", "vitals", {"spo2": 85}).status_code == 200
    s = health.snapshot("a", ms)
    i = s["indicators"]["spo2"]
    assert i["level"] == 2 and i["population"]["status"] == "critical" and i["population"]["verified"] is False
    assert [(a["id"], a["level"]) for a in s["alerts"]] == [("ind_spo2", 2)]
    assert s["systems"]["lungs"]["level"] == 2
    assert health.snapshot("k", ms)["alerts"] == []  # nobody else is affected


def test_outside_the_normal_range_is_at_least_level_one_after_launch():
    ms = _day(100)
    assert _checkin("a", "vitals", {"temp": 37.9}).status_code == 200  # fever range, not critical
    i = health.snapshot("a", ms)["indicators"]["temp"]
    assert i["population"]["status"] == "out" and i["level"] >= 1
    assert _checkin("a", "vitals", {"temp": 41}).status_code == 200
    assert health.snapshot("a", ms)["indicators"]["temp"]["level"] == 2


def test_inside_the_population_range_the_personal_baseline_still_raises_level_two():
    ms = _day(100)
    assert _checkin("a", "pvt", {"ms": 450}).status_code == 200  # inside 150 to 500 ms, far from her own 250
    i = health.snapshot("a", ms)["indicators"]["react"]
    assert i["population"]["status"] == "in" and i["z"] >= 2.5 and i["level"] == 2


def test_the_baseline_is_computed_from_the_preflight_days_and_stays_close_to_the_seed():
    for c in catalog.CREW:
        for ind, B in health.baselines(c["id"]).items():
            sd = catalog.INDICATORS[ind]["sd"]
            assert B["from"] == "preflight" and B["n"] >= health.MIN_PREFLIGHT, (c["id"], ind)
            assert abs(B["mean"] - c["base"][ind]) <= 0.35 * sd + 0.5 * 10 ** -catalog.INDICATORS[ind]["dp"], (c["id"], ind)
            assert B["sd"] >= sd  # the floor
    _day(100)
    d = client.get("/api/crew/h", headers=as_("h")).json()["indicators"]["sleep"]
    assert d["baseline_from"] == "preflight" and d["baseline"] == health.baselines("h")["sleep"]["mean"] and d["spread"] >= 0.5


def test_a_plan_without_preflight_falls_back_to_the_catalog_seed():
    plan_no_pre = {"name": "No pre-flight", "legs": [{"location": "rocket", "start": 0, "end": 3}, {"location": "transit", "start": 4, "end": 100}]}
    assert client.put("/api/plan", json=plan_no_pre).status_code == 200
    b = health.baselines("h")
    assert all(x["from"] == "catalog" and x["mean"] == catalog.CREW_BY_ID["h"]["base"][i] for i, x in b.items())


def test_a_preflight_checkin_moves_the_baseline():
    _day(-30)
    before = health.baselines("a")["react"]["mean"]
    for _ in range(3):
        assert _checkin("a", "pvt", {"ms": 400}).status_code == 200
    assert health.baselines("a")["react"]["mean"] != before


def test_a_test_returns_a_conclusion_against_both_references():
    _day(100)
    c = _checkin("a", "pvt", {"ms": 330}).json()["conclusion"]
    assert c["population"] == "Within the normal human range" and "slower than your own average" in c["personal"]
    assert c["text"] == f"{c['population']}, {c['personal']}."
    for kind, payload in (("dsst", {"correct": 50}), ("span", {"span": 6}), ("kss", {"level": 4}), ("tlx", {"scores": {"a": 50}}),
                          ("mood", {"mood": 4, "stress": 2}), ("sleep", {"bed": "23:00", "wake": "06:00", "quality": 3}),
                          ("vitals", {"hr": 60})):
        c = _checkin("a", kind, payload).json()["conclusion"]
        assert c and c["population"] and c["personal"], kind
    assert _checkin("a", "journal", {"lines": 3}).json()["conclusion"] is None
    assert "Past the safety limit" in _checkin("a", "vitals", {"spo2": 85}).json()["conclusion"]["text"]


def test_thresholds_can_be_overridden_for_one_indicator():
    ms = _day(100)
    before = health.snapshot("a", ms)["indicators"]
    db.set_setting("thresholds_by_indicator", {"sleep": {"watch": -9, "act": -8}})
    after = health.snapshot("a", ms)["indicators"]
    assert after["sleep"]["level"] == 2
    assert {i: x["level"] for i, x in after.items() if i != "sleep"} == {i: x["level"] for i, x in before.items() if i != "sleep"}


def test_every_population_range_has_a_source_and_the_readme_table_is_generated_from_it():
    from canary.domain import reference
    import pathlib
    for ind, P in reference.POPULATION.items():
        assert ind in catalog.INDICATORS and P["source"], ind
        assert P["verified"] is False  # the team checks them before the pitch
    assert all(reference.POPULATION[i]["source"].find("assumption") >= 0 for i in ("react", "dsst", "span"))
    readme = (pathlib.Path(__file__).resolve().parents[2] / "README.md").read_text()
    assert reference.table_md() in readme
    assert reference.check("grip", "F", 15)["status"] == "out" and reference.check("grip", "M", 30)["status"] == "in"
    assert reference.check("mood", "F", 1)["status"] == "in"


def test_the_blood_count_returns_every_analyte_with_range_and_status_and_raises_no_alert():
    from canary.domain import nasa
    b = nasa.blood("C001")
    assert b["origin"] == "real" and set(b["analytes"]) == {"wbc", "lym", "neu", "hgb", "hct", "plt", "rbc"}
    for a in b["analytes"].values():
        assert len(a["status"]) == len(b["timepoints"]) == len(a["values"]) and set(a["status"]) <= {"in", "out", None}
        assert a["range"]["min"] < a["range"]["max"]
    assert b["lymphocytes"] == b["analytes"]["lym"]["values"]


# ---------------------------------------------------------------- Prompt 3: risks (fatigue), drift, since_day, one engine for suggestions
def _fatigue(cid, day=None):
    from canary.domain import risk
    ms = mission.state() if day is None else {"day": day}
    return next(r for r in risk.evaluate(cid, ms) if r["id"] == "fatigue")


def test_helena_has_a_level_two_fatigue_risk_on_day_147_and_nobody_else_does():
    ms = at(2)
    r = _fatigue("h")
    assert r["level"] == 2 and r["nasa_red"] and r["systems"] == ["brain"] and r["clock_days"] == 14
    assert len(r["evidence"]) >= 3 and r["trend"] == "rising" and 132 <= r["since_day"] <= 147
    for e in r["evidence"]:
        assert e["text"] and e["origin"] in ("user", "simulated", "real") and e["source"] and (e.get("indicator") or e.get("checkin"))
    assert [x["id"] for x in health.snapshot("h", ms)["risks"]] == ["fatigue"]
    for cid in ("k", "a", "t"):
        assert _fatigue(cid)["level"] == 0 and _fatigue(cid)["since_day"] is None
    _day(100)
    assert _fatigue("h")["level"] == 0


def test_the_behaviour_alert_comes_from_the_fatigue_risk_and_keeps_its_shape():
    a = next(x for x in health.snapshot("h", at(2))["alerts"] if x["id"] == "behaviour")
    assert a["risk"] == "fatigue" and a["level"] == 2 and a["sys"] == "brain" and a["test"] == "pvt"
    assert a["title"] == "Sleep, mood and focus are dropping together." and "slept" in a["why"] and len(a["goals"]) == 3
    _day(100)
    assert not any(x["id"] == "behaviour" for x in health.snapshot("h", mission.state())["alerts"])


def test_one_bad_night_or_two_tired_check_ins_stay_at_level_one_at_most():
    _day(100)
    assert _fatigue("a")["level"] == 0
    assert _checkin("a", "kss", {"level": 8}).status_code == 200
    assert _checkin("a", "tlx", {"raw": 92}).status_code == 200
    r = _fatigue("a")
    assert r["level"] == 1 and {e.get("indicator") for e in r["evidence"]} >= {"kss", "tlx"}
    assert _checkin("a", "sleep", {"hours": 3}).status_code == 200
    assert _checkin("a", "pvt", {"ms": 400}).status_code == 200
    assert _fatigue("a")["level"] <= 1  # a bad night shows on several signals at once, and still has not been building


def test_since_day_is_the_same_whatever_order_the_clock_visits_the_days():
    from canary.domain import risk
    first = {d: _fatigue("h", d)["since_day"] for d in (147, 100, 153, 147, 139, 300)}
    risk.clear_cache()
    for d in (300, 139, 147, 153, 100, 147):
        assert _fatigue("h", d)["since_day"] == first[d]
    assert first[100] is None and first[300] is None and first[147] == first[153] == 139 and first[139] == 139


def test_drift_flags_a_slow_slide_that_will_cross_the_limit_and_ignores_a_flat_line():
    from canary.domain import risk
    slide = [0.1 * i for i in range(14)]           # 0 to 1.3 spreads in 14 days, limit 1.5
    assert risk.drift_of(slide, 1.5)["days_to_limit"] <= 10
    assert risk.drift_of([0.2, -0.1, 0.1, 0.0, 0.2, -0.2] * 2, 1.5) is None
    assert risk.drift_of([1.6] * 14, 1.5) is None  # already past it: that is a level, not a drift
    assert risk.drift_of([0.01 * i for i in range(14)], 1.5) is None  # too slow to matter in 10 days


def test_the_brain_stays_red_for_helena_and_a_lone_indicator_never_makes_a_system_red():
    s = health.snapshot("h", at(2))
    assert s["systems"]["brain"]["level"] == 2 and s["systems"]["brain"]["risks"] == ["fatigue"]
    _day(100)
    assert _checkin("a", "vitals", {"hr": 100}).status_code == 200
    s = health.snapshot("a", mission.state())
    assert s["indicators"]["hr"]["level"] == 2 and s["indicators"]["hr"]["population"]["status"] != "critical"
    assert s["systems"]["heart"]["level"] == 1


def test_suggestions_never_contradict_the_level_of_the_indicator_they_cite():
    from canary.assistant import suggestions
    cited = {"sleep": ["sleep"], "nap": ["kss"], "exercise": ["exer"], "bone": ["bone"], "water": ["water"], "breathe": ["stress", "mood"]}
    for step in range(6):
        at(step)
        for c in catalog.CREW:
            f = suggestions.facts(c["id"])
            for s in suggestions.candidates(f):
                if s["id"] in cited:
                    ok = any(f["ind"][i]["level"] for i in cited[s["id"]]) or (s["id"] == "sleep" and "sleep" in f["risk"]["fatigue"]["signals"])
                    assert ok, (step, c["id"], s["id"])
    at(2)
    assert "talk" not in [s["id"] for s in suggestions.candidates(suggestions.facts("h"))]  # no wellbeing check-in, no "talk"
    assert _checkin("h", "wellbeing", {"phq2": 4, "gad2": 1}).status_code == 200
    assert "talk" in [s["id"] for s in suggestions.candidates(suggestions.facts("h"))]


def test_get_risks_is_a_read_only_tool_with_sources_and_chat_answers_from_it():
    from canary.assistant import tools
    at(2)
    r = tools.get_risks("h")
    assert r["data"][0]["level"] == 2 and r["sources"] and "get_risks" in tools.TOOLS
    a = client.post("/api/assistant/ask", json={"crew_id": "h", "question": "Am I at risk of fatigue?"}, headers=as_("h")).json()
    assert a["mode"] == "grounded" and any(t["tool"] == "get_risks" for t in a["tools_used"])
    assert any("since day" in c["text"] for c in a["claims"]) and all(c["source_ids"] for c in a["claims"])
    assert "risks" in client.get("/api/crew/h", headers=as_("h")).json()


# ---------------------------------------------------------------- Prompt 4: the advice loop, alerts that last, lighter training under fatigue
def _med():
    tok = client.post("/api/medical/session", json={"pin": "1961"}).json()["token"]
    return {"Authorization": f"Bearer {tok}"}


def _counts():
    return {t: db.q(f"SELECT COUNT(*) n FROM {t}")[0]["n"] for t in ("advice", "messages", "settings", "goal_log", "checkins")}


def _advice_messages():
    return db.q("SELECT * FROM messages WHERE kind='advice'")


def test_alert_goals_and_suggestions_say_what_they_verify():
    at(2)
    g = {x["id"]: x for x in client.get("/api/goals/h", headers=as_("h")).json()["personal"]}
    assert g["al_screens"]["verify"] == {"indicator": "sleep", "after_days": 3} and g["al_psy"]["verify"]["indicator"] == "mood"
    items = client.get("/api/suggestions/h", headers=as_("h")).json()["items"]
    assert all(s["verify"] is None or s["verify"]["after_days"] >= 1 for s in items)
    assert next(s for s in items if s["id"] == "sleep")["verify"] == {"indicator": "sleep", "after_days": 7}


def test_the_sleep_suggestion_becomes_an_experiment_whose_result_follows_the_day():
    at(2)  # day 147
    h = as_("h")
    client.post("/api/suggestions/h/sleep/accept", headers=h)
    a = client.get("/api/advice/h", headers=h).json()
    assert [x["goal_id"] for x in a["active"]] == ["sg_sleep"] and a["active"][0]["check_day"] == 154 and a["done"] == []
    _day(149)
    a = client.get("/api/advice/h", headers=h).json()
    assert a["active"][0]["status"] == "pending"
    sg = next(x for x in client.get("/api/goals/h", headers=h).json()["personal"] if x["id"] == "sg_sleep")
    assert sg["advice"] == {"status": "pending", "check_day": 154}

    def result(day):
        _day(day)
        d = client.get("/api/advice/h", headers=h).json()["done"]
        return (d[0]["status"], d[0]["bad_at_check"]) if d else None

    first = {d: result(d) for d in (155, 154, 153, 160, 155, 222)}
    assert first[153] is None and first[154] == first[155] == first[160] == first[222] == first[155]
    assert first[155][0] in ("improved", "same", "worse")
    assert result(155) == first[155]  # any order, any number of times
    assert first[155][0] == "worse"  # the slide is still deepening at day 154 in the simulation


def test_two_rounds_without_improvement_give_one_message_and_one_alternative():
    from canary.assistant import suggestions
    from canary.domain import advice
    advice.start("h", "sg_sleep", "suggestion", {"indicator": "sleep", "after_days": 7}, 140)
    advice.start("h", "sg_breathe", "suggestion", {"indicator": "stress", "after_days": 7}, 147)
    at(2)
    _day(150)  # only the first round has concluded
    assert _advice_messages() == [] and advice.escalation("h", 150) == []
    for d in (154, 154, 160, 154):
        _day(d)
    msgs = _advice_messages()
    assert len(msgs) == 1 and msgs[0]["recipient"] == "k" and msgs[0]["sender"] == "canary"
    ids = [s["id"] for s in suggestions.candidates(suggestions.facts("h"))]
    assert ids.count("alt_fatigue") == 1
    assert client.post("/api/suggestions/h/alt_fatigue/accept", headers=as_("h")).status_code == 200
    assert len(_advice_messages()) == 1  # accepting does not repeat the message
    # advice about the medical officer goes to the substitute
    advice.start("k", "sg_sleep", "suggestion", {"indicator": "sleep", "after_days": 7}, 100)
    advice.start("k", "sg_talk", "suggestion", {"indicator": "mood", "after_days": 7}, 107)
    _day(114)
    assert [m["recipient"] for m in _advice_messages() if m["text"].startswith("Advice review for Kenji")] == ["h"]


def test_advice_reviews_are_private_to_the_medical_officer():
    from canary.domain import advice
    advice.start("h", "sg_sleep", "suggestion", {"indicator": "sleep", "after_days": 7}, 140)
    advice.start("h", "sg_breathe", "suggestion", {"indicator": "stress", "after_days": 7}, 147)
    _day(154)
    assert len(_advice_messages()) == 1
    assert not any(m["kind"] == "advice" for m in client.get("/api/messages").json())
    assert not any(m["kind"] == "advice" for m in client.get("/api/messages", headers=as_("t")).json())
    assert any(m["kind"] == "advice" for m in client.get("/api/messages", headers=_med()).json())
    assert any(m["kind"] == "advice" for m in client.get("/api/messages", headers=as_("k")).json())


def test_reading_never_writes():
    at(2)
    h = as_("h")
    client.post("/api/suggestions/h/sleep/accept", headers=h)
    before = _counts()
    for url in ("/api/advice/h", "/api/goals/h", "/api/suggestions/h", "/api/crew/h", "/api/leaderboard", "/api/crew/overview"):
        assert client.get(url, headers=h).status_code == 200
    _day(160)
    assert _counts() == before


def test_a_seen_alert_stays_seen_but_a_new_episode_is_not():
    _day(100)
    a = as_("a")
    assert _checkin("a", "kss", {"level": 8}).status_code == 200
    al = next(x for x in client.get("/api/crew/a", headers=a).json()["alerts"] if x["id"] == "sleepy")
    assert al["since_day"] == 100 and al["days_active"] == 1 and al["seen"] is False
    assert client.post("/api/alerts/a/sleepy/seen", headers=a).json()["seen"] is True
    assert client.post("/api/alerts/a/sleepy/seen", headers=as_("t")).status_code == 403
    assert next(x for x in client.get("/api/crew/a", headers=a).json()["alerts"] if x["id"] == "sleepy")["seen"] is True
    _day(101)  # a day without it
    assert client.post("/api/alerts/a/sleepy/seen", headers=a).status_code == 404
    _day(102)
    assert _checkin("a", "kss", {"level": 8}).status_code == 200
    al = next(x for x in client.get("/api/crew/a", headers=a).json()["alerts"] if x["id"] == "sleepy")
    assert al["since_day"] == 102 and al["seen"] is False
    _day(100)
    assert next(x for x in client.get("/api/crew/a", headers=a).json()["alerts"] if x["id"] == "sleepy")["seen"] is True


def test_alerts_know_how_long_they_have_been_active_whatever_the_visiting_order():
    s = {d: {a["id"]: (a["since_day"], a["days_active"]) for a in health.snapshot("h", _day(d))["alerts"]} for d in (153, 147, 153)}
    assert s[153]["behaviour"][0] == s[147]["behaviour"][0]
    assert s[153]["behaviour"][1] == 153 - s[153]["behaviour"][0] + 1 and s[147]["behaviour"][0] <= 147


def test_exercise_is_lighter_and_explained_under_fatigue_within_the_medical_limit():
    _day(100)
    plain = next(x for x in client.get("/api/goals/h", headers=as_("h")).json()["personal"] if x["id"] == "exercise")
    assert "lighter" not in plain["title"] and "adjusted" not in plain
    at(2)  # day 147: fatigue level 2
    base_board = client.get("/api/leaderboard").json()
    g = next(x for x in client.get("/api/goals/h", headers=as_("h")).json()["personal"] if x["id"] == "exercise")
    assert g["adjusted"] == {"pct": 30, "minutes": 84, "target": 120, "reason": "fatigue", "max_pct": 30}
    assert "lighter today" in g["title"] and "30%" in g["why"] and "medical team" in g["why"]
    r = client.put("/api/medical/exercise-adjust", json={"max_pct": 10, "level1": 15, "level2": 30}, headers=_med())
    assert r.status_code == 200
    g = next(x for x in client.get("/api/goals/h", headers=as_("h")).json()["personal"] if x["id"] == "exercise")
    assert g["adjusted"]["pct"] == 10 and g["adjusted"]["minutes"] == 108  # never above the limit the doctors set
    assert client.put("/api/medical/exercise-adjust", json={"max_pct": 10, "level1": 15, "level2": 30}).status_code == 401
    assert client.get("/api/leaderboard").json() == base_board  # lighter training does not touch the ranking
    k = next(x for x in client.get("/api/goals/k", headers=as_("k")).json()["personal"] if x["id"] == "exercise")
    assert "adjusted" not in k  # no fatigue risk for Kenji


def test_advice_is_private_to_the_person_and_the_medical_team():
    at(2)
    assert client.get("/api/advice/h", headers=as_("k")).status_code == 403
    assert client.get("/api/advice/h").status_code == 403
    assert client.get("/api/advice/h", headers=as_("h")).status_code == 200
    assert client.get("/api/advice/h", headers=_med()).status_code == 200


def test_ticking_an_alert_goal_opens_its_experiment_once():
    at(2)
    h = as_("h")
    for _ in range(2):
        assert client.post("/api/goals/h/al_screens", json={"done": True}, headers=h).status_code == 200
    a = client.get("/api/advice/h", headers=h).json()
    assert [(x["goal_id"], x["indicator"], x["check_day"], x["origin"]) for x in a["active"]] == [("al_screens", "sleep", 150, "alert")]
