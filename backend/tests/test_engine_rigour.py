"""Rigour of the medical engine: statistics, NASA limits, radiation, honest labels, Mars time."""
import csv
import datetime as dt
import os
import pathlib
import tempfile

os.environ["CANARY_DB"] = os.path.join(tempfile.mkdtemp(), "rigour.db")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from canary import db  # noqa: E402
from canary.config import settings  # noqa: E402
from canary.domain import assumptions, catalog, data, dose, health, mission, nasa, plan, simdata, spacetime, standards, telemetry  # noqa: E402
from canary.main import app  # noqa: E402
from tests import golden_capture as gc  # noqa: E402
from tests.support import GROUND  # noqa: E402

client = TestClient(app)
KEY = "test-ingest-key-not-a-secret"
LAUNCH = dt.date(2036, 3, 1)
UTC = dt.timezone.utc
ROOT = pathlib.Path(__file__).resolve().parents[2]


def ctl():
    return {"Authorization": "Bearer " + gc._token(client, "/api/control/session", gc.CONTROL_PIN)}


@pytest.fixture()
def one(monkeypatch):
    """One registered person on the Mars plan, no data."""
    monkeypatch.setattr(settings, "ingest_key", KEY)
    monkeypatch.setattr(settings, "mission_package", "")
    monkeypatch.setattr(settings, "live_space_weather", False)
    assert gc.reset_demo(client).status_code == 200
    p = {"name": "Ines Almeida", "role": "Commander", "home": "Somewhere", "pin": "3001", "dob": "1985-04-11", "sex": "Female",
         "nationality": "Portuguese", "languages": ["Portuguese"], "agency": "Test agency", "flights": 0, "days_in_space": 0,
         "height_cm": 170, "weight_kg": 68, "blood_type": "A+", "skin_type": "III", "handedness": "Right", "eva": "surface"}
    r = client.post("/api/control/register", headers=ctl(), json={"crew": [p], "ground": GROUND, "mission": {
        "callsign": "T1", "name": "Test", "launch_date": LAUNCH.isoformat(), "preset": "mars", "dose_waiver": True}})
    assert r.status_code == 200, r.text
    mission.set_clock((LAUNCH + dt.timedelta(days=700)).isoformat(), "12:00")  # readings may not be dated in the future
    yield catalog.CREW[0]["id"]
    monkeypatch.setattr(settings, "mission_package", "odyssey1-mars")
    gc.reset_demo(client)


@pytest.fixture()
def demo():
    gc.reset_demo(client)
    yield


def post(rows):
    r = client.post("/api/observations", headers={"X-Canary-Key": KEY}, json={"rows": rows})
    assert r.status_code == 200, r.text


def row(cid, ind, day, v, hour=8, method=None, unit=None, source="test:x", note=None):
    when = dt.datetime.combine(LAUNCH, dt.time(hour)) + dt.timedelta(days=day)
    r = {"crew_id": cid, "indicator": ind, "value": v, "unit": unit or catalog.ACCEPT[ind]["units"][0],
         "measured_at": when.strftime("%Y-%m-%dT%H:%M:%SZ"), "source": source,
         "origin": {"blood": "lab", "urine": "lab", "manual": "manual"}.get(method, "device")}
    if method:
        r["method"] = method
    if note:
        r["note"] = note
    return r


def ms_at(day, storm=None):
    loc = plan.location_at(day)
    return {"day": day, "location": loc, "learning": loc == "earth" and day < 0, "storm": storm}


def series(cid, ind, days, f):
    return [row(cid, ind, d, f(d)) for d in days]


# ---------------------------------------------------------------- statistics
def test_z_is_the_days_own_value_not_smoothed(one):
    post(series(one, "sleep", range(-20, 0), lambda d: 7.4 + (0.3 if d % 2 else -0.3)) + series(one, "sleep", [20, 21], lambda d: 7.4) + [row(one, "sleep", 22, 5.0)])
    i = health.indicator(one, "sleep", ms_at(22))
    assert i["value"] == 5.0 and i["measured_today"] is True
    assert i["z"] == pytest.approx((5.0 - i["baseline"]) / i["spread"], abs=0.01)


def test_a_day_without_a_reading_shows_the_last_one_with_its_age(one):
    post(series(one, "sleep", range(-20, 0), lambda d: 7.4 + (0.3 if d % 2 else -0.3)) + [row(one, "sleep", 20, 6.0)])
    i = health.indicator(one, "sleep", ms_at(21))
    assert i["value"] == 6.0 and i["age_days"] == 1 and i["measured_today"] is False and i["last_measured_day"] == 20


def test_hysteresis_enter_at_2_5_stays_until_below_2_0():
    pts = [(d, v) for d, v in enumerate([2.6, 2.6, 2.4, 2.1, 1.99, 1.4, 0.9, 0.4])]
    lv = [x["level"] for x in health.indicator_level_series(pts, base=0, sd=1, direction="both")]
    assert lv == [1, 2, 2, 2, 1, 1, 0, 0]


def test_persistence_single_blip_is_level_zero_two_days_level_one():
    one_day = health.indicator_level_series([(0, 0.1), (1, 1.6), (2, 0.1)], base=0, sd=1, direction="both")
    assert [x["level"] for x in one_day] == [0, 0, 0]
    two_days = health.indicator_level_series([(0, 0.1), (1, 1.6), (2, 1.7), (3, 0.1)], base=0, sd=1, direction="both")
    assert [x["level"] for x in two_days] == [0, 0, 1, 0]


def test_a_critical_value_alerts_at_once_and_the_adaptation_window_holds_back_the_rest():
    lv = health.indicator_level_series([{"day": 0, "value": 0, "floor": 2}], base=0, sd=1)
    assert lv[0]["level"] == 2
    lv = health.indicator_level_series([{"day": 0, "value": 5, "suppress": True}, {"day": 1, "value": 5, "suppress": True}], base=0, sd=1)
    assert [x["level"] for x in lv] == [0, 0]


def test_confidence_buckets():
    assert [health.confidence(n) for n in (0, 9, 10, 19, 20, 80)] == ["low", "low", "moderate", "moderate", "high", "high"]


def test_in_flight_rebaseline_is_used_for_z_and_the_adaptation_window_holds_alerts(one):
    pre = [58 + (d % 3) - 1 for d in range(-30, 0)]
    post(series(one, "hr", range(-30, 0), lambda d: pre[d + 30]) + series(one, "hr", range(1, 40), lambda d: 80 + (d % 3) - 1))
    early = health.indicator(one, "hr", ms_at(5))
    assert early["adapting"] is True and early["level"] == 0 and early["raw_level"] == 2
    late = health.indicator(one, "hr", ms_at(30))
    assert late["baseline_in_use"] == "inflight" and late["baseline_preflight"] == pytest.approx(58, abs=1)
    assert late["baseline_inflight"]["n"] >= 4 and late["level"] == 0 and abs(late["z"]) < 2


def test_device_reading_beats_self_report_and_all_readings_are_kept(one):
    post(series(one, "sbp", range(-10, 0), lambda d: 118) + [row(one, "sbp", 10, 150, hour=9, method="manual", source="test:cuff"),
                                                              row(one, "sbp", 10, 120, hour=7, method="wearable", source="test:band")])
    o = telemetry.observation(one, "sbp", 10)
    assert o["value"] == 120 and o["method"] == "wearable" and o["readings"] == 2


def test_only_resting_readings_count(one):
    post([row(one, "hr", 3, 60, hour=7, method="wearable", note=simdata.with_context("", activity="rest")),
          row(one, "hr", 3, 150, hour=9, method="wearable", source="test:ex", note=simdata.with_context("", activity="exercise"))])
    assert telemetry.observation(one, "hr", 3)["value"] == 60
    post([row(one, "sbp", 3, 118, hour=7, note=simdata.with_context("", position="seated")),
          row(one, "sbp", 3, 95, hour=9, source="test:st", note=simdata.with_context("", position="standing"))])
    assert telemetry.observation(one, "sbp", 3)["value"] == 118


# ---------------------------------------------------------------- NASA limits
def test_percent_of_baseline_limits_never_use_an_in_flight_baseline(one):
    assert standards.check("grip", one, "transit", 20.0, None)["status"] == "not_assessable"
    assert standards.check("bone", one, "transit", 0.5, None)["status"] == "not_assessable"
    post(series(one, "grip", range(0, 14), lambda d: 40 + (d % 2)) + [row(one, "grip", 30, 20.0)])  # only in-flight data
    i = health.indicator(one, "grip", ms_at(30))
    assert i["baseline_from"] == "early_flight" and i["standard"]["status"] == "not_assessable" and i["standard"]["level"] == 0


def test_grip_limit_reads_the_preflight_baseline(one):
    post(series(one, "grip", range(-20, 0), lambda d: 40 + (d % 2)) + [row(one, "grip", 30, 20.0)])
    s = health.indicator(one, "grip", ms_at(30))["standard"]
    assert s["level"] == 2 and "80%" in s["text"]


def test_bone_has_no_daily_in_flight_readings_and_the_estimate_is_labelled():
    assert catalog.INDICATORS["bone"]["scan"] and catalog.INDICATORS["bone"]["max_age"] > 365
    for pkg in ("odyssey1-mars", "odyssey1-moon", "odyssey1-iss"):
        legs = list(csv.DictReader(open(ROOT / "data/missions" / pkg / "legs.csv")))
        away = [(int(l["start_day"]), int(l["end_day"])) for l in legs if l["location"] != "earth" and int(l["start_day"]) >= 0]
        first, last = away[0][0], away[-1][1]
        days = [int(r["day"]) for r in csv.DictReader(open(ROOT / "data/missions" / pkg / "observations.csv")) if r["indicator"] == "bone"]
        assert days and not [d for d in days if first <= d <= last], pkg


def test_bone_in_flight_is_an_estimate(demo):
    mission.set_day(100)
    i = health.indicator("t", "bone", mission.state())
    assert i["value"] is None and i["inferred"] and i["estimate"]["origin"] == "estimated" and i["estimate"]["loss_pct"] > 0


# ---------------------------------------------------------------- radiation
def event(**kw):
    e = {"id": "t-ev", "kind": "sep", "start_day": 20, "end_day": 20, "locations": ["iss", "transit", "mars"], "extra_dose_msv": 22,
         "origin": "simulated", "source": "simulated", "note": "test event"}
    e.update(kw)
    return data.add_space_event(e)


def storm_alert(cid, day):
    ms = ms_at(day, dose.active_storm(day, plan.location_at(day)))
    return next((a for a in health.snapshot(cid, ms)["alerts"] if a["id"] == "storm"), None)


def test_storm_on_the_station_with_a_quiet_cabin_orders_no_shelter(one):
    plan.use_preset("iss")
    event()
    post([row("cabin", "dose_eq_rate", 20, 0.5, unit="mSv/day", method="dosimeter")])
    a = storm_alert(one, 20)
    assert a["level"] == 1 and a["env"] and a["escalate"] and a["recipients"] == ["cmo", "earth"] and not a["shelter"]["order"]
    post([row("cabin", "dose_eq_rate", 20, 12, unit="mSv/day", method="dosimeter", source="test:hot", hour=9)])
    assert storm_alert(one, 20)["level"] == 2


def test_storm_in_transit_orders_the_shelter_and_is_escalated(one):
    event()
    a = storm_alert(one, 20)
    assert plan.location_at(20) == "transit" and a["level"] == 2 and a["escalate"] is True and a["env"] is True
    assert a["recipients"] == ["cmo", "earth"] and a["origin"] == "simulated"


def test_a_donki_event_does_not_apply_on_the_mars_surface(one):
    event(start_day=250, end_day=250)
    assert plan.location_at(250) == "mars" and dose.active_event(250, "mars") is None
    event(id="t-mars", kind="mars", start_day=250, end_day=250, locations=["mars"])
    assert dose.active_event(250, "mars")["kind"] == "mars"


def test_storm_text_comes_from_the_event(one):
    event()
    a = storm_alert(one, 20)
    text = a["title"] + " " + a["why"]
    assert "51 times" not in text and "20 May 2024" not in text and "10 May 2024" not in text and "test event" in text and "simulated" in text
    event(note="radiation was 51 times above normal")
    assert "51 times above normal" in storm_alert(one, 20)["why"]


def test_dose_windows_career_and_the_design_reference(one, monkeypatch):
    post([row("cabin", "dose_eq_rate", d, 1.0, unit="mSv/day", method="dosimeter") for d in range(0, 40)])
    w = dose.windows(one, 39)
    assert w["d30"]["msv"] == 30.0 and w["d365"]["msv"] == 40.0 and w["d30"]["origin"] == "measured" and "no limit applied" in w["d30"]["label"]
    monkeypatch.setattr(standards, "prior_dose", lambda c: {"msv": 590.0, "estimate": False, "source": "test"})
    d = health.dose(ms_at(39), one)
    assert d["career_msv"] == 630.0 and d["career_pct_of_limit"] >= 100 and d["career_origin"] == "measured"
    e = dose.event_dose({"id": "x", "kind": "sep", "start_day": 1, "extra_dose_msv": 22, "origin": "simulated"})
    assert e["design_reference_msv"] == 250 and e["pct_of_design_reference"] == 8.8 and e["below_design_reference"]


def test_absorbed_dose_is_converted_and_dose_equivalent_wins(one):
    post([row("cabin", "dose_rate", 5, 1.0, unit="mGy/day", method="dosimeter")])
    assert dose.rate_today(one, 5)["msv_day"] == pytest.approx(assumptions.value("dose.quality_factor"))
    post([row("cabin", "dose_eq_rate", 5, 3.0, unit="mSv/day", method="dosimeter", source="test:eq")])
    assert dose.rate_today(one, 5)["msv_day"] == 3.0


# ---------------------------------------------------------------- honest labels
def test_inspiration4_blood_is_simulated_in_every_package():
    for pkg in ("odyssey1-mars", "odyssey1-moon", "odyssey1-iss"):
        rows = [r for r in csv.DictReader(open(ROOT / "data/missions" / pkg / "observations.csv")) if r["method"] == "blood" and r["indicator"] in ("lym", "wbc", "creatinine")]
        assert rows and {r["origin"] for r in rows} == {"simulated"}
        assert all(r["source"].startswith("modelled on Inspiration4 (NASA OSDR OSD-5") for r in rows)
        ev = list(csv.DictReader(open(ROOT / "data/missions" / pkg / "space_events.csv")))
        assert {e["origin"] for e in ev} == {"simulated"}


def test_blood_card_is_labelled_simulated(demo):
    assert nasa.blood("h", "F")["origin"] == "simulated"


def test_sources_and_space_weather_do_not_claim_a_fixed_window_when_live(monkeypatch):
    ids = {s["id"]: s for s in nasa.SOURCES}
    assert ids["inspiration4"]["name"] == "Inspiration4 (SpaceX, 2021)" and ids["simulated"]["url"] == ""
    assert "pattern for the simulated crew blood counts" in ids["nasa:osd569"]["used_for"].lower()
    monkeypatch.setattr(settings, "live_space_weather", True)
    monkeypatch.setattr(nasa, "_live", lambda: {"window": "2036-01-01 to 2036-01-31", "sep_events": 0, "kp_max": 3})
    sw = nasa.space_weather()
    assert sw["mode"] == "live" and sw["window"] == "2036-01-01 to 2036-01-31" and sw["kp"] == []


def test_every_assumption_has_a_value_unit_and_source():
    assert len(assumptions.ASSUMPTIONS) > 40
    for k, a in assumptions.ASSUMPTIONS.items():
        assert a["unit"] and a["source"] and "value" in a, k


# ---------------------------------------------------------------- Mars time and plan
def test_light_time_at_opposition_and_conjunction():
    opp = dt.datetime(2035, 9, 15, 19, 33, tzinfo=UTC)
    assert 4.2 * 60 < spacetime.light_time_s(opp) < 4.6 * 60 and not spacetime.blackout(opp)
    conj = opp + dt.timedelta(days=389.97)
    assert 20.5 * 60 < spacetime.light_time_s(conj) < 21.5 * 60 and spacetime.blackout(conj)
    assert spacetime.one_way_light_s("moon", opp)[0] == 1.28 and spacetime.one_way_light_s("iss", opp) == (0.0, False)


def test_sol_length_msd_and_met():
    assert assumptions.value("mars.sol_s") == 88775.244
    assert spacetime.sol_after(1.0274912517) == 1 and spacetime.sol_after(1.0274) == 0
    assert spacetime.msd(dt.datetime(2000, 1, 6, 0, 0, tzinfo=UTC)) == pytest.approx(44796.0, abs=0.01)
    launch = dt.datetime(2035, 6, 1, tzinfo=UTC)
    assert spacetime.met(launch, dt.datetime(2035, 6, 4, 13, 5, tzinfo=UTC)) == "3/13:05"
    assert 0 <= spacetime.lmst_hours(launch) < 24


def test_mission_state_carries_met_gmt_sol_and_blackout(demo):
    s = mission.set_day(222)
    assert s["met"] == "222/12:00" and s["gmt"].endswith("T12:00:00Z") and s["day_label"] == "Sol 12" and s["mars_time"]["lmst"]
    conj = dt.datetime(2035, 9, 15, 19, 33, tzinfo=UTC) + dt.timedelta(days=389.97)
    s = mission.set_clock(conj.date().isoformat(), "12:00")
    assert s["blackout"] is True and s["place"]["blackout"] and s["one_way_light_s"] > 1200
    assert s["place"]["reply"].endswith("minutes")


def test_mars_preset_has_a_return_leg_and_the_demo_crew_needs_a_waiver(demo):
    legs = plan.PRESETS["mars"]["legs"]
    assert [l["location"] for l in legs[-2:]] == ["transit", "earth"] and plan.transit_direction(len(legs) - 2) == "back"
    ids = [c["id"] for c in catalog.CREW]
    proj = dose.career_projections(0, ids, {c: standards.prior_dose(c) for c in ids})
    assert all(p["exceeds_career_limit"] and p["projected_career_msv"] > 600 and p["origin"] == "estimated" for p in proj.values())
    assert all(health.dose(ms_at(0), c)["exceeds_career_limit"] for c in ids)
