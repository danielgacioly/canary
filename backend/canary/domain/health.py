"""Personal baseline, alert levels, body-system status and the physical / mental readiness scores.

Each indicator is compared with the person's own pre-flight normal, never with a
population average:  z = (recent value - baseline) / personal spread.
Levels: 0 on track, 1 watch, 2 act. Thresholds are set by the medical team.
"""
import json
import statistics
from typing import Dict, List, Optional

from .. import db
from . import plan, reference, risk, telemetry
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


MIN_PREFLIGHT = 5  # measurements needed before the pre-flight mean is trusted over the catalog seed
_baselines: Dict[tuple, Dict[str, dict]] = {}


def baselines(crew_id: str) -> Dict[str, dict]:
    """Personal baseline per indicator, computed from the plan's pre-flight days.

    mean and spread of every measurement on those days (file rows plus the person's own check-ins). The spread never
    goes below the catalog's `sd`, so a quiet pre-flight cannot turn ordinary noise into alerts. The mean is shown with
    the precision the app displays (`dp`), so the "normal 55" on screen is the number the alert used. With too few
    pre-flight measurements (or no pre-flight leg in the plan) it falls back to the catalog seed. Cached per
    crew member, plan version and number of pre-flight check-ins.
    """
    key = (crew_id, plan.version(), telemetry.preflight_checkins(crew_id))
    hit = _baselines.get(key)
    if hit is None:
        if len(_baselines) > 64:
            _baselines.clear()
        hit = {}
        for ind, I in INDICATORS.items():
            vals = list(telemetry.preflight_values(crew_id, ind).values())
            if len(vals) >= MIN_PREFLIGHT:
                hit[ind] = {"mean": round(statistics.mean(vals), I["dp"]), "sd": max(statistics.pstdev(vals), I["sd"]), "n": len(vals), "from": "preflight"}
            else:
                hit[ind] = {"mean": CREW_BY_ID[crew_id]["base"][ind], "sd": I["sd"], "n": len(vals), "from": "catalog"}
        _baselines[key] = hit
    return hit


def thresholds_by_indicator() -> dict:
    """Optional per-indicator override of the global thresholds: {"sleep": {"watch": 1.0, "act": 2.0}}. No screen yet."""
    return db.get_setting("thresholds_by_indicator", {})


def indicator(crew_id: str, ind: str, ms: dict, th: Optional[dict] = None, last: Optional[Dict[str, int]] = None,
              uv: Optional[dict] = None, by_ind: Optional[dict] = None) -> dict:
    th = {**(th or thresholds()), **(thresholds_by_indicator() if by_ind is None else by_ind).get(ind, {})}
    day = ms["day"]
    last = telemetry.last_user_day(crew_id, day) if last is None else last
    obs = telemetry.observation(crew_id, ind, day, uv)  # where today's value came from
    I = INDICATORS[ind]
    B = baselines(crew_id)[ind]
    base, sd = B["mean"], B["sd"]
    if ind == "exer":  # the exercise plan changes with the place: compare with today's plan, not with pre-flight
        base = min(base, EXERCISE_BY_PLACE[ms["location"]][1])
    v = telemetry.current(crew_id, ind, day)
    z = (v - base) / sd
    bad = -z if I["dir"] == "low" else z if I["dir"] == "high" else abs(z)
    level = 0 if ms["learning"] else 2 if bad >= th["act"] else 1 if bad >= th["watch"] else 0
    # population range: the safety limit. A critical single reading today is level 2 even in learning;
    # a recent value outside the normal range is at least level 1 (after launch).
    pop = reference.check(ind, CREW_BY_ID[crew_id]["sex"], v)
    if reference.check(ind, CREW_BY_ID[crew_id]["sex"], obs["value"])["status"] == "critical":
        pop["status"] = "critical"
    if pop["status"] == "critical":
        level = 2
    elif pop["status"] == "out" and not ms["learning"]:
        level = max(level, 1)
    return {"id": ind, "name": I["name"], "unit": I["unit"], "area": I["area"], "facet": I.get("facet"),
            "dp": I["dp"], "value": round(v, 2), "baseline": round(base, 3), "delta": round(v - base, 2),
            "z": round(z, 2), "bad": round(bad, 2), "level": level,
            "source": f"telemetry:{crew_id}:{ind}:day{day}",
            "origin": obs["origin"], "last_measured_day": last.get(ind),
            "age_days": day - last[ind] if ind in last else None,
            "spread": round(sd, 3), "baseline_from": B["from"], "baseline_n": B["n"], "population": pop}


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


def dose(ms: dict) -> dict:
    total = telemetry.cumulative_dose(ms["day"], ms["location"], ms["storm"])
    return {"mission_msv": total, "rate_msv_day": LOCATIONS[ms["location"]]["dose_rate"],
            "career_limit_msv": CAREER_LIMIT_MSV, "pct_of_limit": round(100 * total / CAREER_LIMIT_MSV, 1),
            "simulated": True}


def systems(crew_id: str, ms: dict, inds: Dict[str, dict], risks: Optional[List[dict]] = None) -> Dict[str, dict]:
    """Colour of each body system: the highest level among the risks that act on it. One indicator outside your
    normal, with no risk behind it, is a watch (level 1) at most, unless it is past the population safety limit."""
    risks = risks or []
    out = {}
    for sid, S in SYSTEMS.items():
        worst = max([inds[i]["level"] for i in S["indicators"]] or [0])
        critical = any(inds[i]["population"]["status"] == "critical" for i in S["indicators"])
        lv = 2 if critical else max(risk.level_for(risks, sid), min(1, worst))
        note = None
        if sid == "eyes":
            a = latest_checkin(crew_id, "amsler", ms["day"])
            if a and a.get("distortion"):
                lv, note = 2, "Wavy or missing lines on the last Amsler grid."
            elif a:
                note = "Last Amsler grid was clear."
        if sid == "skin":
            d = dose(ms)
            if ms["storm"]:
                lv, note = 2, "Radiation storm in progress."
            elif d["pct_of_limit"] >= 50:
                lv, note = 1, f"{d['pct_of_limit']}% of the career limit used."
        if sid == "immune" and not ms["learning"] and 152 <= ms["day"] <= 165:
            lv, note = max(lv, 1), "Blood count due after the radiation storm."
        if ms["learning"]:  # nothing to watch yet, except a safety limit
            lv = 2 if any(inds[i]["population"]["status"] == "critical" for i in S["indicators"]) else 0
        out[sid] = {"id": sid, "name": S["name"], "area": S["area"], "level": lv, "status": STATUS[lv],
                    "indicators": S["indicators"], "note": note,
                    "risks": [r["id"] for r in risks if sid in r["systems"] and r["level"]]}
    return out


def score(inds: Dict[str, dict], area: str, syss: Dict[str, dict]) -> int:
    """Readiness 0 to 100. Prototype assumption: each indicator loses 18 points for every spread beyond 0.6 of its
    own normal, the area is their mean, and physical loses 6 points per level of eyes, skin and immune (no
    indicators of their own). The formula is a design choice, not a published score."""
    vals = [max(0.0, min(100.0, 100 - 18 * max(0.0, i["bad"] - 0.6))) for i in inds.values() if i["area"] == area]
    s = sum(vals) / len(vals)
    if area == "physical":
        s -= 6 * sum(x["level"] for k, x in syss.items() if k in ("eyes", "skin", "immune"))
    return int(round(max(0, min(100, s))))


def _indicator_alert(i: str, d: dict) -> dict:
    """Alert for one indicator on its own: outside the personal normal, or past the population safety limit."""
    sysid = next((k for k, s in SYSTEMS.items() if i in s["indicators"]), None)
    p = d["population"]
    critical = p["status"] == "critical"
    why = f"Today {d['value']:.{d['dp']}f} {d['unit']}. Your normal is {d['baseline']:.{d['dp']}f} {d['unit']}."
    if p["status"] != "in" and (p["low"] is not None or p["high"] is not None):
        lo = "no lower limit" if p["low"] is None else f"from {p['low']:g}"
        hi = "no upper limit" if p["high"] is None else f"up to {p['high']:g}"
        why += f" The usual adult range is {lo} {hi} {d['unit']}."
    return {"id": f"ind_{i}", "level": d["level"], "sys": sysid,
            "title": f"{d['name']} is past the safety limit." if critical else f"{d['name']} is outside your normal.",
            "why": why,
            "todo": TODO_BY_INDICATOR.get(i, ["Measure again in 1 hour", "If it stays, tell the medical officer"]),
            "sources": [d["source"]], "goals": []}


def alerts(crew_id: str, ms: dict, inds: Dict[str, dict], risks: Optional[List[dict]] = None) -> List[dict]:
    """Cross-signal rules first, then single indicators that are left. Each alert says what to do."""
    if ms["learning"]:  # no early warnings while Canary learns the baseline; a safety limit still speaks
        return [_indicator_alert(i, d) for i, d in inds.items() if d["population"]["status"] == "critical"]
    risks = risk.evaluate(crew_id, ms) if risks is None else risks
    A, used = [], set()
    lv = lambda i: inds[i]["level"]  # noqa: E731
    c = CREW_BY_ID[crew_id]
    place = LOCATIONS[ms["location"]]

    if ms["storm"]:
        mars = ms["storm"] == "mars"
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
        classic = all(inds[i]["level"] for i in ("sleep", "mood", "react"))  # the familiar text, when its three signals are all up
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
                  "sources": [f"goal:{crew_id}:mood:day{day}"], "goals": []})

    for i, d in inds.items():
        if d["level"] and (i not in used or d["population"]["status"] == "critical"):
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
        lvl = max([s["level"] for s in syss.values() if s["area"] == area] + [i["level"] for i in inds.values() if i["area"] == area])
        areas[area] = {"score": score(inds, area, syss), "level": lvl, "status": STATUS[lvl]}
    top = max([a["level"] for a in al if not a.get("data")] + [0])  # missing data is not a health risk
    return {"crew_id": crew_id, "indicators": inds, "systems": syss, "alerts": al, "risks": risks, "areas": areas,
            "level": top, "status": STATUS[top], "dose": dose(ms)}
