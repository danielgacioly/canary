"""The entry points: readings, space events and mission packages all go through domain/data.py, validated first and
written in one transaction. The engine reads only the database."""
import csv
import io
import os
import pathlib
import shutil
import sqlite3
import tempfile
import time
import zipfile

os.environ["CANARY_DB"] = os.path.join(tempfile.mkdtemp(), "ingest.db")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from canary import db  # noqa: E402
from canary.config import settings  # noqa: E402
from canary.domain import catalog, data, goals, selftests, simdata, telemetry  # noqa: E402
from canary.main import app  # noqa: E402

client = TestClient(app)
ROOT = pathlib.Path(__file__).resolve().parents[2]
MARS = ROOT / "data" / "missions" / "odyssey1-mars"
KEY = "test-ingest-key-not-a-secret"
GOOD = {"crew_id": "h", "indicator": "sleep", "value": 3.3, "unit": "h", "measured_at": "2035-06-11T09:30:00Z", "source": "test:band"}


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    monkeypatch.setattr(settings, "ingest_key", KEY)
    monkeypatch.setattr(settings, "mission_package", "odyssey1-mars")
    client.post("/api/demo/reset")
    yield
    monkeypatch.setattr(settings, "mission_package", "odyssey1-mars")
    client.post("/api/demo/reset")


def key():
    return {"X-Canary-Key": KEY}


def ctl():
    return {"X-Canary-Control": client.post("/api/control/session", json={"pin": "4242"}).json()["token"]}


def me(cid="h", pin="1001"):
    return {"X-Canary-Viewer": client.post(f"/api/crew/{cid}/session", json={"pin": pin}).json()["token"]}


def n_obs():
    return db.q("SELECT COUNT(*) n FROM observations")[0]["n"]


def fields(r):
    return [e["field"] for e in r.json()["detail"]]


# ---------------------------------------------------------------- POST /api/observations
def test_a_valid_batch_shows_up_in_the_person_page_value_and_series():
    before = n_obs()
    r = client.post("/api/observations", headers=key(), json={"rows": [
        GOOD, {"crew_id": "k", "indicator": "hr", "value": 61, "unit": "bpm", "day": 10, "origin": "real", "source": "test:band"}]})
    assert r.status_code == 200 and r.json() == {"accepted": 2, "duplicates": 0}
    assert n_obs() == before + 2
    client.put("/api/mission", json={"day": 10})
    assert telemetry.observation("h", "sleep", 10)["value"] == 3.3
    assert telemetry.observation("h", "sleep", 10)["source"] == "test:band"
    page = client.get("/api/crew/h", headers=me()).json()
    assert [v for d, v in page["trends"]["sleep"] if d == 10] == [3.3]
    assert page["indicators"]["sleep"]["value"] < 6  # 60% of today's 3.3 pulled the weighted value down
    k = client.get("/api/crew/k", headers=me("k", "1002")).json()
    assert [v for d, v in k["trends"]["hr"] if d == 10] == [61]  # `day` is stamped at 08:00 UTC of that mission day
    assert db.q("SELECT measured_at FROM observations WHERE source='test:band' AND crew_id='k'")[0]["measured_at"] == "2035-06-11T08:00:00Z"


@pytest.mark.parametrize("patch,field", [
    ({"indicator": "bogus"}, "rows.1.indicator"),
    ({"unit": "min"}, "rows.1.unit"),
    ({"value": 400}, "rows.1.value"),
    ({"value": "abc"}, "rows.1.value"),
    ({"value": None}, "rows.1.value"),
    ({"crew_id": "zz"}, "rows.1.crew_id"),
    ({"crew_id": None}, "rows.1.crew_id"),
    ({"measured_at": "yesterday"}, "rows.1.measured_at"),
    ({"measured_at": None}, "rows.1.measured_at"),
    ({"measured_at": None, "day": "x"}, "rows.1.day"),
    ({"origin": "dream"}, "rows.1.origin"),
])
def test_an_invalid_row_is_refused_with_its_path_and_nothing_is_written(patch, field):
    before = n_obs()
    r = client.post("/api/observations", headers=key(), json={"rows": [GOOD, {**GOOD, **patch}]})
    assert r.status_code == 422 and fields(r) == [field], r.text
    assert n_obs() == before  # the good row before it was not stored either


def test_every_bad_row_is_named_not_only_the_first():
    r = client.post("/api/observations", headers=key(), json={"rows": [{**GOOD, "value": 999}, GOOD, {**GOOD, "unit": "x"}]})
    assert fields(r) == ["rows.0.value", "rows.2.unit"]


def test_the_batch_shape_and_size_are_checked():
    assert fields(client.post("/api/observations", headers=key(), json={"nope": 1})) == ["rows"]
    assert fields(client.post("/api/observations", headers=key(), json={"rows": "x"})) == ["rows"]
    r = client.post("/api/observations", headers=key(), json={"rows": [GOOD] * 5001})
    assert r.status_code == 422 and fields(r) == ["rows"] and n_obs() == data.count_observations()
    assert client.post("/api/observations", headers=key(), json={"rows": [GOOD] * 5000}).json() == {"accepted": 1, "duplicates": 4999}


def test_without_a_configured_key_ingest_is_off(monkeypatch):
    monkeypatch.setattr(settings, "ingest_key", "")
    before = n_obs()
    for h in ({}, key(), {"X-Canary-Key": ""}):
        r = client.post("/api/observations", headers=h, json={"rows": [GOOD]})
        assert r.status_code == 503 and r.json()["detail"] == "Ingest is off"
    assert n_obs() == before


def test_a_wrong_or_missing_key_is_refused_and_never_echoed():
    before = n_obs()
    for h in ({}, {"X-Canary-Key": "wrong"}, {"X-Canary-Key": KEY + "x"}, {"X-Canary-Key": ""}):
        r = client.post("/api/observations", headers=h, json={"rows": [GOOD]})
        assert r.status_code == 401 and KEY not in r.text
    assert n_obs() == before


def test_the_same_batch_twice_stores_nothing_new():
    rows = [GOOD, {**GOOD, "indicator": "hr", "value": 60, "unit": "bpm"}]
    assert client.post("/api/observations", headers=key(), json={"rows": rows}).json() == {"accepted": 2, "duplicates": 0}
    n = n_obs()
    assert client.post("/api/observations", headers=key(), json={"rows": rows}).json() == {"accepted": 0, "duplicates": 2}
    assert n_obs() == n
    # the same reading from another source is a different reading
    assert client.post("/api/observations", headers=key(), json={"rows": [{**GOOD, "source": "test:other"}]}).json()["accepted"] == 1


def test_a_reading_changes_the_health_numbers_it_feeds():
    """The caches that hold computed health are keyed on the data version, so new readings are not hidden by them."""
    client.put("/api/mission", json={"day": 10})
    before = client.get("/api/crew/h", headers=me()).json()["indicators"]["sleep"]["value"]
    assert client.post("/api/observations", headers=key(), json={"rows": [GOOD]}).status_code == 200
    after = client.get("/api/crew/h", headers=me()).json()["indicators"]["sleep"]["value"]
    assert after < before


def test_the_dose_rate_is_a_measurement_but_not_an_indicator():
    assert "dose_rate" in catalog.ACCEPT and "dose_rate" not in catalog.INDICATORS
    row = {"crew_id": "cabin", "indicator": "dose_rate", "value": 0.7, "unit": "mSv/day", "day": 5, "source": "test:dosimeter"}
    assert client.post("/api/observations", headers=key(), json={"rows": [row]}).json()["accepted"] == 1
    assert telemetry.last_observation("cabin", "dose_rate", 5)["value"] == 0.7
    assert client.post("/api/observations", headers=key(), json={"rows": [{**row, "value": 500}]}).status_code == 422
    assert catalog.INDICATORS.keys() <= catalog.ACCEPT.keys()


def test_the_plausibility_ranges_of_vitals_are_the_check_in_limits():
    for k, rng in selftests.VITALS_LIMITS.items():
        assert catalog.ACCEPT[k]["range"] == rng


# ---------------------------------------------------------------- mission packages
def package_files(tmp_path, bad_line=None):
    """A copy of the Mars package; with `bad_line`, that observation row gets an impossible value."""
    dst = tmp_path / "pkg"
    shutil.copytree(MARS, dst)
    if bad_line is not None:
        lines = (dst / "observations.csv").read_text(encoding="utf-8").split("\n")
        cells = next(csv.reader([lines[bad_line]]))
        cells[3] = "9999"
        out = io.StringIO()
        csv.writer(out, lineterminator="").writerow(cells)
        lines[bad_line] = out.getvalue()
        (dst / "observations.csv").write_text("\n".join(lines), encoding="utf-8")
    return dst


def upload(files, headers=None):
    parts = [("file", (name, content, "text/csv")) for name, content in files.items()]
    return client.post("/api/control/import", headers=headers or ctl(), files=parts)


def test_importing_a_package_with_one_bad_row_names_the_row_and_writes_nothing(tmp_path):
    client.post("/api/demo/reset")
    snap = (n_obs(), db.q("SELECT COUNT(*) n FROM goal_log")[0]["n"], db.q("SELECT COUNT(*) n FROM scenes")[0]["n"], data.version())
    pkg = package_files(tmp_path, bad_line=1201)  # line 1202 of the file
    with pytest.raises(data.ValidationFailure) as e:
        data.import_package(pkg)
    assert [x["field"] for x in e.value.errors] == ["observations.1200.value"] and "line 1202" in e.value.errors[0]["message"]
    r = upload({f.name: f.read_bytes() for f in pkg.glob("*.csv")})
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "observations.1200.value" and r.json()["accepted"] == {}
    assert "observations.csv" in r.json()["errors"][0]["message"]
    assert snap == (n_obs(), db.q("SELECT COUNT(*) n FROM goal_log")[0]["n"], db.q("SELECT COUNT(*) n FROM scenes")[0]["n"], data.version())


def test_a_bad_row_in_a_later_file_writes_nothing_from_the_earlier_ones(tmp_path):
    monkey = settings.mission_package
    settings.mission_package = ""
    try:
        client.post("/api/demo/reset")
        assert n_obs() == 0
        pkg = package_files(tmp_path)
        (pkg / "scenes.csv").write_text("index,day,location,person,storm,when,text\n0,1,mars_base,h,,x,y\n", encoding="utf-8")
        r = upload({f.name: f.read_bytes() for f in pkg.glob("*.csv")})
        assert r.status_code == 422 and r.json()["errors"][0]["field"] == "scenes.0.location"
        assert n_obs() == 0 and db.q("SELECT COUNT(*) n FROM space_events")[0]["n"] == 0 and db.get_setting("registry") is None
    finally:
        settings.mission_package = monkey


def test_a_zip_of_a_package_imports_and_a_second_time_adds_no_readings(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "mission_package", "")
    client.post("/api/demo/reset")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for f in MARS.glob("*.csv"):
            z.write(f, "odyssey1-mars/" + f.name)  # a folder inside the zip is fine
        z.writestr("__MACOSX/._x", "junk")
        z.write(MARS / "README.md", "odyssey1-mars/README.md")
    t = time.time()
    r = client.post("/api/control/import", headers=ctl(), files=[("file", ("pkg.zip", buf.getvalue(), "application/zip"))])
    assert r.status_code == 200, r.text
    assert time.time() - t < 5
    body = r.json()
    assert body["errors"] == [] and body["accepted"]["observations"] == n_obs() > 50000
    assert body["accepted"]["scenes"] == 6 and body["accepted"]["crew"] == 4 and body["accepted"]["space_events"] == 2
    again = client.post("/api/control/import", headers=ctl(), files=[("file", ("pkg.zip", buf.getvalue(), "application/zip"))]).json()
    assert again["accepted"]["observations"] == 0 and again["duplicates"]["observations"] == body["accepted"]["observations"]
    assert len(client.get("/api/scenes").json()) == 6


def test_loose_csv_files_import_and_unknown_files_are_refused(monkeypatch):
    monkeypatch.setattr(settings, "mission_package", "")
    client.post("/api/demo/reset")
    r = upload({"notes.csv": b"a,b\n1,2\n"})
    assert r.status_code == 422 and "Unknown file" in r.json()["errors"][0]["message"]
    r = upload({"observations.csv": b"crew_id,day,indicator,value,unit\nh,1,sleep,7,h\n"})
    assert r.status_code == 422 and "Unknown crew id" in r.json()["errors"][0]["message"]  # nobody is registered yet
    r = upload({"crew.csv": (MARS / "crew.csv").read_bytes(), "observations.csv": b"crew_id,day,indicator,value,unit\nh,1,sleep,7,h\n"})
    assert r.status_code == 200 and r.json()["accepted"]["observations"] == 1 and r.json()["accepted"]["crew"] == 4 and n_obs() == 1


def test_a_bundled_package_loads_by_name_and_paths_are_refused():
    h = ctl()
    for bad in ("../data", "..", "/etc", "odyssey1-mars/../odyssey1-moon", "nope", "", None, 5):
        r = client.post("/api/control/import", headers=h, json={"package": bad})
        assert r.status_code == 422 and r.json()["errors"][0]["field"] == "package", bad
    before = n_obs()
    r = client.post("/api/control/import", headers=h, json={"package": "odyssey1-mars"})
    assert r.status_code == 200 and r.json()["accepted"]["observations"] == 0 and n_obs() == before  # already loaded
    assert client.post("/api/control/import", headers=h, content=b"x").status_code == 415


def test_the_import_of_a_whole_package_is_fast(monkeypatch):
    monkeypatch.setattr(settings, "mission_package", "")
    client.post("/api/demo/reset")
    data._prepared_cache.clear()
    t = time.time()
    r = data.import_named("odyssey1-mars")
    assert time.time() - t < 5 and r["accepted"]["observations"] > 50000 and r["accepted"]["goal_log"] > 30000


# ---------------------------------------------------------------- reset, scenes, start-up
def test_reset_with_no_package_starts_empty(monkeypatch):
    monkeypatch.setattr(settings, "mission_package", "")
    assert client.post("/api/demo/reset").status_code == 200
    for t in ("observations", "space_events", "scenes", "goal_log"):
        assert db.q(f"SELECT COUNT(*) n FROM {t}")[0]["n"] == 0, t
    assert client.get("/api/scenes").json() == [] and data.table().obs == {}
    # a package named in the settings loads again on the next reset
    monkeypatch.setattr(settings, "mission_package", "odyssey1-mars")
    client.post("/api/demo/reset")
    assert n_obs() > 50000


def test_start_up_loads_the_package_once_and_only_when_empty(monkeypatch):
    monkeypatch.setattr(settings, "mission_package", "")
    client.post("/api/demo/reset")
    assert data.bootstrap() is None  # nothing configured: stays empty
    monkeypatch.setattr(settings, "mission_package", "odyssey1-mars")
    assert data.bootstrap()["accepted"]["observations"] > 50000
    n = n_obs()
    assert data.bootstrap() is None and n_obs() == n  # data present: nothing happens


def test_reset_loads_the_mars_package_and_the_scenes_are_the_demo_bookmarks():
    s = client.get("/api/scenes").json()
    assert len(s) == 6 and [x["index"] for x in s] == list(range(6))
    assert [(x["day"], x["location"], x["person"]) for x in s] == [(st["day"], st["loc"], st["me"]) for st in simdata.load_demo_crew()["story"]]
    assert set(s[0]) == {"index", "day", "location", "person", "storm", "when", "text"} and s[0]["storm"] is None
    assert [e["id"] for e in data.events()] == ["replay-2024-05-10-sep", "replay-2024-05-20-rad"] and data.events()[0]["locations"] == ["transit", "moon"]
    assert data.mission_time() == "12:00" and data.loaded_package() == {"name": "odyssey1-mars", "preset": "mars", "bundled": True}


def test_old_databases_gain_the_goal_time_column(tmp_path):
    f = tmp_path / "old.db"
    c = sqlite3.connect(f)
    c.execute("CREATE TABLE goal_log (crew_id TEXT NOT NULL, day INTEGER NOT NULL, goal_id TEXT NOT NULL, done INTEGER NOT NULL, "
              "updated_at REAL NOT NULL, PRIMARY KEY (crew_id, day, goal_id))")
    c.execute("INSERT INTO goal_log VALUES('h',1,'water',1,5)")
    c.commit()
    c.close()
    old = db._conn
    try:
        conn = db.connect(str(f))
        assert "done_at_time" in [r[1] for r in conn.execute("PRAGMA table_info(goal_log)")]
        assert conn.execute("SELECT done_at_time FROM goal_log").fetchone()[0] is None
        assert goals.is_done("h", "water", 1, 1) is True  # a row without a time counts
    finally:
        db._conn = old
        db._forget()
        db._bump_epoch()


# ---------------------------------------------------------------- the goal log
def test_a_goal_row_counts_on_past_days_and_on_today_only_once_its_time_has_come():
    log = {(5, "water"): (1, "18:30"), (6, "water"): (1, "11:59"), (6, "sleep"): (1, "12:00"), (6, "mood"): (1, "12:01"),
           (6, "exercise"): (0, "08:00"), (6, "window"): (1, None)}
    d = lambda gid, day, today: goals.is_done("h", gid, day, today, log, "12:00")  # noqa: E731
    assert d("water", 5, 6) is True and d("water", 5, 5) is False   # a late row counts once the day is past
    assert d("water", 6, 6) is True and d("sleep", 6, 6) is True    # at or before the mission time
    assert d("mood", 6, 6) is False and d("mood", 6, 7) is True
    assert d("exercise", 6, 7) is False                             # done=0: not done, whatever the time
    assert d("window", 6, 6) is True and d("home", 6, 6) is False   # no time counts; no row is not done


def test_a_goal_ticked_in_the_app_counts_at_once_with_the_mission_time():
    client.put("/api/mission", json={"step": 2})
    day = client.get("/api/mission").json()["day"]
    gid = next(g["id"] for g in client.get("/api/goals/h", headers=me()).json()["personal"] if not g["done"] and g["by"] == "routine")
    assert client.post(f"/api/goals/h/{gid}", headers=me(), json={"done": True}).status_code == 200
    row = db.q("SELECT done,done_at_time,updated_at FROM goal_log WHERE crew_id='h' AND day=? AND goal_id=?", (day, gid))[0]
    assert row["done"] == 1 and row["done_at_time"] == "12:00" and row["updated_at"] > 0
    assert next(g for g in client.get("/api/goals/h", headers=me()).json()["personal"] if g["id"] == gid)["done"] is True


# ---------------------------------------------------------------- changing the plan
def test_changing_to_a_preset_reloads_its_package_and_keeps_what_the_crew_did():
    client.put("/api/mission", json={"step": 2})
    day = client.get("/api/mission").json()["day"]
    gid = next(g["id"] for g in client.get("/api/goals/h", headers=me()).json()["personal"] if not g["done"] and g["by"] == "routine")
    client.post(f"/api/goals/h/{gid}", headers=me(), json={"done": True})
    client.post("/api/checkins", headers=me(), json={"crew_id": "h", "kind": "mood", "payload": {"mood": 4, "stress": 2}})
    mars_n = n_obs()
    assert client.post("/api/plan/preset", json={"preset": "moon"}).status_code == 200
    moon_rows = list(csv.DictReader(open(ROOT / "data" / "missions" / "odyssey1-moon" / "observations.csv", encoding="utf-8")))
    assert n_obs() == len(moon_rows) != mars_n and data.loaded_package()["preset"] == "moon"
    assert db.q("SELECT COUNT(*) n FROM goal_log WHERE updated_at=0")[0]["n"] > 1000
    assert db.q("SELECT COUNT(*) n FROM goal_log WHERE crew_id='h' AND day=? AND goal_id=? AND updated_at>0", (day, gid))[0]["n"] == 1
    assert db.q("SELECT COUNT(*) n FROM checkins WHERE crew_id='h'")[0]["n"] == 1
    assert [e["id"] for e in data.events()] == ["replay-2024-05-10-sep", "replay-2024-05-20-rad"]
    assert client.post("/api/plan/preset", json={"preset": "mars"}).status_code == 200 and n_obs() == mars_n


def test_a_custom_plan_does_not_change_the_data():
    before = (n_obs(), data.version())
    custom = {"name": "Short hop", "legs": [{"location": "earth", "start": -30, "end": -1}, {"location": "rocket", "start": 0, "end": 2},
                                            {"location": "moon", "start": 3, "end": 40}]}
    assert client.put("/api/plan", json=custom).status_code == 200
    assert (n_obs(), data.version()) == before


# ---------------------------------------------------------------- space events and the control session
def test_the_control_endpoints_need_the_control_session():
    ev = {"kind": "sep", "start_day": 10, "end_day": 11, "locations": ["transit"], "extra_dose_msv": 5}
    for h in ({}, {"X-Canary-Control": "control.1.abc"}, me()):
        assert client.get("/api/control/space-events", headers=h).status_code == 401
        assert client.post("/api/control/space-events", headers=h, json=ev).status_code == 401
        assert client.post("/api/control/import", headers=h, json={"package": "odyssey1-mars"}).status_code == 401
    assert client.get("/api/control/space-events", headers=key()).status_code == 401  # the ingest key is not a control session
    assert [e["id"] for e in client.get("/api/control/space-events", headers=ctl()).json()["events"]] == ["replay-2024-05-10-sep", "replay-2024-05-20-rad"]


def test_a_space_event_is_validated_stored_and_listed():
    h = ctl()
    ok = {"kind": "sep", "start_day": 10, "end_day": 12, "locations": ["transit", "moon"], "extra_dose_msv": 5, "note": "test"}
    r = client.post("/api/control/space-events", headers=h, json=ok)
    assert r.status_code == 200
    e = r.json()
    assert e["id"].startswith("ev_") and e["locations"] == ["transit", "moon"] and e["origin"] == "simulated" and e["extra_dose_msv"] == 5
    assert e in client.get("/api/control/space-events", headers=h).json()["events"]
    again = client.post("/api/control/space-events", headers=h, json={**ok, "id": "mine", "end_day": 10}).json()
    assert again["id"] == "mine" and again["end_day"] == 10
    n = len(data.events())
    for patch, field in (({"end_day": 9}, "event.end_day"), ({"locations": ["mars_base"]}, "event.locations"), ({"locations": []}, "event.locations"),
                         ({"extra_dose_msv": 2001}, "event.extra_dose_msv"), ({"extra_dose_msv": -1}, "event.extra_dose_msv"),
                         ({"kind": "party"}, "event.kind"), ({"kind": "storm"}, "event.kind"), ({"start_day": None}, "event.start_day"), ({"id": "a b"}, "event.id"),
                         ({"origin": "dream"}, "event.origin")):
        r = client.post("/api/control/space-events", headers=h, json={**ok, **patch})
        assert r.status_code == 422 and fields(r) == [field], (patch, r.text)
    assert len(data.events()) == n


def test_the_engine_no_longer_reads_the_file_or_generates_rows():
    import inspect
    src = inspect.getsource(telemetry)
    assert "OBS_FILE" not in src and "Generator" not in src and "read_csv" not in src
    assert not hasattr(goals, "_sim_done")


# ---------------------------------------------------------------- GET /api/control/data-status (Mission Control sees counts and dates, never values)
def _keys(x):
    if isinstance(x, dict):
        for k, v in x.items():
            yield k
            yield from _keys(v)
    elif isinstance(x, list):
        for v in x:
            yield from _keys(v)


def test_data_status_needs_the_control_session():
    assert client.get("/api/control/data-status").status_code == 401
    assert client.get("/api/control/data-status", headers=me()).status_code == 401


def test_data_status_has_counts_and_dates_but_no_values_and_no_health():
    r = client.get("/api/control/data-status", headers=ctl())
    assert r.status_code == 200
    body = r.json()
    assert body["ingest_configured"] is True and body["package"] == "odyssey1-mars"
    assert set(body["counts"]) == {"observations", "goal_entries", "events", "scenes"}
    assert body["counts"]["observations"] > 0 and body["readings"]
    assert set(body["readings"][0]) == {"crew_id", "indicator", "last_day", "last_received_at", "count"}
    forbidden = {"value", "values", "baseline", "z", "bad", "level", "status", "alerts", "risks", "systems", "areas", "delta", "trend"}
    assert not (set(_keys(body)) & forbidden)
    assert KEY not in r.text and "ingest_key" not in r.text


def test_data_status_never_shows_the_key_when_ingest_is_off(monkeypatch):
    monkeypatch.setattr(settings, "ingest_key", "")
    body = client.get("/api/control/data-status", headers=ctl()).json()
    assert body["ingest_configured"] is False
