"""Mission dose: measured by dosimeters where there are readings, estimated from the plan where there are not.

The dose of one day (mSv), in this order:
1. the person's own dosimeter (`dose_rate` readings with the crew id),
2. the cabin dosimeter (`dose_rate` readings with the crew id `cabin`),
3. the rate of the place in the plan (`catalog.LOCATIONS[...]["dose_rate"]`), marked estimated, plus the `extra_dose_msv`
   of the space events that start that day and hit that place (the plan's place, that day).
A measured day already contains its storm: the dosimeter saw it, so the event adds nothing on top of the reading.

Future days (the projection to the end of the plan) always use the plan: rates plus the events that exist.
The mission dose "up to day D" adds the days 0..D-1 and today's rate: today's reading, else the rate of the place
the crew is in now (which the crew may have overridden).

Each day is kept as two numbers, the base (a reading minus the storm it contains, or the rate of the place) and the
extra of a storm that starts that day. They are summed apart and added at the end, so the total does not depend on where
in the series a storm falls (a tie such as 592.45 always rounds the same way as before the dose moved to dosimeters).

Privacy: crew-wide pages call these functions with no crew id, so they only ever show the cabin (or the plan). A person's
own dosimeter counts only when their own snapshot or the medical console asks with their id.

Results are cached per plan version, data version and person; the arrays cover days 0..max(end of plan, asked day).
"""
from typing import Dict, List, Optional

from . import data, plan
from .catalog import CABIN_ID, CAREER_LIMIT_MSV, LOCATIONS

INDICATOR = "dose_rate"
_cache: Dict[tuple, dict] = {}
_curves: Dict[tuple, List[float]] = {}


def _arrays(crew_id: Optional[str], day: int) -> dict:
    end = max(l["end"] for l in plan.get()["legs"])
    n = max(end, day, 0) + 1
    key = (plan.version(), data.token(), crew_id)
    hit = _cache.get(key)
    if hit is not None and hit["n"] >= n:
        return hit
    if len(_cache) > 64:
        _cache.clear()
        _curves.clear()
    own = data.daily(crew_id, INDICATOR, 0, n - 1) if crew_id else {}
    cabin = data.daily(CABIN_ID, INDICATOR, 0, n - 1)
    base: List[float] = []       # day as counted when it is today or earlier: the reading minus its storm, else the plan's rate
    extra: List[float] = []      # the storm's extra on that day (inside the reading, or estimated)
    f_base: List[float] = []     # day as projected: the plan's rate ...
    f_extra: List[float] = []    # ... and the events that exist
    measured: List[bool] = []
    simulated: List[bool] = []
    personal: List[bool] = []
    for d in range(n):
        ev = data.extra_dose(d)
        rate = LOCATIONS[plan.location_at(d)]["dose_rate"]
        f_base.append(rate)
        f_extra.append(ev)
        m = own.get(d) or cabin.get(d)
        if m is not None:
            inside = ev if m[0] >= ev else 0.0
            base.append(round(m[0] - inside, 4))
            extra.append(inside)
            measured.append(True)
            simulated.append(m[1] == "simulated")
            personal.append(d in own)
        else:
            base.append(rate)
            extra.append(ev)
            measured.append(False)
            simulated.append(True)
            personal.append(False)
    out = {"n": n, "end": end, "base": base, "extra": extra, "f_base": f_base, "f_extra": f_extra, "measured": measured,
           "simulated": simulated, "personal": personal}
    _cache[key] = out
    return out


def _sum(xs: List[float]) -> float:
    t = 0.0
    for x in xs:  # one fixed left-to-right order, whatever the Python version
        t += x
    return t


def mission(crew_id: Optional[str], day: int, location_now: Optional[str] = None) -> dict:
    """Mission dose in mSv up to `day`: {"msv", "measured_days", "estimated_days", "simulated", "personal", "origin"}.
    `location_now` is the place the crew is in today when it differs from the plan (the crew can override it).
    With a crew id, that person's own dosimeter counts first; without, only the cabin (and the plan)."""
    if day < 0:
        return {"msv": 0.0, "measured_days": 0, "estimated_days": 0, "simulated": True, "personal": False, "origin": "estimated"}
    A = _arrays(crew_id, day)
    run, run_extra = _sum(A["base"][:day]), _sum(A["extra"][:day])
    m_days = sum(1 for d in range(0, day) if A["measured"][d])
    sim = any(A["simulated"][d] for d in range(0, day))
    pers = any(A["personal"][d] for d in range(0, day + 1))
    if A["measured"][day]:
        run += A["base"][day]
        run_extra += A["extra"][day]
        m_days += 1
        sim = sim or A["simulated"][day]
    else:  # today has no reading yet: the rate of the place the crew is in now
        run += LOCATIONS[location_now or plan.location_at(day)]["dose_rate"]
        run_extra += A["extra"][day]
        sim = True
    est = day + 1 - m_days
    return {"msv": round(run + run_extra, 1), "measured_days": m_days, "estimated_days": est, "simulated": sim, "personal": pers,
            "origin": "measured" if est == 0 else "estimated" if m_days == 0 else "partial"}


def curve(crew_id: Optional[str], today: int) -> List[float]:
    """Mission dose (mSv) at the end of each day 0..end of the plan: what was counted up to `today`, the plan after it."""
    A = _arrays(crew_id, today)
    key = (plan.version(), data.token(), crew_id, today)
    hit = _curves.get(key)
    if hit is None:
        if len(_curves) > 3000:
            _curves.clear()
        hit, run, run_extra = [], 0.0, 0.0
        for d in range(0, A["end"] + 1):
            run += A["base"][d] if d <= today else A["f_base"][d]
            run_extra += A["extra"][d] if d <= today else A["f_extra"][d]
            hit.append(round(run + run_extra, 1))
        _curves[key] = hit
    return hit


def projection(crew_id: Optional[str], day: int, prior_msv: float = 0.0) -> dict:
    """Career dose today (dose before this mission + mission dose) and the first day of the plan on which it passes the
    career limit (None when it never does). NASA-STD-3001 V1 4030 counts every earlier flight."""
    c = curve(crew_id, day)
    m = c[day] if 0 <= day < len(c) else (c[-1] if day >= len(c) else 0.0)
    now = round(prior_msv + m, 1)
    cross = next((d for d in range(max(day, 0), len(c)) if prior_msv + c[d] > CAREER_LIMIT_MSV), None)
    return {"now_msv": now, "mission_msv": m, "prior_msv": prior_msv, "limit_msv": CAREER_LIMIT_MSV,
            "pct": round(100 * now / CAREER_LIMIT_MSV, 1), "cross_day": cross}
