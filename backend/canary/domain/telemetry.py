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
from .catalog import LOCATIONS
from .simdata import h01  # noqa: F401  (re-exported: goals and suggestions use it)


class TelemetrySource(Protocol):
    def value(self, crew_id: str, ind: str, day: int) -> float: ...


class DatasetSource:
    """Reads the stored observations (see data.py). On a day without a measurement it returns the last observation;
    `last_observation` also says how old it is. A self check-in still wins on top of it (see `overrides`)."""

    def last_observation(self, crew_id: str, ind: str, day: int) -> Optional[dict]:
        return data.last(crew_id, ind, day)

    def rows_between(self, crew_id: str, ind: str, d0: int, d1: int) -> Dict[int, float]:
        """Stored rows on days d0..d1, by day."""
        return data.rows_between(crew_id, ind, d0, d1)

    def value(self, crew_id: str, ind: str, day: int) -> float:
        o = data.last(crew_id, ind, day)
        if o is not None:
            return o["value"]
        first = data.first(crew_id, ind)  # before the first measurement: the first one is the best guess
        if first is None:
            raise KeyError(f"no observations for {crew_id}/{ind}")
        return first


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


def preflight_checkins(crew_id: str) -> int:
    """How many check-ins exist before launch: part of the baseline cache key."""
    return db.q("SELECT COUNT(*) n FROM checkins WHERE crew_id=? AND day<0", (crew_id,))[0]["n"]


def overrides(crew_id: str, day: int) -> Dict[str, float]:
    """Self-measured values for one day (latest check-in wins)."""
    return {i: v["value"] for i, v in user_values(crew_id, day, day).get(day, {}).items()}


def observation(crew_id: str, ind: str, day: int, uv: Optional[Dict[int, Dict[str, dict]]] = None) -> dict:
    """The one way to read a value: {"value", "origin", "source", "day"}.

    A self check-in of that day wins (origin "user"); otherwise the last stored row up to
    that day, with the origin and source of the row; before the first row, the first row.
    """
    u = (uv if uv is not None else user_values(crew_id, day, day)).get(day, {}).get(ind)
    if u is not None:
        return {"value": u["value"], "origin": "user", "source": f"checkin:{crew_id}:{u['kind']}:day{day}", "day": day}
    o = last_observation(crew_id, ind, day)
    if o is not None:
        return {"value": o["value"], "origin": o["origin"], "source": o["source"], "day": o["day"]}
    return {"value": SOURCE.value(crew_id, ind, day), "origin": "simulated", "source": f"recipe:{ind}", "day": day}


def reading(crew_id: str, ind: str, day: int, ov: Optional[Dict[str, float]] = None) -> float:
    if ov is not None and ind in ov:
        return ov[ind]
    return observation(crew_id, ind, day)["value"]


def current(crew_id: str, ind: str, day: int) -> float:
    """Weighted recent value: 60% today, 25% yesterday, 15% the day before. Check-ins count on all three days."""
    uv = user_values(crew_id, day - 2, day)
    return sum(w * observation(crew_id, ind, day - k, uv)["value"] for k, w in enumerate((0.6, 0.25, 0.15)))


def series(crew_id: str, ind: str, day: int, n: int = 30) -> list:
    uv = user_values(crew_id, day - n + 1, day)
    return [[d, round(observation(crew_id, ind, d, uv)["value"], 2)] for d in range(day - n + 1, day + 1)]


def cumulative_dose(day: int, location_now: str, storm: Optional[str]) -> float:
    """Mission dose in mSv up to `day`, following the reference timeline. Simulated."""
    if day < 0:
        return 0.0
    total = sum(LOCATIONS[plan.location_at(d)]["dose_rate"] for d in range(0, day))
    total += LOCATIONS[location_now]["dose_rate"]
    if day >= 152 and plan.location_at(152) in ("transit", "moon"):
        total += 22.0  # simulated extra dose behind the storm shelter during the replayed May 2024 storm
    return round(total, 1)
