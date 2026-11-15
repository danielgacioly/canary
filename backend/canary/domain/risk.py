"""Risks: a level, the evidence behind it, a trend and the day it started.

A single alert looks at one signal (or a fixed combination). A risk adds up everything Canary knows about one
NASA risk area for one person, against that person's own normal, and says how sure it is: level 0 / 1 / 2.

Eight risks: `fatigue` (behavioural health and performance), `radiation`, `sans` (vision), `nutrition`, `renal`,
`immune`, `cardio` and `bone_muscle`. Four are NASA's red risks for Mars (Patel et al., npj Microgravity 2020):
radiation, SANS, behavioural health and nutrition (`nasa_red`). Each risk reads only data Canary already has, says
how old and how real that data is (`data`), and names the hazards that are possible factors (`hazards`).
To add one: an entry in `SPECS` and an evidence function in `GATHER`.

Rules, not a model: every number below is a data table that a person can read, review and change. Nothing here
is learned, and nothing is stored: a risk is a function of the day, so the demo clock can jump anywhere.
"""
import json
import math
from typing import Dict, List, Optional, Tuple

from .. import db
from . import assumptions as A
from . import care, catalog, data, dose, plan

# ---------------------------------------------------------------- tables (prototype assumption)
# Every weight and cut below is a prototype assumption kept in domain/assumptions.py: no published model sums these
# signals. They are chosen so that two weeks of several signals slipping together reach level 2, and one bad night or one
# noisy test does not.
FATIGUE = {
    "source": "prototype assumption", "verified": False,
    # points of an indicator = weight x its level (0, 1 or 2) against the person's own normal
    "weights": A.value("fatigue.weights"),
    # check-in evidence: wellbeing = PHQ-2 or GAD-2 of 3 or more in the last 14 days; missing_mood = no mood check-in for 3 days
    "checkins": A.value("fatigue.checkins"),
    # a slow slide still inside the normal range adds this much per indicator, at most `cap` in all
    "drift": A.value("fatigue.drift"),
    "cuts": A.value("fatigue.cuts"),   # score needed for level 1 and level 2
    "min_signals_level_2": A.value("fatigue.min_signals_level_2"),   # distinct signals (indicators and check-ins, not drift) needed for level 2
    "sustained_days": A.value("fatigue.sustained_days"),   # level 2 also needs level 1 or more two days earlier: a bad night alone is never level 2
    "trend": A.value("fatigue.trend"),  # score now against 3 days ago: rising / falling beyond +-0.5
    "lookback_days": A.value("fatigue.lookback_days"),   # how far back since_day looks
}
DRIFT = {"source": "prototype assumption", "verified": False, **A.value("drift")}  # days fitted, days looked ahead, spreads per day the line must climb

NAMES = {"fatigue": "Behavioural health and performance"}


# ---------------------------------------------------------------- cache
_cache: Dict[tuple, dict] = {}


def _token(crew_id: str) -> tuple:
    """Everything a risk reads that can change without the day changing."""
    from . import health
    c = db.q("SELECT COUNT(*) n, COALESCE(MAX(id),0) m, COALESCE(SUM(day),0) d, COALESCE(SUM(LENGTH(payload)),0) p FROM checkins WHERE crew_id=?", (crew_id,))[0]
    g = db.q("SELECT COUNT(*) n, COALESCE(SUM(done),0) d, COALESCE(SUM(day),0) s FROM goal_log WHERE crew_id=?", (crew_id,))[0]
    return (plan.version(), data.token(), json.dumps(health.thresholds(), sort_keys=True), json.dumps(health.thresholds_by_indicator(), sort_keys=True),
            c["n"], c["m"], c["d"], c["p"], g["n"], g["d"], g["s"], care.token(crew_id))


def clear_cache() -> None:
    _cache.clear()
    _gcache.clear()
    _inds_cache.clear()


def _day_ms(day: int) -> dict:
    loc = plan.location_at(day)
    return {"day": day, "location": loc, "learning": loc == "earth" and day < 0, "storm": None}


# ---------------------------------------------------------------- drift
def fit(ys: List[float]) -> Tuple[float, float]:
    """Least-squares line through ys at x = 0..n-1: (slope, value at the last x)."""
    n = len(ys)
    mx, my = (n - 1) / 2, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in range(n))
    b = sum((x - mx) * (y - my) for x, y in enumerate(ys)) / sxx if sxx else 0.0
    return b, my + b * (n - 1 - mx)


def drift_of(bad: List[float], limit: float) -> Optional[dict]:
    """Does the line through the last days of one indicator (as "badness" in personal spreads, higher is worse)
    cross `limit` within DRIFT["horizon"] days? None when it does not, or when it is already past it."""
    if len(bad) < 3:
        return None
    slope, end = fit(bad)
    if slope < DRIFT["min_slope"] or end >= limit:
        return None
    days = math.ceil((limit - end) / slope)
    return {"slope": round(slope, 3), "days_to_limit": days} if days <= DRIFT["horizon"] else None


def drift(crew_id: str, ind: str, day: int, base: float, sd: float, limit: float) -> Optional[dict]:
    """Drift of one indicator over the last DRIFT["window"] days, from the same series the charts show."""
    from . import telemetry
    from .catalog import INDICATORS
    sign = {"low": -1.0, "high": 1.0}.get(INDICATORS[ind]["dir"])
    if sign is None:
        return None
    if base is None or sd is None:  # no normal of their own yet: nothing to drift from
        return None
    ys = [sign * (v - base) / sd for _d, v in telemetry.series(crew_id, ind, day, DRIFT["window"]) if v is not None]  # a gap is no point
    return drift_of(ys, limit)


# ---------------------------------------------------------------- fatigue
def _fmt(v: float, dp: int) -> str:
    return f"{v:.{dp}f}"


def _fatigue(crew_id: str, day: int) -> dict:
    """Score, evidence and signal count of the fatigue risk on one day (no trend, no since_day)."""
    from . import goals, health, telemetry
    ms = _day_ms(day)
    out = {"score": 0.0, "evidence": [], "signals": 0, "level_raw": 0}
    if ms["learning"]:
        return out
    th, by_ind = health.thresholds(), health.thresholds_by_indicator()
    last = telemetry.last_user_day(crew_id, day)
    uv = telemetry.user_values(crew_id, day, day)
    ev, signals, drift_pts = [], 0, 0.0
    for ind, w in FATIGUE["weights"].items():
        d = health.indicator(crew_id, ind, ms, th, last, uv, by_ind)
        if d["value"] is None:  # no current reading: an absent signal adds nothing
            continue
        base = {"indicator": ind, "value": d["value"], "baseline": d["baseline"], "z": d["z"], "origin": d["origin"], "source": d["source"]}
        if d["level"]:
            if d["delta"] is None:  # no normal of their own yet: only a safety limit speaks
                text = f"{d['name']} {_fmt(d['value'], d['dp'])} {d['unit']}, outside the safe range"
            else:
                text = (f"{d['name']} {_fmt(d['value'], d['dp'])} {d['unit']}, {_fmt(abs(d['delta']), d['dp'])} {d['unit']} "
                        f"{'above' if d['delta'] > 0 else 'below'} your normal")
            ev.append({**base, "points": round(w * d["level"], 2), "text": text})
            signals += 1
        elif drift_pts < FATIGUE["drift"]["cap"]:
            lim = {**th, **by_ind.get(ind, {})}["watch"]
            dr = drift(crew_id, ind, day, d["baseline"], d["spread"], lim)
            if dr:
                pts = min(FATIGUE["drift"]["weight"], FATIGUE["drift"]["cap"] - drift_pts)
                drift_pts += pts
                ev.append({**base, "points": round(pts, 2), "drift": dr,
                           "text": f"{d['name']} is drifting towards your limit (about {dr['days_to_limit']} days at this pace)"})
    wb = health.latest_checkin(crew_id, "wellbeing", day, window=14)
    if wb and max(wb.get("phq2", 0), wb.get("gad2", 0)) >= 3:
        ev.append({"checkin": "wellbeing", "value": max(wb.get("phq2", 0), wb.get("gad2", 0)), "baseline": None, "z": None, "origin": "user",
                   "source": f"checkin:{crew_id}:wellbeing:day{wb['day']}", "points": FATIGUE["checkins"]["wellbeing"],
                   "text": "Wellbeing answers point to a hard stretch"})
        signals += 1
    log = goals._log(crew_id)
    if not any(goals.is_done(crew_id, "mood", d, day, log) for d in (day, day - 1, day - 2)):
        ev.append({"checkin": "missing_mood", "value": None, "baseline": None, "z": None, "origin": "user",
                   "source": f"goal:{crew_id}:mood:day{day}", "points": FATIGUE["checkins"]["missing_mood"],
                   "text": "No mood check-in for 3 days"})
        signals += 1
    score = round(sum(e["points"] for e in ev), 2)
    ev.sort(key=lambda e: -e["points"])
    level = 2 if score >= FATIGUE["cuts"][2] and signals >= FATIGUE["min_signals_level_2"] else 1 if score >= FATIGUE["cuts"][1] else 0
    return {"score": score, "evidence": ev, "signals": signals, "level_raw": level}


def _eval(crew_id: str, day: int, tok: Optional[tuple] = None) -> dict:
    """One day of the fatigue risk, cached per person, day and everything the person has entered."""
    tok = tok or _token(crew_id)
    key = (crew_id, day, tok)
    hit = _cache.get(key)
    if hit is None:
        if len(_cache) > 4000:
            _cache.clear()
        r = _fatigue(crew_id, day)
        level = r["level_raw"]
        early = day - FATIGUE["sustained_days"]
        if level == 2 and early >= 0 and _eval(crew_id, early, tok)["level_raw"] < 1:
            level = 1  # a bad night alone is never level 2: it has to have been building
        hit = _cache[key] = {**r, "level": level}
    return hit


def _since(crew_id: str, day: int, tok: tuple) -> Optional[int]:
    """First day of the unbroken stretch at level 1 or more that ends on `day`. Walks back, never stored."""
    if _eval(crew_id, day, tok)["level"] < 1:
        return None
    d = day
    stop = max(0, day - FATIGUE["lookback_days"])
    while d > stop and _eval(crew_id, d - 1, tok)["level"] >= 1:
        d -= 1
    return d


def _trend(crew_id: str, day: int, tok: tuple) -> str:
    t = FATIGUE["trend"]
    delta = _eval(crew_id, day, tok)["score"] - _eval(crew_id, day - t["days"], tok)["score"]
    return "rising" if delta >= t["delta"] else "falling" if delta <= -t["delta"] else "stable"


def _fatigue_risk(crew_id: str, day: int, tok: tuple) -> dict:
    e = _eval(crew_id, day, tok)
    return {"id": "fatigue", "name": NAMES["fatigue"], "nasa_red": True, "systems": ["brain"], "clock_days": 14,
            "level": e["level"], "score": e["score"], "trend": _trend(crew_id, day, tok), "evidence": e["evidence"],
            "since_day": _since(crew_id, day, tok), "source": FATIGUE["source"], "verified": FATIGUE["verified"]}


# ---------------------------------------------------------------- the other risks
# Every number in this section is a prototype assumption (`verified: False`, domain/assumptions.py) unless a `source` says
# otherwise: no published model adds these signals up.
_SPEC = A.value("risk.specs")
SPECS: Dict[str, dict] = {
    "radiation": {"name": "Radiation", "nasa_red": True, "systems": ["skin"], "reads": ["dose", "lym"]},
    "sans": {"name": "Vision and eye pressure (SANS)", "nasa_red": True, "systems": ["eyes"], "reads": ["amsler", "symptoms"]},
    "nutrition": {"name": "Food and nutrition", "nasa_red": True, "systems": ["gut"], "reads": ["weight", "gluc"]},
    "renal": {"name": "Kidneys and hydration", "nasa_red": False, "systems": ["kidneys"], "reads": ["water", "bone", "creatinine", "calcium", "urine_volume"]},
    "immune": {"name": "Blood and immunity", "nasa_red": False, "systems": ["immune"],
               "reads": ["temp", "wbc", "lym", "neu", "hgb", "hct", "plt", "rbc", "crp"]},
    "cardio": {"name": "Heart and circulation", "nasa_red": False, "systems": ["heart", "lungs"], "reads": ["hr", "sbp", "dbp", "spo2", "vo2", "potassium"]},
    "bone_muscle": {"name": "Bones and muscles", "nasa_red": False, "systems": ["skeleton", "muscles"], "reads": ["bone", "grip", "exer"]},
}
for _rid, _s in SPECS.items():
    _s.update(_SPEC[_rid])
SOURCE = {"source": "prototype assumption", "verified": False}
PANELS = {  # how often each kind of exam is due, in days. DATASET.md: blood analyser about every 30 days, urine every 15
    "blood": {"every_days": 30, "indicators": ["wbc", "lym", "neu", "hgb", "hct", "plt", "rbc", "creatinine", "potassium", "calcium", "crp"]},
    "urine": {"every_days": 15, "indicators": ["urine_volume"]},
}
PANEL_OF = {i: k for k, P in PANELS.items() for i in P["indicators"]}
BLOOD_COUNT = ["wbc", "lym", "neu", "hgb", "hct", "plt", "rbc"]
# Reference ranges for exams with no laboratory range in the NASA files. Blood counts (OSD-569) and creatinine,
# potassium and calcium (OSD-575) take the range of the laboratory that ran them, by sex (see simdata.lab_range).
# Urine volume is a prototype choice.
EXTRA_RANGES = {
    "urine_volume": {"low": 1500, "high": None, "unit": "mL/24h",
                     "source": "prototype assumption: a low 24 h urine volume is a kidney-stone factor", "verified": False},
}
RULES = {**A.value("risk.rules"), "sans": {**A.value("risk.rules")["sans"], "weak": "The Amsler grid is a weak indicator of SANS: a clear grid does not rule it out."}}
VISION_ITEMS = ("Eye discomfort", "Blurred vision")
INDICATOR_RISK = {**{i: "fatigue" for i in FATIGUE["weights"]}, "hr": "cardio", "sbp": "cardio", "dbp": "cardio", "spo2": "cardio", "vo2": "cardio",
                  "bone": "bone_muscle", "grip": "bone_muscle", "exer": "bone_muscle", "gluc": "nutrition",
                  "water": "renal", "temp": "immune"}

_inds_cache: Dict[tuple, dict] = {}


def dose_origin(d: dict) -> str:
    """The data origin of a dose figure for a risk: "simulated" when the readings are simulated or there are none (an
    estimate from the plan), "real" when every day was measured, "partial" for a mix."""
    if d.get("simulated") or d["origin"] == "estimated":
        return "simulated"
    return "real" if d["origin"] == "measured" else "partial"


def event_origin(origin: Optional[str]) -> str:
    """The origin of a space event for the evidence: donki (live NASA data) counts as real, a simulated replay stays simulated."""
    return "real" if origin in ("real", "donki") else "simulated"


def _storm_on(day: int) -> Optional[str]:
    """Id of the storm that hit the plan's place on a past `day` (the history of radiation: past days carry no ms["storm"])."""
    return dose.active_storm(day, plan.location_at(day))


def _inds(crew_id: str, day: int, tok: tuple) -> dict:
    """Every catalog indicator on one day, computed once per person, day and entered data."""
    from . import health
    key = (crew_id, day, tok)
    hit = _inds_cache.get(key)
    if hit is None:
        if len(_inds_cache) > 2000:
            _inds_cache.clear()
        hit = _inds_cache[key] = health.indicators(crew_id, _day_ms(day))
    return hit


def _ind_ev(inds: dict, ind: str, weight: float = 1.0) -> Optional[dict]:
    """Evidence from one catalog indicator against the person's own normal; None when it is on track."""
    d = inds[ind]
    if not d["level"] or d["value"] is None:  # on track, or no current reading: an absent signal adds nothing
        return None
    if d["delta"] is None:  # no normal of their own yet: only a safety limit speaks
        text = f"{d['name']} {_fmt(d['value'], d['dp'])} {d['unit']}, outside the safe range"
    else:
        word = "above" if d["delta"] > 0 else "below"
        text = (f"{d['name']} {_fmt(100 * d['value'] / d['baseline'], 1)} % of the pre-flight scan, {_fmt(abs(100 * d['delta'] / d['baseline']), 1)} % {word} your normal" if ind == "bone"
                else f"{d['name']} {_fmt(d['value'], d['dp'])} {d['unit']}, {_fmt(abs(d['delta']), d['dp'])} {d['unit']} {word} your normal")
    ev = {"key": ind, "indicator": ind, "value": d["value"], "baseline": d["baseline"], "z": d["z"], "origin": d["origin"], "source": d["source"],
          "points": round(weight * d["level"], 2), "text": text}
    std = d.get("standard") or {}
    if std.get("level"):  # past (2) or close to (1) a NASA-STD-3001 limit: the risk is at least that level
        ev.update(floor=std["level"], standard=std, text=f"{std['text']} (NASA-STD-3001 {std['item']})")
    return ev


def _panel_ev(crew_id: str, ind: str, day: int, sex: str) -> Optional[dict]:
    """An exam: out of its reference range (points) or too old (stale, no points). None when fresh and in range or missing."""
    from . import telemetry
    from .catalog import INDICATORS
    from . import nasa
    o = telemetry.last_observation(crew_id, ind, day)
    if o is None:
        return None
    kind = PANEL_OF[ind]
    every = PANELS[kind]["every_days"]
    base = {"key": ind, "indicator": ind, "value": o["value"], "origin": o["origin"], "source": o["source"], "age_days": o["age"]}
    if o["age"] > every:
        return {**base, "points": 0.0, "stale": True, "due_every_days": every,
                "text": f"The {kind} exam is {o['age']} days old (due every {every} days)"}
    if ind in EXTRA_RANGES:
        R = EXTRA_RANGES[ind]
        lo = R["low"].get(sex) if isinstance(R["low"], dict) else R["low"]
        hi = R["high"].get(sex) if isinstance(R["high"], dict) else R["high"]
        unit = R["unit"]
    else:  # the laboratory's own range for this sex (OSD-569 blood count, OSD-575 metabolic panel)
        from .simdata import lab_range
        snap = nasa.snapshot()
        rng = lab_range(snap, ind, sex)
        if rng is None:
            return None  # no range for this exam (C-reactive protein): read elsewhere against the person's own pre-flight
        lo, hi = rng
        unit = next(snap[s]["an"][ind]["unit"] for s in ("cbc", "cmp") if ind in snap.get(s, {}).get("an", {}))
    out = lambda v: (lo is not None and v < lo) or (hi is not None and v > hi)  # noqa: E731
    if not out(o["value"]):
        return None
    unit = unit.replace("_per_", "/").replace("_", " ")
    name = INDICATORS[ind]["name"] if ind in INDICATORS else ind.replace("_", " ").capitalize()
    rng = f"{'-' if lo is None else f'{lo:g}'} to {'-' if hi is None else f'{hi:g}'}"
    pre = list(telemetry.preflight_values(crew_id, ind).values())
    if pre and out(sum(pre) / len(pre)):  # the person's own pre-flight normal is already outside the range: not a new signal
        return {**base, "points": 0.0, "baseline_outside": True, "range": {"low": lo, "high": hi}, "unit": unit,
                "text": f"{name} {o['value']:g} {unit} is outside the usual range ({rng}), as it was before launch (your normal)"}
    return {**base, "points": 1.0, "range": {"low": lo, "high": hi}, "unit": unit,
            "text": f"{name} {o['value']:g} {unit} is outside the usual range ({rng})"}


def _g_radiation(crew_id: str, ms: dict, tok: tuple) -> List[dict]:
    from . import health, standards
    from .catalog import CREW_BY_ID, SPE_LIMIT_MSV
    day = ms["day"]
    R = RULES["radiation"]
    ev: List[dict] = []
    si = health.storm_info(crew_id, ms)
    if si:
        order = si["shelter"]["order"]
        ev.append({"key": "dose", "origin": event_origin(si["event"]["origin"]), "points": 2.0 if order else 1.0, "floor": 2 if order else 1,
                   "source": si["event"]["source"], "text": health.storm_text(si)})
    prior = standards.prior_dose(crew_id)
    p = dose.projection(crew_id, day, prior["msv"])
    ds = {"key": "dose", "origin": dose_origin(dose.mission(crew_id, day)), "value": p["now_msv"], "baseline": None, "z": None, "source": f"dose:day{day}"}
    earlier = (f" ({p['prior_msv']:g} mSv from earlier flights{', estimated' if prior['estimate'] else ''})"
               if p["prior_msv"] else "")
    if p["now_msv"] >= p["limit_msv"]:
        ev.append({**ds, "points": 2.0, "floor": 2,
                   "text": f"Career dose {p['now_msv']:g} mSv{earlier} is past NASA's {p['limit_msv']} mSv limit (V1 4030)"})
    elif p["pct"] >= R["watch_pct_of_limit"] and p["cross_day"] is not None:
        ev.append({**ds, "points": 1.0, "floor": 1,
                   "text": f"Career dose {p['now_msv']:g} mSv{earlier}, {p['pct']:g}% of NASA's limit, projected to pass it on day {p['cross_day']}"})
    elif p["pct"] >= R["watch_pct_of_limit"]:
        ev.append({**ds, "points": 0.0, "text": f"Career dose {p['now_msv']:g} mSv{earlier}, {p['pct']:g}% of NASA's limit; the plan ends below it"})
    lym = _panel_ev(crew_id, "lym", day, CREW_BY_ID[crew_id]["sex"])
    if lym:
        low = lym["range"]["low"] if "range" in lym else None
        if lym["points"] and low is not None and lym["value"] < low:  # radiation lowers the count; a high one is not its evidence
            lym.update(points=R["lym_points"], floor=1)
        elif not lym.get("stale"):
            lym = None
        if lym:
            ev.append(lym)
    return ev


def _g_sans(crew_id: str, ms: dict, tok: tuple) -> List[dict]:
    from . import health
    day, R = ms["day"], RULES["sans"]
    ev: List[dict] = []
    am = health.latest_checkin(crew_id, "amsler", day, window=R["window_days"])
    if am and am.get("distortion"):
        ev.append({"key": "amsler", "origin": "user", "value": 1, "baseline": None, "z": None, "points": R["amsler_points"],
                   "source": f"checkin:{crew_id}:amsler:day{am['day']}", "text": "Wavy or missing lines on the Amsler grid (a weak indicator on its own)"})
    sy = health.latest_checkin(crew_id, "symptoms", day, window=R["window_days"])
    items = [i for i in (sy or {}).get("items", []) if i in VISION_ITEMS]
    if items:
        ev.append({"key": "symptoms", "origin": "user", "value": len(items), "baseline": None, "z": None, "points": R["vision_symptom_points"],
                   "source": f"checkin:{crew_id}:symptoms:day{sy['day']}", "text": f"Reported {', '.join(i.lower() for i in items)}"})
    return ev


def _g_nutrition(crew_id: str, ms: dict, tok: tuple) -> List[dict]:
    import statistics
    from . import telemetry
    day, R = ms["day"], RULES["nutrition"]
    inds = _inds(crew_id, day, tok)
    ev = [e for e in [_ind_ev(inds, "gluc")] if e]
    pre = list(telemetry.preflight_values(crew_id, "weight").values())
    o = telemetry.last_observation(crew_id, "weight", day)
    adapting = bool(plan.location_at(day) != "earth" and A.value("adaptation.first_day") <= day <= A.value("adaptation.last_day"))  # fluid shift: body mass moves in the first days
    if pre and o and o["age"] <= (catalog.max_age("weight") or 10**6) and not adapting:  # an old weight is not today's weight
        base = statistics.mean(pre)
        loss = 100 * (base - o["value"]) / base
        pts = 2.0 if loss >= R["loss_pct"][2] else 1.0 if loss >= R["loss_pct"][1] else 0.0
        if pts:
            ev.append({"key": "weight", "indicator": "weight", "value": o["value"], "baseline": round(base, 1), "z": None, "origin": o["origin"],
                       "source": o["source"], "age_days": o["age"], "points": pts,
                       "text": f"Weight {o['value']:g} kg, {loss:.1f}% below your pre-flight {base:.1f} kg"})
    return ev


def _bone_rate(crew_id: str, day: int) -> Optional[float]:
    """Estimated % of bone density lost in the last 30 days (positive = loss), from the model of exercise and time in
    microgravity (bone density cannot be measured on board). None before day 30."""
    from . import health
    if day < 30:
        return None
    now, then = health.bone_estimate(crew_id, day), health.bone_estimate(crew_id, day - 30)
    return None if now is None or then is None else now["loss_pct"] - then["loss_pct"]


def _g_renal(crew_id: str, ms: dict, tok: tuple) -> List[dict]:
    from .catalog import CREW_BY_ID
    day, R = ms["day"], RULES["renal"]
    inds = _inds(crew_id, day, tok)
    ev = [e for e in [_ind_ev(inds, "water")] if e]
    rate = _bone_rate(crew_id, day)
    if rate is not None and rate >= R["bone_loss_pct_30d"]:
        d = inds["bone"]
        ev.append({"key": "bone", "indicator": "bone", "estimate": True, "value": round(rate, 2), "baseline": None, "z": None, "origin": "estimated",
                   "source": d["source"], "points": R["points"],
                   "text": f"Estimated bone loss of {rate:.1f}% in the last 30 days (a model of exercise and time in microgravity, not a scan)"})
    sex = CREW_BY_ID[crew_id]["sex"]
    ev += [e for e in (_panel_ev(crew_id, i, day, sex) for i in ("creatinine", "calcium", "urine_volume")) if e]
    return ev


def _g_immune(crew_id: str, ms: dict, tok: tuple) -> List[dict]:
    from .catalog import CREW_BY_ID
    day, R = ms["day"], RULES["immune"]
    inds = _inds(crew_id, day, tok)
    ev = [e for e in [_ind_ev(inds, "temp")] if e]
    sex = CREW_BY_ID[crew_id]["sex"]
    blood = [e for e in (_panel_ev(crew_id, i, day, sex) for i in BLOOD_COUNT) if e]
    fresh = [e for e in blood if not e.get("stale")]
    for e in fresh:
        e["points"] = R["blood_point"] if e["points"] else 0.0
    cap = R["blood_cap"]
    tot = 0.0
    for e in fresh:  # at most `blood_cap` points from the blood count in all
        e["points"] = min(e["points"], max(0.0, cap - tot))
        tot += e["points"]
    ev += fresh + [e for e in blood if e.get("stale")][:1]
    crp = _crp_ev(crew_id, day)
    if crp:
        ev.append(crp)
    follow = data.storms_following(day, R["storm_follow_days"], R["follow_kinds"])
    if follow:
        e0 = follow[0]
        ev.append({"key": "dose", "origin": event_origin(e0["origin"]), "value": None, "baseline": None, "z": None, "points": R["storm_points"],
                   "source": e0["source"], "text": "Blood count due after the radiation storm"})
    return ev


def _crp_ev(crew_id: str, day: int) -> Optional[dict]:
    """C-reactive protein against the person's own pre-flight mean (its panel gives no range). None when it is not
    raised, too old, or never measured; a stale exam is left to the blood count's own stale evidence."""
    import statistics
    from . import telemetry
    R = RULES["immune"]
    o = telemetry.last_observation(crew_id, "crp", day)
    pre = list(telemetry.preflight_values(crew_id, "crp").values())
    if o is None or not pre or o["age"] > PANELS["blood"]["every_days"] or day < 0:
        return None
    base = statistics.mean(pre)
    rise = 100 * (o["value"] - base) / base if base else 0.0
    if rise < R["crp_rise_pct"]:
        return None
    return {"key": "crp", "indicator": "crp", "value": o["value"], "baseline": round(base, 2), "z": None, "origin": o["origin"],
            "source": o["source"], "age_days": o["age"], "points": R["crp_points"],
            "text": f"C-reactive protein {o['value']:g} mg/L, {rise:.0f}% above your pre-flight mean (inflammation)"}


def _g_cardio(crew_id: str, ms: dict, tok: tuple) -> List[dict]:
    from .catalog import LOCATIONS
    from .catalog import CREW_BY_ID
    inds = _inds(crew_id, ms["day"], tok)
    ev = [e for e in (_ind_ev(inds, i) for i in ("hr", "sbp", "dbp", "spo2", "vo2")) if e]
    k = _panel_ev(crew_id, "potassium", ms["day"], CREW_BY_ID[crew_id]["sex"])
    if k:  # potassium out of its range can disturb the heart rhythm
        ev.append(k)
    pr = inds["sbp"] if inds["sbp"]["level"] or not inds["dbp"]["level"] else inds["dbp"]
    if LOCATIONS[_day_ms(ms["day"])["location"]]["gravity_key"] == "gp" and pr["level"] and inds["hr"]["level"]:
        ev.append({"key": "regravity", "origin": pr["origin"], "value": None, "baseline": None, "z": None,
                   "points": RULES["cardio"]["regravity_points"], "source": pr["source"],
                   "text": "Pressure and pulse both away from your normal after the change to partial gravity (the re-adaptation pattern)"})
    return ev


def _g_bone_muscle(crew_id: str, ms: dict, tok: tuple) -> List[dict]:
    inds = _inds(crew_id, ms["day"], tok)
    ev = [e for e in (_ind_ev(inds, i) for i in ("bone", "grip", "exer")) if e]
    b, R = inds["bone"], RULES["bone_muscle"]
    est = b.get("estimate")
    if est and est["loss_pct"] >= R["estimate_loss_pct"]:  # bone cannot be scanned on board: the model speaks, labelled as an estimate
        ev.append({"key": "bone", "indicator": "bone", "estimate": True, "value": est["loss_pct"], "baseline": None, "z": None, "origin": "estimated",
                   "source": b["source"], "points": R["estimate_points"],
                   "text": f"Estimated bone loss {est['loss_pct']:g}% since launch from exercise and time in microgravity (an estimate, not a scan; "
                           f"the next measured value is the post-flight DXA)"})
    return ev


GATHER = {"radiation": _g_radiation, "sans": _g_sans, "nutrition": _g_nutrition, "renal": _g_renal,
          "immune": _g_immune, "cardio": _g_cardio, "bone_muscle": _g_bone_muscle}
_gcache: Dict[tuple, dict] = {}


def _g_eval(rid: str, crew_id: str, day: int, storm: Optional[str], tok: tuple) -> dict:
    """One day of one risk: its evidence, score and level. Cached per person, day, storm and entered data."""
    key = (rid, crew_id, day, storm, tok)
    hit = _gcache.get(key)
    if hit is None:
        if len(_gcache) > 6000:
            _gcache.clear()
        ms = {**_day_ms(day), "storm": storm}
        S = SPECS[rid]
        ev = [] if ms["learning"] else GATHER[rid](crew_id, ms, tok)
        ev.sort(key=lambda e: -e["points"])
        score = round(sum(e["points"] for e in ev), 2)
        signals = sum(1 for e in ev if e["points"] > 0)
        level = 2 if score >= S["cuts"][2] and signals >= S["min2"] else 1 if score >= S["cuts"][1] else 0
        level = max([level] + [e.get("floor", 0) for e in ev])
        hit = _gcache[key] = {"evidence": ev, "score": score, "level": level}
    return hit


def _g_since(rid: str, crew_id: str, ms: dict, tok: tuple) -> Optional[int]:
    day = ms["day"]
    if _g_eval(rid, crew_id, day, ms.get("storm"), tok)["level"] < 1:
        return None
    d, stop = day, max(0, day - FATIGUE["lookback_days"])
    while d > stop and _g_eval(rid, crew_id, d - 1, _storm_on(d - 1), tok)["level"] >= 1:
        d -= 1
    return d


def _g_trend(rid: str, crew_id: str, ms: dict, tok: tuple) -> str:
    t, day = FATIGUE["trend"], ms["day"]
    now = _g_eval(rid, crew_id, day, ms.get("storm"), tok)["score"]
    before = _g_eval(rid, crew_id, day - t["days"], _storm_on(day - t["days"]), tok)["score"]
    return "rising" if now - before >= t["delta"] else "falling" if now - before <= -t["delta"] else "stable"


# ---------------------------------------------------------------- hazards and data origin
HAZARD_FIX = {"wellbeing": "mood", "missing_mood": "mood"}


def hazards_for(keys: List[str], ms: dict) -> Tuple[List[str], List[dict]]:
    """The hazards of the team's matrix linked to these evidence keys that are moderate or high at the current place
    and day. Possible factors, never a cause. Returns (hazard ids in R, I, D, G, E order, the links with their why and source)."""
    from . import privacy
    from .catalog import HAZARDS_BY_INDICATOR
    levels = {h["id"]: h["level"] for h in privacy.ridge(ms["location"], ms.get("storm"), ms["day"])}
    links = []
    for k in dict.fromkeys(HAZARD_FIX.get(k, k) for k in keys if k):
        for l in HAZARDS_BY_INDICATOR.get(k, []):
            if levels.get(l["hazard"], 0) >= 1:
                links.append({**l, "key": k})
    ids = [h["id"] for h in privacy.RIDGE if any(l["hazard"] == h["id"] for l in links)]
    return ids, links


def hazard_note(ids: List[str]) -> str:
    from . import privacy
    names = {h["id"]: h["name"] for h in privacy.RIDGE}
    return f"Possible factors here: {', '.join(names[i] for i in ids)}. Not a cause." if ids else ""


def _origins(ev: List[dict]) -> set:
    return {e["origin"] for e in ev if e.get("origin") and not e.get("stale") and e.get("checkin") != "missing_mood"}  # a missing check-in is not data


def data_origin(origins: set) -> str:
    """real (all measured: NASA data or typed in the app), simulated (none) or partial (a mix); "none" when there is no data."""
    if origins and origins <= {"none"}:
        return "none"
    origins = origins - {"none"}
    if "partial" in origins:
        return "partial"
    measured = {o for o in origins if o in ("real", "user")}
    if not origins or not measured:
        return "simulated"
    return "real" if measured == origins else "partial"


def _read_origins(rid: str, crew_id: str, ms: dict, tok: tuple) -> set:
    """Where the data a risk reads comes from, when no evidence is active: the latest row of each input."""
    from . import telemetry
    out = set()
    inds = _inds(crew_id, ms["day"], tok)
    for k in SPECS[rid]["reads"] if rid in SPECS else []:
        if k == "dose":
            out.add(dose_origin(dose.mission(crew_id, ms["day"])))
        elif k in inds:
            out.add(inds[k]["origin"])
        elif k in ("amsler", "symptoms"):
            out.add("user")
        else:
            o = telemetry.last_observation(crew_id, k, ms["day"])
            if o:
                out.add(o["origin"])
    return out


# Which body system an evidence is about, when the catalog's indicator lists do not say.
EVIDENCE_SYSTEM = {"dose": "skin", "lym": "immune", "wbc": "immune", "neu": "immune", "hgb": "immune", "hct": "immune", "plt": "immune",
                   "rbc": "immune", "amsler": "eyes", "symptoms": "eyes", "weight": "gut", "regravity": "heart", "creatinine": "kidneys",
                   "urine_volume": "kidneys", "calcium": "kidneys", "potassium": "heart", "crp": "immune", "vo2": "heart"}


def _system_levels(r: dict) -> Dict[str, int]:
    """The level of the risk on each body system its evidence is about (the others stay at 0 for this risk)."""
    from .catalog import SYSTEMS
    hit = set()
    for e in r["evidence"]:
        k = e.get("key") or e.get("indicator") or e.get("checkin")
        if e.get("stale") or not (e["points"] or e.get("floor")):
            continue
        sid = EVIDENCE_SYSTEM.get(k) or next((s for s, S in SYSTEMS.items() if k in S["indicators"]), None)
        hit.add(sid if sid in r["systems"] else None)
    if not r["level"]:
        return {}
    return {sid: r["level"] for sid in r["systems"] if sid in hit or None in hit}


def _finish(r: dict, ms: dict, origins: set) -> dict:
    keys = [e.get("key") or e.get("indicator") or e.get("checkin") for e in r["evidence"] if not e.get("stale")]
    ids, links = hazards_for(keys, ms) if r["level"] else ([], [])
    return {**r, "system_levels": _system_levels(r), "hazards": ids, "hazard_links": links, "hazard_note": hazard_note(ids), "data": data_origin(origins),
            "panel_due": any(e.get("stale") for e in r["evidence"])}


def _generic_risk(rid: str):
    def fn(crew_id: str, ms: dict, tok: tuple) -> dict:
        S, day, storm = SPECS[rid], ms["day"], ms.get("storm")
        e = _g_eval(rid, crew_id, day, storm, tok)
        r = {"id": rid, "name": S["name"], "nasa_red": S["nasa_red"], "systems": S["systems"], "clock_days": S["clock_days"],
             "level": e["level"], "score": e["score"], "trend": _g_trend(rid, crew_id, ms, tok), "evidence": e["evidence"],
             "since_day": _g_since(rid, crew_id, ms, tok), **SOURCE}
        if rid == "sans":
            r["note"] = RULES["sans"]["weak"]
        if rid == "radiation":
            from . import standards
            prior = standards.prior_dose(crew_id)
            personal = dose.mission(crew_id, day)["personal"]
            r["dose"] = {**dose.projection(crew_id, day, prior["msv"]), "same_for_everyone": not personal,
                         "prior_estimate": prior["estimate"],
                         "prior_source": prior["source"], "limit_source": "NASA-STD-3001 V1 4030",
                         "note": ("The mission dose comes from your own dosimeter where it has readings, and from the cabin's elsewhere. "
                                  if personal else
                                  "The mission dose is the same for everyone on board: Canary does not invent a dose per person. ")
                                 + "The career dose adds each person's earlier flights, as NASA's limit does."}
        return _finish(r, ms, _origins(e["evidence"]) or _read_origins(rid, crew_id, ms, tok))
    return fn


def _fatigue_wrapped(crew_id: str, ms: dict, tok: tuple) -> dict:
    r = _fatigue_risk(crew_id, ms["day"], tok)
    inds = _inds(crew_id, ms["day"], tok)
    nothing = all(inds[i].get("status") == "no_data" for i in FATIGUE["weights"])
    return _finish(r, ms, _origins(r["evidence"]) or ({"none"} if nothing else {"simulated"}))


RISKS = {"fatigue": _fatigue_wrapped, **{rid: _generic_risk(rid) for rid in SPECS}}


def evaluate(crew_id: str, ms: dict, tok: Optional[tuple] = None) -> List[dict]:
    """Every risk for one person on the mission day of `ms`."""
    tok = tok or _token(crew_id)
    ms = {**_day_ms(ms["day"]), **ms}  # place and learning from the plan when the caller gave only the day
    return [fn(crew_id, ms, tok) for fn in RISKS.values()]


def level_for(risks: List[dict], system_id: str) -> int:
    """The highest level among the risks that act on a body system."""
    return max([r["system_levels"].get(system_id, 0) if "system_levels" in r else r["level"]
                for r in risks if system_id in r["systems"]] or [0])


def get(risks: List[dict], rid: str) -> Optional[dict]:
    return next((r for r in risks if r["id"] == rid), None)
