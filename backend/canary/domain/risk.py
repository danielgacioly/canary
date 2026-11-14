"""Risks: a level, the evidence behind it, a trend and the day it started.

A single alert looks at one signal (or a fixed combination). A risk adds up everything Canary knows about one
NASA risk area for one person, against that person's own normal, and says how sure it is: level 0 / 1 / 2.

Today only `fatigue` (Behavioural health and performance) exists. The other NASA risks (radiation, nutrition,
kidneys, immunity, cardiovascular, bone, vision) are a later step: add an entry to `RISKS` with a function that
returns the risk dict for a crew member and a day.

Rules, not a model: every number below is a data table that a person can read, review and change. Nothing here
is learned, and nothing is stored: a risk is a function of the day, so the demo clock can jump anywhere.
"""
import json
import math
from typing import Dict, List, Optional, Tuple

from .. import db
from . import care, plan

# ---------------------------------------------------------------- tables (prototype assumption)
# Every weight and cut below is a prototype assumption: no published model sums these signals. They were chosen
# so that two weeks of several signals slipping together reach level 2, and one bad night or one noisy test does not.
FATIGUE = {
    "source": "prototype assumption", "verified": False,
    # points of an indicator = weight x its level (0, 1 or 2) against the person's own normal
    "weights": {"sleep": 1.0, "react": 1.0, "mood": 1.0, "dsst": 0.75, "stress": 0.5, "social": 0.5,
                "span": 0.5, "kss": 0.5, "tlx": 0.5},
    # check-in evidence: wellbeing = PHQ-2 or GAD-2 of 3 or more in the last 14 days; missing_mood = no mood check-in for 3 days
    "checkins": {"wellbeing": 1.0, "missing_mood": 0.5},
    # a slow slide still inside the normal range adds this much per indicator, at most `cap` in all
    "drift": {"weight": 0.5, "cap": 1.0},
    "cuts": {1: 2.0, 2: 4.0},   # score needed for level 1 and level 2
    "min_signals_level_2": 3,   # distinct signals (indicators and check-ins, not drift) needed for level 2
    "sustained_days": 2,        # level 2 also needs level 1 or more two days earlier: a bad night alone is never level 2
    "trend": {"days": 3, "delta": 0.5},  # score now against 3 days ago: rising / falling beyond +-0.5
    "lookback_days": 60,        # how far back since_day looks
}
DRIFT = {"source": "prototype assumption", "verified": False,
         "window": 14, "horizon": 10, "min_slope": 0.08}  # days fitted, days looked ahead, spreads per day the line must climb

NAMES = {"fatigue": "Behavioural health and performance"}


# ---------------------------------------------------------------- cache
_cache: Dict[tuple, dict] = {}


def _token(crew_id: str) -> tuple:
    """Everything a risk reads that can change without the day changing."""
    from . import health
    c = db.q("SELECT COUNT(*) n, COALESCE(MAX(id),0) m, COALESCE(SUM(day),0) d, COALESCE(SUM(LENGTH(payload)),0) p FROM checkins WHERE crew_id=?", (crew_id,))[0]
    g = db.q("SELECT COUNT(*) n, COALESCE(SUM(done),0) d, COALESCE(SUM(day),0) s FROM goal_log WHERE crew_id=?", (crew_id,))[0]
    return (plan.version(), json.dumps(health.thresholds(), sort_keys=True), json.dumps(health.thresholds_by_indicator(), sort_keys=True),
            c["n"], c["m"], c["d"], c["p"], g["n"], g["d"], g["s"], care.token(crew_id))


def clear_cache() -> None:
    _cache.clear()


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
    ys = [sign * (v - base) / sd for _d, v in telemetry.series(crew_id, ind, day, DRIFT["window"])]
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
        base = {"indicator": ind, "value": d["value"], "baseline": d["baseline"], "z": d["z"], "origin": d["origin"], "source": d["source"]}
        if d["level"]:
            word = "above" if d["delta"] > 0 else "below"
            ev.append({**base, "points": round(w * d["level"], 2),
                       "text": f"{d['name']} {_fmt(d['value'], d['dp'])} {d['unit']}, {_fmt(abs(d['delta']), d['dp'])} {d['unit']} {word} your normal"})
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


RISKS = {"fatigue": _fatigue_risk}  # the other NASA risks join here, one entry each


def evaluate(crew_id: str, ms: dict, tok: Optional[tuple] = None) -> List[dict]:
    """Every risk for one person on the mission day of `ms`."""
    tok = tok or _token(crew_id)
    return [fn(crew_id, ms["day"], tok) for fn in RISKS.values()]


def level_for(risks: List[dict], system_id: str) -> int:
    """The highest level among the risks that act on a body system."""
    return max([r["level"] for r in risks if system_id in r["systems"]] or [0])


def get(risks: List[dict], rid: str) -> Optional[dict]:
    return next((r for r in risks if r["id"] == rid), None)
