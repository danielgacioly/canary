"""The data layer: the one place the engine reads measurements from, and the one place every entry point writes them.

What lives here
- `observations`: one row per measurement (crew id or `cabin`, indicator, value, unit, origin, method, source,
  measured_at). The in-memory `simdata.Table` the engine searches ("last value up to day D") is built from this table
  and rebuilt only when a write bumped the data version.
- `space_events`: storms and other space-weather events, with the extra dose they add.
- `scenes`: the guided demo's bookmarks (a day, a place, a person and a sentence).
- the goal history (`goal_log`, written here only by a package import; the app writes its own ticks in goals.py).

Every way in goes through the functions of this module and nothing else writes these tables:
`add_observations` (POST /api/observations), `add_space_event` (POST /api/control/space-events), `import_package`
(POST /api/control/import, POST /api/demo/reset, scripts/load_mission.py) and `reload_for_preset` (changing the plan to
a preset while a bundled package is loaded). All of them validate everything first and write in one transaction, so a bad
row writes nothing.

A mission package is a folder of CSV files (see data/missions/odyssey1-mars/README.md): mission.csv, legs.csv, crew.csv,
observations.csv, space_events.csv, goal_log.csv and scenes.csv. Any subset can be imported.
"""
import csv
import io
import json
import pathlib
import re
import time
import uuid
import zipfile
from contextlib import contextmanager
from datetime import date, datetime, timezone
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple, Union

from .. import auth, db
from ..config import settings
from . import catalog, plan, registry, simdata
from . import validation as V
from .validation import FieldError, ValidationFailure

PACKAGE_FILES = ("mission.csv", "legs.csv", "crew.csv", "observations.csv", "space_events.csv", "goal_log.csv", "scenes.csv")
DEFAULT_MISSION_TIME = "12:00"
# What a space event is. "sep": a solar particle event in space (it reaches a crew away from Earth). "mars": a radiation
# storm at the Mars surface (the crew waits it out indoors). The kind carries the meaning; the id is only a name.
EVENT_KINDS = ("sep", "mars")
EVENT_ORIGINS = ("real", "simulated", "donki")  # donki: imported from NASA DONKI while the clock runs on the real date
EVENT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,39}$")
PACKAGE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
BLOOD_TYPES = ["O−", "O+", "A−", "A+", "B−", "B+", "AB−", "AB+"]
MAX_UPLOAD_BYTES = 120_000_000
CONTROL_EVENT_PREFIX = "ev_"  # events made through the API; a preset reload keeps them
LAUNCH_YEARS = (2025, 2100)


# ---------------------------------------------------------------- the data version and the in-memory table
_state: Dict[str, Any] = {"epoch": -1, "version": 0, "key": None, "table": None}


def version() -> int:
    """Counter bumped by every write to observations, space_events or scenes. Cheap: read from memory."""
    if _state["epoch"] != db.epoch:  # a new connection or a reset: start from what the database says
        _state.update(epoch=db.epoch, version=int(db.get_setting("data_version", 0)), key=None, table=None)
    return _state["version"]


def token() -> tuple:
    """Hashable stamp of the stored data: put it in any cache key that depends on a measurement."""
    return (db.epoch, version())


def table() -> simdata.Table:
    """The observation table, rebuilt from the database only when the data version changed."""
    key = token()
    if _state["key"] != key:
        with db._lock:
            rows = db.connect().execute(
                "SELECT crew_id,day,indicator,value,unit,origin,method,source,note FROM observations ORDER BY day, measured_at, id").fetchall()
        _state.update(key=key, table=simdata.Table(rows))
    return _state["table"]


def count_observations() -> int:
    return db.q("SELECT COUNT(*) n FROM observations")[0]["n"]


@contextmanager
def _transaction():
    """One SQLite transaction on the shared connection. Commits and bumps the data version on success; rolls back on error."""
    with db._lock:
        c = db.connect()
        try:
            yield c
            _set(c, "data_version", version() + 1)
            c.commit()
            _state["version"] += 1
        except BaseException:
            c.rollback()
            raise
        finally:
            db._forget()


def _set(c, key: str, value: Any) -> None:
    c.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, json.dumps(value)))


# ---------------------------------------------------------------- reads used by the engine
def last(crew_id: str, ind: str, day: int) -> Optional[dict]:
    """Last measurement of `ind` up to `day` with its age in days, origin, method, source and note; None if there is none."""
    return table().last(crew_id, ind, day)


def first(crew_id: str, ind: str) -> Optional[float]:
    return table().first(crew_id, ind)


def rows_between(crew_id: str, ind: str, d0: int, d1: int) -> Dict[int, float]:
    """Stored measurements on days d0..d1, by day (the last one of a day wins)."""
    return {d: v for (d, v, *_rest) in table().obs.get((crew_id, ind), []) if d0 <= d <= d1}


_cache: Dict[str, Any] = {"key": None, "events": [], "scenes": []}


def _load() -> None:
    """Space events and scenes are small tables read on every request: keep them until the data version changes."""
    key = token()
    if _cache["key"] != key:
        rows = db.q("SELECT * FROM space_events ORDER BY start_day, id")
        ev = [{**r, "locations": [x for x in r["locations"].split(";") if x]} for r in rows]
        sc = [{"index": r["idx"], "day": r["day"], "location": r["location"], "person": r["person"], "storm": r["storm"] or None,
               "when": r["when_label"], "text": r["text"]} for r in db.q("SELECT * FROM scenes ORDER BY idx")]
        _cache.update(key=key, events=ev, scenes=sc)


def events() -> List[dict]:
    _load()
    return [dict(e) for e in _cache["events"]]


def scenes() -> List[dict]:
    _load()
    return [dict(s) for s in _cache["scenes"]]


def event(event_id: Optional[str]) -> Optional[dict]:
    """One space event by id (what `storm_at` returns), or None."""
    _load()
    return next((dict(e) for e in _cache["events"] if e["id"] == event_id), None) if event_id else None


def _hits(e: dict, location: str) -> bool:
    return location in e["locations"]


def storm_event(day: int, location: str) -> Optional[dict]:
    """The radiation storm (a space event) active on `day` at `location`, or None. The first one when several overlap."""
    _load()
    for e in _cache["events"]:
        if e["start_day"] <= day <= e["end_day"] and _hits(e, location):
            return dict(e)
    return None


def storm_at(day: int, location: str) -> Optional[str]:
    """The kind ("sep" or "mars") of the storm active on `day` at `location`, or None. This is what `mission.state()["storm"]`
    carries: what kind of storm it is, never an event id."""
    e = storm_event(day, location)
    return e["kind"] if e else None


def storms_following(day: int, follow_days: int, kinds: Sequence[str] = ("sep",)) -> List[dict]:
    """Storms of one of `kinds` that hit the place of the plan on their start day and started at most `follow_days` before
    `day` (the day they start counts). Used for the blood-count follow-up: a particle storm in space calls for one, a
    surface storm the crew waits out indoors does not (the kind says which, not the dose)."""
    _load()
    return [dict(e) for e in _cache["events"]
            if e["kind"] in kinds and e["start_day"] <= day <= e["start_day"] + follow_days
            and _hits(e, plan.location_at(e["start_day"]))]


def extra_dose(day: int) -> float:
    """The `extra_dose_msv` of the events that start on `day` and hit the place of the plan that day."""
    _load()
    loc = plan.location_at(day)
    return sum(e["extra_dose_msv"] for e in _cache["events"] if e["start_day"] == day and _hits(e, loc))


def daily(crew_id: str, ind: str, d0: int, d1: int) -> Dict[int, Tuple[float, str]]:
    """Stored measurements on days d0..d1, by day, as (value, origin); the last one of a day wins."""
    return {d: (v, origin) for (d, v, origin, *_rest) in table().obs.get((crew_id, ind), []) if d0 <= d <= d1}


def mission_time() -> str:
    """The time of day of the simulated 'now' (from the mission package; 12:00 when there is none)."""
    return db.get_setting("mission_time", DEFAULT_MISSION_TIME)


def loaded_package() -> Optional[dict]:
    return db.get_setting("package")


# ---------------------------------------------------------------- observations (POST /api/observations)
def _obs_context() -> V.ObsContext:
    return V.ObsContext([c["id"] for c in catalog.CREW], registry.launch_date())


def add_observations(rows: Any) -> dict:
    """Store a batch of measurements. Validates every row first; one bad row stores nothing (ValidationFailure).
    A reading already stored (same person, indicator, time and source) is not stored twice. Returns the counts."""
    good = V.observation_rows(rows, _obs_context())
    with _transaction() as c:
        accepted = _insert_observations(c, good)
    return {"accepted": accepted, "duplicates": len(good) - accepted}


def _insert_observations(c, good: Sequence[tuple]) -> int:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    before = c.total_changes
    c.executemany("INSERT OR IGNORE INTO observations(crew_id,day,indicator,value,unit,origin,method,source,note,measured_at,received_at) "
                  "VALUES(?,?,?,?,?,?,?,?,?,?,?)", ((*r, now) for r in good))
    return c.total_changes - before


# ---------------------------------------------------------------- space events (POST /api/control/space-events)
def _event_row(i: int, raw: Any, prefix: str = "event") -> tuple:
    p = f"{prefix}" if prefix == "event" else f"{prefix}.{i}"
    if not isinstance(raw, dict):
        raise FieldError(p, "An event must be an object")
    g = lambda k: f"{p}.{k}"  # noqa: E731
    eid = raw.get("id")
    if eid in (None, ""):
        eid = CONTROL_EVENT_PREFIX + uuid.uuid4().hex[:10]
    elif not isinstance(eid, str) or not EVENT_ID.match(eid):
        raise FieldError(g("id"), "id must be 1 to 40 letters, digits, dots, dashes or underscores")
    kind = V.one_of(raw, "kind", "kind", EVENT_KINDS, required=True, field=g("kind"))
    start = V.number(raw, "start_day", "start_day", -3650, 36500, integer=True, required=True, field=g("start_day"))
    end = raw.get("end_day")
    end = start if end in (None, "") else V.number(raw, "end_day", "end_day", -3650, 36500, integer=True, required=True, field=g("end_day"))
    if end < start:
        raise FieldError(g("end_day"), "end_day must not be before start_day")
    locs = raw.get("locations")
    if isinstance(locs, str):
        locs = [x.strip() for x in locs.split(";")]
    if not isinstance(locs, list) or not locs or not all(isinstance(x, str) for x in locs):
        raise FieldError(g("locations"), "locations must list at least one place")
    locs = [x for x in locs if x]
    unknown = [x for x in locs if x not in catalog.LOCATIONS]
    if not locs or unknown:
        raise FieldError(g("locations"), "Unknown place: " + ", ".join(unknown) if unknown else "locations must list at least one place")
    extra = raw.get("extra_dose_msv")
    extra = 0 if extra in (None, "") else V.number(raw, "extra_dose_msv", "Extra dose", 0, 2000, "mSv", required=True, field=g("extra_dose_msv"))
    origin = V.one_of({"origin": raw.get("origin") or "simulated"}, "origin", "origin", EVENT_ORIGINS, field=g("origin"))
    src = V.text({"source": raw.get("source") or "control"}, "source", "source", max_len=80, field=g("source"))
    note = V.text({"note": raw.get("note") or ""}, "note", "note", max_len=200, field=g("note"))
    return (eid, kind, int(start), int(end), ";".join(dict.fromkeys(locs)), float(extra), origin, src, note)


def _event_dict(t: tuple) -> dict:
    return {"id": t[0], "kind": t[1], "start_day": t[2], "end_day": t[3], "locations": t[4].split(";"), "extra_dose_msv": t[5],
            "origin": t[6], "source": t[7], "note": t[8]}


def add_space_event(raw: Any) -> dict:
    """Store one space-weather event (an event with the same id is replaced). Returns it as stored."""
    row = _event_row(0, raw)
    with _transaction() as c:
        c.execute("INSERT OR REPLACE INTO space_events(id,kind,start_day,end_day,locations,extra_dose_msv,origin,source,note) VALUES(?,?,?,?,?,?,?,?,?)", row)
    return _event_dict(row)


# ---------------------------------------------------------------- package files -> validated rows
def _csv_rows(text: str) -> List[dict]:
    return list(csv.DictReader(io.StringIO(text, newline="")))


def _need(fname: str, rows: List[dict], cols: Iterable[str]) -> None:
    have = set(rows[0].keys()) if rows else set()
    if rows and not set(cols) <= have:
        raise ValidationFailure([{"field": f"{fname}", "message": f"{fname} is missing the column(s): " + ", ".join(sorted(set(cols) - have))}])


def _num(s: Any) -> Any:
    """A CSV cell as a number when it is one (int stays int), else the text unchanged."""
    if isinstance(s, str):
        t = s.strip()
        if re.fullmatch(r"-?\d+", t):
            return int(t)
        try:
            return float(t)
        except ValueError:
            return s
    return s


def _lines(rows: List[dict], i: int) -> str:
    return f"line {i + 2}"


def _mission_file(rows: List[dict]) -> dict:
    f = "mission.csv"
    if len(rows) != 1:
        raise ValidationFailure([{"field": "mission", "message": f"{f} must have exactly one row"}])
    r = rows[0]
    _need(f, rows, ("callsign", "name", "launch_date", "preset"))
    try:
        callsign = V.text(r, "callsign", "callsign", 2, 24, True, field="mission.callsign").strip()
        name = V.text(r, "name", "name", 2, 80, True, field="mission.name").strip()
        launch = V.text(r, "launch_date", "launch_date", 10, 10, True, field="mission.launch_date")
        d = V.parse_date(launch, "launch_date", "mission.launch_date")
        if not LAUNCH_YEARS[0] <= d.year <= LAUNCH_YEARS[1]:
            raise FieldError("mission.launch_date", f"launch_date must be between {LAUNCH_YEARS[0]} and {LAUNCH_YEARS[1]}")
        preset = V.one_of(r, "preset", "preset", list(plan.PRESETS), required=True, field="mission.preset")
        mt = (r.get("simulated_time") or DEFAULT_MISSION_TIME).strip()
        mt = V.clock_time(mt, "mission.simulated_time")
        sim = (r.get("simulated_today") or "").strip()
        if sim:  # the mission date the clock starts on; empty: the clock follows the real date
            sd = V.parse_date(sim, "simulated_today", "mission.simulated_today")
            if not LAUNCH_YEARS[0] <= sd.year <= LAUNCH_YEARS[1] + 10:
                raise FieldError("mission.simulated_today", "simulated_today must be a date near the mission")
    except FieldError as e:
        raise ValidationFailure([{"field": e.field, "message": f"{f}: {e.message}"}])
    return {"callsign": callsign, "name": name, "launch_date": launch, "preset": preset, "simulated_time": mt,
            "simulated_today": sim or None}


def _legs_file(rows: List[dict], name: str) -> dict:
    f = "legs.csv"
    _need(f, rows, ("start_day", "end_day", "location"))
    legs = []
    for i, r in enumerate(rows):
        s, e = _num(r.get("start_day")), _num(r.get("end_day"))
        for k, v in (("start_day", s), ("end_day", e)):
            if not isinstance(v, int):
                raise ValidationFailure([{"field": f"legs.{i}.{k}", "message": f"{f}: {k} must be a whole number ({_lines(rows, i)})"}])
        legs.append({"location": r.get("location"), "start": s, "end": e, "label": r.get("label") or ""})
    try:
        return plan.validate(name, legs)
    except ValueError as ex:
        raise ValidationFailure([{"field": "legs", "message": f"{f}: {ex}"}])


def _list(v: Any) -> List[str]:
    return [x.strip() for x in str(v or "").split(";") if x.strip()]


def _crew_file(rows: List[dict]) -> Tuple[List[dict], Dict[str, str]]:
    f = "crew.csv"
    _need(f, rows, ("id", "name", "role", "pin"))
    people, pins, errs = [], {}, []
    seen = set()
    for i, r in enumerate(rows):
        g = lambda k: f"crew.{i}.{k}"  # noqa: E731
        try:
            seat = V.one_of(r, "id", "id", registry.SEATS, required=True, field=g("id"))
            if seat in seen:
                raise FieldError(g("id"), f"seat {seat} appears twice")
            seen.add(seat)
            p: Dict[str, Any] = {"seat": seat,
                                 "name": V.text(r, "name", "Name", 2, 60, True, field=g("name")).strip(),
                                 "role": V.text(r, "role", "Role", 2, 60, True, field=g("role")).strip(),
                                 "home": V.text(r, "home", "Home", 0, 80, field=g("home")).strip()}
            dob = V.text(r, "dob", "dob", 10, 10, True, field=g("dob"))
            V.parse_date(dob, "dob", g("dob"))
            p["dob"] = dob
            p["sex"] = V.one_of(r, "sex", "sex", ("", "Female", "Male", "Other"), field=g("sex")) or ""
            for k in ("nationality", "agency"):
                p[k] = V.text(r, k, k, 0, 80, field=g(k)).strip()
            p["languages"] = _list(r.get("languages"))
            n = {k: (None if str(r.get(k) or "").strip() == "" else _num(r.get(k)))
                 for k in ("flights", "days_in_space", "height_cm", "weight_kg", "prior_dose_msv")}
            p["flights"] = int(V.number(n, "flights", "flights", 0, 20, integer=True, required=True, field=g("flights")))
            p["days_in_space"] = int(V.number(n, "days_in_space", "days_in_space", 0, 1000, integer=True, required=True, field=g("days_in_space")))
            p["height_cm"] = V.number(n, "height_cm", "height_cm", 140, 210, "cm", required=True, field=g("height_cm"))
            p["weight_kg"] = V.number(n, "weight_kg", "weight_kg", 40, 150, "kg", required=True, field=g("weight_kg"))
            bt = r.get("blood_type") or ""
            if bt and bt not in BLOOD_TYPES:
                raise FieldError(g("blood_type"), "blood_type must be one of: " + ", ".join(BLOOD_TYPES))
            p["blood_type"] = bt
            p["skin_type"] = V.one_of(r, "skin_type", "skin_type", ("I", "II", "III", "IV", "V", "VI"), required=True, field=g("skin_type"))
            p["handedness"] = V.one_of(r, "handedness", "handedness", ("Right", "Left"), required=True, field=g("handedness"))
            for k in ("vision",):
                p[k] = V.text(r, k, k, 0, 80, field=g(k))
            for k in ("allergies", "medications", "conditions"):
                p[k] = _list(r.get(k))
            p["diet"] = V.text(r, "diet", "diet", 0, 120, field=g("diet"))
            p["vaccinations"] = V.text(r, "vaccinations", "vaccinations", 0, 200, field=g("vaccinations"))
            p["emergency_contact"] = V.text(r, "emergency_contact", "emergency_contact", 0, 200, field=g("emergency_contact"))
            p["eva"] = V.one_of(r, "eva", "eva", ("surface", "microgravity", "none"), field=g("eva")) or None
            prior = V.number(n, "prior_dose_msv", "prior_dose_msv", 0, 600, "mSv", field=g("prior_dose_msv"))
            if prior is not None:  # empty: the app estimates it from days in space
                p["prior_dose_msv"] = prior
            pin = r.get("pin") or ""
            if not auth.valid_pin(pin):
                raise FieldError(g("pin"), "pin must be exactly 4 digits")
            if pin in pins.values():
                raise FieldError(g("pin"), "each seat needs its own pin")
            pins[seat] = pin
            people.append(p)
        except FieldError as e:
            errs.append({"field": e.field, "message": f"{f}: {e.message} ({_lines(rows, i)})"})
    if errs:
        raise ValidationFailure(errs)
    if rows and sorted(seen) != sorted(registry.SEATS):
        raise ValidationFailure([{"field": "crew", "message": f"{f}: register each of the four seats once ({', '.join(registry.SEATS)})"}])
    return people, pins


def _observations_file(rows: List[dict], ctx: V.ObsContext) -> List[tuple]:
    _need("observations.csv", rows, ("crew_id", "indicator", "value", "unit"))
    try:
        return V.observation_rows(rows, ctx, "observations", "observations.csv")
    except ValidationFailure as e:
        raise ValidationFailure([{"field": x["field"], "message": x["message"] + f" (line {int(x['field'].split('.')[1]) + 2})"} for x in e.errors])


def _events_file(rows: List[dict]) -> List[tuple]:
    f = "space_events.csv"
    _need(f, rows, ("id", "kind", "start_day", "end_day", "locations"))
    out, errs, ids = [], [], set()
    for i, r in enumerate(rows):
        try:
            r = {**r, **{k: _num(r.get(k)) for k in ("start_day", "end_day", "extra_dose_msv")}}
            t = _event_row(i, r, "space_events")
            if t[0] in ids:
                raise FieldError(f"space_events.{i}.id", f"id {t[0]} appears twice")
            ids.add(t[0])
            out.append(t)
        except FieldError as e:
            errs.append({"field": e.field, "message": f"{f}: {e.message} ({_lines(rows, i)})"})
    if errs:
        raise ValidationFailure(errs)
    return out


def _goal_file(rows: List[dict], crew_ids: set) -> List[tuple]:
    f = "goal_log.csv"
    _need(f, rows, ("crew_id", "day", "goal_id", "done"))
    out, errs = [], []
    for i, r in enumerate(rows):
        try:
            g = lambda k: f"goal_log.{i}.{k}"  # noqa: E731
            if r.get("crew_id") not in crew_ids:
                raise FieldError(g("crew_id"), f"Unknown crew id: {r.get('crew_id')}")
            d = _num(r.get("day"))
            if not isinstance(d, int) or not -3650 <= d <= 36500:
                raise FieldError(g("day"), "day must be a whole number")
            gid = r.get("goal_id") or ""
            if not gid or len(gid) > 40:
                raise FieldError(g("goal_id"), "goal_id is required")
            done = _num(r.get("done"))
            if done not in (0, 1):
                raise FieldError(g("done"), "done must be 0 or 1")
            t = (r.get("done_at_time") or "").strip() or None
            if t is not None:
                V.clock_time(t, g("done_at_time"))
            out.append((r["crew_id"], d, gid, done, t))
        except FieldError as e:
            errs.append({"field": e.field, "message": f"{f}: {e.message} ({_lines(rows, i)})"})
            if len(errs) >= V.MAX_ERRORS:
                break
    if errs:
        raise ValidationFailure(errs)
    return out


def _scenes_file(rows: List[dict]) -> List[tuple]:
    f = "scenes.csv"
    _need(f, rows, ("index", "day", "location", "person", "when", "text"))
    out, errs, seen = [], [], set()
    for i, r in enumerate(rows):
        try:
            g = lambda k: f"scenes.{i}.{k}"  # noqa: E731
            idx, day = _num(r.get("index")), _num(r.get("day"))
            if not isinstance(idx, int) or idx < 0 or idx in seen:
                raise FieldError(g("index"), "index must be a whole number, once per scene")
            seen.add(idx)
            if not isinstance(day, int):
                raise FieldError(g("day"), "day must be a whole number")
            loc = r.get("location")
            if loc not in catalog.LOCATIONS:
                raise FieldError(g("location"), f"Unknown place: {loc}")
            text = V.text(r, "text", "text", 1, 600, True, field=g("text"))
            out.append((idx, day, loc, r.get("person") or "", r.get("storm") or "", V.text(r, "when", "when", 0, 80, field=g("when")), text))
        except FieldError as e:
            errs.append({"field": e.field, "message": f"{f}: {e.message} ({_lines(rows, i)})"})
    if errs:
        raise ValidationFailure(errs)
    return out


# ---------------------------------------------------------------- prepare (validate) a whole package, then write it
Source = Union[str, pathlib.Path, Mapping[str, bytes]]
_prepared_cache: Dict[tuple, dict] = {}


def _read_files(source: Source) -> Tuple[Dict[str, str], Optional[tuple]]:
    """The package files as text, and a cache key (a folder is cached by file sizes and times; uploads are not)."""
    if isinstance(source, Mapping):
        out = {}
        for name, raw in source.items():
            try:
                out[name] = raw.decode("utf-8-sig") if isinstance(raw, (bytes, bytearray)) else str(raw)
            except UnicodeDecodeError:
                raise ValidationFailure([{"field": name, "message": f"{name} must be UTF-8 text"}])
        return out, None
    folder = pathlib.Path(source)
    if not folder.is_dir():
        raise ValidationFailure([{"field": "package", "message": f"Not a folder: {folder.name}"}])
    out, key = {}, [str(folder.resolve())]
    for name in PACKAGE_FILES:
        f = folder / name
        if f.is_file():
            st = f.stat()
            key.append((name, st.st_size, st.st_mtime_ns))
            out[name] = None  # read below, only when the key misses the cache
    key_t = tuple(key)
    if key_t in _prepared_cache:
        return out, key_t
    for name in list(out):
        out[name] = (folder / name).read_text(encoding="utf-8-sig")
    return out, key_t


def prepare(source: Source) -> dict:
    """Parse and validate every file of a package without touching the database. Raises ValidationFailure listing what
    is wrong (file, row and field); returns the rows ready to write otherwise."""
    files, key = _read_files(source)
    if key is not None and key in _prepared_cache:
        return _prepared_cache[key]
    unknown = [n for n in files if n not in PACKAGE_FILES]
    if unknown or not files:
        raise ValidationFailure([{"field": "package", "message": ("Unknown file: " + ", ".join(unknown) + ". ") if unknown else "No files. "
                                  + "A package has: " + ", ".join(PACKAGE_FILES)}])
    errs: List[dict] = []

    def run(fn, *a):
        try:
            return fn(*a)
        except ValidationFailure as e:
            errs.extend(e.errors)
            return None

    parsed = {n: _csv_rows(t) for n, t in files.items()}
    out: Dict[str, Any] = {"mission": None, "plan": None, "crew": None, "pins": {}, "observations": [], "space_events": [],
                           "goal_log": [], "scenes": [], "present": sorted(files)}
    if "mission.csv" in parsed:
        out["mission"] = run(_mission_file, parsed["mission.csv"])
    cur = registry.mission_info() or registry.DEMO_MISSION
    mname = (out["mission"] or {}).get("name") or cur.get("name") or "Mission plan"
    if "legs.csv" in parsed:
        out["plan"] = run(_legs_file, parsed["legs.csv"], mname)
    if "crew.csv" in parsed:
        r = run(_crew_file, parsed["crew.csv"])
        if r:
            out["crew"], out["pins"] = r
    crew_ids = {p["seat"] for p in out["crew"]} if out["crew"] else {c["id"] for c in catalog.CREW}
    launch = (out["mission"] or {}).get("launch_date") or cur["launch_date"]
    if "observations.csv" in parsed:
        out["observations"] = run(_observations_file, parsed["observations.csv"], V.ObsContext(crew_ids, launch)) or []
    if "space_events.csv" in parsed:
        out["space_events"] = run(_events_file, parsed["space_events.csv"]) or []
    if "goal_log.csv" in parsed:
        out["goal_log"] = run(_goal_file, parsed["goal_log.csv"], crew_ids | {catalog.CABIN_ID}) or []
    if "scenes.csv" in parsed:
        out["scenes"] = run(_scenes_file, parsed["scenes.csv"]) or []
    if out["mission"] and "crew.csv" not in parsed and registry.stored() is None:
        errs.append({"field": "mission", "message": "mission.csv needs crew.csv too while no crew is registered"})
    if errs:
        raise ValidationFailure(errs[:V.MAX_ERRORS])
    if key is not None and "crew.csv" in files and "mission.csv" in files:
        _prepared_cache.clear()  # one package at a time is plenty: they are tens of MB of tuples
        _prepared_cache[key] = out
    return out


def _counts(p: dict, accepted_obs: int) -> dict:
    return {"accepted": {"mission": 1 if p["mission"] else 0, "legs": len(p["plan"]["legs"]) if p["plan"] else 0,
                         "crew": len(p["crew"] or []), "observations": accepted_obs, "space_events": len(p["space_events"]),
                         "goal_log": len(p["goal_log"]), "scenes": len(p["scenes"])},
            "duplicates": {"observations": len(p["observations"]) - accepted_obs}}


def import_package(source: Source, name: Optional[str] = None, bundled: bool = False) -> dict:
    """Load a mission package (a folder, or a dict of file name -> bytes) into the database. Everything is validated
    first; any error raises ValidationFailure and nothing is written. Returns {"accepted": {...}, "duplicates": {...}}.

    mission.csv sets the callsign, name and launch date (and the plan's preset), legs.csv the itinerary, crew.csv the
    registered crew and their PINs (the same registry Mission Control fills), the rest is data. Readings already stored
    are not stored twice. Imported goal-log rows never replace a goal the person ticked in the app."""
    p = prepare(source)
    pkg_name = name or (pathlib.Path(source).name if not isinstance(source, Mapping) else "upload")
    was_empty = count_observations() == 0
    with _transaction() as c:
        accepted = _write(c, p)
        if p["mission"] or p["observations"]:
            _set(c, "package", {"name": pkg_name, "preset": (p["mission"] or {}).get("preset") or (loaded_package() or {}).get("preset"),
                                "bundled": bool(bundled)})
    _after_settings(p)
    if was_empty and p["observations"] and accepted == len(p["observations"]):
        # The table holds exactly these rows: reuse the one built from them (a reset reloads the same package again and again).
        if "_table" not in p:
            p["_table"] = simdata.Table(p["observations"])
        _state.update(key=token(), table=p["_table"])
    return _counts(p, accepted)


def _write(c, p: dict) -> int:
    """Write a prepared package inside an open transaction. Returns how many observations were new."""
    if p["mission"]:
        m = p["mission"]
        legs = p["plan"]["legs"] if p["plan"] else plan.preset_legs(m["preset"])
        rover = any(plan.is_rover(l["location"]) for l in legs)
        _set(c, "plan", {**(p["plan"] or {"name": m["name"], "legs": legs}), "name": m["name"], "preset": m["preset"]})
        _set(c, "mission_time", m["simulated_time"])
        _set(c, "sim_date", m["simulated_today"])  # None: the clock follows the real date
        _set(c, "mission", {"scene": None, "location": None, "custom": False})
        if p["crew"] is None and registry.stored() is not None:
            r = registry.stored()
            _set(c, "registry", {**r, "mission": {k: m[k] for k in ("callsign", "name", "launch_date", "preset")} | {"rover": rover}})
    elif p["plan"]:
        cur = plan.get()
        _set(c, "plan", {**p["plan"], "preset": cur.get("preset")})
    if p["crew"]:
        m = p["mission"] or registry.mission_info() or registry.DEMO_MISSION
        legs = p["plan"]["legs"] if p["plan"] else plan.get()["legs"]
        rover = any(plan.is_rover(l["location"]) for l in legs)
        _set(c, "registry", {"crew": p["crew"], "mission": {k: m[k] for k in ("callsign", "name", "launch_date", "preset")} | {"rover": rover}})
        # A PIN that equals the configured default needs no stored hash (it is the same check, and PBKDF2 is slow on purpose).
        changed = {s: pin for s, pin in p["pins"].items() if pin != settings.crew_pins.get(s)}
        if changed:
            _set(c, "pins", auth.hashed_pins(changed))
    n = 0
    if p["observations"]:
        n = _insert_observations(c, p["observations"])
    if p["space_events"]:
        c.executemany("INSERT OR REPLACE INTO space_events(id,kind,start_day,end_day,locations,extra_dose_msv,origin,source,note) VALUES(?,?,?,?,?,?,?,?,?)", p["space_events"])
    if p["scenes"]:
        c.execute("DELETE FROM scenes")
        c.executemany("INSERT INTO scenes(idx,day,location,person,storm,when_label,text) VALUES(?,?,?,?,?,?,?)", p["scenes"])
    if p["goal_log"]:
        c.executemany("INSERT OR IGNORE INTO goal_log(crew_id,day,goal_id,done,updated_at,done_at_time) VALUES(?,?,?,?,0,?)", p["goal_log"])
    return n


def _after_settings(p: dict) -> None:
    """Refresh what is cached from settings (registered crew, plan) after a package wrote them."""
    plan.reset_cache()
    registry.load()


# ---------------------------------------------------------------- bundled packages by name, and the plan preset
def package_dir(name: str) -> pathlib.Path:
    """Folder of a bundled package (under data/missions). Only plain names that exist are accepted: no paths, no `..`."""
    if not isinstance(name, str) or not PACKAGE_NAME.match(name):
        raise ValidationFailure([{"field": "package", "message": "package must be the name of a bundled mission package"}])
    root = pathlib.Path(settings.missions_dir).resolve()
    d = (root / name).resolve()
    if d.parent != root or not d.is_dir():
        have = sorted(p.name for p in root.iterdir() if p.is_dir()) if root.is_dir() else []
        raise ValidationFailure([{"field": "package", "message": f"No mission package named {name}. Bundled: {', '.join(have) or 'none'}"}])
    return d


def import_named(name: str) -> dict:
    return import_package(package_dir(name), name=name, bundled=True)


def bootstrap() -> Optional[dict]:
    """First start: with no measurements and no registered crew, load the configured package once."""
    if settings.mission_package and count_observations() == 0 and registry.stored() is None:
        return import_named(settings.mission_package)
    return None


def reload_for_preset(preset: str) -> bool:
    """The plan changed to a preset while a bundled package is loaded: replace the observations, space events, scenes and
    package goal history with those of `odyssey1-<preset>`. Check-ins, goals ticked in the app, the registered crew and
    events made through the API stay. Returns True when data was reloaded."""
    pkg = loaded_package()
    if not pkg or not pkg.get("bundled") or pkg.get("preset") == preset:
        return False
    try:
        d = package_dir("-".join(pkg["name"].split("-")[:-1] + [preset]))
    except ValidationFailure:
        return False
    p = prepare(d)
    with _transaction() as c:
        c.execute("DELETE FROM observations")
        c.execute(f"DELETE FROM space_events WHERE id NOT LIKE '{CONTROL_EVENT_PREFIX}%'")
        c.execute("DELETE FROM scenes")
        c.execute("DELETE FROM goal_log WHERE updated_at=0")
        _write(c, {**p, "mission": None, "plan": None, "crew": None, "pins": {}})
        _set(c, "package", {**pkg, "name": d.name, "preset": preset})
    return True


# ---------------------------------------------------------------- uploads (zip, or CSV files)
def files_from_upload(items: Sequence[Tuple[str, bytes]]) -> Dict[str, bytes]:
    """Package files from an upload: one .zip, or several CSV files named like the package files."""
    if len(items) == 1 and items[0][0].lower().endswith(".zip"):
        try:
            z = zipfile.ZipFile(io.BytesIO(items[0][1]))
        except zipfile.BadZipFile:
            raise ValidationFailure([{"field": "file", "message": "The zip file is not readable"}])
        infos = [i for i in z.infolist() if not i.is_dir() and not i.filename.startswith("__MACOSX")]
        if sum(i.file_size for i in infos) > MAX_UPLOAD_BYTES * 2:
            raise ValidationFailure([{"field": "file", "message": "The zip file is too large"}])
        out = {}
        for i in infos:
            base = pathlib.PurePosixPath(i.filename).name
            if base in PACKAGE_FILES:
                out[base] = z.read(i)
        if not out:
            raise ValidationFailure([{"field": "file", "message": "The zip holds none of: " + ", ".join(PACKAGE_FILES)}])
        return out
    out, errs = {}, []
    for name, raw in items:
        base = pathlib.PurePosixPath(name.replace("\\", "/")).name
        if base not in PACKAGE_FILES:
            errs.append({"field": name or "file", "message": f"Unknown file: {base or name}. Expected: " + ", ".join(PACKAGE_FILES)})
        else:
            out[base] = raw
    if errs:
        raise ValidationFailure(errs)
    if not out:
        raise ValidationFailure([{"field": "file", "message": "Send a zip file or the CSV files of a mission package"}])
    return out
