"""Where sensor readings come from.

`TelemetrySource` is the seam for real devices. Today the only implementation is
`SimulatedSource`: deterministic (same input, same number), with the demo story
written into it. A self check-in stored in the database overrides the simulated
value for that day.
"""
import json
from typing import Dict, Optional, Protocol

from .. import db
from .catalog import CREW_BY_ID, INDICATORS, LOCATIONS, timeline_location


def h01(key: str) -> float:
    """Stable pseudo-random number in [0, 1) from a string (FNV-1a + avalanche)."""
    h = 2166136261
    for ch in key.encode():
        h ^= ch
        h = (h * 16777619) & 0xFFFFFFFF
    h ^= h >> 15
    h = (h * 2246822507) & 0xFFFFFFFF
    h ^= h >> 13
    return (h % 100000) / 100000


class TelemetrySource(Protocol):
    def value(self, crew_id: str, ind: str, day: int) -> float: ...


class SimulatedSource:
    """Personal baseline + day-to-day noise + place effects + the demo story."""

    def value(self, crew_id: str, ind: str, day: int) -> float:
        c = CREW_BY_ID[crew_id]
        I = INDICATORS[ind]
        if ind == "bone":
            return self._bone(crew_id, day)
        v = c["base"][ind] + (h01(f"{crew_id}{ind}{day}") - 0.5) * 1.6 * I["sd"]
        # Story: Helena's slow slide on the way to Mars (days 132-153), then recovery
        if crew_id == "h":
            r = 0 if day < 132 else (day - 132) / 16 if day <= 153 else max(0.0, 1.3 - (day - 153) / 12)
            v += {"sleep": -1.5, "mood": -1.2, "react": 70, "stress": 1.1, "social": -38}.get(ind, 0) * min(r, 1.3)
        # Story: Tomás, space sickness in the first days
        if crew_id == "t" and 1 <= day <= 6:
            v += {"hr": 12, "water": -1.1, "exer": -50, "mood": -0.6}.get(ind, 0) * (1 - (day - 1) / 6)
        # Everyone: readapting to gravity on Mars
        if 210 <= day <= 240:
            v += {"bp": -14, "hr": 12, "grip": -3}.get(ind, 0) * (1 - (day - 210) / 30)
        # Exercise target is lower in the first hours and on the surface
        if ind == "exer" and timeline_location(day) == "rocket":
            v = min(v, 25 + 10 * h01(f"x{crew_id}{day}"))
        if ind in ("mood", "stress"):
            v = min(5.0, max(1.0, v))
        return v

    def _bone(self, crew_id: str, day: int) -> float:
        """Estimated % change of weight-bearing bone density since launch."""
        if day <= 0:
            return (h01(f"b{crew_id}{day}") - 0.5) * 0.4
        c = CREW_BY_ID[crew_id]
        # 0.35%/month with full exercise, up to 1%/month without (order of magnitude from NASA HRP; verify)
        per_month = 1.0 - 0.65 * min(1.0, c["base"]["exer"] / 110)
        zero_g_days = min(day, 210)
        loss = per_month * zero_g_days / 30
        if day > 210:  # partial gravity on Mars slows the loss
            loss += per_month * 0.4 * (day - 210) / 30
        return -loss + (h01(f"b{crew_id}{day}") - 0.5) * 0.3


SOURCE: TelemetrySource = SimulatedSource()


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
    total = sum(LOCATIONS[timeline_location(d)]["dose_rate"] for d in range(0, day))
    total += LOCATIONS[location_now]["dose_rate"]
    if day >= 152:
        total += 22.0  # simulated extra dose behind the storm shelter on day 152
    return round(total, 1)
