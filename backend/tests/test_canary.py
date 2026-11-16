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
from canary.domain import catalog, goals, health, mission, plan as plan_mod, registry  # noqa: E402
from canary.main import app  # noqa: E402
from tests.golden_capture import reset_demo  # noqa: E402
from tests.support import GROUND, client_from, plan_preset, plan_put, plan_setup, control_headers, crew_headers, empty, fresh as fresh_demo, medical_headers  # noqa: E402,F401

client = TestClient(app)


@pytest.fixture(autouse=True)
def fresh():
    reset_demo(client)
    yield
    reset_demo(client)


PINS = {"h": "1001", "k": "1002", "a": "1003", "t": "1004"}


def as_(cid):
    """Sign in with the default PIN and send the session token, as the web app does."""
    r = client.post(f"/api/crew/{cid}/session", json={"pin": PINS[cid]})
    assert r.status_code == 200
    return {"Authorization": "Bearer " + r.json()["token"]}


def at(step):
    return client.put("/api/mission", json={"step": step}, headers=control_headers(client)).json()


def test_no_alerts_while_learning_on_earth():
    ms = at(0)
    assert ms["learning"]
    for c in catalog.CREW:
        assert [a for a in health.snapshot(c["id"], ms)["alerts"] if not a.get("data")] == []  # missing data is not a health alert


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
    lb = client.get("/api/leaderboard", headers=as_("h")).json()
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


def test_ranking_and_crew_missions_never_reveal_alert_doctor_goals_or_health_numbers():
    """The crew sees effort on routine goals only. A goal from an alert, the medical team or a suggestion, and
    the measured exercise minutes, are health data: ticking one must not move anything the crew can see."""
    at(3)
    lb = client.get("/api/leaderboard", headers=as_("h")).json()
    for r in lb["rows"]:
        assert set(r) == {"crew_id", "goals_week", "completion_7d", "streak", "badges_earned", "patches", "rank", "name", "initials", "role"}
        assert all(set(x) == {"id", "name"} for x in r["patches"]) and len(r["patches"]) == r["badges_earned"]
    ex = next(t for t in lb["team"] if t["id"] == "team_exercise")
    # Each mission names the personal goal that counts toward it (catalog data) and carries no per-person numbers.
    assert ex["unit"] == "sessions" and ex["personal_ids"] == ["exercise"] and "contrib" not in ex
    assert {t["id"]: t["personal_ids"] for t in lb["team"]}["team_books"] == ["read"]
    assert all(set(g) == set(ex) for g in lb["team"]) and all(len(g["personal_ids"]) == 1 for g in lb["team"])

    def public():
        ov = client.get("/api/crew/overview", headers=as_("h")).json()
        return client.get("/api/leaderboard", headers=as_("h")).json(), {k: v for k, v in ov.items() if k in ("people", "team", "crew_streak")}

    before = public()
    h = as_("h")
    for gid in ("al_probe", "med_999", "sg_probe"):
        assert client.post(f"/api/goals/h/{gid}", json={"done": True}, headers=h).status_code == 200
    assert public() == before
    for gid in ("al_probe", "med_999", "sg_probe"):
        client.post(f"/api/goals/h/{gid}", json={"done": False}, headers=h)


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
    assert client.post(f"/api/briefings/{b['id']}/approve", headers=_med()).json()["status"] == "queued"


def test_medical_endpoints_need_the_pin():
    assert client.get("/api/medical/overview").status_code == 401
    assert client.post("/api/medical/session", json={"account_id": "k", "pin": "0000"}).status_code == 401
    tok = medical_headers(client)["Authorization"][7:]
    assert client.get("/api/medical/overview", headers={"Authorization": f"Bearer {tok}"}).status_code == 200


def test_closing_an_emergency_creates_follow_up_goals_and_a_report():
    at(4)
    e = client.post("/api/emergencies", json={"responder": "k"}, headers=crew_headers(client, "h")).json()
    client.post(f"/api/emergencies/{e['id']}", json={"protocol": "seizure", "patient": "t", "text": "Seizure stopped at 02:10"}, headers=crew_headers(client, "h"))
    client.post(f"/api/emergencies/{e['id']}", json={"close": True, "outcome": "stable"}, headers=crew_headers(client, "h"))
    titles = [g["title"] for g in client.get("/api/goals/t", headers=as_("t")).json()["personal"] if g["by"] == "medical"]
    assert titles and any("Glucose" in t for t in titles)
    assert any(m["kind"] == "report" for m in client.get("/api/messages", headers=crew_headers(client, "h")).json())


def test_plan_drives_the_place_and_goals():
    plan_preset("iss")
    ms = client.put("/api/mission", json={"day": 100}, headers=control_headers(client)).json()
    assert ms["location"] == "iss" and ms["leg"]["label"].startswith("Expedition")
    titles = [g["title"] for g in client.get("/api/goals/h", headers=as_("h")).json()["personal"]]
    assert any("treadmill" in t for t in titles) and any("cupola" in t for t in titles)
    assert client.put("/api/mission", json={"day": 200}, headers=control_headers(client)).json()["location"] == "earth"


def test_custom_plan_is_validated_and_used():
    bad = {"name": "x", "legs": [{"location": "earth", "start": 0, "end": 10}, {"location": "moon", "start": 5, "end": 20}]}
    assert plan_put(bad).status_code == 400
    good = {"name": "Short hop", "legs": [{"location": "earth", "start": -30, "end": -1}, {"location": "rocket", "start": 0, "end": 2},
                                          {"location": "moon", "start": 3, "end": 40, "label": "Base camp"}]}
    assert plan_put(good).status_code == 200
    ms = client.put("/api/mission", json={"day": 10}, headers=control_headers(client)).json()
    assert ms["location"] == "moon" and ms["place"]["gravity"] == "1/6 g" and ms["leg"]["label"] == "Base camp"
    assert any(p["variant"] for p in client.get("/api/protocols").json()["protocols"]["rad"]["steps"])


def test_bone_loss_estimate_depends_on_gravity_in_the_plan():
    """Bone density cannot be scanned on board: the estimate follows the days in each gravity (the plan), and is labelled one."""
    plan_preset("mars")
    at(2)
    mars = health.bone_estimate("t", 30)["loss_pct"]
    plan_preset("moon")
    moon = health.bone_estimate("t", 30)["loss_pct"]  # days 5 to 19 on the Moon (1/6 g) instead of in 0 g
    assert mars > moon > 0


def test_crew_overview_hides_private_health():
    at(2)
    o = client.get("/api/crew/overview", headers=as_("h")).json()
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
    import io
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (1, 1), (10, 20, 30)).save(buf, "PNG")
    png = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()  # a real 1x1 image (decoded on save)
    assert client.put("/api/crew/h/photo", json={"data_url": png}, headers=as_("k")).status_code == 403
    assert client.put("/api/crew/h/photo", json={"data_url": "javascript:alert(1)"}, headers=as_("h")).status_code == 400
    assert client.put("/api/crew/h/photo", json={"data_url": png}, headers=as_("h")).json() == {"h": png}
    assert client.get("/api/crew/photos", headers=as_("h")).json() == {"h": png}
    assert client.delete("/api/crew/h/photo", headers=as_("h")).json() == {}

def test_medical_team_sees_everyone_and_storm_is_a_crew_hazard():
    tok = medical_headers(client)["Authorization"][7:]
    med = {"Authorization": f"Bearer {tok}"}
    assert client.get("/api/crew/h", headers=med).json()["access"] == "medical"
    assert client.get("/api/crew").status_code == 401
    at(2)
    assert all("ops" in p for p in client.get("/api/crew", headers=med).json()["crew"])
    ov = client.get("/api/medical/overview", headers=med).json()["crew"]
    assert next(c for c in ov if c["id"] == "h")["ops"]["key"] == "rest"
    o = client.get("/api/crew/overview", headers=as_("h")).json() if at(3) else None
    assert o["hazards"][0]["level"] == 2 and not o["eva_open"]


# ---------------------------------------------------------------- the mission clock before and after the plan
@pytest.mark.parametrize("day", [-60, -365, -31, 800, 2000])
def test_every_page_works_on_any_mission_day(day):
    assert client.put("/api/mission", json={"day": day}, headers=control_headers(client)).json()["day"] == day
    h = as_("h")
    for path in ("/api/crew/overview", "/api/leaderboard"):
        assert client.get(path, headers=h).status_code == 200, path
    for path in ("/api/crew/h", "/api/goals/h"):
        assert client.get(path, headers=h).status_code == 200, path


# ---------------------------------------------------------------- PINs and sessions
def test_wrong_pin_is_401_and_the_right_one_returns_a_token():
    assert client.post("/api/crew/h/session", json={"pin": "9999"}).status_code == 401
    r = client.post("/api/crew/h/session", json={"pin": "1001"}).json()
    assert r["crew_id"] == "h" and r["token"].startswith("crew.h.") and r["expires_at"] > 0
    assert client.post("/api/crew/h/session", json={"pin": "12"}).status_code == 422  # exactly 4 digits
    assert client.post("/api/crew/zz/session", json={"pin": "1001"}).status_code == 404


def test_pin_attempts_are_rate_limited_per_person_and_per_address():
    auth.clear_failures()
    elsewhere = client_from("10.9.8.7")  # another terminal
    for _ in range(5):
        assert client.post("/api/crew/h/session", json={"pin": "0000"}).status_code == 401
    assert client.post("/api/crew/h/session", json={"pin": "1001"}).status_code == 429  # even the right PIN waits
    assert elsewhere.post("/api/crew/h/session", json={"pin": "1001"}).status_code == 429  # Helena's account is paused from everywhere
    assert elsewhere.post("/api/crew/k/session", json={"pin": "1002"}).status_code == 200  # another person, another address: open
    assert client.post("/api/crew/k/session", json={"pin": "1002"}).status_code == 429  # the first address is paused for everybody
    auth.clear_failures()


def test_a_plain_id_in_the_viewer_header_is_rejected():
    assert client.get("/api/goals/h", headers={"Authorization": "Bearer " + "h"}).status_code == 403
    assert client.get("/api/crew/h", headers={"Authorization": "Bearer " + "h"}).status_code == 403
    exp = int(time.time()) - 10  # a correctly signed but expired token
    body = f"crew.h.crew.{exp}.abcdef0123456789"
    assert client.get("/api/goals/h", headers={"Authorization": "Bearer " + f"{body}.{auth._sig(body)}"}).status_code == 403
    assert client.get("/api/goals/h", headers={"Authorization": "Bearer " + as_("h")["Authorization"][7:] + "0"}).status_code == 403


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
    assert '"2468"' not in stored and set(db.get_setting("pins")["h"]) == {"salt", "hash"}  # stored salted and hashed (a run of hex digits may spell 2468 by chance)
    reset_demo(client)
    assert client.post("/api/crew/h/session", json={"pin": "1001"}).status_code == 200  # reset restores defaults


def test_medical_pin_is_four_digits():
    assert client.post("/api/medical/session", json={"account_id": "k", "pin": "196"}).status_code == 422
    assert client.post("/api/medical/session", json={"account_id": "k", "pin": "1002"}).status_code == 200


# ---------------------------------------------------------------- mission setup
def test_setup_saves_the_plan_and_marks_it_done():
    assert client.get("/api/mission").json()["setup_done"] is True  # configured by the mission admin
    legs = [{"location": "earth", "start": -60, "end": -1, "label": "Training"},
            {"location": "rocket", "start": 0, "end": 4, "label": "Transfer"},
            {"location": "moon", "start": 5, "end": 34, "label": "Surface"}]
    bad = plan_setup({"name": "x", "legs": [legs[1], {**legs[2], "start": 3}]})
    assert bad.status_code == 400
    ms = plan_setup({"name": "Artemis", "legs": legs}).json()
    assert ms["setup_done"] and ms["plan_name"] == "Artemis" and ms["step"] == 0
    assert client.put("/api/mission", json={"day": 10}, headers=control_headers(client)).json()["location"] == "moon"
    reset_demo(client)
    ms = client.get("/api/mission").json()
    assert ms["setup_done"] is True and ms["plan_name"] == "Mars reference mission"  # reset restores the demo mission


def test_ridge_hazards_follow_place_and_storm():
    o = client.get("/api/crew/overview", headers=as_("h")).json()  # pre-flight, on Earth
    assert [h["id"] for h in o["ridge"]] == ["R", "I", "D", "G", "E"] and all(h["level"] == 0 for h in o["ridge"])
    o = client.get("/api/crew/overview", headers=as_("h")).json() if at(3) else None  # the replayed May 2024 storm, in transit
    r = {h["id"]: h for h in o["ridge"]}
    assert r["R"]["level"] == 2 and r["G"]["label"] == "High" and o["warnings"][0]["id"] == "storm"


def test_plan_conditions_project_the_dose():
    c = client.get("/api/plan/conditions").json()
    assert [l["location"] for l in c["legs"]] == ["earth", "rocket", "transit", "mars", "mars_rover", "mars", "transit", "earth"]
    doses = [v for _, v in c["dose"]["series"]]
    assert doses == sorted(doses) and c["dose"]["end_msv"] > c["dose"]["limit_msv"] * 0.5
    assert c["dose"]["origin"] == "estimated" and c["dose"]["crew_exceeding"] == len(catalog.CREW)  # the return leg takes every demo crew past 600 mSv


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


def test_my_information_is_private_and_ages_with_the_mission():
    at(0)  # L-30
    r = client.get("/api/crew/h/record", headers=as_("h")).json()
    assert r["blood_type"] == "O−" and r["age"] == 46 and r["bmi"] == 21.8 and r["date_today"] == "2035-05-02"
    assert client.get("/api/crew/h/record", headers=as_("k")).status_code == 403
    tok = medical_headers(client)["Authorization"][7:]
    assert client.get("/api/crew/h/record", headers={"Authorization": f"Bearer {tok}"}).status_code == 200


def test_mission_control_registers_from_zero_and_reset_restores_the_demo():
    assert client.post("/api/control/session", json={"account_id": "g-mcc1", "pin": "0000"}).status_code == 401
    assert client.get("/api/control/overview").status_code == 401
    med = medical_headers(client)["Authorization"][7:]
    assert client.get("/api/control/overview", headers={"Authorization": "Bearer " + med}).status_code == 401  # a medical token is not a control token
    c = control_headers(client)
    assert client.get("/api/mission/overview").json()["callsign"] == "Odyssey 1"
    demo = client.get("/api/control/demo", headers=c).json()
    assert client.post("/api/control/register", headers=c, json={"crew": demo["crew"], "mission": demo["mission"], "ground": demo["ground"]}).status_code == 409  # registered: locked

    empty(client)  # what a system with nothing registered looks like
    assert client.get("/api/catalog").json()["crew"] == [] and client.get("/api/mission").json()["registered"] is False
    crew = [dict(p) for p in demo["crew"]]
    crew[0] = {**crew[0], "name": "Ana Lima", "pin": "2468"}
    c = control_headers(client)  # the first-access sign-in: no MCC account exists yet
    o = client.post("/api/control/register", headers=c, json={"crew": crew, "mission": {**demo["mission"], "callsign": "Kestrel 2", "preset": "iss"}, "ground": demo["ground"]}).json()
    assert o["registered"] and o["overview"]["callsign"] == "Kestrel 2" and o["mission"]["step"] == 0
    assert any(p["name"] == "Ana Lima" and p["initials"] == "AL" for p in client.get("/api/catalog").json()["crew"])
    assert client.post("/api/crew/h/session", json={"pin": "2468"}).status_code == 200
    assert client.get("/api/plan").json()["preset"] == "iss"

    reset_demo(client)
    assert client.get("/api/catalog").json()["crew"][0]["name"] == "Helena Duarte"


def test_mission_control_brings_back_the_demo_data_on_an_empty_system_only():
    assert client.post("/api/control/demo-data").status_code == 401
    c = control_headers(client)
    before = client.get("/api/control/data-status", headers=c).json()["counts"]
    assert client.post("/api/control/demo-data", headers=c).status_code == 409  # registered: only the demo reset starts over
    empty(client)
    c = control_headers(client)
    o = client.post("/api/control/demo-data", headers=c).json()
    assert o["registered"] and o["overview"]["callsign"] == "Odyssey 1" and len(o["people"]) == 4
    c = control_headers(client)
    assert client.get("/api/control/data-status", headers=c).json()["counts"] == before
    assert client.get("/api/scenes").json()  # the demo story is back
    assert client.get("/api/control/overview", headers=c).status_code == 200  # Mission Control stays signed in


def _register_form(crew, mission, demo):
    """Register on an empty system (a registered mission is locked) and answer the response."""
    empty(client)
    return client.post("/api/control/register", headers=control_headers(client), json={"crew": crew, "mission": mission, "ground": demo["ground"]})


def _register(c, **mission):
    demo = client.get("/api/control/demo", headers=control_headers(client)).json()
    return _register_form(demo["crew"], {**demo["mission"], **mission}, demo)


def _legs():
    return client.get("/api/plan").json()["legs"]


def test_the_demo_form_carries_eva_role_and_the_rover_presets():
    demo = client.get("/api/control/demo", headers=_ctl()).json()
    assert [p["eva"] for p in demo["crew"]] == ["surface", "none", "surface", "surface"]
    assert all("prior_dose_msv" in p for p in demo["crew"])  # empty in the demo: the form shows the estimate
    assert demo["rover_presets"] == ["mars", "moon"] and demo["iss_dose_msv_per_day"] == catalog.LOCATIONS["iss"]["dose_rate"]
    assert demo["itineraries"]["moon"]["rover"] != demo["itineraries"]["moon"]["plain"] and demo["itineraries"]["iss"]["rover"] == demo["itineraries"]["iss"]["plain"]


@pytest.mark.parametrize("preset,rover_place,body", [("moon", "moon_rover", "moon"), ("mars", "mars_rover", "mars")])
def test_registering_moon_or_mars_with_or_without_the_rover_leg(preset, rover_place, body):
    c = _ctl()
    assert _register(c, preset=preset).status_code == 200  # left out: the profile's default, with the rover
    with_rover = _legs()
    assert rover_place in [l["location"] for l in with_rover]
    assert _register(c, preset=preset, rover=True).status_code == 200 and _legs() == with_rover

    assert _register(c, preset=preset, rover=False).status_code == 200
    without = _legs()
    assert rover_place not in [l["location"] for l in without]
    # the traverse days stay on the surface: same first and last day, no gap, no overlap, no two neighbours alike
    assert (without[0]["start"], without[-1]["end"]) == (with_rover[0]["start"], with_rover[-1]["end"])
    assert all(b["start"] == a["end"] + 1 and a["location"] != b["location"] for a, b in zip(without, without[1:]))
    assert client.get("/api/mission/overview").json()["legs"] == without
    assert client.post("/api/crew/h/session", json={"pin": "1001"}).status_code == 200


def test_the_rover_is_refused_for_profiles_without_one_and_nothing_is_saved():
    c = _ctl()
    assert "mission.rover" in _fields(_register(c, preset="iss", rover=True))
    assert not registry.registered() and catalog.CREW == []  # a refused registration saves nothing
    assert _register(c, preset="iss", rover=False).status_code == 200
    assert _register(c, preset="iss").status_code == 200  # left out: no rover, no error
    assert not any(l["location"].endswith("_rover") for l in _legs())
    assert "mission.rover" in _fields(_register(c, preset="mars", rover="maybe"))


def test_eva_role_and_prior_dose_reach_my_information_and_the_medical_team():
    c = _ctl()
    demo = client.get("/api/control/demo", headers=c).json()
    crew = [dict(p) for p in demo["crew"]]
    crew[0].update(eva="microgravity", prior_dose_msv=120.5)
    assert _register_form(crew, demo["mission"], demo).status_code == 200
    r = client.get("/api/crew/h/record", headers=as_("h")).json()
    assert r["eva"] == "microgravity" and r["prior_dose_msv"] == 120.5 and r["prior_dose"] == {"msv": 120.5, "estimate": False, "source": "personal record"}
    k = client.get("/api/crew/k/record", headers=as_("k")).json()  # no recorded dose: the estimate from 181 days in space
    assert k["prior_dose"]["estimate"] and k["prior_dose"]["msv"] == round(181 * catalog.LOCATIONS["iss"]["dose_rate"], 1) and k["eva"] == "none"
    d = client.get("/api/crew/h", headers=as_("h")).json()
    assert d["standard_profile"]["eva"] == "microgravity" and d["dose"]["prior_msv"] == 120.5 and not d["dose"]["prior_estimate"]


def _rows(x):
    """Every dict that describes one person (it has initials), at any depth. A place has an id and a name too, and its own `eva`."""
    if isinstance(x, dict):
        if "id" in x and "initials" in x:
            yield x
        for v in x.values():
            yield from _rows(v)
    elif isinstance(x, list):
        for v in x:
            yield from _rows(v)


def test_mission_and_control_overviews_carry_no_eva_role_or_prior_dose_per_person():
    c = _ctl()
    demo = client.get("/api/control/demo", headers=c).json()
    crew = [dict(p) for p in demo["crew"]]
    crew[0].update(eva="microgravity", prior_dose_msv=120.5)  # a marker that would show if it leaked
    assert _register_form(crew, demo["mission"], demo).status_code == 200
    c = control_headers(client)
    mission_ov, control_ov = client.get("/api/mission/overview", headers=as_("h")), client.get("/api/control/overview", headers=c)
    for name, body in {"mission overview": mission_ov.json(), "control overview": control_ov.json(),
                       "crew overview": client.get("/api/crew/overview", headers=as_("h")).json()}.items():
        rows = list(_rows(body))
        assert rows, name
        for row in rows:
            assert not {"eva", "prior_dose_msv", "prior_dose", "prior_msv", "prior_estimate"} & set(row), (name, row)
    assert not {"eva", "prior_dose_msv", "prior_msv"} & set(_keys(client.get("/api/leaderboard", headers=as_("h")).json()))
    assert "120.5" not in mission_ov.text and "120.5" not in control_ov.text


def test_mission_control_and_the_medical_console_talk_with_the_signal_delay():
    at(2)  # transit: 10 minutes each way, 20x faster in the demo = 15 s
    client.post("/api/messages", json={"recipient": "medical", "text": "Confirm the crew is in the shelter."}, headers=control_headers(client))
    client.post("/api/messages", json={"recipient": "mission-control", "text": "All four in the shelter."}, headers=_med())
    msgs = client.get("/api/messages", headers=control_headers(client)).json()
    out = next(m for m in msgs if m["sender"] == "g-mcc1")  # the sender is the account that signed in
    back = next(m for m in msgs if m["recipient"] == "mission-control")
    assert back["sender"] == "k"
    assert not out["delivered"] and 10 <= out["eta_s"] <= 15
    assert out["text"].startswith("Confirm the crew") and not out["in_transit"]  # the sender still sees what they sent
    assert back["in_transit"] and back["text"] == ""  # the receiving side gets the text when the signal does
    at_medical = client.get("/api/messages", headers=_med()).json()
    assert next(m for m in at_medical if m["sender"] == "g-mcc1")["text"] == ""  # and the other way round
    assert next(m for m in at_medical if m["recipient"] == "mission-control")["text"].startswith("All four")  # the sender's own text


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
    md = simdata.REPORT_FILE.read_text(encoding="utf-8")
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
    assert simdata.OBS_FILE.read_text(encoding="utf-8") == simdata.csv_text(rows), "run: python data/generate_dataset.py"
    assert simdata.REPORT_FILE.read_text(encoding="utf-8") == simdata.report(rows, rec, plan_mod.PRESETS["mars"]["name"])
    assert simdata.OBS_FILE.stat().st_size < 10_000_000
    assert simdata.csv_text(rows) == simdata.csv_text(simdata.Generator(plan_mod.PRESETS["mars"]["legs"], rec, simdata.REAL_DIR).observations())


def test_osd569_rows_are_modelled_simulated_and_keep_the_original_label():
    from canary.domain import nasa, simdata
    rows_all = simdata.read_csv(simdata.OBS_FILE)
    assert not [r for r in rows_all if r["origin"] == "real"]  # nothing in the demo is a real person's measurement
    lab = [r for r in rows_all if "Inspiration4" in r["note"]]
    assert {r["origin"] for r in lab} == {"simulated"}
    assert {r["source"] for r in lab} == {"modelled on Inspiration4 (NASA OSDR OSD-569)", "modelled on Inspiration4 (NASA OSDR OSD-575)"}
    assert len([r for r in lab if "OSD-575" in r["source"]]) == 4 * 4 * 7  # creatinine, potassium, calcium, crp
    rows = [r for r in lab if "OSD-569" in r["source"]]
    assert len(rows) == 4 * 7 * 7
    h_lym = {r["note"].split()[0]: float(r["value"]) for r in rows if r["crew_id"] == "h" and r["indicator"] == "lym"}
    shown = nasa.blood("h", "F")
    assert [h_lym[t] for t in nasa.snapshot()["cbc"]["tp"]] == shown["lymphocytes"] and shown["subject"] == "C002" and shown["origin"] == "simulated"
    assert set(h_lym) == {"L-92", "L-44", "L-3", "R+1", "R+45", "R+82", "R+194"}
    # pre-flight collections set the baseline of the other simulated rows
    pre = [float(r["value"]) for r in rows if r["crew_id"] == "h" and r["indicator"] == "lym" and int(r["day"]) < 0]
    sim = [float(r["value"]) for r in rows_all if r["crew_id"] == "h" and r["indicator"] == "lym"]
    assert abs(sum(sim) / len(sim) - sum(pre) / len(pre)) < 600


def test_simdata_follows_the_plan_the_same_way_plan_does():
    from canary.domain import plan as plan_mod, simdata
    for key in ("mars", "iss", "moon"):
        plan_preset(key)
        legs = plan_mod.get()["legs"]
        for d in range(-70, 800, 7):
            assert simdata.location_at(legs, d) == plan_mod.location_at(d)
            assert simdata.days_since_gravity_change(legs, d) == plan_mod.days_since_gravity_change(d)


def test_a_custom_plan_gets_its_own_table_and_value_never_breaks():
    from canary.domain import telemetry
    good = {"name": "Short hop", "legs": [{"location": "earth", "start": -30, "end": -1}, {"location": "rocket", "start": 0, "end": 2},
                                          {"location": "moon", "start": 3, "end": 40}]}
    assert plan_put(good).status_code == 200
    assert telemetry.last_observation("h", "co2", 10) is None  # co2 belongs to "cabin"
    assert telemetry.last_observation("cabin", "co2", 10)["value"] > 1000
    assert telemetry.SOURCE.value("t", "hr", -500) is None  # before the first measurement: no value, and never an exception
    for d in (0, 20, 40, 41, 3000):
        assert isinstance(telemetry.SOURCE.value("t", "hr", d), float)


# ---------------------------------------------------------------- Prompt 1: everything the person measures is an observation
def _day(d):
    return client.put("/api/mission", json={"day": d}, headers=control_headers(client)).json()


def _no_device(cid, inds, days=(99, 100)):
    """Drop the simulated instrument rows of these indicators so a self-report on those days is the only reading (an instrument
    reading takes precedence over a self-report, by design)."""
    from canary.domain import data
    with data._transaction() as c:
        for i in ([inds] if isinstance(inds, str) else inds):
            c.execute("DELETE FROM observations WHERE crew_id=? AND indicator=? AND method!='manual' AND day BETWEEN ? AND ?", (cid, i, days[0], days[-1]))


def _checkin(cid, kind, payload):
    return client.post("/api/checkins", json={"crew_id": cid, "kind": kind, "payload": payload}, headers=as_(cid))


def test_a_pvt_checkin_is_the_days_own_value_and_is_not_smoothed():
    from canary.domain import telemetry
    _day(100)
    stored = {d: telemetry.observation("a", "react", d)["value"] for d in (101, 102)}
    assert _checkin("a", "pvt", {"ms": 600}).status_code == 200
    assert dict(telemetry.series("a", "react", 100, 5))[100] == 600
    assert dict(telemetry.series("a", "react", 102, 5))[100] == 600  # still there in later charts
    assert health.indicator("a", "react", mission.state())["value"] == 600  # the day's own value, no weighting with earlier days
    for d in (101, 102):  # the next days read their own readings: the check-in does not bleed into them
        assert telemetry.observation("a", "react", d)["value"] == stored[d]


@pytest.mark.parametrize("kind,payload,ind,value", [("dsst", {"correct": 10}, "dsst", 10), ("span", {"span": 3}, "span", 3),
                                                    ("kss", {"level": 9}, "kss", 9), ("tlx", {"scores": {"mental": 100, "physical": 100}}, "tlx", 100)])
def test_cognitive_and_self_report_tests_feed_their_indicator(kind, payload, ind, value):
    _day(100)
    before = client.get("/api/crew/a", headers=as_("a")).json()["indicators"][ind]
    assert before["origin"] == "simulated" and before["last_measured_day"] <= 100
    r = _checkin("a", kind, payload).json()["snapshot"]["indicators"][ind]
    assert r["origin"] == "user" and r["age_days"] == 0 and r["last_measured_day"] == 100
    assert r["value"] != before["value"] and r["bad"] > before["bad"]
    assert dict(client.get("/api/crew/a", headers=as_("a")).json()["trends"][ind])[100] == value
    _day(103)
    later = client.get("/api/crew/a", headers=as_("a")).json()["indicators"][ind]
    assert later["origin"] != "user" and later["last_measured_day"] <= 103


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
    assert all([a for a in health.snapshot(c["id"], ms)["alerts"] if not a.get("data")] == [] for c in catalog.CREW)
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
    assert [a for a in health.snapshot("a", ms)["alerts"] if not a.get("data")] == []


def test_vitals_outside_what_can_be_typed_are_refused():
    _day(100)
    for bad in ({"hr": 900}, {"hr": 5}, {"temp": 80}, {"spo2": 120}, {"sbp": 0}, {"hr": "fast"}):
        r = _checkin("a", "vitals", bad)
        assert r.status_code == 422, bad  # was 400 before every bad input answered with the same {field, message} shape
        assert r.json()["detail"][0]["field"] in ("hr", "sbp", "temp", "spo2")
    assert _checkin("a", "vitals", {"hr": 62, "sbp": 118, "temp": 36.6, "spo2": 98}).status_code == 200
    latest = {t["id"]: t["latest"] for t in client.get("/api/checkins/a", headers=as_("a")).json()["tests"]}
    assert latest["vitals"]["payload"]["hr"] == 62
    assert selftests_limits_are_not_clinical()


def selftests_limits_are_not_clinical():
    from canary.domain import selftests
    return selftests.VITALS_LIMITS_SOURCE["verified"] is False and "not clinical" in selftests.VITALS_LIMITS_SOURCE["source"]


# ---------------------------------------------------------------- Prompt 2: two references (population safety limit + personal baseline)
STORY_ALERTS = {  # scene step -> crew -> (alert id, level). Bone density is no longer measured on board (no ind_bone alert), levels
    # need two readings in a row, and a pulse or pressure is read against the in-flight re-baseline from flight day 15.
    1: {"t": [("sickness", 1)]},
    2: {"h": [("behaviour", 2), ("missing_mood", 1)]},
    3: {"h": [("storm", 2), ("behaviour", 2), ("missing_mood", 1)], "k": [("storm", 2)], "a": [("storm", 2)], "t": [("storm", 2)]},
    4: {"h": [("behaviour", 2), ("missing_mood", 1)]},
    5: {"h": [("storm", 2), ("regravity", 1)], "k": [("storm", 2), ("regravity", 1), ("ind_grip", 1)],
        "a": [("storm", 2), ("regravity", 1), ("ind_grip", 1)], "t": [("storm", 2), ("regravity", 1)]},
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
    _no_device("a", "spo2", (-30, -30))
    assert _checkin("a", "vitals", {"spo2": 85}).status_code == 200
    s = health.snapshot("a", ms)
    i = s["indicators"]["spo2"]
    assert i["level"] == 2 and i["population"]["status"] == "critical" and i["population"]["verified"] is True
    assert [(a["id"], a["level"]) for a in s["alerts"]] == [("ind_spo2", 2)]
    assert s["systems"]["lungs"]["level"] == 2
    assert health.snapshot("k", ms)["alerts"] == []  # nobody else is affected


def test_outside_the_normal_range_is_at_least_level_one_after_launch():
    _no_device("a", "temp")
    _day(99)
    assert _checkin("a", "vitals", {"temp": 37.9}).status_code == 200  # fever range, not critical
    ms = _day(100)
    assert health.snapshot("a", ms)["indicators"]["temp"]["level"] == 0  # one reading is not yet a finding (persistence)
    assert _checkin("a", "vitals", {"temp": 37.9}).status_code == 200
    i = health.snapshot("a", ms)["indicators"]["temp"]
    assert i["population"]["status"] == "out" and i["level"] >= 1  # two in a row
    assert _checkin("a", "vitals", {"temp": 41}).status_code == 200  # critical: at once
    assert health.snapshot("a", ms)["indicators"]["temp"]["level"] == 2


def test_inside_the_population_range_the_personal_baseline_still_raises_level_two():
    _day(99)
    assert _checkin("a", "pvt", {"ms": 450}).status_code == 200  # inside 150 to 500 ms, far from her own 250
    ms = _day(100)
    assert _checkin("a", "pvt", {"ms": 450}).status_code == 200  # two days in a row
    i = health.snapshot("a", ms)["indicators"]["react"]
    assert i["population"]["status"] == "in" and i["z"] >= 2.5 and i["level"] == 2


def test_the_baseline_is_computed_from_the_preflight_days_and_stays_close_to_the_seed():
    from canary.domain import simdata
    seeds = {c["id"]: c for c in simdata.load_demo_crew()["crew"]}  # the generator's seeds: the engine has none
    for c in catalog.CREW:
        assert "base" not in c
        for ind, B in health.baselines(c["id"]).items():
            sd = catalog.INDICATORS[ind]["sd"]
            need = catalog.INDICATORS[ind].get("min_baseline", health.MIN_PREFLIGHT)
            assert B["from"] == "preflight" and B["n"] >= need and B["confidence"] in ("low", "moderate", "high"), (c["id"], ind)
            if ind == "bone":  # a DXA scan: two before launch, no seed to compare with
                continue
            assert abs(B["mean"] - seeds[c["id"]]["base"][ind]) <= 0.35 * sd + 0.5 * 10 ** -catalog.INDICATORS[ind]["dp"], (c["id"], ind)
            assert B["sd"] >= sd  # the floor
    _day(100)
    d = client.get("/api/crew/h", headers=as_("h")).json()["indicators"]["sleep"]
    assert d["baseline_from"] == "preflight" and d["baseline"] == health.baselines("h")["sleep"]["mean"] and d["spread"] >= 0.5


def test_a_plan_without_preflight_learns_from_the_first_flight_days_never_from_the_catalog_seed():
    plan_no_pre = {"name": "No pre-flight", "legs": [{"location": "rocket", "start": 0, "end": 3}, {"location": "transit", "start": 4, "end": 100}]}
    assert plan_put(plan_no_pre).status_code == 200
    b = health.baselines("h")
    assert not any(x["from"] == "catalog" for x in b.values())
    assert b["sleep"]["from"] == "early_flight" and b["sleep"]["n"] >= health.MIN_PREFLIGHT  # daily readings: five in the first days
    for x in b.values():  # a baseline either has a number from the person's own data or is still learning
        assert (x["mean"] is None) == (x["from"] == "learning")


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
    for kind, payload in (("dsst", {"correct": 50}), ("span", {"span": 6}), ("kss", {"level": 4}), ("tlx", {"scores": {"mental": 50}}),
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
        assert all("https://" in c for c in P["checked"]), ind  # each checked number names the page it was read on
        assert P["verified"] is False or P["checked"], ind  # verified only when its numbers were read on the guideline
    assert all(reference.POPULATION[i]["source"].find("assumption") >= 0 for i in ("react", "dsst", "span"))
    doc = (pathlib.Path(__file__).resolve().parents[2] / "docs" / "health-model.md").read_text(encoding="utf-8")
    assert reference.table_md() in doc  # the generated table lives in docs/health-model.md
    assert reference.check("grip", "F", 15)["status"] == "out" and reference.check("grip", "M", 30)["status"] == "in"
    assert reference.check("mood", "F", 1)["status"] == "in"


def test_the_blood_count_returns_every_analyte_with_range_and_status_and_raises_no_alert():
    from canary.domain import nasa
    b = nasa.blood("k", "M")  # k's own blood observations in the demo package (simulated on the Inspiration4 pattern)
    assert b["origin"] == "simulated" and set(b["analytes"]) == {"wbc", "lym", "neu", "hgb", "hct", "plt", "rbc",
                                                            "creatinine", "potassium", "calcium", "crp"}
    for k, a in b["analytes"].items():
        assert len(a["status"]) == len(b["timepoints"]) == len(a["values"]) and set(a["status"]) <= {"in", "out", None}
        if k == "crp":  # no range in its panel
            assert a["range"] is None and set(a["status"]) == {None}
        else:
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
    assert [x["id"] for x in health.snapshot("h", ms)["risks"]] == ["fatigue", "radiation", "sans", "nutrition", "renal", "immune", "cardio", "bone_muscle"]
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
    _day(99)
    assert _checkin("a", "kss", {"level": 8}).status_code == 200
    assert _checkin("a", "tlx", {"raw": 92}).status_code == 200
    _day(100)
    assert _fatigue("a")["level"] == 0  # one day of readings is not yet a finding
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
    _no_device("a", "hr")
    _day(99)
    assert _checkin("a", "vitals", {"hr": 100}).status_code == 200
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
    r = tools.run_tool(tools._bind("h"), "get_risks", {})  # strict tool: crew_id comes from the ToolContext
    assert r.ok and r.data[0]["level"] == 2 and r.sources and "get_risks" in tools.TOOLS
    assert tools.run_tool(tools._bind("h"), "get_risks", {"crew_id": "k"}).error  # never a model argument
    a = client.post("/api/assistant/ask", json={"crew_id": "h", "question": "Am I at risk of fatigue?"}, headers=as_("h")).json()
    assert a["mode"] == "grounded" and any(t["tool"] == "get_risks" for t in a["tools_used"])
    assert any("since day" in c["text"] for c in a["claims"]) and all(c["source_ids"] for c in a["claims"])
    assert "risks" in client.get("/api/crew/h", headers=as_("h")).json()


# ---------------------------------------------------------------- Prompt 4: the advice loop, alerts that last, lighter training under fatigue
def _med():
    tok = medical_headers(client)["Authorization"][7:]
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
    assert first[155][0] in ("improved", "same", "worse", "no_adherence")
    assert result(155) == first[155]  # any order, any number of times
    assert first[155][0] == "no_adherence"  # the sleep goal was ticked on 2 of the 7 days: under the 70% gate, no result is claimed


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
    assert not any(m["kind"] == "advice" for m in client.get("/api/messages", headers=crew_headers(client, "h")).json())
    assert not any(m["kind"] == "advice" for m in client.get("/api/messages", headers=as_("t")).json())
    assert any(m["kind"] == "advice" for m in client.get("/api/messages", headers=_med()).json())
    assert any(m["kind"] == "advice" for m in client.get("/api/messages", headers=as_("k")).json())


def test_reading_never_writes():
    at(2)
    h = as_("h")
    client.post("/api/suggestions/h/sleep/accept", headers=h)
    _day(160)  # the day sync may write (an environment alert now reaches the officer and Earth); reading never does
    before = _counts()
    for url in ("/api/advice/h", "/api/goals/h", "/api/suggestions/h", "/api/crew/h", "/api/leaderboard", "/api/crew/overview"):
        assert client.get(url, headers=h).status_code == 200
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
    base_board = client.get("/api/leaderboard", headers=as_("h")).json()
    g = next(x for x in client.get("/api/goals/h", headers=as_("h")).json()["personal"] if x["id"] == "exercise")
    assert g["adjusted"] == {"pct": 30, "minutes": 84, "target": 120, "reason": "fatigue", "max_pct": 30}
    assert "lighter today" in g["title"] and "30%" in g["why"] and "medical team" in g["why"]
    r = client.put("/api/medical/exercise-adjust", json={"max_pct": 10, "level1": 15, "level2": 30}, headers=_med())
    assert r.status_code == 200
    g = next(x for x in client.get("/api/goals/h", headers=as_("h")).json()["personal"] if x["id"] == "exercise")
    assert g["adjusted"]["pct"] == 10 and g["adjusted"]["minutes"] == 108  # never above the limit the doctors set
    assert client.put("/api/medical/exercise-adjust", json={"max_pct": 10, "level1": 15, "level2": 30}).status_code == 401
    assert client.get("/api/leaderboard", headers=as_("h")).json() == base_board  # lighter training does not touch the ranking
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


# ---------------------------------------------------------------- Prompt 5: critical alerts reach the medical officer, emergencies leave a care window
def _close(protocol, patient, outcome="stable"):
    e = client.post("/api/emergencies", json={"responder": "k"}, headers=crew_headers(client, "h")).json()
    client.post(f"/api/emergencies/{e['id']}", json={"protocol": protocol, "patient": patient}, headers=crew_headers(client, "h"))
    return client.post(f"/api/emergencies/{e['id']}", json={"close": True, "outcome": outcome}, headers=crew_headers(client, "h")).json()


def _med_goals(who):
    return {g["title"]: g["to_day"] - g["from_day"] for g in db.q("SELECT * FROM medical_goals WHERE who=?", (who,))}


def test_every_protocol_with_a_window_has_days_ops_and_an_illustrative_note():
    from canary.domain import protocols
    bank = client.get("/api/protocols").json()
    assert bank["care_note"]["verified"] is False and bank["care_note"]["source"] == "prototype assumption"
    for pid, p in bank["protocols"].items():
        assert p["source"] == f"protocol:{pid}"  # the care fields must not replace the protocol's own source
        assert p["ops"] in ("full", "limited", "rest") and p["window_days"] >= 0
        assert [i["title"] for i in p["after_items"]] == p["after"] and all(i["days"] >= 0 for i in p["after_items"])
        assert all(i["days"] <= max(p["window_days"], 7) for i in p["after_items"])
    sz = protocols.care("seizure")
    assert sz["window_days"] == 3 and sz["ops"] == "rest"
    assert {i["title"]: i["days"] for i in sz["after_items"]}["No critical task or spacewalk for 72 h"] == 3
    assert next(i["days"] for i in protocols.care("rad")["after_items"] if i["title"].startswith("Blood count")) == 7
    assert protocols.care("triage")["window_days"] == 0


def test_closing_a_seizure_gives_follow_ups_their_own_days_and_a_restricted_window():
    _day(153)
    assert client.get("/api/crew/t", headers=as_("t")).json()["ops"]["key"] != "rest"
    e = _close("seizure", "t")
    days = _med_goals("t")
    assert days["Glucose and vital signs every 30 min for 2 h"] == 1 and days["No critical task or spacewalk for 72 h"] == 3
    assert days["Blood count and a review of current medication"] == 3
    d = client.get("/api/crew/t", headers=as_("t")).json()
    assert d["ops"]["key"] == "rest" and d["ops"]["until_day"] == 156 and "Seizure" in d["ops"]["reason"] and "156" in d["ops"]["reason"]
    ev = d["care_events"][0]
    assert (ev["protocol"], ev["day"], ev["outcome"], ev["origin"], ev["until_day"]) == ("seizure", 153, "stable", "user", 156)
    for day in (154, 156):
        _day(day)
        got = client.get("/api/crew/t", headers=as_("t")).json()["ops"]
        assert got["key"] == "rest" and got["until_day"] == 156
    # EMG-04: after its last day the window is "awaiting review" and keeps its restriction until medical records a review
    _day(157)
    assert client.get("/api/crew/t", headers=as_("t")).json()["ops"]["key"] == "rest"
    assert client.get("/api/crew/t", headers=as_("t")).json()["care_events"][0]["status"] == "awaiting review"
    assert client.post(f"/api/medical/care-windows/{e['id']}/review", json={"resolution": "Cleared to resume"}, headers=_med()).status_code == 200
    assert client.get("/api/crew/t", headers=as_("t")).json()["ops"]["key"] != "rest"  # the review ends it on the day it is recorded
    _day(150)  # the clock can go back: the event is not on record yet
    assert client.get("/api/crew/t", headers=as_("t")).json()["care_events"] == []


def test_closing_twice_does_not_repeat_goals_or_the_window():
    _day(153)
    e = _close("seizure", "t")
    n = (len(db.q("SELECT 1 FROM medical_goals")), len(db.q("SELECT 1 FROM messages WHERE kind='report'")))
    client.post(f"/api/emergencies/{e['id']}", json={"close": True, "outcome": "stable"}, headers=crew_headers(client, "h"))
    assert (len(db.q("SELECT 1 FROM medical_goals")), len(db.q("SELECT 1 FROM messages WHERE kind='report'"))) == n
    assert len(db.q("SELECT 1 FROM care_events")) == 1


def test_the_report_to_earth_keeps_the_delay_of_the_place():
    _day(153)
    _close("seizure", "t")
    r = next(m for m in db.q("SELECT * FROM messages WHERE kind='report'"))
    assert r["recipient"] == "earth" and r["deliver_at"] - r["sent_at"] > 5


def test_inside_the_window_thresholds_tighten_for_the_patient_only():
    _day(153)
    ms = mission.state()
    prev = {**ms, "day": 152, "location": plan_mod.location_at(152)}
    # the indicator Tomás is furthest from his normal on both of the last two days (a level needs two readings in a row)
    score = {}
    for i in catalog.INDICATORS:
        x, y = health.indicator("t", i, ms), health.indicator("t", i, prev)
        if x["bad"] is not None and y["bad"] is not None and x["measured_today"] and y["measured_today"]:
            score[i] = min(x["bad"], y["bad"])
    ind = max(score, key=score.get)
    watch = round(score[ind] * 1.1, 2)  # just above what he has today: level 0 by the normal rule
    client.put("/api/medical/thresholds", json={"watch": watch, "act": 5}, headers=_med())
    before = {c: health.indicator(c, ind, ms) for c in "hkat"}
    assert before["t"]["level"] == 0 and all("sensitive_until" not in i for i in before.values())
    e = _close("seizure", "t")
    after = {c: health.indicator(c, ind, ms) for c in "hkat"}
    assert after["t"]["level"] == 1 and after["t"]["sensitive_until"] == 156
    assert all(after[c]["level"] == before[c]["level"] and "sensitive_until" not in after[c] for c in "hka")
    _day(157)  # after its last day it awaits review (EMG-04): still tighter until medical reviews it
    assert "sensitive_until" in health.indicator("t", ind, mission.state())
    assert client.post(f"/api/medical/care-windows/{e['id']}/review", json={"resolution": "Back to normal"}, headers=_med()).status_code == 200
    t = health.indicator("t", ind, mission.state())
    assert "sensitive_until" not in t
    assert client.put("/api/medical/care-sensitivity", json={"factor": 1.0}, headers=_med()).json()["factor"] == 1.0
    assert client.put("/api/medical/care-sensitivity", json={"factor": 0.2}, headers=_med()).status_code == 422
    assert client.get("/api/medical/care-sensitivity").status_code == 401
    assert client.get("/api/medical/care-sensitivity", headers=_med()).json()["verified"] is False


def _alert_msgs(kind="alert"):
    return db.q("SELECT * FROM messages WHERE kind=? ORDER BY id", (kind,))


def test_a_critical_alert_reaches_the_medical_officer_once_per_episode():
    from canary.domain import notify
    _day(147)
    to_k = [m for m in _alert_msgs() if m["recipient"] == "k"]
    assert len(to_k) == 1 and "Helena" in to_k[0]["text"] and "Sleep, mood and focus" in to_k[0]["text"]
    for _ in range(3):
        assert notify.sync(mission.state()) == 0
    _day(148), _day(147), _day(146)
    client.post("/api/checkins", json={"crew_id": "h", "kind": "mood", "payload": {"mood": 3, "stress": 3}}, headers=as_("h"))
    assert len([m for m in _alert_msgs() if m["recipient"] == "k"]) == 1 and len(db.q("SELECT 1 FROM alert_events WHERE recipients LIKE '%level2%'")) == 1
    earth = _alert_msgs("alert_earth")
    assert len(earth) == 1 and earth[0]["recipient"] == "earth" and earth[0]["deliver_at"] - earth[0]["sent_at"] > 5


def test_a_critical_alert_of_the_medical_officer_goes_to_the_substitute():
    _day(100)
    assert _alert_msgs() == []
    _no_device("k", "spo2", (100, 100))
    assert _checkin("k", "vitals", {"spo2": 85}).status_code == 200
    msgs = _alert_msgs()
    assert [m["recipient"] for m in msgs] == ["h"] and "Kenji" in msgs[0]["text"]
    assert _checkin("k", "vitals", {"spo2": 84}).status_code == 200  # same episode: no second message
    assert len(_alert_msgs()) == 1
    ev = client.get("/api/alerts/events", headers=_med()).json()["events"]
    assert [r["id"] for e in ev if e["crew_id"] == "k" for r in e["recipients"] if r["reason"] == "level2" and r["role"] == "cmo"] == ["h"]


def test_alerts_and_windows_are_private_to_the_medical_team():
    _day(147)
    _close("seizure", "t")
    _no_device("k", "spo2", (147, 147))
    _checkin("k", "vitals", {"spo2": 85})
    assert client.get("/api/medical/overview").status_code == 401
    ov = client.get("/api/medical/overview", headers=_med()).json()
    told = [e for e in client.get("/api/alerts/events", headers=_med()).json()["events"] if any(r["reason"] == "level2" for r in e["recipients"])]
    assert {e["crew_id"] for e in told} >= {"h", "k"} and all(e["title"] and e["opened_day"] <= 147 for e in told) and "notices" not in ov
    assert any(c["id"] == "t" and c["care_events"] and c["ops"]["key"] == "rest" for c in ov["crew"])
    kinds = lambda hdr: {m["kind"] for m in client.get("/api/messages", headers=hdr).json()}  # noqa: E731
    assert client.get("/api/messages").status_code == 401
    assert not kinds(control_headers(client)) & {"alert", "alert_earth", "advice"}
    assert not kinds(as_("a")) & {"alert", "alert_earth"} and not kinds(as_("t")) & {"alert", "alert_earth"}
    assert "alert" in kinds(as_("k")) and "alert" in kinds(as_("h"))  # each sees only what is addressed to them
    assert not any(m["kind"] == "alert" and m["recipient"] != "k" for m in client.get("/api/messages", headers=as_("k")).json())
    assert "alert_earth" in kinds(_med())
    o = str(client.get("/api/crew/overview", headers=as_("h")).json())
    for leak in ("care_events", "until_day", "alert_events", "Critical alert for", "Guided Response ("):
        assert leak not in o
    assert client.get("/api/crew/t", headers=as_("a")).status_code == 403


def test_reading_never_writes_the_notice_tables():
    _day(147)
    _close("seizure", "t")
    n = _counts() | {t: db.q(f"SELECT COUNT(*) n FROM {t}")[0]["n"] for t in ("alert_events", "care_events", "medical_goals")}
    for path in ("/api/mission", "/api/crew", "/api/crew/overview", "/api/protocols", "/api/emergencies"):
        client.get(path, headers=_med())
    for cid in "hkat":
        client.get(f"/api/crew/{cid}", headers=as_(cid))
    client.get("/api/medical/overview", headers=_med())
    assert n == _counts() | {t: db.q(f"SELECT COUNT(*) n FROM {t}")[0]["n"] for t in ("alert_events", "care_events", "medical_goals")}


# ---------------------------------------------------------------- Prompt 6: the other risks, RIDGE from the plan, hazard labels
RISK_IDS = ["fatigue", "radiation", "sans", "nutrition", "renal", "immune", "cardio", "bone_muscle"]


def _risk(cid, rid, day=None, ms=None):
    from canary.domain import risk
    ms = ms or (mission.state() if day is None else {"day": day})
    return next(r for r in risk.evaluate(cid, ms) if r["id"] == rid)


@pytest.fixture
def shift(monkeypatch):
    """Move indicators away from a person's normal by some personal spreads on every flight day, to build a level on purpose
    (the baseline, read from the pre-flight days, stays where it was)."""
    from canary.domain import risk, telemetry
    shifts = {}
    orig_obs, orig_dr = telemetry.observation, telemetry.day_readings

    def delta(crew, ind):
        I = catalog.INDICATORS[ind]
        return (-1 if I["dir"] == "low" else 1) * shifts[(crew, ind)] * max(I["sd"], health.baselines(crew)[ind]["sd"])

    def obs(crew, ind, day, uv=None):
        o = orig_obs(crew, ind, day, uv)
        if (crew, ind) in shifts and o["value"] is not None and (o["day"] or 0) >= 0:
            o = {**o, "value": o["value"] + delta(crew, ind)}
        return o

    def dr(crew, ind, d0, d1):
        out = orig_dr(crew, ind, d0, d1)
        if (crew, ind) in shifts:
            out = {d: ({**r, "value": r["value"] + delta(crew, ind)} if d >= 0 else r) for d, r in out.items()}
        return out

    monkeypatch.setattr(telemetry, "observation", obs)
    monkeypatch.setattr(telemetry, "day_readings", dr)

    def go(crew, ind, spreads):
        shifts[(crew, ind)] = spreads
        risk.clear_cache()
        health._alert_cache.clear()
        health._scache.clear()
    yield go
    risk.clear_cache()
    health._alert_cache.clear()
    health._scache.clear()


@pytest.fixture
def exam(monkeypatch):
    """Make the latest row of an exam be this value, this old, from this origin (an exam the file has no row for that day)."""
    from canary.domain import risk, telemetry
    rows = {}
    orig = telemetry.last_observation

    def last(crew, ind, day):
        if (crew, ind) in rows:
            v, age, origin = rows[(crew, ind)]
            return {"day": day - age, "value": v, "age": age, "origin": origin, "method": "blood", "source": f"test:{ind}", "note": ""}
        return orig(crew, ind, day)

    monkeypatch.setattr(telemetry, "last_observation", last)

    def go(crew, ind, value, age=0, origin="real"):
        rows[(crew, ind)] = (value, age, origin)
        risk.clear_cache()
    yield go
    risk.clear_cache()


def test_there_are_eight_risks_and_four_are_nasas_red_ones():
    at(2)
    r = client.get("/api/crew/h", headers=as_("h")).json()["risks"]
    assert [x["id"] for x in r] == RISK_IDS
    assert {x["id"] for x in r if x["nasa_red"]} == {"fatigue", "radiation", "sans", "nutrition"}
    for x in r:
        assert x["data"] in ("real", "partial", "simulated") and isinstance(x["hazards"], list) and x["clock_days"] > 0
        assert x["source"] and x["verified"] is False


def test_radiation_is_level_one_from_half_the_limit_and_names_the_day_the_plan_passes_it():
    from canary.domain import dose, risk
    curve = dose.curve(None, -1)  # the projection: the plan's rates and the storm events
    assert all(abs(curve[d] - dose.mission(None, d)["msv"]) < 0.11 for d in (0, 5, 100, 152, 153, 300, 513))  # the cabin dosimeter says the same
    assert next(d for d, v in enumerate(curve) if v > catalog.CAREER_LIMIT_MSV) == 513
    _day(100)
    assert _risk("a", "radiation")["level"] == 0
    _day(156)
    assert _risk("a", "radiation")["level"] == 0
    _day(157)
    r = _risk("a", "radiation")
    assert r["level"] == 1 and any("projected to pass it on day 513" in e["text"] for e in r["evidence"])
    assert r["dose"]["same_for_everyone"] and r["dose"]["cross_day"] == 513 and r["data"] == "simulated"
    assert r["dose"]["prior_msv"] == 0 and r["dose"]["now_msv"] == r["dose"]["mission_msv"]
    assert {_risk(c, "radiation")["dose"]["mission_msv"] for c in "hkat"} == {r["dose"]["mission_msv"]}  # one mission dose for the crew
    _day(513)
    assert _risk("a", "radiation")["level"] == 2 and "past NASA's 600 mSv limit" in _risk("a", "radiation")["evidence"][0]["text"]


def test_radiation_is_level_two_in_both_storm_scenes_and_the_storm_alert_carries_it():
    from canary.domain import standards
    for step in (3, 5):
        ms = at(step)
        assert ms["storm"]
        for c in "hkat":
            r = _risk(c, "radiation", ms=ms)
            assert r["level"] == 2 and r["nasa_red"] and r["hazards"] == ["R"]
            # the demo storms are simulated replays and the cabin dosimeter is simulated: the data is labelled simulated
            assert r["data"] == "simulated", (step, c, r["data"])
            assert r["dose"]["prior_msv"] == standards.prior_dose(c)["msv"]
        storm = next(a for a in health.snapshot("h", ms)["alerts"] if a["id"] == "storm")
        assert storm["risk"] == "radiation" and storm["hazards"] == ["R"]


def test_radiation_reads_a_low_lymphocyte_count_but_not_a_high_one(exam):
    _day(100)
    exam("a", "lym", 5000)  # above the range: not radiation's sign
    assert _risk("a", "radiation")["level"] == 0
    exam("a", "lym", 600)
    r = _risk("a", "radiation")
    assert r["level"] == 1 and r["evidence"][0]["indicator"] == "lym" and r["evidence"][0]["origin"] == "real"


def test_sans_reads_the_amsler_grid_and_vision_symptoms_and_says_the_grid_is_weak():
    _day(100)
    r = _risk("h", "sans")
    assert r["level"] == 0 and "weak indicator" in r["note"] and r["nasa_red"]
    assert _checkin("h", "symptoms", {"items": ["Headache"], "severity": 2}).status_code == 200
    assert _risk("h", "sans")["level"] == 0  # not a vision symptom
    assert _checkin("h", "symptoms", {"items": ["Blurred vision"], "severity": 2}).status_code == 200
    assert _risk("h", "sans")["level"] == 1
    assert _checkin("h", "amsler", {"distortion": True}).status_code == 200
    r = _risk("h", "sans")
    assert r["level"] == 2 and r["data"] == "real" and {e["key"] for e in r["evidence"]} == {"amsler", "symptoms"}
    assert health.snapshot("h", mission.state())["systems"]["eyes"]["level"] == 2


def test_nutrition_reads_glucose_and_weight_against_the_persons_own_normal(shift, exam):
    _day(100)
    assert _risk("a", "nutrition")["level"] == 0
    shift("a", "gluc", 2.0)
    r = _risk("a", "nutrition")
    assert r["level"] == 1 and r["evidence"][0]["indicator"] == "gluc" and r["nasa_red"]
    assert health.snapshot("a", mission.state())["systems"]["gut"]["level"] == 1
    shift("a", "gluc", 0.0)
    assert _risk("a", "nutrition")["level"] == 0
    exam("a", "weight", 60.0, origin="user")  # about 9% under a pre-flight near 66 kg
    r = _risk("a", "nutrition")
    assert r["level"] == 1 and "below your pre-flight" in r["evidence"][0]["text"] and r["evidence"][0]["origin"] == "user" and r["data"] == "real"


def test_renal_reads_water_bone_loss_and_the_exams_and_a_stale_exam_is_not_a_risk(shift, exam):
    _day(100)
    assert _risk("a", "renal")["level"] == 0
    shift("a", "water", 2.0)
    assert _risk("a", "renal")["level"] == 1
    shift("a", "water", 0.0)
    exam("a", "creatinine", 2.5, origin="real")
    r = _risk("a", "renal")
    assert r["level"] == 1 and r["evidence"][0]["indicator"] == "creatinine" and not r["panel_due"]
    exam("a", "creatinine", 2.5, age=40)  # an old exam: say it is due, do not count it
    r = _risk("a", "renal")
    assert r["level"] == 0 and r["panel_due"] and r["evidence"][0]["stale"] and r["evidence"][0]["due_every_days"] == 30
    exam("a", "creatinine", 0.9, age=0)
    exam("a", "urine_volume", 900, age=3)
    r = _risk("a", "renal")
    assert r["level"] == 1 and r["evidence"][0]["indicator"] == "urine_volume"


def test_immune_reads_the_blood_count_temperature_and_the_days_after_the_storm(shift, exam):
    _day(100)
    assert _risk("a", "immune")["level"] == 0
    shift("a", "temp", 3.0)
    assert _risk("a", "immune")["level"] == 1
    shift("a", "temp", 0.0)
    exam("a", "hgb", 9.0)
    exam("a", "hct", 28.0)
    r = _risk("a", "immune")
    assert r["level"] == 1 and {e["indicator"] for e in r["evidence"]} == {"hgb", "hct"} and r["data"] == "real"
    exam("a", "hgb", 9.0, age=45)
    exam("a", "hct", 28.0, age=45)
    r = _risk("a", "immune")
    assert r["level"] == 0 and r["panel_due"]
    _day(160)
    assert any(e["text"] == "Blood count due after the radiation storm" for e in _risk("h", "immune")["evidence"])


def test_a_blood_value_that_was_already_outside_the_range_before_launch_is_not_a_new_signal(exam):
    from canary.domain import telemetry
    _day(100)
    pre = telemetry.preflight_values("a", "lym")
    assert pre  # Amara's pre-flight lymphocytes are in the file
    exam("a", "wbc", 2000.0)  # far below the range of 4 to 11 thousand
    assert _risk("a", "immune")["level"] in (0, 1)  # the pre-flight wbc of this file sits inside the range, so this one counts
    ev = [e for e in _risk("a", "immune")["evidence"] if e["indicator"] == "wbc"]
    assert ev and ev[0]["points"] == 0.5


def test_cardio_absorbs_regravity_and_stays_level_zero_when_all_is_normal(shift):
    _day(100)
    assert _risk("a", "cardio")["level"] == 0
    shift("a", "hr", 2.0)
    r = _risk("a", "cardio")
    assert r["level"] == 1 and r["evidence"][0]["indicator"] == "hr"
    ms = at(5)  # Mars, partial gravity: pressure and pulse away from normal is the re-adaptation pattern
    assert _risk("h", "cardio", ms=ms)["systems"] == ["heart", "lungs"]
    regr = next(a for a in health.snapshot("h", ms)["alerts"] if a["id"] == "regravity")
    assert regr["risk"] == "cardio"
    assert any(e["key"] == "regravity" for e in _risk("h", "cardio", ms=ms)["evidence"])


def test_bone_muscle_reads_bone_grip_and_exercise_and_colours_only_the_system_it_is_about(shift):
    _day(100)
    assert _risk("a", "bone_muscle")["level"] == 0
    shift("a", "grip", 2.0)
    r = _risk("a", "bone_muscle")
    assert r["level"] == 1 and r["evidence"][0]["indicator"] == "grip"
    s = health.snapshot("a", mission.state())["systems"]
    assert s["muscles"]["level"] == 1 and s["skeleton"]["level"] == 0  # grip is about the muscles, not the bones


def test_every_risk_says_where_its_data_comes_from():
    from canary.domain import risk
    assert risk.data_origin({"real"}) == "real" and risk.data_origin({"user", "real"}) == "real"
    assert risk.data_origin({"real", "simulated"}) == "partial" and risk.data_origin({"user", "simulated"}) == "partial"
    assert risk.data_origin({"simulated"}) == "simulated" and risk.data_origin(set()) == "simulated"
    ms = at(2)
    assert _risk("h", "fatigue", ms=ms)["data"] == "simulated" and _risk("h", "radiation", ms=ms)["data"] == "simulated"


def test_ridge_on_day_147_in_transit_is_what_it_was_and_the_levels_follow_the_plan():
    from canary.domain import privacy
    lv = lambda loc, day, storm=None: {h["id"]: h["level"] for h in privacy.ridge(loc, storm, day)}  # noqa: E731
    assert lv("transit", 147) == {"R": 2, "I": 2, "D": 2, "G": 2, "E": 1}
    assert lv("earth", -30) == {"R": 0, "I": 0, "D": 0, "G": 0, "E": 0}
    assert lv("rocket", 2)["I"] == 1 and lv("transit", 147)["I"] == 2  # isolation grows with the days since launch
    assert lv("mars", 215)["G"] == 2 and lv("mars", 300)["G"] == 1    # re-adaptation for 30 days after the change of gravity
    assert lv("transit", 150, "sep")["R"] == 2 and lv("mars", 300)["R"] == 1
    assert lv("iss", 10)["D"] == 0 and lv("moon", 10)["D"] == 1
    h = privacy.ridge("transit", None, 147)
    assert all(x["basis"] for x in h) and [x["assumption"] for x in h] == [False, False, False, False, True]
    assert h[0]["here"] and h[0]["label"] == "High" and privacy.RIDGE_CUTS["verified"] is False


def test_the_ridge_in_the_overview_uses_the_mission_day():
    at(2)
    o = client.get("/api/crew/overview", headers=as_("h")).json()
    assert {h["id"]: h["level"] for h in o["ridge"]} == {"R": 2, "I": 2, "D": 2, "G": 2, "E": 1}
    assert all("basis" in h for h in o["ridge"])


def test_helenas_fatigue_risk_on_day_147_lists_isolation_as_a_possible_factor():
    ms = at(2)
    r = _risk("h", "fatigue", ms=ms)
    assert "I" in r["hazards"] and r["hazard_note"].startswith("Possible factors here:") and "Isolation" in r["hazard_note"]
    assert all(l["source"] and l["why"] and (l["verified"] is False or l["checked"]) for l in r["hazard_links"])
    assert "caused" not in r["hazard_note"].lower()
    b = next(a for a in health.snapshot("h", ms)["alerts"] if a["id"] == "behaviour")
    assert b["risk"] == "fatigue" and "I" in b["hazards"] and b["hazard_note"] == r["hazard_note"]
    assert _risk("k", "fatigue", ms=ms)["hazards"] == []  # no hazard label without a risk


def test_every_alert_keeps_its_id_and_gains_a_risk_and_hazards():
    seen = set()
    for step in range(6):
        ms = at(step)
        for c in "hkat":
            for a in health.snapshot(c, ms)["alerts"]:
                assert "risk" in a and isinstance(a["hazards"], list)
                seen.add(a["id"])
                if a["id"].startswith("ind_"):
                    assert a["risk"] in ("fatigue", "cardio", "bone_muscle", "nutrition", "renal", "immune")
    assert {"storm", "behaviour", "missing_mood", "regravity", "sickness"} <= seen


def test_the_hazard_matrix_is_the_teams_with_a_source_on_every_link():
    from canary.domain.catalog import HAZARDS_BY_INDICATOR as M
    assert {l["hazard"] for l in M["sleep"]} == {"I", "E"} and {l["hazard"] for l in M["dose"]} == {"R"}
    assert {l["hazard"] for l in M["mood"]} == {"I", "D", "E"} and {l["hazard"] for l in M["bone"]} == {"D", "G"}
    links = [l for ls in M.values() for l in ls]
    assert all(l["source"] and l["why"] for l in links)
    # a link is verified only with the finding it was checked against; HRP-only links stay unverified until read
    assert all(l["checked"].startswith("Patel 2020 (") for l in links if l["verified"])
    assert not any(l["verified"] for l in links if "Patel" not in l["source"] and l["source"] != "real data RadLab, DONKI")
    assert {l["verified"] for l in M["amsler"]} == {True} and {l["verified"] for l in M["cortisol"]} == {False}
    assert all(l["source"].startswith("prototype assumption") for k in ("dsst", "span", "kss", "tlx", "urine_volume") for l in M[k])


def test_the_assistant_exposes_the_risks_with_hazards_and_cards():
    from canary.assistant import knowledge, tools
    ms = at(2)
    res = tools.run_tool(tools._bind("h"), "get_risks", {})
    assert [r["id"] for r in res.data] == RISK_IDS and "card:risk:fatigue" in res.sources and "card:hazard:I" in res.sources
    cards = knowledge.by_id(ms["location"])
    assert "card:risk:radiation" in cards and "card:hazard:G" in cards and "never a proven cause" in cards["card:hazard:I"]["text"]
    a = client.post("/api/assistant/ask", json={"crew_id": "h", "question": "What is my fatigue risk and why?"}, headers=as_("h")).json()
    assert any("Possible factors here" in c["text"] for c in a["claims"])


# ---------------------------------------------------------------- NASA standards, blood corrections, rover, read cache
def test_the_blood_files_are_corrected_and_each_seat_reads_a_subject_of_its_own_sex():
    from canary.domain import nasa, simdata
    snap = nasa.snapshot()
    c3 = snap["cbc"]["crew"]["C003"]
    assert (c3["lym"][0], c3["neu"][0], c3["plt"][0]) == (1997, 6826, 330)  # realigned from MCH on (was 6826, 10.1, 12.9)
    assert snap["cbc"]["an"]["hgb"]["unit"] == "grams_per_deciliter"
    assert snap["cbc"]["an"]["hgb"]["F"] == {"min": 11.7, "max": 15.5} and snap["cbc"]["an"]["hgb"]["M"] == {"min": 13.2, "max": 17.1}
    i4_sex = {"C001": "M", "C002": "F", "C003": "F", "C004": "M"}  # OSD-569 sample metadata
    assert all(i4_sex[c["cbc_subject"]] == c["sex"] for c in simdata.load_demo_crew()["crew"])  # the generator's seeds
    assert simdata.lab_range(snap, "creatinine", "F") == (0.5, 1.05) and simdata.lab_range(snap, "crp", "F") is None
    assert "glucose" not in snap["cmp"]["an"]  # left out on purpose (R+45 samples processed late)


def test_real_metabolic_panel_rows_feed_the_kidney_heart_and_immune_risks(exam):
    from canary.domain import telemetry
    o = telemetry.last_observation("h", "creatinine", -3)
    assert o["origin"] == "simulated" and o["source"] == "modelled on Inspiration4 (NASA OSDR OSD-575)"
    _day(100)
    exam("t", "potassium", 6.2)  # above the laboratory range (3.5 to 5.3)
    assert any(e["key"] == "potassium" and e["points"] for e in _risk("t", "cardio")["evidence"])
    exam("a", "calcium", 11.0)  # above 8.6 to 10.4 (female range)
    assert any(e["key"] == "calcium" and e["points"] for e in _risk("a", "renal")["evidence"])
    pre = list(telemetry.preflight_values("k", "crp").values())
    exam("k", "crp", 3 * sum(pre) / len(pre))  # three times the pre-flight mean: inflammation
    assert any(e["key"] == "crp" and "above your pre-flight mean" in e["text"] for e in _risk("k", "immune")["evidence"])


def test_the_aerobic_limit_depends_on_the_place_and_on_the_persons_eva_role():
    from canary.domain import standards
    assert standards.check("vo2", "t", "transit", 34.0, None)["level"] == 1    # enough for 0 g EVAs, not for Mars ahead
    assert standards.check("vo2", "t", "mars", 34.0, None)["level"] == 2       # below 36.5 where EVAs are on the surface
    assert standards.check("vo2", "t", "mars_rover", 37.0, None)["level"] == 0
    assert standards.check("vo2", "t", "iss", 32.0, None)["item"] == "V1 4001"  # below 32.9 even for 0 g
    assert standards.check("vo2", "k", "mars", 30.0, None) is None             # Kenji does no EVA
    assert standards.check("vo2", "t", "rocket", 30.0, None) is None           # no EVA during launch


def test_strength_and_bone_have_nasa_floors_and_the_risk_and_system_follow_them():
    from canary.domain import standards
    assert standards.check("grip", "h", "mars", 26.0, 34.0)["level"] == 2 and standards.check("grip", "h", "mars", 30.0, 34.0)["level"] == 1
    assert standards.check("bone", "h", "transit", 0.90, 1.0)["level"] == 2 and standards.check("bone", "h", "transit", 0.965, 1.0)["verified"] is False
    assert standards.check("bone", "h", "transit", 0.99, 1.0)["level"] == 0
    assert standards.check("bone", "h", "transit", 0.90, None)["status"] == "not_assessable"  # no pre-flight scan: never an in-flight baseline
    assert standards.check("sleep", "h", "transit", 5.0, 7.4) is None  # V1 6001 plans a sleep period, it is not a measured limit


def test_the_career_dose_counts_earlier_flights():
    from canary.domain import standards
    h, a = standards.prior_dose("h"), standards.prior_dose("a")
    assert h["estimate"] and h["msv"] == 107.0 and a["msv"] == 0.0  # 214 days in space x 0.5 mSv/day
    _day(120)
    rh, ra = _risk("h", "radiation"), _risk("a", "radiation")
    assert rh["dose"]["mission_msv"] == ra["dose"]["mission_msv"] and rh["dose"]["now_msv"] == ra["dose"]["now_msv"] + 107.0
    assert rh["level"] == 1 and ra["level"] == 0 and rh["dose"]["cross_day"] < ra["dose"]["cross_day"]
    d = client.get("/api/crew/h", headers=as_("h")).json()
    assert d["dose"]["career_msv"] == round(d["dose"]["mission_msv"] + 107.0, 1) and d["standard_profile"]["eva"] == "surface"


def test_a_rover_traverse_is_a_place_of_its_own_on_the_mars_plan():
    from canary.domain import goals as goals_mod, privacy, protocols
    ms = _day(305)
    assert ms["location"] == "mars_rover" and ms["day_label"] == "Sol 92"  # the sol count keeps running from landing, with the real 88,775.244 s sol
    assert ms["place"]["eva"] == "surface" and ms["place"]["body"] == "mars"
    assert goals_mod._title({"id": "exercise"}, "mars_rover").startswith("30 min")
    assert {h["id"] for h in privacy.ridge("mars_rover", None, 305)} == {"R", "I", "D", "G", "E"}
    res = protocols.resolve("mars_rover")["protocols"]
    mars = protocols.resolve("mars")["protocols"]
    assert any(s["variant"] for p in res.values() for s in p["steps"])
    assert [s["variant"] for s in res["rad"]["steps"]] == [s["variant"] for s in mars["rad"]["steps"]]
    assert client.get("/api/crew/overview", headers=as_("h")).status_code == 200


def test_the_read_cache_never_outlives_a_write():
    db.set_setting("cache_probe", 1)
    assert db.get_setting("cache_probe") == 1
    db.set_setting("cache_probe", 2)
    assert db.get_setting("cache_probe") == 2
    rows = db.q("SELECT value FROM settings WHERE key=?", ("cache_probe",))
    rows[0]["value"] = "tampered"  # a caller editing its rows cannot change what the next caller reads
    assert db.get_setting("cache_probe") == 2


def test_the_standard_is_described_with_what_it_does_not_check():
    s = client.get("/api/catalog").json()["standards"]
    assert s["document"]["url"].startswith("https://www.nasa.gov/") and {"vo2", "grip", "bone", "radiation", "sleep"} <= set(s["checked"])
    assert {i for n in s["not_checked"] for i in n["items"]} >= {"V1 4020", "Table 4.8-1"}


def test_the_indicator_guide_maps_to_ids_canary_has():
    import pathlib
    from canary.domain import risk, simdata
    d = pathlib.Path(__file__).resolve().parents[2] / "data" / "indicator_guide"
    guide = json.loads((d / "indicadores.json").read_text(encoding="utf-8"))
    m = json.loads((d / "id_map.json").read_text(encoding="utf-8"))["map"]
    assert set(m) == {i["id"] for i in guide["indicadores"]}  # every guide entry is mapped, nothing more
    recipes = simdata.load_recipes()["indicators"]
    where = {"indicator": set(catalog.INDICATORS), "lab": set(recipes), "risk": set(risk.RISKS)}
    for gid, e in m.items():
        assert (e["v1"] is None) == (e["kind"] == "none"), gid
        if e["v1"] is not None:
            assert e["v1"] in where[e["kind"]], (gid, e)
    covered = {e["v1"] for e in m.values() if e["kind"] == "indicator"}
    readme = (d / "README.md").read_text(encoding="utf-8")
    for ind in set(catalog.INDICATORS) - covered:  # the README names every indicator the guide leaves without text
        assert f"`{ind}`" in readme.split("does not cover")[1], ind


# ---------------------------------------------------------------- input checks: every form refuses bad input with {field, message}
def _fields(r):
    assert r.status_code == 422, r.text
    d = r.json()["detail"]
    assert isinstance(d, list) and all(set(e) == {"field", "message"} for e in d)
    return {e["field"]: e["message"] for e in d}


def _ctl():
    return control_headers(client)


def _tests_count(cid, kind):
    t = {x["id"]: x for x in client.get(f"/api/checkins/{cid}", headers=as_(cid)).json()["tests"]}
    return t[kind].get("count", 1 if t[kind]["latest"] else 0)


@pytest.mark.parametrize("kind,payload,field,text", [
    ("vitals", {"hr": 10}, "hr", "Pulse must be between 25 and 250 bpm"),
    ("vitals", {"sbp": 300}, "sbp", "between 60 and 260 mmHg"),
    ("vitals", {"temp": 36.55}, "temp", "decimal place"),
    ("vitals", {"spo2": 97.5}, "spo2", "whole number"),
    ("vitals", {"hr": None, "sbp": None}, "form", "Type at least one value"),
    ("vitals", {"hr": "abc"}, "hr", "must be a number"),
    ("sleep", {"bed": "23:00", "wake": "23:30", "quality": 3}, "wake", "between 1 and 16 h"),
    ("sleep", {"bed": "", "wake": "07:00"}, "bed", "required"),
    ("reading", {"title": "  ", "minutes": 20}, "title", "required"),
    ("reading", {"title": "Dune", "minutes": 601}, "minutes", "between 1 and 600"),
    ("reading", {"title": "Dune", "minutes": 20, "pages": 2001}, "pages", "between 0 and 2000"),
    ("journal", {"lines": 0}, "lines", "between 1 and 3"),
    ("wellbeing", {"answers": [1, 1, -1, 1]}, "answers.2", "needs an answer"),
    ("symptoms", {"items": ["Headache"], "severity": 0}, "severity", "how strong"),
    ("symptoms", {"items": ["Toothache"], "severity": 1}, "items", "from the list"),
    ("mood", {"mood": 5}, "stress", "required"),
    ("dsst", {"correct": "many"}, "correct", "must be a number"),
    ("span", {"span": None}, "span", "required"),
])
def test_a_bad_check_in_is_refused_with_the_field_and_nothing_is_saved(kind, payload, field, text):
    _day(100)
    before = db.q("SELECT COUNT(*) AS n FROM checkins")[0]["n"]
    f = _fields(_checkin("a", kind, payload))
    assert field in f and text in f[field], f
    assert db.q("SELECT COUNT(*) AS n FROM checkins")[0]["n"] == before


def test_a_valid_check_in_of_each_kind_still_saves():
    _day(100)
    ok = {"vitals": {"hr": 62, "sbp": 118, "temp": 36.6, "spo2": 98}, "sleep": {"bed": "23:00", "wake": "07:00", "quality": 4},
          "reading": {"title": "Dune", "minutes": 25, "pages": None, "absorbing": 4}, "journal": {"lines": 2},
          "wellbeing": {"answers": [0, 1, 2, 3]}, "symptoms": {"items": [], "severity": 0, "note": ""},
          "tlx": {"scores": {"mental": 50, "physical": 20}}, "kss": {"level": 3}, "pvt": {"ms": 320}, "amsler": {"distortion": False},
          "dsst": {"correct": 40, "errors": 2}, "span": {"span": 6}, "mood": {"mood": 4, "stress": 2}}
    for kind, payload in ok.items():
        assert _checkin("a", kind, payload).status_code == 200, kind


def test_medical_goal_messages_thresholds_and_questions_refuse_bad_input_and_write_nothing():
    med = _med()
    goals_before = len(client.get("/api/medical/goals", headers=med).json())
    base = {"who": "all", "area": "physical", "title": "Walk 30 minutes", "why": "Keeps the legs working.", "days": 7}
    for patch, field in (({"title": "ab"}, "title"), ({"title": "   "}, "title"), ({"why": "x" * 201}, "why"), ({"days": 0}, "days"),
                         ({"days": 61}, "days"), ({"days": 2.5}, "days"), ({"who": "zz"}, "who")):
        assert field in _fields(client.post("/api/medical/goals", json={**base, **patch}, headers=med)), patch
    assert len(client.get("/api/medical/goals", headers=med).json()) == goals_before
    assert client.post("/api/medical/goals", json=base, headers=med).status_code == 200

    ctl = control_headers(client)
    n = len(client.get("/api/messages", headers=ctl).json())
    for text in ("", "   ", "x" * 1001):
        assert "text" in _fields(client.post("/api/messages", json={"recipient": "medical", "text": text}, headers=ctl))
    assert len(client.get("/api/messages", headers=ctl).json()) == n
    assert client.post("/api/messages", json={"recipient": "medical", "text": "Hello"}, headers=ctl).status_code == 200

    before = db.get_setting("thresholds")
    assert "act" in _fields(client.put("/api/medical/thresholds", json={"watch": 2.0, "act": 1.5}, headers=med))
    assert "watch" in _fields(client.put("/api/medical/thresholds", json={"watch": 9, "act": 3}, headers=med))
    assert db.get_setting("thresholds") == before  # the refused values were not stored
    assert client.put("/api/medical/thresholds", json={"watch": 1.0, "act": 2.0}, headers=med).status_code == 200
    assert db.get_setting("thresholds") == {"watch": 1.0, "act": 2.0} != before

    h = as_("h")
    asked = len(client.get("/api/assistant/history/h", headers=h).json())
    for q in ("", "   ", "x" * 501):
        assert "question" in _fields(client.post("/api/assistant/ask", json={"crew_id": "h", "question": q}, headers=h))
    assert len(client.get("/api/assistant/history/h", headers=h).json()) == asked


def test_control_registration_names_every_wrong_seat_field_and_saves_nothing_until_it_is_right():
    demo = client.get("/api/control/demo", headers=_ctl()).json()
    empty(client)  # a registered mission is locked: the form is checked on a system with nothing registered
    c = _ctl()
    names = []
    good = {"crew": demo["crew"], "mission": demo["mission"], "ground": demo["ground"]}

    def bad(seat, **patch):
        crew = [dict(p) for p in good["crew"]]
        crew[seat].update(patch)
        return _fields(client.post("/api/control/register", json={"crew": crew, "mission": good["mission"], "ground": good["ground"]}, headers=c))

    assert "crew.1.name" in bad(1, name="K")
    assert "crew.0.role" in bad(0, role="")
    assert "crew.2.pin" in bad(2, pin="12a4")
    assert "already used by person 1" in bad(3, pin=good["crew"][0]["pin"])["crew.3.pin"]
    assert "crew.0.dob" in bad(0, dob="2030-01-01") and "crew.0.dob" in bad(0, dob="1900-01-01") and "crew.0.dob" in bad(0, dob="1990-02-31")
    assert "at least 140" in bad(1, height_cm=100)["crew.1.height_cm"]
    assert "crew.1.weight_kg" in bad(1, weight_kg=200)
    assert "crew.2.blood_type" in bad(2, blood_type="Z+") and "crew.2.skin_type" in bad(2, skin_type="VII")
    assert "crew.0.flights" in bad(0, flights=21) and "crew.0.days_in_space" in bad(0, days_in_space=1001)
    assert "crew.0.prior_dose_msv" in bad(0, prior_dose_msv=601) and "crew.0.eva" in bad(0, eva="moon")
    assert set(bad(0, name="", pin="1")) == {"crew.0.name", "crew.0.pin"}  # all at once, not one by one
    assert [p["name"] for p in client.get("/api/catalog").json()["crew"]] == names  # nothing was registered

    def bad_mission(**patch):
        return _fields(client.post("/api/control/register", json={"crew": good["crew"], "mission": {**good["mission"], **patch}, "ground": good["ground"]}, headers=c))

    def bad_ground(ground, **patch):
        return _fields(client.post("/api/control/register", json={"crew": good["crew"], "mission": {**good["mission"], **patch}, "ground": ground}, headers=c))

    assert "mission.callsign" in bad_mission(callsign="K") and "mission.callsign" in bad_mission(callsign="x" * 25)
    assert "mission.name" in bad_mission(name="  ") and "mission.launch_date" in bad_mission(launch_date="2035-13-40")
    assert "mission.preset" in bad_mission(preset="venus")
    assert "ground.1.pin" in bad_ground([good["ground"][1], {**good["ground"][0], "id": None, "pin": good["ground"][1]["pin"]}])
    assert [p["name"] for p in client.get("/api/catalog").json()["crew"]] == names

    crew = [dict(p) for p in good["crew"]]
    crew[0]["name"] = "Ana Lima"
    assert client.post("/api/control/register", json={"crew": crew, "mission": good["mission"], "ground": good["ground"]}, headers=c).status_code == 200
    assert client.post("/api/control/register", json={"crew": crew, "mission": good["mission"], "ground": good["ground"]}, headers=control_headers(client)).status_code == 409


def test_auth_errors_keep_their_plain_shape():
    assert client.get("/api/control/overview").status_code == 401 and isinstance(client.get("/api/control/overview").json()["detail"], str)
    assert client.get("/api/crew/h/record", headers=as_("k")).status_code == 403


def test_nan_and_null_numbers_in_the_raw_json_are_refused_not_saved():
    _day(100)
    before = db.q("SELECT COUNT(*) AS n FROM checkins")[0]["n"]
    h = {**as_("a"), "Content-Type": "application/json"}
    r = client.post("/api/checkins", content='{"crew_id":"a","kind":"vitals","payload":{"hr":NaN}}', headers=h)
    assert "hr" in _fields(r)
    r = client.post("/api/checkins", content='{"crew_id":"a","kind":"vitals","payload":{"hr":null,"sbp":null,"temp":null,"spo2":null}}', headers=h)
    assert "form" in _fields(r)
    assert db.q("SELECT COUNT(*) AS n FROM checkins")[0]["n"] == before


# ---------------------------------------------------------------- funnel: personal numbers stay in My space and the medical team's view
PERSONAL = ("prior_msv", "prior_estimate", "career_msv", "career_pct_of_limit", "standard_profile", "risks", "care", "reason",
            "until_day", "care_events", "prior_dose", "standard")


def _crew_facing():
    ctl = control_headers(client)
    return {"crew overview": client.get("/api/crew/overview", headers=as_("h")).json(), "mission overview": client.get("/api/mission/overview").json(),
            "leaderboard": client.get("/api/leaderboard", headers=as_("h")).json(), "plan conditions": client.get("/api/plan/conditions").json(),
            "control overview": client.get("/api/control/overview", headers=ctl).json()}


def _keys(x):
    """Every key of a nested JSON value."""
    if isinstance(x, dict):
        for k, v in x.items():
            yield k
            yield from _keys(v)
    elif isinstance(x, list):
        for v in x:
            yield from _keys(v)


@pytest.mark.parametrize("step", [0, 2, 3, 4])
def test_crew_facing_endpoints_never_carry_career_dose_risks_eva_or_care(step):
    at(step)
    _close("seizure", "t")  # a care window is open for Tomas: Earth and the crew must not learn why he is restricted
    for name, body in _crew_facing().items():
        bad = set(PERSONAL) & set(_keys(body))
        assert not bad, (name, bad)
        assert "After Guided Response" not in str(body), name  # the emergency itself is crew-wide; the window after it is not
    dose = client.get("/api/crew/overview", headers=as_("h")).json()["dose"]
    assert "career_msv" not in dose and dose["mission_msv"] >= 0  # the mission dose is the same for everyone and stays


def test_the_career_dose_reaches_the_person_and_the_medical_team_only():
    at(3)
    for cid in "hkat":
        d = client.get(f"/api/crew/{cid}", headers=as_(cid)).json()
        assert {"prior_msv", "prior_estimate", "career_msv", "career_pct_of_limit"} <= set(d["dose"]) and "risks" in d and "standard_profile" in d
        assert client.get(f"/api/crew/{cid}").status_code == 403
        assert client.get(f"/api/crew/{cid}", headers=as_("k" if cid != "k" else "h")).status_code == 403
    med = client.get("/api/crew/t", headers=_med())
    assert med.status_code == 200 and med.json()["dose"]["career_msv"] >= med.json()["dose"]["prior_msv"]


def test_the_medical_overview_carries_career_dose_and_red_risks():
    at(3)
    assert client.get("/api/medical/overview").status_code == 401
    for c in client.get("/api/medical/overview", headers=_med()).json()["crew"]:
        assert c["dose"]["career_msv"] >= c["dose"]["prior_msv"] and c["standard_profile"]["eva"] in ("none", "microgravity", "surface")
        assert c["risks"] and all({"id", "name", "nasa_red", "level", "trend", "since_day", "data"} == set(r) for r in c["risks"])
        assert any(r["nasa_red"] for r in c["risks"])  # slim: no evidence text or hazard links here, the person view has those


def test_the_catalog_carries_the_indicator_guide_with_its_sources():
    g = client.get("/api/catalog").json()["guide"]
    assert {"sbp", "hr", "temp", "spo2", "gluc", "exer", "sleep", "mood", "vo2", "grip", "bone", "radiation"} <= set(g)
    for k, e in g.items():
        assert e["how"] and e["effect"] and set(e["actions"]) == {"green", "amber", "red"}, k
        assert not any(w in str(e).lower() for w in ("manguito", "sem gravidade")), k  # English only
    assert g["sbp"]["sources"]["how"] is None and g["vo2"]["sources"]["actions"]  # no source listed -> the app says so


# ---------------------------------------------------------------- C2: photo of the display kept with a vitals check-in
import base64  # noqa: E402

import io as _io  # noqa: E402
from PIL import Image as _Image  # noqa: E402
_buf = _io.BytesIO()
_Image.new("RGB", (1, 1), (200, 30, 30)).save(_buf, "JPEG")
_JPEG = "data:image/jpeg;base64," + base64.b64encode(_buf.getvalue()).decode()  # a real JPEG (EDIT-06)


def _vitals(cid="h", **extra):
    return client.post("/api/checkins", headers=as_(cid), json={"crew_id": cid, "kind": "vitals", "payload": {"hr": 62}, **extra})


def test_a_vitals_photo_is_kept_apart_and_returned_to_the_person_and_the_medical_team():
    r = _vitals(photo=_JPEG)
    assert r.status_code == 200
    hist = client.get("/api/checkins/h", headers=as_("h")).json()
    item = hist["recent"][0]
    assert item["has_photo"] is True and "photo" not in str(item["payload"])
    url = f"/api/checkins/h/{item['id']}/photo"
    assert client.get(url, headers=as_("h")).json() == {"data_url": _JPEG}
    assert client.get(url, headers=_med()).json() == {"data_url": _JPEG}
    assert client.get(f"/api/checkins/h", headers=_med()).json()["recent"][0]["has_photo"] is True
    ev = client.get("/api/crew/h", headers=_med()).json()["events"][0]
    assert ev["has_photo"] is True and _JPEG not in json.dumps(client.get("/api/crew/h", headers=_med()).json())
    assert client.get(f"/api/checkins/h/{item['id'] + 99}/photo", headers=as_("h")).status_code == 404


def test_a_vitals_without_photo_says_so():
    _vitals()
    assert client.get("/api/checkins/h", headers=as_("h")).json()["recent"][0]["has_photo"] is False


def test_the_photo_is_private_to_the_person_and_the_medical_team():
    _vitals(photo=_JPEG)
    cid = client.get("/api/checkins/h", headers=as_("h")).json()["recent"][0]["id"]
    url = f"/api/checkins/h/{cid}/photo"
    assert client.get(url).status_code == 403
    assert client.get(url, headers=as_("k")).status_code == 403
    assert client.get("/api/checkins/h", headers=as_("k")).status_code == 403


@pytest.mark.parametrize("kind,payload", [("mood", {"mood": 3, "stress": 2}), ("kss", {"level": 3})])
def test_only_vitals_take_a_photo(kind, payload):
    r = client.post("/api/checkins", headers=as_("h"), json={"crew_id": "h", "kind": kind, "payload": payload, "photo": _JPEG})
    assert r.status_code == 422 and r.json()["detail"][0]["field"] == "photo"
    assert client.get("/api/checkins/h", headers=as_("h")).json()["recent"] == []


@pytest.mark.parametrize("bad", [
    "not a data url", "data:text/html;base64,PGI+", "data:image/gif;base64,R0lGODlh", "data:image/jpeg;base64,@@@@",
    "data:image/jpeg;base64," + base64.b64encode(b"hello world, not a jpeg").decode(),
    "data:image/jpeg;base64," + base64.b64encode(b"\xff\xd8\xff" + b"\x00" * 600_000).decode(), 7, ""])
def test_a_bad_photo_is_refused_and_nothing_is_saved(bad):
    r = _vitals(photo=bad)
    assert r.status_code == 422 and r.json()["detail"][0]["field"] == "photo"
    assert client.get("/api/checkins/h", headers=as_("h")).json()["recent"] == []


def test_the_photo_never_reaches_crew_mission_or_control_overviews_and_a_reset_clears_it():
    at(3)
    _vitals(photo=_JPEG)
    for name, body in _crew_facing().items():
        assert "has_photo" not in set(_keys(body)) and "base64" not in json.dumps(body), name
    assert db.q("SELECT COUNT(*) n FROM checkin_photos")[0]["n"] == 1
    reset_demo(client)
    assert db.q("SELECT COUNT(*) n FROM checkin_photos")[0]["n"] == 0
