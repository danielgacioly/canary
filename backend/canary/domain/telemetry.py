"""Where sensor readings come from.

`TelemetrySource` is the seam for real devices. Today the only implementation is `DatasetSource`, which reads the
`observations` table of the database through domain/data.py (one row per measurement with its origin). The table is
filled only through the entry points: POST /api/observations, a mission package import, scripts/load_mission.py.
On one day every reading is kept; the engine reads one of them: an instrument reading takes precedence over a self-report
(a manual row or a check-in), then the latest. A reading whose context does not count for its indicator (a pulse taken
during exercise, a pressure taken standing) is kept but never read as the day's value or used in a baseline.
"""
import bisect
import json
from typing import Dict, List, Optional, Protocol

from .. import db
from . import data, plan
from .catalog import INDICATORS, max_age
from .simdata import h01  # noqa: F401  (re-exported: goals and suggestions use it)


class TelemetrySource(Protocol):
    def value(self, crew_id: str, ind: str, day: int) -> Optional[float]: ...


class DatasetSource:
    """Reads the stored observations (see data.py). On a day without a measurement it returns the last observation;
    `last_observation` also says how old it is. A self check-in still wins on top of it (see `overrides`)."""

    def last_observation(self, crew_id: str, ind: str, day: int) -> Optional[dict]:
        return data.last(crew_id, ind, day)

    def rows_between(self, crew_id: str, ind: str, d0: int, d1: int) -> Dict[int, float]:
        """Stored rows on days d0..d1, by day."""
        return data.rows_between(crew_id, ind, d0, d1)

    def value(self, crew_id: str, ind: str, day: int) -> Optional[float]:
        """The last stored value up to `day`, or None when there is no row at all (never an exception)."""
        o = data.last(crew_id, ind, day)
        return None if o is None else o["value"]


SOURCE: TelemetrySource = DatasetSource()


def last_observation(crew_id: str, ind: str, day: int) -> Optional[dict]:
    """Last measurement of `ind` up to `day` with its age in days, origin, method, source and note; None if there is none."""
    return SOURCE.last_observation(crew_id, ind, day)  # type: ignore[attr-defined]


# Which check-in field feeds which indicator: kind -> [(payload field, indicator)].
CHECKIN_FIELDS = {
    "mood": [("mood", "mood"), ("stress", "stress")],
    "pvt": [("ms", "react")],
    "sleep": [("hours", "sleep")],
    "vitals": [("hr", "hr"), ("sbp", "sbp"), ("dbp", "dbp"), ("temp", "temp"), ("spo2", "spo2")],
    "dsst": [("correct", "dsst")],
    "span": [("span", "span")],
    "kss": [("level", "kss")],
    "tlx": [("raw", "tlx")],
}
# The optional context a vitals check-in carries, by indicator: payload field -> context key.
CHECKIN_CONTEXT = {"hr": ("activity", "activity"), "sbp": ("position", "position"), "dbp": ("position", "position")}

_ckcache: Dict[tuple, list] = {}


def _checkins(crew_id: str) -> list:
    """Every check-in of one person, parsed once per (count, last id): [(day, kind, payload)] in the order they were made."""
    c = db.q("SELECT COUNT(*) n, COALESCE(MAX(id),0) m FROM checkins WHERE crew_id=?", (crew_id,))[0]
    key = (db.epoch, crew_id, c["n"], c["m"])
    hit = _ckcache.get(key)
    if hit is None:
        if len(_ckcache) > 64:
            _ckcache.clear()
        hit = _ckcache[key] = [(r["day"], r["kind"], json.loads(r["payload"]))
                               for r in db.q("SELECT kind,day,payload FROM checkins WHERE crew_id=? ORDER BY id", (crew_id,))]
    return hit


def user_values(crew_id: str, d0: int, d1: int) -> Dict[int, Dict[str, dict]]:
    """Self-measured values by day and indicator (latest check-in of the day wins), with the check-in kind and, when the
    check-in says how the value was taken, its `context`."""
    out: Dict[int, Dict[str, dict]] = {}
    for day, kind, p in _checkins(crew_id):
        if not d0 <= day <= d1:
            continue
        for field, ind in CHECKIN_FIELDS.get(kind, []):
            if p.get(field) is not None:
                ctx = {}
                if ind in CHECKIN_CONTEXT and p.get(CHECKIN_CONTEXT[ind][0]):
                    ctx = {CHECKIN_CONTEXT[ind][1]: str(p[CHECKIN_CONTEXT[ind][0]])}
                out.setdefault(day, {})[ind] = {"value": float(p[field]), "kind": kind, "context": ctx}
    return out


def last_user_day(crew_id: str, day: int) -> Dict[str, int]:
    """For each indicator, the last day up to `day` on which the person measured it themselves."""
    out: Dict[str, int] = {}
    for d, inds in sorted(user_values(crew_id, -10**6, day).items()):
        for ind in inds:
            out[ind] = d
    return out


# ---------------------------------------------------------------- which reading of a day counts
def counts(ind: str, reading: dict) -> bool:
    """False for a reading whose context says it is not the resting one (pulse during exercise, pressure standing)."""
    c = (INDICATORS.get(ind) or {}).get("context")
    if not c:
        return True
    v = (reading.get("context") or {}).get(c["field"])
    return v is None or v in c["counts"]


def pick(ind: str, readings: List[dict]) -> Optional[dict]:
    """The reading of a day the engine uses: among those that count, an instrument reading before a self-report, then
    the latest one. The others stay stored."""
    ok = [r for r in readings if counts(ind, r)]
    if not ok:
        return None
    dev = [r for r in ok if r.get("device")]
    return (dev or ok)[-1]


# Check-ins that are timed by the app itself (a reaction, digit-symbol or digit-span test): an instrument reading, not a self-report.
TEST_KINDS = {"pvt", "dsst", "span"}


def _checkin_reading(crew_id: str, day: int, u: dict) -> dict:
    return {"day": day, "value": u["value"], "origin": "user", "method": "manual", "source": f"checkin:{crew_id}:{u['kind']}:day{day}",
            "note": "", "device": u["kind"] in TEST_KINDS, "context": u.get("context") or {}}


def readings_on(crew_id: str, ind: str, day: int, uv: Optional[Dict[int, Dict[str, dict]]] = None) -> List[dict]:
    """Every reading of one day (stored rows, then the check-in), none dropped."""
    rows = data.table().rows_on(crew_id, ind, day)
    u = (uv if uv is not None else user_values(crew_id, day, day)).get(day, {}).get(ind)
    return rows + ([_checkin_reading(crew_id, day, u)] if u is not None else [])


_drcache: Dict[tuple, tuple] = {}


def _all_day_readings(crew_id: str, ind: str) -> tuple:
    """(sorted days, {day: reading}) for the whole history of one indicator, kept until the stored data or the person's
    check-ins change."""
    c = db.q("SELECT COUNT(*) n, COALESCE(MAX(id),0) m FROM checkins WHERE crew_id=?", (crew_id,))[0]
    key = (data.token(), crew_id, ind, c["n"], c["m"])
    hit = _drcache.get(key)
    if hit is None:
        if len(_drcache) > 600:
            _drcache.clear()
        tbl = data.table()
        users = user_values(crew_id, -10 ** 6, 10 ** 6)
        days = set(tbl.days.get((crew_id, ind)) or []) | {d for d, m in users.items() if ind in m}
        out: Dict[int, dict] = {}
        for d in sorted(days):
            r = pick(ind, readings_on(crew_id, ind, d, users))
            if r is not None:
                out[d] = r
        hit = _drcache[key] = (sorted(out), out)
    return hit


def day_readings(crew_id: str, ind: str, d0: int, d1: int) -> Dict[int, dict]:
    """The reading each day uses (see `pick`) on days d0..d1, by day. Days with no usable reading are left out."""
    days, by = _all_day_readings(crew_id, ind)
    lo, hi = bisect.bisect_left(days, d0), bisect.bisect_right(days, d1)
    return {d: by[d] for d in days[lo:hi]}


def day_values(crew_id: str, ind: str, d0: int, d1: int) -> Dict[int, float]:
    days, by = _all_day_readings(crew_id, ind)
    lo, hi = bisect.bisect_left(days, d0), bisect.bisect_right(days, d1)
    return {d: by[d]["value"] for d in days[lo:hi]}


def preflight_values(crew_id: str, ind: str) -> Dict[int, float]:
    """Every measurement of `ind` on the plan's pre-flight days (Earth legs that end before launch), by day.

    The reading of each day (instrument before self-report, resting context only). Never the carried-forward value.
    """
    days = [(l["start"], min(l["end"], -1)) for l in plan.get()["legs"] if l["location"] == "earth" and l["start"] < 0]
    out: Dict[int, float] = {}
    for d0, d1 in days:
        out.update(day_values(crew_id, ind, d0, d1))
    return out


def early_flight_values(crew_id: str, ind: str, window: int = 14) -> Dict[int, float]:
    """The measurements of `ind` in the person's first `window` days of flight data (from their first measurement on or after
    launch), by day. What a person who starts in flight learns their normal from. Empty when there is none."""
    vals = day_values(crew_id, ind, 0, 10 ** 6)
    if not vals:
        return {}
    first = min(vals)
    return {d: v for d, v in vals.items() if d < first + window}


def inflight_values(crew_id: str, ind: str, first_day: int, last_day: int) -> Dict[int, float]:
    """Measurements on flight days first_day..last_day (days since launch) away from Earth: the in-flight re-baseline."""
    return {d: v for d, v in day_values(crew_id, ind, first_day, last_day).items() if plan.location_at(d) != "earth"}


def preflight_checkins(crew_id: str) -> int:
    """How many check-ins the person has made: part of the baseline cache key."""
    return db.q("SELECT COUNT(*) n FROM checkins WHERE crew_id=?", (crew_id,))[0]["n"]


def overrides(crew_id: str, day: int) -> Dict[str, float]:
    """Self-measured values for one day (latest check-in wins)."""
    return {i: v["value"] for i, v in user_values(crew_id, day, day).get(day, {}).items()}


def observation(crew_id: str, ind: str, day: int, uv: Optional[Dict[int, Dict[str, dict]]] = None) -> dict:
    """The one way to read a value: {"value", "origin", "source", "method", "context", "day", "age_days", "stale", "readings"}.

    The reading of that day when there is one (instrument before self-report, then the latest; a reading taken in a
    context that does not count is skipped); otherwise the last such reading on an earlier day, with how many days old it
    is and whether that is past the indicator's `max_age` (stale). It is never relabelled as today's: `day` and `age_days`
    say when it was taken. With no reading at all: value None, origin "none".
    """
    todays = readings_on(crew_id, ind, day, uv)
    r = pick(ind, todays)
    if r is not None:
        return _obs(r, day, 0, False, len(todays))
    limit = max_age(ind)
    for d, rows in data.table().days_back(crew_id, ind, day - 1):
        r = pick(ind, rows)
        if r is not None:
            age = day - d
            return _obs(r, d, age, limit is not None and age > limit, len(rows))
    return {"value": None, "origin": "none", "source": None, "method": None, "context": {}, "day": None, "age_days": None, "stale": False, "readings": 0}


def _obs(r: dict, day: int, age: int, stale: bool, n: int) -> dict:
    return {"value": r["value"], "origin": r["origin"], "source": r["source"], "method": r["method"], "context": r.get("context") or {},
            "day": day, "age_days": age, "stale": stale, "readings": n}


def is_current(o: dict) -> bool:
    """True when the observation has a value that is not stale."""
    return o["value"] is not None and not o["stale"]


def reading(crew_id: str, ind: str, day: int, ov: Optional[Dict[str, float]] = None) -> Optional[float]:
    """The value of the day when it is current, else None (a stale or missing reading is not today's value)."""
    if ov is not None and ind in ov:
        return ov[ind]
    o = observation(crew_id, ind, day)
    return o["value"] if is_current(o) else None


def current(crew_id: str, ind: str, day: int) -> Optional[float]:
    """DISPLAY ONLY: weighted recent value (60% today, 25% yesterday, 15% the day before) over the days whose observation is
    current. The alert levels never use it: they read the day's own value (`observation`). None when none of the three
    days has a current reading."""
    uv = user_values(crew_id, day - 2, day)
    num = den = 0.0
    n = 0
    for k, w in enumerate((0.6, 0.25, 0.15)):
        o = observation(crew_id, ind, day - k, uv)
        if is_current(o) and o["age_days"] == 0:
            num += w * o["value"]
            den += w
            n += 1
    return None if n == 0 else num if n == 3 else num / den


def series(crew_id: str, ind: str, day: int, n: int = 30) -> list:
    """[day, value] for the last `n` days; a day whose observation is stale or missing is [day, None] (null in JSON).
    One exception, kept so the demo charts stay identical: on the days before the person's first stored measurement the
    chart still draws that first value (the line starts flat). It is a chart nicety only: `observation()` never uses it.
    A person with no measurement at all has no line. A scan indicator (bone density) is drawn only on the days it was
    measured."""
    uv = user_values(crew_id, day - n + 1, day)
    first = data.first(crew_id, ind)
    scan = INDICATORS.get(ind, {}).get("scan")
    out = []
    for d in range(day - n + 1, day + 1):
        o = observation(crew_id, ind, d, uv)
        if scan:
            v = o["value"] if o["age_days"] == 0 else None
        else:
            v = o["value"] if is_current(o) else (first if o["origin"] == "none" else None)
        out.append([d, None if v is None else round(v, 2)])
    return out
