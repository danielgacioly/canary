"""Where sensor readings come from.

`TelemetrySource` is the seam for real devices. Today the only implementation is `DatasetSource`, which reads the
`observations` table of the database through domain/data.py (one row per measurement with its origin). The table is
filled only through the entry points: POST /api/observations, a mission package import, scripts/load_mission.py.
A self check-in stored in the database overrides the stored value for that day.
"""
import json
from typing import Dict, Optional, Protocol

from .. import db
from . import data, plan
from .catalog import max_age
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
    "vitals": [("hr", "hr"), ("bp", "bp"), ("temp", "temp"), ("spo2", "spo2")],
    "dsst": [("correct", "dsst")],
    "span": [("span", "span")],
    "kss": [("level", "kss")],
    "tlx": [("raw", "tlx")],
}


def _rows(crew_id: str, d0: int, d1: int) -> list:
    return db.q("SELECT kind,day,payload FROM checkins WHERE crew_id=? AND day>=? AND day<=? ORDER BY id", (crew_id, d0, d1))


def user_values(crew_id: str, d0: int, d1: int) -> Dict[int, Dict[str, dict]]:
    """Self-measured values by day and indicator (latest check-in of the day wins), with the check-in kind."""
    out: Dict[int, Dict[str, dict]] = {}
    for r in _rows(crew_id, d0, d1):
        p = json.loads(r["payload"])
        for field, ind in CHECKIN_FIELDS.get(r["kind"], []):
            if p.get(field) is not None:
                out.setdefault(r["day"], {})[ind] = {"value": float(p[field]), "kind": r["kind"]}
    return out


def last_user_day(crew_id: str, day: int) -> Dict[str, int]:
    """For each indicator, the last day up to `day` on which the person measured it themselves."""
    out: Dict[str, int] = {}
    for d, inds in sorted(user_values(crew_id, -10**6, day).items()):
        for ind in inds:
            out[ind] = d
    return out


def preflight_values(crew_id: str, ind: str) -> Dict[int, float]:
    """Every measurement of `ind` on the plan's pre-flight days (Earth legs that end before launch), by day.

    The stored rows, with the person's own check-ins of those days on top. Never the carried-forward value.
    """
    days = [(l["start"], min(l["end"], -1)) for l in plan.get()["legs"] if l["location"] == "earth" and l["start"] < 0]
    out: Dict[int, float] = {}
    for d0, d1 in days:
        out.update(SOURCE.rows_between(crew_id, ind, d0, d1))  # type: ignore[attr-defined]
        for d, inds in user_values(crew_id, d0, d1).items():
            if ind in inds:
                out[d] = inds[ind]["value"]
    return out


def early_flight_values(crew_id: str, ind: str, window: int = 14) -> Dict[int, float]:
    """The measurements of `ind` in the person's first `window` days of flight data (from their first measurement on or after
    launch), by day: stored rows with the person's own check-ins on top. What a person who starts in flight learns their
    normal from. Empty when there is none."""
    vals: Dict[int, float] = dict(SOURCE.rows_between(crew_id, ind, 0, 10 ** 6))  # type: ignore[attr-defined]
    for d, inds in user_values(crew_id, 0, 10 ** 6).items():
        if ind in inds:
            vals[d] = inds[ind]["value"]
    if not vals:
        return {}
    first = min(vals)
    return {d: v for d, v in vals.items() if d < first + window}


def preflight_checkins(crew_id: str) -> int:
    """How many check-ins the person has made: part of the baseline cache key (pre-flight ones and the early flight days
    both feed the baseline)."""
    return db.q("SELECT COUNT(*) n FROM checkins WHERE crew_id=?", (crew_id,))[0]["n"]


def overrides(crew_id: str, day: int) -> Dict[str, float]:
    """Self-measured values for one day (latest check-in wins)."""
    return {i: v["value"] for i, v in user_values(crew_id, day, day).get(day, {}).items()}


def observation(crew_id: str, ind: str, day: int, uv: Optional[Dict[int, Dict[str, dict]]] = None) -> dict:
    """The one way to read a value: {"value", "origin", "source", "day", "age_days", "stale"}.

    A self check-in of that day wins (origin "user"); otherwise the last stored row up to that day, with the origin and
    source of the row, how many days old it is and whether that is past the indicator's `max_age` (stale). With no row at
    all: value None, origin "none". A day before the first measurement has no value either.
    """
    u = (uv if uv is not None else user_values(crew_id, day, day)).get(day, {}).get(ind)
    if u is not None:
        return {"value": u["value"], "origin": "user", "source": f"checkin:{crew_id}:{u['kind']}:day{day}", "day": day, "age_days": 0, "stale": False}
    o = last_observation(crew_id, ind, day)
    if o is not None:
        age = day - o["day"]
        limit = max_age(ind)
        return {"value": o["value"], "origin": o["origin"], "source": o["source"], "day": o["day"], "age_days": age,
                "stale": limit is not None and age > limit}
    return {"value": None, "origin": "none", "source": None, "day": None, "age_days": None, "stale": False}


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
    """Weighted recent value: 60% today, 25% yesterday, 15% the day before, over the days whose observation is current
    (not stale, not missing); the weights are renormalised over those days. None when none of the three is current.
    Check-ins count on all three days."""
    uv = user_values(crew_id, day - 2, day)
    num = den = 0.0
    n = 0
    for k, w in enumerate((0.6, 0.25, 0.15)):
        o = observation(crew_id, ind, day - k, uv)
        if is_current(o):
            num += w * o["value"]
            den += w
            n += 1
    return None if n == 0 else num if n == 3 else num / den


def series(crew_id: str, ind: str, day: int, n: int = 30) -> list:
    """[day, value] for the last `n` days; a day whose observation is stale or missing is [day, None] (null in JSON).
    One exception, kept so the demo charts stay identical: on the days before the person's first stored measurement the
    chart still draws that first value (the line starts flat). It is a chart nicety only: `observation()` and `current()`
    never use it. A person with no measurement at all has no line."""
    uv = user_values(crew_id, day - n + 1, day)
    first = data.first(crew_id, ind)
    out = []
    for d in range(day - n + 1, day + 1):
        o = observation(crew_id, ind, d, uv)
        v = o["value"] if is_current(o) else (first if o["origin"] == "none" else None)
        out.append([d, None if v is None else round(v, 2)])
    return out
