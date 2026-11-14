"""Where sensor readings come from.

`TelemetrySource` is the seam for real devices. Today the only implementation is
`DatasetSource`, which reads the observation table (`data/observations.csv`, one row
per measurement with its origin, built from `data/recipes.json` by
`data/generate_dataset.py`). Real rows dropped into `data/real/` replace simulated ones.
A self check-in stored in the database overrides the file value for that day.
"""
import json
from typing import Dict, Optional, Protocol

from .. import db
from . import plan, simdata
from .catalog import LOCATIONS
from .simdata import h01  # noqa: F401  (re-exported: goals and suggestions use it)


class TelemetrySource(Protocol):
    def value(self, crew_id: str, ind: str, day: int) -> float: ...


class DatasetSource:
    """Reads the observation table (backend/canary/data/observations.csv, built by data/generate_dataset.py).

    With the default mission plan it reads the file. With any other plan it generates the same table in
    memory with the same generator, once per plan (cached). On a day without a measurement it returns the
    last observation; `last_observation` also says how old it is. A self check-in still wins on top of it
    (see `overrides`).
    """

    def __init__(self, path=simdata.OBS_FILE):
        self.path = path
        self._tables: Dict[tuple, simdata.Table] = {}
        self._ver: Optional[tuple] = None  # (plan version, plan signature)

    def _table(self) -> simdata.Table:
        v = plan.version()
        if self._ver is None or self._ver[0] != v:
            self._ver = (v, simdata.signature(plan.get()["legs"]))
        sig = self._ver[1]
        t = self._tables.get(sig)
        if t is None:
            default = sig == simdata.signature(plan.PRESETS[plan.DEFAULT]["legs"])
            if default and self.path.exists():
                rows = [(r["crew_id"], r["day"], r["indicator"], r["value"], r["unit"], r["origin"], r["method"], r["source"], r["note"])
                        for r in simdata.read_csv(self.path)]
            else:
                rows = simdata.Generator(plan.get()["legs"]).observations()
            t = self._tables[sig] = simdata.Table(rows)
        return t

    def last_observation(self, crew_id: str, ind: str, day: int) -> Optional[dict]:
        return self._table().last(crew_id, ind, day)

    def value(self, crew_id: str, ind: str, day: int) -> float:
        t = self._table()
        o = t.last(crew_id, ind, day)
        if o is not None:
            return o["value"]
        first = t.first(crew_id, ind)  # before the first measurement: the first one is the best guess
        if first is None:
            raise KeyError(f"no observations for {crew_id}/{ind}")
        return first


SOURCE: TelemetrySource = DatasetSource()


def last_observation(crew_id: str, ind: str, day: int) -> Optional[dict]:
    """Last measurement of `ind` up to `day` with its age in days, origin, method, source and note; None if there is none."""
    return SOURCE.last_observation(crew_id, ind, day)  # type: ignore[attr-defined]


def overrides(crew_id: str, day: int) -> Dict[str, float]:
    """Self-measured values for one day (latest check-in wins)."""
    out: Dict[str, float] = {}
    for r in db.q("SELECT kind,payload FROM checkins WHERE crew_id=? AND day=? ORDER BY id", (crew_id, day)):
        p = json.loads(r["payload"])
        if r["kind"] == "mood":
            out["mood"] = float(p["mood"])
            if "stress" in p:
                out["stress"] = float(p["stress"])
        elif r["kind"] == "pvt":
            out["react"] = float(p["ms"])
        elif r["kind"] == "sleep" and p.get("hours") is not None:
            out["sleep"] = float(p["hours"])
        elif r["kind"] == "vitals":
            for k in ("hr", "bp", "temp", "spo2"):
                if p.get(k) is not None:
                    out[k] = float(p[k])
    return out


def reading(crew_id: str, ind: str, day: int, ov: Optional[Dict[str, float]] = None) -> float:
    ov = overrides(crew_id, day) if ov is None else ov
    return ov[ind] if ind in ov else SOURCE.value(crew_id, ind, day)


def current(crew_id: str, ind: str, day: int) -> float:
    """Weighted recent value: 60% today, 25% yesterday, 15% the day before."""
    ov = overrides(crew_id, day)
    return 0.6 * reading(crew_id, ind, day, ov) + 0.25 * SOURCE.value(crew_id, ind, day - 1) + 0.15 * SOURCE.value(crew_id, ind, day - 2)


def series(crew_id: str, ind: str, day: int, n: int = 30) -> list:
    return [[d, round(SOURCE.value(crew_id, ind, d), 2)] for d in range(day - n + 1, day + 1)]


def cumulative_dose(day: int, location_now: str, storm: Optional[str]) -> float:
    """Mission dose in mSv up to `day`, following the reference timeline. Simulated."""
    if day < 0:
        return 0.0
    total = sum(LOCATIONS[plan.location_at(d)]["dose_rate"] for d in range(0, day))
    total += LOCATIONS[location_now]["dose_rate"]
    if day >= 152 and plan.location_at(152) in ("transit", "moon"):
        total += 22.0  # simulated extra dose behind the storm shelter during the replayed May 2024 storm
    return round(total, 1)
