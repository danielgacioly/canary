"""Mission dose: measured by dosimeters where there are readings, estimated from the plan where there are not.

Dosimeter readings come as `dose_eq_rate` (dose equivalent, mSv/day) or `dose_rate` (absorbed dose, mGy/day; a `dose_rate`
row in mSv/day is read as the dose equivalent). The effective dose is estimated by the dosimeter's dose equivalent: the
organ-weighted model is not applied (assumptions: dose.model_note). An absorbed-only reading is converted with the
mean quality factor of assumptions.py.

The dose of one day (mSv), in this order:
1. the person's own dosimeter (readings with the crew id),
2. the cabin dosimeter (readings with the crew id `cabin`),
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
import datetime as dt
from typing import Dict, List, Optional, Tuple

from . import assumptions as A
from . import data, plan
from .catalog import CABIN_ID, CAREER_LIMIT_MSV, LOCATIONS, SPE_LIMIT_MSV

INDICATOR = "dose_rate"
EQ_INDICATOR = "dose_eq_rate"
TRACKED = "tracked, no limit applied by Canary"
_cache: Dict[tuple, dict] = {}
_curves: Dict[tuple, List[float]] = {}


def _daily(crew_id: str, d1: int) -> Dict[int, Tuple[float, str]]:
    """The dose equivalent (mSv/day) the dosimeter of `crew_id` recorded on days 0..d1, by day, with the origin of the reading."""
    tbl = data.table()
    out: Dict[int, Tuple[float, str]] = {}
    days = sorted({d for ind in (INDICATOR, EQ_INDICATOR) for d in (tbl.days.get((crew_id, ind)) or []) if 0 <= d <= d1})
    for d in days:
        eq = tbl.rows_on(crew_id, EQ_INDICATOR, d)
        if eq:
            r, v = eq[-1], eq[-1]["value"]
        else:
            r = tbl.rows_on(crew_id, INDICATOR, d)[-1]
            v = r["value"] * A.value("dose.quality_factor") if r["unit"] == "mGy/day" else r["value"]
        out[d] = (v, r["origin"])
    return out


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
    own = _daily(crew_id, n - 1) if crew_id else {}
    cabin = _daily(CABIN_ID, n - 1)
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
    """Career dose today (dose before this mission + mission dose), the first day of the plan on which it passes the career
    limit (None when it never does), and the career dose projected at the end of the plan with `exceeds_career_limit`.
    NASA-STD-3001 Vol 1, 4.2.10 [V1 4030] counts every earlier flight. The projection is an estimate: it runs the plan's rates
    and the events that exist for the days still to come."""
    c = curve(crew_id, day)
    m = c[day] if 0 <= day < len(c) else (c[-1] if day >= len(c) else 0.0)
    now = round(prior_msv + m, 1)
    cross = next((d for d in range(max(day, 0), len(c)) if prior_msv + c[d] > CAREER_LIMIT_MSV), None)
    projected = round(prior_msv + c[-1], 1)
    return {"now_msv": now, "mission_msv": m, "prior_msv": prior_msv, "limit_msv": CAREER_LIMIT_MSV,
            "pct": round(100 * now / CAREER_LIMIT_MSV, 1), "cross_day": cross,
            "projected_career_msv": projected, "exceeds_career_limit": projected > CAREER_LIMIT_MSV, "projection_origin": "estimated"}


def legs_dose(legs: List[dict]) -> float:
    """The mission dose (mSv) a plan projects before anything is measured: the rate of each leg's place for each of its days
    from day 0 (the pre-flight days on Earth are not mission days). Used to decide, at registration, whether a plan can
    take a crew past the career limit."""
    return sum(LOCATIONS[l["location"]]["dose_rate"] * max(0, l["end"] - max(l["start"], 0) + 1) for l in legs)


def career_check(prior_msv: List[float], legs: List[dict]) -> dict:
    """Each person's projected career dose (what they carry in plus the plan's mission dose) against the NASA limit."""
    mission_msv = round(legs_dose(legs), 1)
    careers = [round(p + mission_msv, 1) for p in prior_msv]
    peak = max(careers, default=0.0)
    return {"mission_msv": mission_msv, "careers": careers, "max_msv": peak, "limit_msv": CAREER_LIMIT_MSV, "over": peak > CAREER_LIMIT_MSV}


def _origin(measured: int, total: int) -> str:
    return "measured" if total and measured == total else "estimated" if measured == 0 else "partial"


def windows(crew_id: Optional[str], day: int) -> dict:
    """The dose of the last 30 and 365 days of the mission (mSv), counted from the same daily series as the mission dose.
    Tracked only: Canary applies no limit to them (the organ short-term limits could not be verified)."""
    if day < 0:
        return {}
    A_ = _arrays(crew_id, day)
    c = curve(crew_id, day)
    out = {}
    for name, n in (("d30", 30), ("d365", 365)):
        lo = max(0, day - n + 1)
        hi_i = min(day, len(c) - 1)  # past the end of the plan the curve stops: the window ends with it
        total = round(c[hi_i] - (c[lo - 1] if 0 < lo <= len(c) else 0.0), 1)
        days = day - lo + 1
        meas = sum(1 for d in range(lo, day + 1) if d < len(A_["measured"]) and A_["measured"][d])
        out[name] = {"msv": total, "days": days, "measured_days": meas, "estimated_days": days - meas, "origin": _origin(meas, days),
                     "limit": None, "label": TRACKED}
    return out


def career(crew_id: Optional[str], day: int, prior: dict, location_now: Optional[str] = None) -> dict:
    """Career effective dose (prior flights + this mission) against 600 mSv [V1 4030], with where the number comes from:
    measured (every day read by a dosimeter and a recorded prior dose), estimated (nothing measured) or partial."""
    m = mission(crew_id, day, location_now)
    total = round(prior["msv"] + m["msv"], 1)
    prior_origin = "estimated" if prior["estimate"] else "measured"
    parts = {m["origin"], prior_origin} if prior["msv"] else {m["origin"]}
    origin = "measured" if parts == {"measured"} else "estimated" if parts == {"estimated"} else "partial"
    return {"msv": total, "limit_msv": CAREER_LIMIT_MSV, "pct": round(100 * total / CAREER_LIMIT_MSV, 1), "origin": origin,
            "mission_origin": m["origin"], "prior_origin": prior_origin, "model": A.value("dose.model_note"),
            "limit_item": "NASA-STD-3001 Vol 1, 4.2.10 [V1 4030]", "past_limit": total >= CAREER_LIMIT_MSV}


def event_dose(e: dict) -> dict:
    """An event's estimated dose against the design reference for a solar particle event (250 mSv effective dose, [V1 4031]).
    The reference is a vehicle and shielding design requirement: it is a yardstick for an event, not a personal limit."""
    msv = float(e["extra_dose_msv"])
    return {"id": e["id"], "kind": e["kind"], "start_day": e["start_day"], "dose_msv": msv, "origin": "estimated", "event_origin": e["origin"],
            "design_reference_msv": SPE_LIMIT_MSV, "pct_of_design_reference": round(100 * msv / SPE_LIMIT_MSV, 1),
            "below_design_reference": msv < SPE_LIMIT_MSV, "item": "NASA-STD-3001 Vol 1 [V1 4031]",
            "label": "design reference for a solar particle event, compared with the event's estimated dose; not a personal limit"}


def events_vs_design(day: int) -> List[dict]:
    return [event_dose(e) for e in data.events() if e["kind"] == "sep" and e["start_day"] <= day]


# ---------------------------------------------------------------- where an event applies, and when to shelter
LEO = ("iss", "rocket")                      # Earth orbit: the magnetosphere attenuates solar particles
OPEN_SPACE = ("moon", "moon_rover", "transit")  # no magnetic shield
MARS_SURFACE = ("mars", "mars_rover")


def applies(kind: str, location: str) -> dict:
    """Whether a space event of `kind` reaches `location`. DONKI solar particle events (`sep`, measured at the Sun-Earth L1
    point) apply to Earth orbit (attenuated by the magnetosphere), the Moon and deep space; the Mars surface is hit by its
    own events (`mars`, from RAD), not by DONKI's. Nothing reaches the ground on Earth."""
    if kind == "sep":
        if location in OPEN_SPACE:
            return {"applies": True, "attenuated": False}
        if location in LEO:
            return {"applies": True, "attenuated": True}
        return {"applies": False, "attenuated": False}
    if kind == "mars":
        return {"applies": location in MARS_SURFACE, "attenuated": False}
    return {"applies": False, "attenuated": False}


def active_event(day: int, location: str) -> Optional[dict]:
    """The space event active on `day` at `location` that applies there, or None."""
    for e in data.events():
        if e["start_day"] <= day <= e["end_day"] and location in e["locations"] and applies(e["kind"], location)["applies"]:
            return e
    return None


def active_storm(day: int, location: str) -> Optional[str]:
    e = active_event(day, location)
    return e["kind"] if e else None


def rate_today(crew_id: Optional[str], day: int) -> Optional[dict]:
    """The dosimeter reading of the day in mSv/day (the person's own, else the cabin's), or None when nobody measured it."""
    if day < 0:
        return None
    A_ = _arrays(crew_id, day)
    if not A_["measured"][day]:
        return None
    return {"msv_day": round(A_["base"][day] + A_["extra"][day], 3), "personal": A_["personal"][day], "origin": "simulated" if A_["simulated"][day] else "measured"}


def shelter(crew_id: Optional[str], day: int, location: str, event: Optional[dict]) -> dict:
    """Whether to order the shelter (level 2). With a dosimeter reading it depends on the measured dose rate: above
    `dose.shelter_ratio` times the quiet rate of the place (a Canary assumption); in low Earth orbit also above the
    attenuated-orbit floor, because the magnetosphere protects the station. Without a reading, on an active event at a place the
    event applies to (and not attenuated). The numbers are in assumptions.py, labelled as assumptions."""
    quiet = LOCATIONS[location]["dose_rate"]
    ratio = A.value("dose.shelter_ratio")
    thr = ratio * quiet
    att = bool(event) and applies(event["kind"], location)["attenuated"]
    if att:
        thr = max(thr, A.value("dose.earth_orbit_shelter_msv_day"))
    r = rate_today(crew_id, day)
    out = {"threshold_msv_day": round(thr, 3), "quiet_msv_day": quiet, "ratio_rule": ratio, "attenuated": att,
           "assumption": "Canary assumption: " + f"{ratio:g}x the quiet rate of the place orders the shelter"}
    if r is not None:
        out.update(order=r["msv_day"] > thr, basis="dosimeter", rate_msv_day=r["msv_day"], ratio=round(r["msv_day"] / quiet, 1) if quiet else None,
                   dosimeter="personal" if r["personal"] else "cabin")
    else:
        out.update(order=bool(event) and not att, basis="event", rate_msv_day=None, ratio=None, dosimeter=None)
    return out


def plan_conditions(day: int, crew_ids: List[str], priors: Dict[str, dict]) -> dict:
    """What the plan projects, for the plan page: the dose is an estimate (the plan's rates and the events that exist), never a
    measurement. `crew_exceeding` counts the people whose projected career dose passes 600 mSv; who they are is not here
    (a prior dose is a private record): `career_projections` gives it per person to the medical team."""
    p = [projection(None, day, priors[c]["msv"]) for c in crew_ids]  # the cabin's dose, never a person's own dosimeter: this page is public
    return {"origin": "estimated", "crew_exceeding": sum(1 for x in p if x["exceeds_career_limit"]),
            "max_projected_career_msv": max([x["projected_career_msv"] for x in p] or [0.0])}


def career_projections(day: int, crew_ids: List[str], priors: Dict[str, dict]) -> Dict[str, dict]:
    """Per person: projected_career_msv, exceeds_career_limit (a waiver is needed when it does), the first day the career dose
    passes the limit, and origin "estimated". Private: for the medical team and the person."""
    out = {}
    for c in crew_ids:
        p = projection(c, day, priors[c]["msv"])
        out[c] = {k: p[k] for k in ("projected_career_msv", "exceeds_career_limit", "cross_day", "limit_msv", "prior_msv")}
        out[c].update(origin="estimated", prior_estimate=priors[c]["estimate"])
    return out
