"""The demo mission as spreadsheet packages (data/missions/*): they must say exactly what the engine knows today."""
import csv
import os
import pathlib
import sys
import tempfile

os.environ["CANARY_DB"] = os.path.join(tempfile.mkdtemp(), "package.db")

import pytest  # noqa: E402

from canary.domain import catalog, goals, plan, registry, simdata, telemetry  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "data"))
import generate_dataset as gd  # noqa: E402

FILES = ["mission.csv", "legs.csv", "crew.csv", "observations.csv", "space_events.csv", "goal_log.csv", "scenes.csv", "README.md"]


def read(pkg, name):
    with open(ROOT / "data" / "missions" / pkg / name, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def key(r):
    return (r["crew_id"], int(r["day"]), r["indicator"], r["value"], r["unit"], r["origin"], r["method"], r["source"], r["note"])


@pytest.mark.parametrize("pkg", [p for p, _ in gd.PACKAGES])
def test_files_exist(pkg):
    for f in FILES:
        assert (ROOT / "data" / "missions" / pkg / f).stat().st_size > 0, f


@pytest.mark.parametrize("pkg,preset", gd.PACKAGES)
def test_mission_and_legs(pkg, preset):
    m = read(pkg, "mission.csv")
    assert len(m) == 1 and m[0]["preset"] == preset and m[0]["simulated_time"] == "12:00"
    assert m[0]["simulated_today"] == "2035-05-02" and m[0]["callsign"] == gd.DEMO_MISSION["callsign"]
    legs = [{"start": int(r["start_day"]), "end": int(r["end_day"]), "location": r["location"]} for r in read(pkg, "legs.csv")]
    assert legs == [{k: l[k] for k in ("start", "end", "location")} for l in plan.preset_legs(preset)]


def test_mars_legs_equal_default_plan():
    default = plan.PRESETS[plan.DEFAULT]["legs"]
    legs = [(int(r["start_day"]), int(r["end_day"]), r["location"]) for r in read("odyssey1-mars", "legs.csv")]
    assert legs == [(l["start"], l["end"], l["location"]) for l in default]


def test_crew_matches_registry():
    rows = read("odyssey1-mars", "crew.csv")
    assert [r["id"] for r in rows] == [c["id"] for c in gd.DEMO_CREW]
    for r, c in zip(rows, gd.DEMO_CREW):
        assert (r["name"], r["role"], r["initials"], r["home"]) == (c["name"], c["role"], c["initials"], c["home"])
        assert r["sex"][0] == c["sex"] and r["pin"] in ("1001", "1002", "1003", "1004")
        assert r["languages"].split(";") == gd.DEMO_RECORDS[c["id"]]["languages"]
        assert "base" not in r and "cbc_subject" not in r and r["prior_dose_msv"] == ""
    assert all(f in rows[0] for f in registry.RECORD_FIELDS)


def test_mars_observations_equal_engine_file():
    pkg = [key(r) for r in read("odyssey1-mars", "observations.csv") if r["indicator"] != "dose_rate"]
    engine = [key(r) for r in simdata.read_csv(simdata.OBS_FILE)]
    assert pkg == engine
    row = read("odyssey1-mars", "observations.csv")[0]
    assert row["measured_at"].endswith("T08:00:00Z")


@pytest.mark.parametrize("pkg,preset", gd.PACKAGES)
def test_observations_match_generator(pkg, preset):
    if preset == "mars":
        return
    legs = plan.preset_legs(preset)
    engine = [(r[0], str(r[1]), r[2], r[3], r[4], r[5], r[6], r[7], r[8]) for r in simdata.Generator(legs).observations()]
    got = [tuple(str(x) for x in key(r)) for r in read(pkg, "observations.csv") if r["indicator"] != "dose_rate"]
    assert got == [tuple(str(x) if i != 1 else str(x) for i, x in enumerate(e)) for e in engine]


@pytest.mark.parametrize("pkg,preset", gd.PACKAGES)
def test_dose_rate_rows(pkg, preset):
    legs = plan.preset_legs(preset)
    rows = [r for r in read(pkg, "observations.csv") if r["indicator"] == "dose_rate"]
    assert [int(r["day"]) for r in rows] == list(range(0, max(l["end"] for l in legs) + 1))
    for r in rows:
        assert (r["crew_id"], r["unit"], r["origin"], r["method"], r["source"]) == ("cabin", "mSv/day", "simulated", "dosimeter", "mock:dosimeter")
        day, loc = int(r["day"]), simdata.location_at(legs, int(r["day"]))
        # the storm's extra dose is inside the reading of the day the storm starts, when it hits the place
        extra = sum(float(e[5]) for e in gd.SPACE_EVENTS if e[2] == day and loc in e[4].split(";"))
        assert float(r["value"]) == pytest.approx(catalog.LOCATIONS[loc]["dose_rate"] + extra)


def test_the_storm_is_in_the_cabin_dosimeter_of_its_start_day():
    rate = {int(r["day"]): float(r["value"]) for r in read("odyssey1-mars", "observations.csv") if r["indicator"] == "dose_rate"}
    assert rate[152] == pytest.approx(1.8 + 22) and rate[151] == 1.8 and rate[153] == 1.8
    assert rate[222] == catalog.LOCATIONS["mars"]["dose_rate"]  # the Mars storm adds no dose


def test_space_events():
    ev = {r["id"]: r for r in read("odyssey1-mars", "space_events.csv")}
    assert (ev["replay-2024-05-10-sep"]["start_day"], ev["replay-2024-05-10-sep"]["locations"], ev["replay-2024-05-10-sep"]["extra_dose_msv"], ev["replay-2024-05-10-sep"]["source"]) == ("152", "transit;moon", "22", "nasa:donki")
    assert (ev["replay-2024-05-20-rad"]["start_day"], ev["replay-2024-05-20-rad"]["locations"], ev["replay-2024-05-20-rad"]["extra_dose_msv"], ev["replay-2024-05-20-rad"]["source"]) == ("222", "mars", "0", "nasa:rad")


def minutes(t):
    h, m = t.split(":")
    return int(h) * 60 + int(m)


def reference_sim_done(crew_id, goal_id, day, today):
    """The rule the engine used before the goal history moved into the goal log (goals._sim_done, now removed). Kept here
    as the reference the package must reproduce."""
    p = {"h": 0.86, "k": 0.84, "a": 0.9, "t": 0.74}[crew_id]
    g = catalog.PERSONAL_BY_ID.get(goal_id)
    if crew_id == "h" and 132 <= day <= 153 and g and g["area"] == "mental":
        p = 0.35
    if crew_id == "t" and 1 <= day <= 4:
        p = 0.3
    if day == today:
        p *= 0.45
    return telemetry.h01(f"goal:{crew_id}:{goal_id}:{day}") < p


def test_goal_log_reproduces_the_old_simulated_history():
    """goals.is_done on the package's goal log gives exactly what the removed simulation gave, for any 'today'."""
    plan.reset_cache()
    rows = read("odyssey1-mars", "goal_log.csv")
    done = {(r["crew_id"], int(r["day"]), r["goal_id"]): minutes(r["done_at_time"]) for r in rows}
    assert all(r["done"] == "1" for r in rows) and len(done) == len(rows)
    for r in rows:
        assert 8 * 60 <= minutes(r["done_at_time"]) < 12 * 60 or 18 * 60 <= minutes(r["done_at_time"]) < 22 * 60
    log = {c["id"]: {} for c in gd.DEMO_CREW}
    for r in rows:
        log[r["crew_id"]][(int(r["day"]), r["goal_id"])] = (1, r["done_at_time"])
    last = max(l["end"] for l in plan.get()["legs"])
    for today in (-30, -5, 2, 147, 152, 153, 222, 400):
        for c in gd.DEMO_CREW:
            for day in range(gd.HISTORY_START, last + 1):
                for gid in goals.daily_goal_ids(plan.location_at(day)):
                    assert goals.is_done(c["id"], gid, day, today, log[c["id"]], "12:00") == reference_sim_done(c["id"], gid, day, today), (c["id"], gid, day, today)


def test_scenes():
    rows = read("odyssey1-mars", "scenes.csv")
    assert [(int(r["day"]), r["location"], r["person"]) for r in rows] == [(s["day"], s["loc"], s["me"]) for s in gd.STORY]
