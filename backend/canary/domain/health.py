"""Personal baseline, alert levels, body-system status and the physical / mental readiness scores.

Each indicator is compared with the person's own pre-flight normal, never with a
population average:  z = (recent value - baseline) / personal spread.
Levels: 0 on track, 1 watch, 2 act. Thresholds are set by the medical team.
"""
import json
import statistics
from typing import Dict, List, Optional

from .. import db
from . import care, data, plan, reference, risk, standards, telemetry
from . import dose as dose_mod
from .catalog import CAREER_LIMIT_MSV, CREW_BY_ID, EXERCISE_BY_PLACE, INDICATORS, LOCATIONS, SYSTEMS

STATUS = ["On track", "Watch", "Act"]
TODO_BY_INDICATOR = {
    "bone": ["Add 20 min of resistive exercise to today's session", "Calcium and vitamin D with breakfast", "The medical officer reviews the trend weekly"],
    "exer": ["Book today's exercise slot now", "Start with 20 min: something beats nothing"],
    "water": ["Keep a drink bag at your workstation", "A few sips every 30 minutes"],
    "social": ["Join the crew for the next meal", "Plan one off-duty hour with someone today"],
    "spo2": ["Measure again at rest in 10 minutes", "Check the cabin CO₂ reading"],
    "temp": ["Measure again in 1 hour", "Rest and drink water", "Tell the medical officer if it passes 38 °C"],
}
DEFAULT_THRESHOLDS = {"watch": 1.5, "act": 2.5}


def thresholds() -> dict:
    return db.get_setting("thresholds", DEFAULT_THRESHOLDS)


MIN_PREFLIGHT = 5  # measurements needed before a person's own normal is trusted
EARLY_FLIGHT_DAYS = 14  # a person who starts in flight learns their normal from their first 14 days of measurements
_baselines: Dict[tuple, Dict[str, dict]] = {}


def baselines(crew_id: str) -> Dict[str, dict]:
    """Personal baseline per indicator, from the person's own measurements, never from a seed.

    - `from: "preflight"`: mean and spread of every measurement on the plan's pre-flight days (file rows plus the person's
      own check-ins). The spread never goes below the catalog's `sd`, so a quiet pre-flight cannot turn ordinary noise
      into alerts. The mean is shown with the precision the app displays (`dp`), so the "normal 55" on screen is the
      number the alert used.
    - `from: "early_flight"`: fewer than MIN_PREFLIGHT pre-flight values, but at least that many in the person's first 14
      days of flight data. Less reliable, and labelled so.
    - `from: "learning"`: neither. `mean` and `sd` are None: the indicator is only read against the population range and
      the NASA standard until there is a normal to compare with. `n` measurements so far, `need` wanted.

    Cached per crew member, plan version, stored data and number of check-ins.
    """
    key = (crew_id, plan.version(), data.token(), telemetry.preflight_checkins(crew_id))
    hit = _baselines.get(key)
    if hit is None:
        if len(_baselines) > 64:
            _baselines.clear()
        hit = {}
        for ind, I in INDICATORS.items():
            vals = list(telemetry.preflight_values(crew_id, ind).values())
            early = list(telemetry.early_flight_values(crew_id, ind, EARLY_FLIGHT_DAYS).values())
            if len(vals) >= MIN_PREFLIGHT:
                src, use = "preflight", vals
            elif len(early) >= MIN_PREFLIGHT:
                src, use = "early_flight", early
            else:
                hit[ind] = {"mean": None, "sd": None, "from": "learning", "n": max(len(vals), len(early)), "need": MIN_PREFLIGHT}
                continue
            hit[ind] = {"mean": round(statistics.mean(use), I["dp"]), "sd": max(statistics.pstdev(use), I["sd"]), "n": len(use), "from": src}
        _baselines[key] = hit
    return hit


def thresholds_by_indicator() -> dict:
    """Optional per-indicator override of the global thresholds: {"sleep": {"watch": 1.0, "act": 2.0}}. No screen yet."""
    return db.get_setting("thresholds_by_indicator", {})


def indicator(crew_id: str, ind: str, ms: dict, th: Optional[dict] = None, last: Optional[Dict[str, int]] = None,
              uv: Optional[dict] = None, by_ind: Optional[dict] = None) -> dict:
    th = {**(th or thresholds()), **(thresholds_by_indicator() if by_ind is None else by_ind).get(ind, {})}
    day = ms["day"]
    window = None if ms["learning"] else care.active(crew_id, day)  # inside the care window of a closed emergency: tighter, for this person only
    if window:
        f = care.sensitivity()["factor"]
        th = {k: v * f for k, v in th.items()}
    last = telemetry.last_user_day(crew_id, day) if last is None else last
    obs = telemetry.observation(crew_id, ind, day, uv)  # where today's value came from
    I = INDICATORS[ind]
    B = baselines(crew_id)[ind]
    base, sd = B["mean"], B["sd"]
    learning = base is None  # no normal of their own yet: only the population range and the NASA standard speak
    spread = I["sd"] if learning else sd
    if ind == "exer" and base is not None:  # the exercise plan changes with the place: compare with today's plan, not with pre-flight
        base = min(base, EXERCISE_BY_PLACE[ms["location"]][1])
    v = telemetry.current(crew_id, ind, day)
    out = {"id": ind, "name": I["name"], "unit": I["unit"], "area": I["area"], "facet": I.get("facet"), "dp": I["dp"]}
    seen_day = last.get(ind)
    if v is None:  # no row at all, or only stale ones: it is not a health finding, and the last reading is still shown
        if obs["day"] is not None and (seen_day is None or obs["day"] > seen_day):
            seen_day = obs["day"]
        return {**out, "value": None, "baseline": None if base is None else round(base, 3), "delta": None, "z": None, "bad": None,
                "level": 0, "status": "no_data", "source": f"telemetry:{crew_id}:{ind}:day{day}", "origin": obs["origin"],
                "last_measured_day": seen_day, "age_days": day - seen_day if seen_day is not None else None, "stale": obs["stale"],
                "spread": round(spread, 3), "baseline_from": B["from"], "baseline_n": B["n"], "baseline_need": B.get("need"), "learning": learning,
                "population": {"low": None, "high": None, "status": "no_data", "source": None, "verified": False}, "standard": None,
                **({"sensitive_until": window["sensitive_until"]} if window else {})}
    z = bad = None if learning else 0.0
    if not learning:
        z = (v - base) / sd
        bad = -z if I["dir"] == "low" else z if I["dir"] == "high" else abs(z)
    level = 0 if ms["learning"] or learning else 2 if bad >= th["act"] else 1 if bad >= th["watch"] else 0
    # population range: the safety limit. A critical single reading today is level 2 even in learning;
    # a recent value outside the normal range is at least level 1 (after launch).
    pop = reference.check(ind, CREW_BY_ID[crew_id]["sex"], v)
    if telemetry.is_current(obs) and reference.check(ind, CREW_BY_ID[crew_id]["sex"], obs["value"])["status"] == "critical":
        pop["status"] = "critical"
    if pop["status"] == "critical":
        level = 2
    elif pop["status"] == "out" and not ms["learning"]:
        level = max(level, 1)
    # NASA-STD-3001: an in-flight limit (strength, bone, aerobic capacity for EVA). It only raises the level, and only
    # in flight: on Earth before launch there is no in-mission limit to break.
    std = None if ms["learning"] else standards.check(ind, crew_id, ms["location"], v, B["mean"])
    if std:
        level = max(level, std["level"])
    return {**out, "value": round(v, 2), "baseline": None if base is None else round(base, 3),
            "delta": None if base is None else round(v - base, 2),
            "z": None if z is None else round(z, 2), "bad": None if bad is None else round(bad, 2), "level": level,
            "source": f"telemetry:{crew_id}:{ind}:day{day}",
            "origin": obs["origin"], "last_measured_day": last.get(ind),
            "age_days": day - last[ind] if ind in last else None, "stale": False,
            "spread": round(spread, 3), "baseline_from": B["from"], "baseline_n": B["n"], "baseline_need": B.get("need"), "learning": learning, "population": pop,
            "standard": std,
            **({"sensitive_until": window["sensitive_until"]} if window else {})}


def indicators(crew_id: str, ms: dict) -> Dict[str, dict]:
    th = thresholds()
    last = telemetry.last_user_day(crew_id, ms["day"])
    uv = telemetry.user_values(crew_id, ms["day"], ms["day"])
    by_ind = thresholds_by_indicator()
    return {i: indicator(crew_id, i, ms, th, last, uv, by_ind) for i in INDICATORS}


def latest_checkin(crew_id: str, kind: str, day: int, window: int = 7) -> Optional[dict]:
    rows = db.q("SELECT payload,day FROM checkins WHERE crew_id=? AND kind=? AND day<=? AND day>? ORDER BY id DESC LIMIT 1",
                (crew_id, kind, day, day - window))
    return {**json.loads(rows[0]["payload"]), "day": rows[0]["day"]} if rows else None


def dose(ms: dict, crew_id: Optional[str] = None) -> dict:
    """Mission dose in mSv: the cabin dosimeter, or the plan where it has no reading (dose.py), the same for everyone on
    board. With a crew member, it counts that person's own dosimeter first, and adds their career dose: NASA's 600 mSv
    limit counts every earlier flight (NASA-STD-3001 V1 4030)."""
    d = dose_mod.mission(crew_id, ms["day"], ms["location"])
    total = d["msv"]
    out = {"mission_msv": total, "rate_msv_day": LOCATIONS[ms["location"]]["dose_rate"],
           "career_limit_msv": CAREER_LIMIT_MSV, "pct_of_limit": round(100 * total / CAREER_LIMIT_MSV, 1),
           "simulated": d["simulated"], "limit_source": "NASA-STD-3001 V1 4030",
           "origin": d["origin"], "measured_days": d["measured_days"], "estimated_days": d["estimated_days"]}
    if crew_id is not None:
        prior = standards.prior_dose(crew_id)
        career = round(prior["msv"] + total, 1)
        out.update(prior_msv=prior["msv"], prior_estimate=prior["estimate"], prior_source=prior["source"],
                   career_msv=career, career_pct_of_limit=round(100 * career / CAREER_LIMIT_MSV, 1))
    return out


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
            if ms["storm"]:
                lv, note = 2, "Radiation storm in progress."
            elif d["career_pct_of_limit"] >= 100:
                lv, note = 2, f"Career dose {d['career_msv']:g} mSv, past NASA's 600 mSv limit."
            elif d["career_pct_of_limit"] >= 50:
                lv, note = max(lv, 1), f"{d['career_pct_of_limit']}% of the career limit used, earlier flights included."
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
    """Readiness 0 to 100. Prototype assumption: each indicator loses 18 points for every spread beyond 0.6 of its
    own normal, the area is their mean, and physical loses 6 points per level of eyes, skin and immune (no
    indicators of their own). The formula is a design choice, not a published score."""
    vals = [max(0.0, min(100.0, 100 - 18 * max(0.0, i["bad"] - 0.6))) for i in inds.values() if i["area"] == area and i["bad"] is not None]
    if not vals:  # nothing measured in this area: no score (never a made-up one)
        return None
    s = sum(vals) / len(vals)
    if area == "physical":
        s -= 6 * sum(x["level"] for k, x in syss.items() if k in ("eyes", "skin", "immune"))
    return int(round(max(0, min(100, s))))


def _indicator_alert(i: str, d: dict) -> dict:
    """Alert for one indicator on its own: outside the personal normal, or past the population safety limit."""
    sysid = next((k for k, s in SYSTEMS.items() if i in s["indicators"]), None)
    p = d["population"]
    std = d.get("standard") or {}
    critical = p["status"] == "critical"
    if i == "bone":  # the bone row is the % change since launch; say it the way the tile and NASA's limit do
        why = f"Today {100 + d['value']:.1f} % of your pre-flight density. Your normal is 100 %."
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
    "al_head": ("hr", 2), "al_salt": ("bp", 3), "al_stand": ("bp", 3), "al_talk": ("mood", 7),
}
# Which risk each alert belongs to, and which evidence keys of the hazard matrix it rests on. The ids and texts of the
# alerts do not change; they only gain `risk`, `hazards` (possible factors, never a cause) and `hazard_note`.
ALERT_RISK = {"storm": "radiation", "sickness": "renal", "regravity": "cardio", "amsler": "sans", "behaviour": "fatigue",
              "wellbeing": "fatigue", "sleepy": "fatigue", "missing_mood": "fatigue", "symptoms": None}
ALERT_KEYS = {"storm": ["dose"], "sickness": ["hr", "water", "exer", "mood"], "regravity": ["bp", "hr"], "amsler": ["amsler"],
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
    A = _alerts(crew_id, ms, inds, risks)
    for a in A:
        rid = a["id"][4:] if a["id"].startswith("ind_") else None
        a["risk"] = ALERT_RISK[a["id"]] if a["id"] in ALERT_RISK else risk.INDICATOR_RISK.get(rid)
        parent = risk.get(risks, a["risk"]) if a["id"] == "behaviour" else None
        ids, _links = (parent["hazards"], parent["hazard_links"]) if parent else risk.hazards_for(ALERT_KEYS.get(a["id"], [rid] if rid else []), {**ms, "location": ms["location"]})
        a["hazards"], a["hazard_note"] = ids, risk.hazard_note(ids)
    tok = risk._token(crew_id)
    seen = db.get_setting("alerts_seen", {})
    for a in A:
        since = ms["day"] if a["id"] == "storm" else _alert_since(crew_id, ms["day"], a["id"], tok)
        a.update({"since_day": since, "days_active": ms["day"] - since + 1, "seen": f"{crew_id}:{a['id']}:{since}" in seen})
        for g in a.get("goals", []):
            if g["id"] in ALERT_GOAL_VERIFY:
                g["verify"] = dict(zip(("indicator", "after_days"), ALERT_GOAL_VERIFY[g["id"]]))
    return A


def mark_seen(crew_id: str, alert: dict, day: int) -> None:
    seen = db.get_setting("alerts_seen", {})
    seen[f"{crew_id}:{alert['id']}:{alert['since_day']}"] = day
    db.set_setting("alerts_seen", seen)


def _alerts(crew_id: str, ms: dict, inds: Dict[str, dict], risks: Optional[List[dict]] = None) -> List[dict]:
    """Cross-signal rules first, then single indicators that are left. Each alert says what to do."""
    if ms["learning"]:  # no early warnings while Canary learns the baseline; a safety limit still speaks
        return [_indicator_alert(i, d) for i, d in inds.items() if d["population"]["status"] == "critical"]
    risks = risk.evaluate(crew_id, ms) if risks is None else risks
    A, used = [], set()
    lv = lambda i: inds[i]["level"]  # noqa: E731
    c = CREW_BY_ID[crew_id]
    place = LOCATIONS[ms["location"]]

    if ms["storm"]:
        mars = ms.get("storm") == "mars"  # the surface storm, not the particle storm
        A.append({"id": "storm", "level": 2, "env": True, "sys": "skin", "protocol": "rad",
                  "title": "Radiation is 51 times above normal." if mars else "A solar particle storm is hitting.",
                  "why": ("Curiosity's RAD detector recorded the peak at 06:15 on 20 May 2024. Nobody leaves the habitat today."
                          if mars else "NASA's DONKI logged particles above 10 MeV on 10 May 2024. In deep space nothing filters them."),
                  "todo": ["Go to the shelter and stay until the alert ends", "No activity outside today", "Write down your dosimeter reading"],
                  "sources": ["nasa:rad:2024-05-20" if mars else "nasa:donki:sep:2024-05"], "goals": []})

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
        A.append({"id": "behaviour", "level": 2, "sys": "brain", "test": "pvt", "risk": "fatigue",
                  "title": "Sleep, mood and focus are dropping together.",
                  "why": why,
                  "todo": ["Hand over any critical task today", "Retake the reaction test before any decision", "Follow the 3-night sleep plan"],
                  "sources": [inds[i]["source"] for i in ("sleep", "mood", "react")] if classic else [e["source"] for e in ev[:3]],
                  "goals": [{"id": "al_light", "area": "mental", "title": "Bright light on waking, amber light 2 h before bed"},
                            {"id": "al_screens", "area": "mental", "title": "No screens after 21:00 for 3 nights"},
                            {"id": "al_psy", "area": "mental", "title": "Record a private message for the mission psychologist"}]})

    if ms["location"] == "rocket" and lv("hr") and lv("water"):
        used.update(["hr", "water", "exer", "mood"])
        A.append({"id": "sickness", "level": 1, "sys": "kidneys",
                  "title": "Space sickness. It usually passes in 2 to 3 days.",
                  "why": "Your pulse is high and you have barely had water in your first hours in 0 g. Most astronauts go through this.",
                  "todo": ["Take a small sip of water every 15 minutes", "Move your head slowly and fix your eyes on one point",
                           "Tell the medical officer if you vomit more than twice"],
                  "sources": [inds["hr"]["source"], inds["water"]["source"]],
                  "goals": [{"id": "al_sip", "area": "physical", "title": "A sip of water every 15 minutes until dinner"},
                            {"id": "al_head", "area": "physical", "title": "Slow head movements, 5 min, three times today"}]})

    if place["gravity_key"] == "gp" and lv("bp") and lv("hr"):
        used.update(["bp", "hr"])
        A.append({"id": "regravity", "level": 1, "sys": "heart",
                  "title": "Your body is relearning weight.",
                  "why": "Lower pressure and a faster pulse than your normal when you stand. Expected in the first weeks after months in 0 g.",
                  "todo": ["Stand up in two steps: sit, wait, then stand", "Salted water in the morning", "No solo suited walks this week"],
                  "sources": [inds["bp"]["source"], inds["hr"]["source"]],
                  "goals": [{"id": "al_salt", "area": "physical", "title": "500 mL of salted water on waking"},
                            {"id": "al_stand", "area": "physical", "title": "Measure pressure lying down and standing"}]})

    am = latest_checkin(crew_id, "amsler", ms["day"])
    if am and am.get("distortion"):
        A.append({"id": "amsler", "level": 2, "sys": "eyes", "title": "Wavy lines on the Amsler grid.",
                  "why": "It can signal a change at the back of the eye, which is linked to fluid shift in 0 g.",
                  "todo": ["Repeat the test tomorrow at the same time", "Send an eye photo to Earth"],
                  "sources": [f"checkin:{crew_id}:amsler:day{am['day']}"], "goals": []})

    wb = latest_checkin(crew_id, "wellbeing", ms["day"], window=14)
    if wb and max(wb.get("phq2", 0), wb.get("gad2", 0)) >= 3:
        A.append({"id": "wellbeing", "level": 1, "sys": "brain", "title": "Your answers point to a hard stretch.",
                  "why": "Low mood or worry on more than half the days of the last two weeks. That is common on long missions and it helps to say it out loud.",
                  "todo": ["Talk to the medical officer this week", "Record a private message for the mission psychologist", "Protect your sleep window"],
                  "sources": [f"checkin:{crew_id}:wellbeing:day{wb['day']}"],
                  "goals": [{"id": "al_talk", "area": "mental", "title": "Book 15 minutes with the medical officer"}]})

    kss = latest_checkin(crew_id, "kss", ms["day"], window=1)
    if kss and int(kss.get("level", 0)) >= 7:
        A.append({"id": "sleepy", "level": 1, "sys": "brain", "title": "You rated yourself very sleepy.",
                  "why": "On the Karolinska scale, 7 or more means reactions are slower than they feel.",
                  "todo": ["Hand over critical or precise work for now", "Take a 20-minute nap if the schedule allows", "Retake the reaction test after resting"],
                  "sources": [f"checkin:{crew_id}:kss:day{kss['day']}"], "goals": []})

    sy = latest_checkin(crew_id, "symptoms", ms["day"], window=2)
    if sy and int(sy.get("severity", 0)) >= 3 and sy.get("items"):
        A.append({"id": "symptoms", "level": 1, "sys": None, "title": f"You reported strong {', '.join(sy['items'][:2]).lower()}.",
                  "why": "Strong symptoms are worth a look even when the sensors look normal.",
                  "todo": ["Tell the medical officer today", "Log it again tomorrow so the trend is clear"],
                  "sources": [f"checkin:{crew_id}:symptoms:day{sy['day']}"], "goals": []})

    from . import goals  # late import: goals imports health
    day = ms["day"]
    log = goals._log(crew_id)
    if not any(goals.is_done(crew_id, "mood", d, day, log) for d in (day, day - 1, day - 2)):
        A.append({"id": "missing_mood", "level": 1, "data": True, "sys": "brain", "test": "mood",
                  "title": "No mood check-in for 3 days.",
                  "why": "Canary reads your mood and stress less well without a check-in, and the numbers can look better than the days feel. Nothing is wrong with skipping; days get busy.",
                  "todo": ["A 30-second mood check-in is enough", "Add a line about why if you want the medical team to know"],
                  "sources": [f"goals:{crew_id}:mood:day{day}"], "goals": []})

    for i, d in inds.items():
        if d["level"] and (i not in used or d["population"]["status"] == "critical" or (d.get("standard") or {}).get("level") == 2):
            A.append(_indicator_alert(i, d))
    return sorted(A, key=lambda a: -a["level"])


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
