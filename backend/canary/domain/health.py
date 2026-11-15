"""Personal baseline, alert levels, body-system status and the physical / mental readiness scores.

Each indicator is compared with the person's own pre-flight normal, never with a
population average:  z = (the day's own value - baseline) / personal spread. No smoothing: a day with no reading shows
the last reading with its age.
Levels: 0 on track, 1 watch, 2 act. Thresholds are set by the medical team (defaults in domain/assumptions.py); a level
needs two consecutive readings and is kept until the distance falls 0.5 sd below its entry (indicator_level_series).
"""
import json
import statistics
from typing import Dict, List, Optional, Sequence

from .. import db
from . import assumptions as A
from . import care, data, plan, reference, risk, standards, telemetry
from . import dose as dose_mod
from .catalog import CAREER_LIMIT_MSV, CREW_BY_ID, EXERCISE_BY_PLACE, INDICATORS, LOCATIONS, MEASURED_EVERY, SPE_LIMIT_MSV, SYSTEMS

STATUS = ["On track", "Watch", "Act"]
TODO_BY_INDICATOR = {
    "bone": ["Add 20 min of resistive exercise to today's session", "Calcium and vitamin D with breakfast", "The medical officer reviews the trend weekly"],
    "exer": ["Book today's exercise slot now", "Start with 20 min: something beats nothing"],
    "water": ["Keep a drink bag at your workstation", "A few sips every 30 minutes"],
    "social": ["Join the crew for the next meal", "Plan one off-duty hour with someone today"],
    "spo2": ["Measure again at rest in 10 minutes", "Check the cabin CO₂ reading"],
    "temp": ["Measure again in 1 hour", "Rest and drink water", "Tell the medical officer if it passes 38 °C"],
}
DEFAULT_THRESHOLDS = {"watch": A.value("z.watch"), "act": A.value("z.act")}


def thresholds() -> dict:
    return db.get_setting("thresholds", DEFAULT_THRESHOLDS)


MIN_PREFLIGHT = A.value("baseline.min_points")  # measurements needed before a person's own normal is trusted
EARLY_FLIGHT_DAYS = A.value("baseline.early_flight_days")  # a person who starts in flight learns their normal from their first days of measurements
_baselines: Dict[tuple, Dict[str, dict]] = {}


def confidence(n: int) -> str:
    """How much to trust a personal baseline from the number of readings behind it: low (<10), moderate (10 to 19), high (20 or more)."""
    return "high" if n >= A.value("baseline.confidence_high") else "moderate" if n >= A.value("baseline.confidence_moderate") else "low"


def baselines(crew_id: str) -> Dict[str, dict]:
    """Personal baseline per indicator, from the person's own measurements, never from a seed.

    - `from: "preflight"`: mean and spread of the reading of every pre-flight day (instrument before self-report, resting
      context only). The spread never goes below the catalog's `sd`, so a quiet pre-flight cannot turn ordinary noise into
      alerts. The mean is shown with the precision the app displays (`dp`).
    - `from: "early_flight"`: fewer than the minimum pre-flight values, but enough in the person's first 14 days of flight data.
    - `from: "learning"`: neither. `mean` and `sd` are None: the indicator is read only against the population range and the
      NASA standard until there is a normal to compare with. `n` measurements so far, `need` wanted.
    - `n` is the number of readings used and `confidence` is "low" (under 10), "moderate" (10 to 19) or "high" (20 or more).
    - `inflight`, for indicators flagged `adapts_in_flight`: mean, spread and `n` over flight days 8 to 14 (the in-flight
      re-baseline). It is used for the z-score from flight day 15; the NASA percent-of-baseline limits never use it.

    Cached per crew member, plan version, stored data and number of check-ins.
    """
    key = (crew_id, plan.version(), data.token(), telemetry.preflight_checkins(crew_id))
    hit = _baselines.get(key)
    if hit is None:
        if len(_baselines) > 64:
            _baselines.clear()
        hit = {}
        for ind, I in INDICATORS.items():
            need = I.get("min_baseline", MIN_PREFLIGHT)
            vals = list(telemetry.preflight_values(crew_id, ind).values())
            early = [] if I.get("scan") else list(telemetry.early_flight_values(crew_id, ind, EARLY_FLIGHT_DAYS).values())
            if len(vals) >= need:
                src, use = "preflight", vals
            elif len(early) >= need:
                src, use = "early_flight", early
            else:
                n = max(len(vals), len(early))
                hit[ind] = {"mean": None, "sd": None, "from": "learning", "n": n, "need": need, "confidence": "low"}
                continue
            hit[ind] = {"mean": round(statistics.mean(use), I["dp"]), "sd": max(statistics.pstdev(use), I["sd"]), "n": len(use), "from": src,
                        "confidence": confidence(len(use))}
            if I.get("adapts_in_flight"):
                fl = list(telemetry.inflight_values(crew_id, ind, A.value("adaptation.rebaseline_first"), A.value("adaptation.rebaseline_last")).values())
                if len(fl) >= A.value("adaptation.min_points"):
                    hit[ind]["inflight"] = {"mean": round(statistics.mean(fl), I["dp"]), "sd": max(statistics.pstdev(fl), I["sd"]), "n": len(fl),
                                            "days": [A.value("adaptation.rebaseline_first"), A.value("adaptation.rebaseline_last")],
                                            "confidence": confidence(len(fl))}
        _baselines[key] = hit
    return hit


def thresholds_by_indicator() -> dict:
    """Optional per-indicator override of the global thresholds: {"sleep": {"watch": 1.0, "act": 2.0}}. No screen yet."""
    return db.get_setting("thresholds_by_indicator", {})


# ---------------------------------------------------------------- levels from the history of readings
def _badness(z: Optional[float], direction: str) -> Optional[float]:
    if z is None:
        return None
    return -z if direction == "low" else z if direction == "high" else abs(z)


def indicator_level_series(points: Sequence, base: Optional[float] = None, sd: Optional[float] = None, direction: str = "both",
                           th: Optional[dict] = None, hysteresis: Optional[float] = None, persistence: Optional[int] = None,
                           max_gap: Optional[int] = None) -> List[dict]:
    """The alert level of one indicator on each measured day, from the history alone (a pure function: nothing is stored,
    so another module can persist the result as alert events).

    `points` are (day, value) pairs or dicts with `day`, `value` and optionally their own `base`, `sd` and these flags:
    `out` (outside the population range), `near` (inside a NASA early-warning step), `floor` (0, 1 or 2: a critical
    population bound or a NASA limit, which alerts at once), `suppress` (inside the microgravity adaptation window: the
    deviation raises no alert). Each point gives {"day", "value", "z", "bad", "raw", "level"}; `raw` is the level of that
    reading alone, `level` the one reported.

    z is the day's own value against the personal baseline and spread, never a smoothed value. Rules:
    - persistence: level 1 needs the watch condition on `persistence` (2) consecutive readings (no more than `max_gap` days
      apart); level 2 needs two in a row at the act threshold. A single reading beyond the act threshold is reported as level 1.
    - hysteresis: a level reached stays until the distance falls `hysteresis` (0.5 sd) below its entry threshold.
    - a `floor` skips both rules.
    """
    th = th or DEFAULT_THRESHOLDS
    h = A.value("z.hysteresis") if hysteresis is None else hysteresis
    need = A.value("z.persistence_readings") if persistence is None else persistence
    pts = sorted(({"day": p[0], "value": p[1]} if isinstance(p, (tuple, list)) else dict(p) for p in points), key=lambda p: p["day"])
    out: List[dict] = []
    prev_day: Optional[int] = None
    run1 = run2 = 0
    level = 0
    for p in pts:
        b, s = p.get("base", base), p.get("sd", sd)
        z = None if b is None or not s else (p["value"] - b) / s
        bad = _badness(z, direction)
        raw = 0 if bad is None else 2 if bad >= th["act"] else 1 if bad >= th["watch"] else 0
        raw = max(raw, 1 if p.get("out") or p.get("near") else 0)
        suppressed = bool(p.get("suppress"))
        if suppressed:
            raw, bad = 0, None
        floor = int(p.get("floor") or 0)
        raw = max(raw, floor)
        gap_ok = prev_day is not None and (max_gap is None or p["day"] - prev_day <= max_gap)
        run1 = run1 + 1 if raw >= 1 and gap_ok else 1 if raw >= 1 else 0
        run2 = run2 + 1 if raw >= 2 and gap_ok else 1 if raw >= 2 else 0
        entry = 2 if run2 >= need else 1 if run1 >= need or raw == 2 else 0
        held = 0
        if bad is not None and not suppressed:
            if level == 2 and bad >= th["act"] - h:
                held = 2
            elif level >= 1 and bad >= th["watch"] - h:
                held = 1
        elif p.get("out") and level >= 1 and not suppressed:
            held = 1
        level = max(entry, held, floor)
        out.append({"day": p["day"], "value": p["value"], "z": None if z is None else round(z, 3), "bad": None if bad is None else round(bad, 3),
                    "raw": raw, "level": level})
        prev_day = p["day"]
    return out


def _flight(day: int, location: Optional[str] = None) -> bool:
    """On or after launch and away from Earth."""
    return day >= 0 and (location or plan.location_at(day)) != "earth"


def _adapting(I: dict, day: int, location: Optional[str] = None) -> bool:
    """Inside the microgravity adaptation window (flight days 1 to 14) for an indicator flagged adapts_in_flight."""
    return bool(I.get("adapts_in_flight")) and _flight(day, location) and A.value("adaptation.first_day") <= day <= A.value("adaptation.last_day")


def _base_for(ind: str, I: dict, B: dict, day: int, location: Optional[str] = None) -> tuple:
    """(mean, sd, which) the z-score of a day reads: the in-flight re-baseline from flight day 15 for the indicators that
    adapt, else the pre-flight (or early-flight) normal. The exercise plan changes with the place, so exercise is compared
    with that day's plan when it is lower than the person's normal."""
    if I.get("adapts_in_flight") and B.get("inflight") and _flight(day, location) and day > A.value("adaptation.last_day"):
        return B["inflight"]["mean"], B["inflight"]["sd"], "inflight"
    mean = B["mean"]
    if ind == "exer" and mean is not None:
        mean = min(mean, EXERCISE_BY_PLACE[location or plan.location_at(day)][1])
    return mean, B["sd"], B["from"]


def indicator_levels(crew_id: str, ind: str, day: int, span: Optional[int] = None) -> List[dict]:
    """Per-day alert levels of one indicator up to `day` (see `indicator_level_series`): the function to persist as alert events."""
    ms = {"day": day, "location": plan.location_at(day), "learning": plan.location_at(day) == "earth" and day < 0}
    return _series(crew_id, ind, ms, thresholds(), span)[1]


_scache: Dict[tuple, tuple] = {}


def _series(crew_id: str, ind: str, ms: dict, th: dict, span: Optional[int] = None, upto: Optional[int] = None) -> tuple:
    """(points, levels) of the reading history ending on `upto` (default today). Cached per person, indicator, day, place and
    thresholds until the stored data, the plan or the person's check-ins change."""
    key = (crew_id, ind, ms["day"], ms["location"], ms["learning"], tuple(sorted(th.items())), span, upto, data.token(), plan.version(),
           telemetry.preflight_checkins(crew_id))
    hit = _scache.get(key)
    if hit is None:
        if len(_scache) > 20000:
            _scache.clear()
        hit = _scache[key] = _series_uncached(crew_id, ind, ms, th, span, upto)
    return hit


def _series_uncached(crew_id: str, ind: str, ms: dict, th: dict, span: Optional[int] = None, upto: Optional[int] = None) -> tuple:
    I, B, sex = INDICATORS[ind], baselines(crew_id)[ind], CREW_BY_ID[crew_id]["sex"]
    end = ms["day"] if upto is None else upto
    span = span or max(A.value("history.window_points"), 4 * (MEASURED_EVERY.get(ind, 1)))
    pre = B["mean"] if B["from"] == "preflight" else None
    pts = []
    for d, r in telemetry.day_readings(crew_id, ind, end - span, end).items():
        loc = ms["location"] if d == ms["day"] else plan.location_at(d)
        learning_d = ms["learning"] if d == ms["day"] else (loc == "earth" and d < 0)
        base, sd, _which = _base_for(ind, I, B, d, loc)
        pop = reference.check(ind, sex, r["value"])
        std = None if learning_d else standards.check(ind, crew_id, loc, r["value"], pre)
        pts.append({"day": d, "value": r["value"], "base": None if learning_d else base, "sd": sd,
                    "out": pop["status"] == "out" and not learning_d, "near": bool(std and std["level"] == 1),
                    "floor": 2 if pop["status"] == "critical" or (std and std["level"] == 2) else 0,
                    "suppress": _adapting(I, d, loc) and not learning_d})
    return pts, indicator_level_series(pts, direction=I["dir"], th=th, max_gap=I["max_age"])


def indicator(crew_id: str, ind: str, ms: dict, th: Optional[dict] = None, last: Optional[Dict[str, int]] = None,
              uv: Optional[dict] = None, by_ind: Optional[dict] = None) -> dict:
    th = {**(th or thresholds()), **(thresholds_by_indicator() if by_ind is None else by_ind).get(ind, {})}
    day = ms["day"]
    window = None if ms["learning"] else care.active(crew_id, day)  # inside the care window of a closed emergency: tighter, for this person only
    if window:
        f = care.sensitivity()["factor"]
        th = {k: v * f for k, v in th.items()}
    obs = telemetry.observation(crew_id, ind, day, uv)  # the day's own reading, or the last one with its age
    I = INDICATORS[ind]
    B = baselines(crew_id)[ind]
    base, sd, in_use = _base_for(ind, I, B, day, ms["location"])
    learning = base is None  # no normal of their own yet: only the population range and the NASA standard speak
    spread = I["sd"] if learning else sd
    in_flight = _flight(day, ms["location"])
    v = obs["value"] if telemetry.is_current(obs) else None
    out = {"id": ind, "name": I["name"], "unit": I["unit"], "area": I["area"], "facet": I.get("facet"), "dp": I["dp"]}
    meta = {"spread": round(spread, 3), "baseline_from": B["from"], "baseline_in_use": in_use, "baseline_n": B["n"], "n": B["n"],
            "confidence": B.get("confidence", "low"), "baseline_need": B.get("need"), "learning": learning,
            "baseline_preflight": B["mean"] if B["from"] == "preflight" else None,
            "baseline_inflight": B.get("inflight"), "adapts_in_flight": bool(I.get("adapts_in_flight")), "adapting": _adapting(I, day, ms["location"]),
            "scan": bool(I.get("scan")), **({"sensitive_until": window["sensitive_until"]} if window else {})}
    scan_in_flight = bool(I.get("scan")) and in_flight
    if v is None or scan_in_flight:  # no row at all, only stale ones, or a scan that cannot be taken on board: not a health finding
        seen_day = obs["day"]
        est = estimate(crew_id, ind, ms) if scan_in_flight else None
        return {**out, **meta, "value": None, "baseline": None if base is None else round(base, 3), "delta": None, "z": None, "bad": None,
                "level": 0, "raw_level": 0, "status": "no_data", "source": f"telemetry:{crew_id}:{ind}:day{day}", "origin": obs["origin"],
                "last_measured_day": seen_day, "age_days": obs["age_days"], "stale": obs["stale"], "measured_today": False,
                "last_value": None if obs["value"] is None else round(obs["value"], 2), "method": obs["method"], "context": obs["context"],
                "population": {"low": None, "high": None, "status": "no_data", "source": None, "verified": False}, "standard": None,
                **({"estimate": est, "inferred": True} if est else {})}
    z = bad = None if learning else 0.0
    if not learning:
        z = (v - base) / sd
        bad = _badness(z, I["dir"])
    pop = reference.check(ind, CREW_BY_ID[crew_id]["sex"], v)
    # NASA-STD-3001: an in-flight limit (strength, bone, aerobic capacity for EVA). Only in flight or after it: on Earth
    # before launch there is no in-mission limit to break. Percent-of-baseline limits read the PRE-FLIGHT baseline only.
    std = None if ms["learning"] else standards.check(ind, crew_id, ms["location"], v, B["mean"] if B["from"] == "preflight" else None)
    pts, levels = _series(crew_id, ind, ms, th, upto=obs["day"])
    if levels and levels[-1]["day"] == obs["day"]:
        level = levels[-1]["level"]  # persistence, hysteresis, adaptation window, critical bounds and NASA limits are all in the series
    else:
        level = 2 if pop["status"] == "critical" or (std and std["level"] == 2) else 0
    raw_level = 0 if ms["learning"] or learning or bad is None else 2 if bad >= th["act"] else 1 if bad >= th["watch"] else 0
    return {**out, **meta, "value": round(v, 2), "baseline": None if base is None else round(base, 3),
            "delta": None if base is None else round(v - base, 2),
            "z": None if z is None else round(z, 2), "bad": None if bad is None else round(bad, 2), "level": level, "raw_level": raw_level,
            "source": f"telemetry:{crew_id}:{ind}:day{day}",
            "origin": obs["origin"], "last_measured_day": obs["day"], "age_days": obs["age_days"], "stale": False,
            "measured_today": obs["age_days"] == 0, "method": obs["method"], "context": obs["context"], "readings_today": obs["readings"],
            "population": pop, "standard": std}


def estimate(crew_id: str, ind: str, ms: dict) -> Optional[dict]:
    """What an indicator that cannot be measured on board is inferred to be (bone density: from exercise and time in
    microgravity). Always labelled an estimate: origin "estimated", never a measurement."""
    if ind != "bone":
        return None
    e = bone_estimate(crew_id, ms["day"])
    if e is None:
        return None
    pre = baselines(crew_id)["bone"]
    out = {**e, "origin": "estimated", "label": "Estimate from exercise and time in microgravity, not a scan"}
    if pre["from"] == "preflight":
        out["value"] = round(pre["mean"] * (1 - e["loss_pct"] / 100), 3)
        out["unit"] = INDICATORS["bone"]["unit"]
    return out


def bone_estimate(crew_id: str, day: int) -> Optional[dict]:
    """Estimated % of weight-bearing bone density lost since launch, from the days in each gravity and the exercise the
    person logged (`exer`; the plan's minutes where nothing was logged). The model rates are in domain/assumptions.py."""
    if day < 1:
        return None
    key = (crew_id, day, data.token(), plan.version())
    hit = _bone_cache.get(key)
    if hit is None:
        if len(_bone_cache) > 4000:
            _bone_cache.clear()
        M = A.value("bone.model")
        logged = telemetry.day_values(crew_id, "exer", 0, day)
        loss, mins, n = 0.0, 0.0, 0
        for d in range(1, day + 1):
            loc = plan.location_at(d)
            m = logged.get(d, EXERCISE_BY_PLACE[loc][1])
            mins, n = mins + m, n + 1
            per_day = (M["max_pct_per_month"] - M["exercise_gain"] * min(1.0, m / M["exercise_full_min"])) / 30
            loss = max(0.0, loss + per_day * M["gravity_rate"][LOCATIONS[loc]["gravity_key"]])
        hit = _bone_cache[key] = {"loss_pct": round(loss, 2), "mean_exercise_min": round(mins / n, 1), "days": n,
                                  "model": "about 1% a month without countermeasures, reduced by logged exercise (domain/assumptions.py: bone.model)"}
    return hit


_bone_cache: Dict[tuple, dict] = {}


def indicators(crew_id: str, ms: dict) -> Dict[str, dict]:
    th = thresholds()
    last = telemetry.last_user_day(crew_id, ms["day"])
    uv = telemetry.user_values(crew_id, ms["day"], ms["day"])
    by_ind = thresholds_by_indicator()
    out = {i: indicator(crew_id, i, ms, th, last, uv, by_ind) for i in INDICATORS}
    # `bp` is the old name of the systolic pressure: kept in the output for readers that still ask for it (not a second indicator).
    out["bp"] = {**out["sbp"], "id": "bp", "alias_of": "sbp"}
    return out


def latest_checkin(crew_id: str, kind: str, day: int, window: int = 7) -> Optional[dict]:
    rows = db.q("SELECT payload,day FROM checkins WHERE crew_id=? AND kind=? AND day<=? AND day>? ORDER BY id DESC LIMIT 1",
                (crew_id, kind, day, day - window))
    return {**json.loads(rows[0]["payload"]), "day": rows[0]["day"]} if rows else None


def dose(ms: dict, crew_id: Optional[str] = None) -> dict:
    """Mission dose in mSv: the cabin dosimeter, or the plan where it has no reading (dose.py), the same for everyone on
    board. With a crew member, it counts that person's own dosimeter first, and adds their career dose: NASA's 600 mSv
    limit counts every earlier flight (NASA-STD-3001 Vol 1, 4.2.10 [V1 4030]). The effective dose is approximated by the
    dosimeter's dose equivalent; the organ-weighted model is not applied. The 30-day and 365-day totals are tracked only."""
    d = dose_mod.mission(crew_id, ms["day"], ms["location"])
    total = d["msv"]
    out = {"mission_msv": total, "rate_msv_day": LOCATIONS[ms["location"]]["dose_rate"],
           "career_limit_msv": CAREER_LIMIT_MSV, "pct_of_limit": round(100 * total / CAREER_LIMIT_MSV, 1),
           "simulated": d["simulated"], "limit_source": "NASA-STD-3001 Vol 1, 4.2.10 [V1 4030]",
           "origin": d["origin"], "measured_days": d["measured_days"], "estimated_days": d["estimated_days"],
           "model": A.value("dose.model_note"), "windows": dose_mod.windows(crew_id, ms["day"]),
           "spe_design_reference_msv": SPE_LIMIT_MSV, "spe_events": dose_mod.events_vs_design(ms["day"])}
    if crew_id is not None:
        prior = standards.prior_dose(crew_id)
        c = dose_mod.career(crew_id, ms["day"], prior, ms["location"])
        proj = dose_mod.projection(crew_id, ms["day"], prior["msv"])
        out.update(prior_msv=prior["msv"], prior_estimate=prior["estimate"], prior_source=prior["source"],
                   career_msv=c["msv"], career_pct_of_limit=c["pct"], career_origin=c["origin"],
                   projected_career_msv=proj["projected_career_msv"], exceeds_career_limit=proj["exceeds_career_limit"])
    return out


def storm_info(crew_id: Optional[str], ms: dict) -> Optional[dict]:
    """The storm of the day with the decision to shelter: {"event", "shelter"}, or None when there is none."""
    if not ms.get("storm"):
        return None
    ev = dose_mod.active_event(ms["day"], ms["location"]) or data.storm_event(ms["day"], ms["location"])
    ev = ev or {"id": None, "kind": ms["storm"], "origin": "simulated", "source": "simulated", "start_day": ms["day"], "extra_dose_msv": 0.0, "note": ""}
    return {"event": ev, "shelter": dose_mod.shelter(crew_id, ms["day"], ms["location"], ev)}


def systems(crew_id: str, ms: dict, inds: Dict[str, dict], risks: Optional[List[dict]] = None) -> Dict[str, dict]:
    """Colour of each body system: the highest level among the risks that act on it. One indicator outside your
    normal, with no risk behind it, is a watch (level 1) at most, unless it is past the population safety limit."""
    risks = risks or []
    out = {}
    for sid, S in SYSTEMS.items():
        worst = max([inds[i]["level"] for i in S["indicators"]] or [0])
        critical = any(inds[i]["population"]["status"] == "critical" or (inds[i].get("standard") or {}).get("level") == 2
                       for i in S["indicators"])
        lv = 2 if critical else max(risk.level_for(risks, sid), min(1, worst))
        note = None
        if sid == "eyes":
            a = latest_checkin(crew_id, "amsler", ms["day"])
            if a and a.get("distortion"):
                lv, note = 2, "Wavy or missing lines on the last Amsler grid."
            elif a:
                note = "Last Amsler grid was clear."
        if sid == "skin":
            d = dose(ms, crew_id)
            si = storm_info(crew_id, ms)
            if si:
                order = si["shelter"]["order"]
                lv = 2 if order else max(lv, 1)
                note = "Radiation storm in progress." if order else "A space-weather event is active; the dose rate is below the shelter threshold."
            elif d["career_pct_of_limit"] >= 100:
                lv, note = 2, f"Career dose {d['career_msv']:g} mSv, past NASA's 600 mSv limit."
            elif d["career_pct_of_limit"] >= 50:
                lv, note = max(lv, 1), f"{d['career_pct_of_limit']}% of the career limit used, earlier flights included."
        if sid == "skeleton" and inds["bone"].get("inferred"):
            e = inds["bone"]["estimate"]
            note = f"Not measurable on board. Estimated loss {e['loss_pct']:g}% since launch from exercise and time in 0 g (an estimate, not a scan)."
        if sid == "immune" and not ms["learning"] and data.storms_following(ms["day"], risk.RULES["immune"]["storm_follow_days"]):
            lv, note = max(lv, 1), "Blood count due after the radiation storm."
        if ms["learning"]:  # nothing to watch yet, except a safety limit
            lv = 2 if any(inds[i]["population"]["status"] == "critical" for i in S["indicators"]) else 0
        no_data = bool(S["indicators"]) and all(inds[i].get("status") == "no_data" for i in S["indicators"])
        if no_data and lv == 0 and not note:  # nothing measured (or only stale readings): say so, it is not a finding
            note = "No data yet"
        out[sid] = {"id": sid, "name": S["name"], "area": S["area"], "level": lv, "status": STATUS[lv], "no_data": no_data,
                    "indicators": S["indicators"], "note": note,
                    "risks": [r["id"] for r in risks if sid in r["systems"] and r["level"]]}
    return out


def score(inds: Dict[str, dict], area: str, syss: Dict[str, dict]) -> Optional[int]:
    """Readiness 0 to 100. Prototype assumption (numbers in domain/assumptions.py, readiness.*): each indicator loses points
    for every spread beyond a free distance from its own normal, the area is their mean, and physical loses points per level
    of eyes, skin and immune (no indicators of their own). The formula is a design choice, not a published score."""
    free, per, pen = A.value("readiness.free_spread"), A.value("readiness.points_per_spread"), A.value("readiness.system_penalty")
    vals = [max(0.0, min(100.0, 100 - per * max(0.0, i["bad"] - free))) for i in inds.values()
            if i["area"] == area and i["bad"] is not None and not i.get("alias_of")]
    if not vals:  # nothing measured in this area: no score (never a made-up one)
        return None
    s = sum(vals) / len(vals)
    if area == "physical":
        s -= pen * sum(x["level"] for k, x in syss.items() if k in ("eyes", "skin", "immune"))
    return int(round(max(0, min(100, s))))


def _indicator_alert(i: str, d: dict) -> dict:
    """Alert for one indicator on its own: outside the personal normal, or past the population safety limit."""
    sysid = next((k for k, s in SYSTEMS.items() if i in s["indicators"]), None)
    p = d["population"]
    std = d.get("standard") or {}
    critical = p["status"] == "critical"
    if i == "bone":  # a DXA scan, read against the pre-flight scan
        why = (f"The scan reads {d['value']:.2f} {d['unit']}, {100 * d['value'] / d['baseline']:.1f} % of your pre-flight scan." if d["baseline"]
               else f"The scan reads {d['value']:.2f} {d['unit']}.")
    else:
        why = (f"Today {d['value']:.{d['dp']}f} {d['unit']}. Your normal is {d['baseline']:.{d['dp']}f} {d['unit']}." if d["baseline"] is not None
               else f"Today {d['value']:.{d['dp']}f} {d['unit']}. Canary is still learning your normal.")
    if p["status"] != "in" and (p["low"] is not None or p["high"] is not None):
        lo = "no lower limit" if p["low"] is None else f"from {p['low']:g}"
        hi = "no upper limit" if p["high"] is None else f"up to {p['high']:g}"
        why += f" The usual adult range is {lo} {hi} {d['unit']}."
    sources = [d["source"]]
    if std.get("level"):
        why += f" {std['text']} (NASA-STD-3001 {std['item']})."
        sources.append(f"nasa:std3001v1:{std['item'].replace(' ', '')}")
    title = (f"{d['name']} is past the safety limit." if critical else
             f"{d['name']} is past NASA's limit." if std.get("level") == 2 else
             f"{d['name']} is close to NASA's limit." if std.get("level") == 1 and (d["bad"] is None or d["bad"] < DEFAULT_THRESHOLDS["watch"]) else
             f"{d['name']} is outside your normal.")
    todo = TODO_BY_INDICATOR.get(i, ["Measure again in 1 hour", "If it stays, tell the medical officer"])
    if i == "vo2" and std.get("level"):
        todo = ["No EVA until a new aerobic test meets the limit", "Add interval sessions on the bike or treadmill", "The medical officer reviews the test"]
    return {"id": f"ind_{i}", "level": d["level"], "sys": sysid, "title": title, "why": why, "todo": todo,
            "sources": sources, "goals": [], **({"standard": std} if std.get("level") else {})}


# What each alert goal is meant to move, and after how many days it is checked (see domain/advice.py).
# Prototype assumptions: no published rule says how long a habit takes to show in a number.
ALERT_GOAL_VERIFY = {
    "al_light": ("sleep", 3), "al_screens": ("sleep", 3), "al_psy": ("mood", 7), "al_sip": ("water", 1),
    "al_head": ("hr", 2), "al_salt": ("sbp", 3), "al_stand": ("sbp", 3), "al_talk": ("mood", 7),
}
# Which risk each alert belongs to, and which evidence keys of the hazard matrix it rests on. The ids and texts of the
# alerts do not change; they only gain `risk`, `hazards` (possible factors, never a cause) and `hazard_note`.
ALERT_RISK = {"storm": "radiation", "sickness": "renal", "regravity": "cardio", "amsler": "sans", "behaviour": "fatigue",
              "wellbeing": "fatigue", "sleepy": "fatigue", "missing_mood": "fatigue", "symptoms": None}
ALERT_KEYS = {"storm": ["dose"], "sickness": ["hr", "water", "exer", "mood"], "regravity": ["sbp", "dbp", "hr"], "amsler": ["amsler"],
              "wellbeing": ["mood"], "sleepy": ["kss"], "missing_mood": ["mood"], "symptoms": []}
ALERT_LOOKBACK = 60  # days days_active looks back; a longer episode reads "at least this long"
_alert_cache: Dict[tuple, frozenset] = {}


def _alert_ids(crew_id: str, day: int, tok: tuple) -> frozenset:
    """Ids of the alerts that were active on a (past) day, from that day's data. Cached per person, day and entered data."""
    key = (crew_id, day, tok)
    hit = _alert_cache.get(key)
    if hit is None:
        if len(_alert_cache) > 4000:
            _alert_cache.clear()
        ms = risk._day_ms(day)
        hit = _alert_cache[key] = frozenset(a["id"] for a in _alerts(crew_id, ms, indicators(crew_id, ms), risk.evaluate(crew_id, ms, tok)))
    return hit


def _alert_since(crew_id: str, day: int, aid: str, tok: tuple) -> int:
    """First day of the unbroken stretch in which alert `aid` was active up to `day`. Walks back, never stored."""
    d, stop = day, day - ALERT_LOOKBACK
    while d > stop and aid in _alert_ids(crew_id, d - 1, tok):
        d -= 1
    return d


def alerts(crew_id: str, ms: dict, inds: Dict[str, dict], risks: Optional[List[dict]] = None) -> List[dict]:
    """The alerts of the day, each with how long it has been active (`since_day`, `days_active`) and whether the
    person has marked this episode as seen. An alert that goes away and comes back is a new episode, not seen."""
    risks = risk.evaluate(crew_id, ms) if risks is None else risks
    AL = _alerts(crew_id, ms, inds, risks)
    for a in AL:
        rid = a["id"][4:] if a["id"].startswith("ind_") else None
        a["risk"] = ALERT_RISK[a["id"]] if a["id"] in ALERT_RISK else risk.INDICATOR_RISK.get(rid)
        parent = risk.get(risks, a["risk"]) if a["id"] == "behaviour" else None
        ids, _links = (parent["hazards"], parent["hazard_links"]) if parent else risk.hazards_for(ALERT_KEYS.get(a["id"], [rid] if rid else []), {**ms, "location": ms["location"]})
        a["hazards"], a["hazard_note"] = ids, risk.hazard_note(ids)
    tok = risk._token(crew_id)
    seen = db.get_setting("alerts_seen", {})
    for a in AL:
        since = ms["day"] if a["id"] == "storm" else _alert_since(crew_id, ms["day"], a["id"], tok)
        a.update({"since_day": since, "days_active": ms["day"] - since + 1, "seen": f"{crew_id}:{a['id']}:{since}" in seen})
        for g in a.get("goals", []):
            if g["id"] in ALERT_GOAL_VERIFY:
                g["verify"] = dict(zip(("indicator", "after_days"), ALERT_GOAL_VERIFY[g["id"]]))
    return AL


def mark_seen(crew_id: str, alert: dict, day: int) -> None:
    seen = db.get_setting("alerts_seen", {})
    seen[f"{crew_id}:{alert['id']}:{alert['since_day']}"] = day
    db.set_setting("alerts_seen", seen)


STORM_TITLE = {"sep": "A solar particle event is in progress.", "mars": "A radiation storm is in progress at the Mars surface."}
STORM_KIND = {"sep": "solar particle event", "mars": "Mars surface radiation storm"}
STORM_BASIS = {"real": "recorded by NASA", "donki": "NASA DONKI, live", "simulated": "simulated"}


def storm_text(si: dict) -> str:
    """What is known about the storm, only from the event and the dosimeter: kind, start date, source, origin, the measured
    rate, the estimated dose against the design reference, and the decision with its rule."""
    ev, sh = si["event"], si["shelter"]
    parts = []
    start = None
    try:
        from . import mission
        start = mission.launch_date() + __import__("datetime").timedelta(days=int(ev["start_day"]))
    except Exception:  # noqa: BLE001  no launch date registered: say the mission day only
        pass
    when = f"{start.strftime('%-d %B %Y')} (mission day {ev['start_day']})" if start else f"mission day {ev['start_day']}"
    parts.append(f"A {STORM_KIND.get(ev['kind'], ev['kind'])} started on {when}. Source: {ev['source']}, {STORM_BASIS.get(ev['origin'], ev['origin'])}."
                 + (f" {ev['note']}." if ev.get("note") and not str(ev["note"]).endswith(".") else f" {ev['note']}" if ev.get("note") else ""))
    if sh["basis"] == "dosimeter":
        parts.append(f"The {sh['dosimeter']} dosimeter reads {sh['rate_msv_day']:g} mSv/day, {sh['ratio']:g} times the quiet rate of this place "
                     f"({sh['quiet_msv_day']:g} mSv/day).")
    if ev["kind"] == "sep" and ev.get("extra_dose_msv"):
        d = dose_mod.event_dose(ev)
        parts.append(f"Estimated event dose {d['dose_msv']:g} mSv, {d['pct_of_design_reference']:g}% of the {d['design_reference_msv']:g} mSv design reference "
                     "for a solar particle event (NASA-STD-3001 V1 4031, a design reference, not a personal limit).")
    if sh["order"]:
        parts.append(f"Shelter ordered: the dose rate is above {sh['threshold_msv_day']:g} mSv/day ({sh['assumption']}).")
    elif sh["attenuated"]:
        parts.append(f"In Earth orbit the magnetosphere attenuates these particles: no shelter unless the cabin dosimeter passes {sh['threshold_msv_day']:g} mSv/day.")
    else:
        parts.append(f"No shelter ordered yet: the dose rate is not above {sh['threshold_msv_day']:g} mSv/day. Keep reading the dosimeter.")
    return " ".join(parts)


def _storm_alert(si: dict) -> dict:
    ev, order = si["event"], si["shelter"]["order"]
    todo = (["Go to the shelter and stay until the alert ends", "No activity outside today", "Write down your dosimeter reading"] if order else
            ["Read the dosimeter now and again in an hour", "Postpone any EVA until the rate is back to normal", "Tell the medical officer"])
    return {"id": "storm", "level": 2 if order else 1, "env": True, "escalate": True, "recipients": ["cmo", "earth"], "sys": "skin", "protocol": "rad",
            "title": STORM_TITLE.get(ev["kind"], "A radiation event is in progress."), "why": storm_text(si), "todo": todo,
            "sources": [ev["source"]] + ([f"space_event:{ev['id']}"] if ev.get("id") else []), "origin": ev["origin"],
            "shelter": si["shelter"], "goals": []}


def _alerts(crew_id: str, ms: dict, inds: Dict[str, dict], risks: Optional[List[dict]] = None) -> List[dict]:
    """Cross-signal rules first, then single indicators that are left. Each alert says what to do."""
    if ms["learning"]:  # no early warnings while Canary learns the baseline; a safety limit still speaks
        return [_indicator_alert(i, d) for i, d in inds.items() if d["population"]["status"] == "critical"]
    risks = risk.evaluate(crew_id, ms) if risks is None else risks
    AL, used = [], set()
    lv = lambda i: inds[i]["level"]  # noqa: E731
    c = CREW_BY_ID[crew_id]
    place = LOCATIONS[ms["location"]]

    si = storm_info(crew_id, ms)
    if si:
        AL.append(_storm_alert(si))

    fat = risk.get(risks, "fatigue")
    if fat and fat["level"] == 2:  # the fatigue risk decides; this alert is its voice
        used.update(["sleep", "mood", "react", "stress", "social", "dsst", "span", "kss", "tlx"])
        ev = fat["evidence"]
        classic = all(inds[i]["level"] and inds[i]["value"] is not None and inds[i]["baseline"] is not None
                      for i in ("sleep", "mood", "react"))  # the familiar text, when its three signals are all up
        why = (f"For two weeks you have slept {inds['sleep']['baseline'] - inds['sleep']['value']:.1f} h less than your normal, "
               f"you react {inds['react']['value'] - inds['react']['baseline']:.0f} ms slower and spend less time with the crew."
               if classic else
               "Several signals are away from your normal at once: " + "; ".join(e["text"].lower() for e in ev[:2]) + ".")
        AL.append({"id": "behaviour", "level": 2, "sys": "brain", "test": "pvt", "risk": "fatigue",
                  "title": "Sleep, mood and focus are dropping together.",
                  "why": why,
                  "todo": ["Hand over any critical task today", "Retake the reaction test before any decision", "Follow the 3-night sleep plan"],
                  "sources": [inds[i]["source"] for i in ("sleep", "mood", "react")] if classic else [e["source"] for e in ev[:3]],
                  "goals": [{"id": "al_light", "area": "mental", "title": "Bright light on waking, amber light 2 h before bed"},
                            {"id": "al_screens", "area": "mental", "title": "No screens after 21:00 for 3 nights"},
                            {"id": "al_psy", "area": "mental", "title": "Record a private message for the mission psychologist"}]})

    # space sickness: the pulse is high AND water is low. The pulse is held back from alerts inside the adaptation window
    # (it is expected there), so this reads its raw deviation; the alert says it is the expected pattern.
    if ms["location"] == "rocket" and (lv("hr") or inds["hr"].get("raw_level")) and lv("water"):
        used.update(["hr", "water", "exer", "mood"])
        AL.append({"id": "sickness", "level": 1, "sys": "kidneys",
                  "title": "Space sickness. It usually passes in 2 to 3 days.",
                  "why": "Your pulse is high and you have barely had water in your first hours in 0 g. Most astronauts go through this.",
                  "todo": ["Take a small sip of water every 15 minutes", "Move your head slowly and fix your eyes on one point",
                           "Tell the medical officer if you vomit more than twice"],
                  "sources": [inds["hr"]["source"], inds["water"]["source"]],
                  "goals": [{"id": "al_sip", "area": "physical", "title": "A sip of water every 15 minutes until dinner"},
                            {"id": "al_head", "area": "physical", "title": "Slow head movements, 5 min, three times today"}]})

    if place["gravity_key"] == "gp" and (lv("sbp") or lv("dbp")) and lv("hr"):
        used.update(["sbp", "dbp", "hr"])
        AL.append({"id": "regravity", "level": 1, "sys": "heart",
                  "title": "Your body is relearning weight.",
                  "why": "Lower pressure and a faster pulse than your normal when you stand. Expected in the first weeks after months in 0 g.",
                  "todo": ["Stand up in two steps: sit, wait, then stand", "Salted water in the morning", "No solo suited walks this week"],
                  "sources": [inds["sbp"]["source"], inds["hr"]["source"]],
                  "goals": [{"id": "al_salt", "area": "physical", "title": "500 mL of salted water on waking"},
                            {"id": "al_stand", "area": "physical", "title": "Measure pressure lying down and standing"}]})

    am = latest_checkin(crew_id, "amsler", ms["day"])
    if am and am.get("distortion"):
        AL.append({"id": "amsler", "level": 2, "sys": "eyes", "title": "Wavy lines on the Amsler grid.",
                  "why": "It can signal a change at the back of the eye, which is linked to fluid shift in 0 g.",
                  "todo": ["Repeat the test tomorrow at the same time", "Send an eye photo to Earth"],
                  "sources": [f"checkin:{crew_id}:amsler:day{am['day']}"], "goals": []})

    wb = latest_checkin(crew_id, "wellbeing", ms["day"], window=14)
    if wb and max(wb.get("phq2", 0), wb.get("gad2", 0)) >= 3:
        AL.append({"id": "wellbeing", "level": 1, "sys": "brain", "title": "Your answers point to a hard stretch.",
                  "why": "Low mood or worry on more than half the days of the last two weeks. That is common on long missions and it helps to say it out loud.",
                  "todo": ["Talk to the medical officer this week", "Record a private message for the mission psychologist", "Protect your sleep window"],
                  "sources": [f"checkin:{crew_id}:wellbeing:day{wb['day']}"],
                  "goals": [{"id": "al_talk", "area": "mental", "title": "Book 15 minutes with the medical officer"}]})

    kss = latest_checkin(crew_id, "kss", ms["day"], window=1)
    if kss and int(kss.get("level", 0)) >= 7:
        AL.append({"id": "sleepy", "level": 1, "sys": "brain", "title": "You rated yourself very sleepy.",
                  "why": "On the Karolinska scale, 7 or more means reactions are slower than they feel.",
                  "todo": ["Hand over critical or precise work for now", "Take a 20-minute nap if the schedule allows", "Retake the reaction test after resting"],
                  "sources": [f"checkin:{crew_id}:kss:day{kss['day']}"], "goals": []})

    sy = latest_checkin(crew_id, "symptoms", ms["day"], window=2)
    if sy and int(sy.get("severity", 0)) >= 3 and sy.get("items"):
        AL.append({"id": "symptoms", "level": 1, "sys": None, "title": f"You reported strong {', '.join(sy['items'][:2]).lower()}.",
                  "why": "Strong symptoms are worth a look even when the sensors look normal.",
                  "todo": ["Tell the medical officer today", "Log it again tomorrow so the trend is clear"],
                  "sources": [f"checkin:{crew_id}:symptoms:day{sy['day']}"], "goals": []})

    from . import goals  # late import: goals imports health
    day = ms["day"]
    log = goals._log(crew_id)
    if not any(goals.is_done(crew_id, "mood", d, day, log) for d in (day, day - 1, day - 2)):
        AL.append({"id": "missing_mood", "level": 1, "data": True, "sys": "brain", "test": "mood",
                  "title": "No mood check-in for 3 days.",
                  "why": "Canary reads your mood and stress less well without a check-in, and the numbers can look better than the days feel. Nothing is wrong with skipping; days get busy.",
                  "todo": ["A 30-second mood check-in is enough", "Add a line about why if you want the medical team to know"],
                  "sources": [f"goal:{crew_id}:mood:day{day}"], "goals": []})

    for i, d in inds.items():
        if d.get("alias_of"):  # the old name of the systolic pressure: its alert is the one of `sbp`
            continue
        if d["level"] and (i not in used or d["population"]["status"] == "critical" or (d.get("standard") or {}).get("level") == 2):
            AL.append(_indicator_alert(i, d))
    return sorted(AL, key=lambda a: -a["level"])


def snapshot(crew_id: str, ms: dict) -> dict:
    """Everything health-related for one person at the current mission time."""
    inds = indicators(crew_id, ms)
    risks = risk.evaluate(crew_id, ms)
    syss = systems(crew_id, ms, inds, risks)
    al = alerts(crew_id, ms, inds, risks)
    areas = {}
    for area in ("physical", "mental"):
        lvl = max([s["level"] for s in syss.values() if s["area"] == area] + [i["level"] for i in inds.values() if i["area"] == area] + [0])
        areas[area] = {"score": score(inds, area, syss), "level": lvl, "status": STATUS[lvl]}
    top = max([a["level"] for a in al if not a.get("data")] + [0])  # missing data is not a health risk
    no_data = all(i.get("status") == "no_data" for i in inds.values())  # not one current value
    return {"crew_id": crew_id, "day": ms["day"], "no_data": no_data, "indicators": inds, "systems": syss, "alerts": al, "risks": risks, "areas": areas,
            "level": top, "status": STATUS[top], "dose": dose(ms, crew_id)}
