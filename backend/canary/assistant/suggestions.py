"""Entry 3 of the AI slot: personal suggestions in My space.

Code gathers the facts (each indicator against the person's own normal, how often each goal was
done this week, recent self-tests, the next leg of the mission plan). Rules turn them into
suggestions that carry the numbers behind them. A connected model may only rephrase the "why" of
each suggestion; guard.unknown_numbers rejects any rewrite that brings a number the facts do not
contain. With no model, the rule text is shown as it is.
"""
import json
from typing import Dict, List, Optional


from .. import db
from ..domain import advice, goals, health, mission, risk, telemetry
from ..domain.catalog import CREW, CREW_BY_ID, EXERCISE_BY_PLACE, LOCATIONS
from . import guard
from .providers import ProviderRequest, get_provider

LANGUAGE = {"h": "Portuguese", "k": "Japanese", "a": "Yoruba", "t": "Spanish"}
HOBBIES = {
    "g0": ["Sketch Earth or the stars from the window, ten minutes a day", "Grow lettuce or radishes in the plant chamber",
           "Learn one song on the cabin keyboard", "Build a playlist for each week of the mission"],
    "gp": ["Photograph the landscape from the same window at the same hour each day", "Sketch the rocks you collect before they are stowed",
           "Learn one song on the cabin keyboard", "Keep a field notebook of the sky: dust, clouds, sunsets"],
    "g1": ["Pick up an instrument for 15 minutes a day", "Walk outside without a phone, 20 minutes", "Cook a dish from a crewmate's home city"],
}


# What each suggestion is meant to move and after how many days it is checked (domain/advice.py).
# Prototype assumptions: no published rule says how long a habit takes to show in a number.
VERIFY = {sid: {"indicator": ind, "after_days": n} for sid, (ind, n) in {
    "talk": ("mood", 7), "sleep": ("sleep", 7), "nap": ("kss", 1), "social": ("social", 7), "exercise": ("exer", 7),
    "bone": ("bone", 7), "breathe": ("stress", 7), "water": ("water", 7), "read": ("mood", 7), "prepare": ("exer", 7),
    "hobby": ("mood", 7), "home": ("mood", 7)}.items()}


def _r(x: Optional[float], dp: int):
    """A reading as the app shows it; None stays None (no reading, or no normal of their own yet)."""
    return None if x is None else int(round(x)) if dp == 0 else round(x, dp)


def _week_counts(crew_id: str, today: int) -> Dict[str, int]:
    hist = goals._history(crew_id, today)
    counts: Dict[str, int] = {}
    for d in range(today - 6, today + 1):
        for g in hist.get(d, {}).get("done", []):
            counts[g] = counts.get(g, 0) + 1
    return counts


def facts(crew_id: str) -> dict:
    ms = mission.state()
    snap = health.snapshot(crew_id, ms)
    ind = snap["indicators"]
    fat = risk.get(snap["risks"], "fatigue")
    place = LOCATIONS[ms["location"]]
    leg = ms["leg"]
    nxt = leg.get("next")
    return {
        "crew_id": crew_id, "name": CREW_BY_ID[crew_id]["name"].split(" ")[0], "day": ms["day"], "learning": ms["learning"],
        "location": ms["location"], "gravity_key": place["gravity_key"], "reply": place["reply"],
        "ind": {k: {"value": _r(v["value"], v["dp"]), "normal": _r(v["baseline"], v["dp"]), "unit": v["unit"],
                    "level": v["level"], "source": v["source"]} for k, v in ind.items()},
        "risk": {"fatigue": {"level": fat["level"], "trend": fat["trend"], "since_day": fat["since_day"],
                             "signals": [e.get("indicator") or e["checkin"] for e in fat["evidence"]]}},
        "escalation": [{"risk": e["risk"], "key": e["key"], "alternative": e["alternative"]} for e in advice.escalation(crew_id, ms["day"])],
        "week": _week_counts(crew_id, ms["day"]),
        "exercise_target": EXERCISE_BY_PLACE[ms["location"]][1],
        "next_leg": {"location": nxt["location"], "label": nxt.get("label") or LOCATIONS[nxt["location"]]["name"],
                     "in_days": leg["days_to_next"], "gravity_key": LOCATIONS[nxt["location"]]["gravity_key"]} if nxt else None,
        "reading": health.latest_checkin(crew_id, "reading", ms["day"], window=14),
        "kss": health.latest_checkin(crew_id, "kss", ms["day"], window=1),
        "wellbeing": health.latest_checkin(crew_id, "wellbeing", ms["day"], window=14),
    }


def _pick(options: List[str], crew_id: str, day: int) -> str:
    return options[int(telemetry.h01(f"hobby:{crew_id}:{day // 7}") * len(options)) % len(options)]


def candidates(f: dict) -> List[dict]:
    i, w, out = f["ind"], f["week"], []
    fat = f["risk"]["fatigue"]  # the same layer the alerts use: no limits of our own in this file
    src = lambda *ks: [i[k]["source"] for k in ks if k in i]  # noqa: E731

    def add(sid, area, priority, title, why, steps, goal, sources):
        out.append({"id": sid, "area": area, "priority": priority, "title": title, "why": why, "steps": steps,
                    "goal": goal, "sources": sources, "verify": VERIFY.get(sid)})

    wb = f["wellbeing"]
    if wb and "wellbeing" in fat["signals"]:
        add("talk", "mental", 95, "Talk to someone this week",
            "Your wellbeing answers showed low mood or worry on more than half the days of the last two weeks.",
            ["Book 15 minutes with the medical officer", "Record a private message for the mission psychologist", "Tell one crewmate how you really are"],
            "Book 15 minutes with the medical officer", [f"checkin:{f['crew_id']}:wellbeing:day{wb['day']}"])

    s = i["sleep"]
    if s["level"] or "sleep" in fat["signals"]:
        add("sleep", "mental", 90, "Protect your sleep window",
            f"You are sleeping {s['value']} h against your normal {s['normal']} h.",
            ["Same lights-out time every night, within 30 minutes", "Amber light only, 2 hours before bed", "No screens after 21:00"],
            "Lights out at the same time tonight", src("sleep"))

    k = f["kss"]
    if k and i["kss"]["level"]:
        add("nap", "mental", 85, "Take a short nap before precise work",
            f"You rated your sleepiness {k['level']} of 9 today.",
            ["20 minutes, no longer, with an alarm", "Retake the reaction test after it", "Hand over precise tasks until then"],
            "A 20-minute nap before your next precise task", [f"checkin:{f['crew_id']}:kss:day{k['day']}"])

    soc = i["social"]
    if soc["level"] or w.get("social", 0) <= 3:
        add("social", "mental", 80, "More time with the crew, off duty",
            (f"Time with the crew is {soc['value']} min a day against your normal {soc['normal']} min, and " if soc["level"] else "")
            + f"you met the crew-time goal on {w.get('social', 0)} of the last 7 days.",
            ["Ask someone to share a meal today", "Suggest a film or game night this week", "Ten minutes of talk that is not about work"],
            "Share one meal with someone today", src("social"))

    ex = i["exer"]
    if not f["learning"] and ex["level"]:
        add("exercise", "physical", 78, "Win back your exercise minutes",
            f"You average {ex['value']} min a day; the target here is {f['exercise_target']} min.",
            ["Book your exercise slot first thing in the day", "Split it in two blocks if the schedule is tight", "Resistance first, cardio second"],
            "Exercise in two blocks today", src("exer"))

    bone = i.get("bone")
    if bone and bone["level"]:
        add("bone", "physical", 74, "Load your bones every day",
            f"Your estimated bone density is {100 + bone['value']:.1f}% of its pre-flight value; NASA asks for 95% or more.",
            ["Heavy resistance on the squat and deadlift", "Calcium and vitamin D with breakfast", "Impact work on the treadmill harness"],
            "Resistance session with squats and deadlifts", src("bone"))

    st, md = i["stress"], i["mood"]
    if st["level"] or md["level"]:
        add("breathe", "mental", 70, "Ten minutes of slow breathing after shift",
            (f"Stress is {st['value']} of 5 against your normal {st['normal']}, mood {md['value']} against {md['normal']}."
             if None not in (st["value"], st["normal"], md["value"], md["normal"]) else
             "Stress or mood is outside the range that is safe, or away from your normal."),
            ["Breathe in for 4, out for 6, for 10 minutes", "Same time and place each day", "Log your mood afterwards"],
            "10 minutes of slow breathing after shift", src("stress", "mood"))

    wa = i["water"]
    if wa["level"]:
        add("water", "physical", 65, "Drink before you are thirsty",
            f"You drink {wa['value']} L a day against your normal {wa['normal']} L. Thirst fades in space.",
            ["A full bag with every meal", "One more between meals, at a set time", "Watch urine colour"],
            "Drink 2.5 L today", src("water"))

    r = f["reading"]
    if w.get("read", 0) <= 3 or r:
        title = r.get("title") if r else None
        add("read", "mental", 60, f"Keep going with {title}" if title else "Read more, for yourself",
            (f"You last logged {r.get('minutes')} min of {title}. " if title else "") + f"You met the reading goal on {w.get('read', 0)} of the last 7 days.",
            ["20 minutes before lights out", "Keep the book where you sleep", "Log it on the Tests page"],
            "Read 20 minutes before lights out", [f"checkin:{f['crew_id']}:reading:day{r['day']}"] if r else [])

    nx = f["next_leg"]
    if nx and nx["in_days"] is not None and nx["in_days"] <= 90 and nx["gravity_key"] != f["gravity_key"]:
        to_weight = nx["gravity_key"] in ("gp", "g1")
        add("prepare", "physical", 55, f"Get ready for the next leg, in {nx['in_days']} days",
            f"{nx['label']} starts in {nx['in_days']} days. The body needs weeks to prepare for {'weight again' if to_weight else '0 g'}.",
            (["Add leg and balance work three times a week", "Practise standing up in two steps", "Rehearse the fluid and salt loading plan"]
             if to_weight else ["Practise moving slowly with head still", "Pack motion-sickness medication you know works", "Hydrate well the day before"]),
            "Leg and balance work today", [])

    if w.get("leisure", 0) <= 3 or md["level"]:
        others = [c for c in CREW if c["id"] != f["crew_id"]]
        mate = others[int(telemetry.h01(f"mate:{f['crew_id']}:{f['day'] // 7}") * len(others)) % len(others)]
        hobby = _pick(HOBBIES[f["gravity_key"]] + [f"Learn ten words of {LANGUAGE[mate['id']]} a day with {mate['name'].split(' ')[0]}"], f["crew_id"], f["day"])
        add("hobby", "mental", 50, "Start something just for you",
            f"You made time for something you enjoy on {w.get('leisure', 0)} of the last 7 days. A small hobby gives the week a shape.",
            [hobby, "Fifteen minutes is enough", "Tell someone about it at dinner"],
            hobby, [])

    if w.get("home", 0) <= 2 and f["reply"] != "Live":
        add("home", "mental", 45, "Stay close to home",
            f"You called or recorded for home on {w.get('home', 0)} of the last 7 days. Messages take {f['reply']} each way, so record, do not wait.",
            ["Record a two-minute message tonight", "Ask a question they can answer at length", "Save the replies to play on hard days"],
            "Record a message for home", [])

    for e in f["escalation"]:  # two rounds of advice in a row did not move the numbers: offer a different step
        alt = e["alternative"]
        out.append({"id": alt["id"], "area": alt["area"], "priority": 92, "title": alt["title"],
                    "why": "The last two pieces of advice did not change your numbers, so here is a different kind of step.",
                    "steps": alt["steps"], "goal": alt["goal"], "sources": [f"advice:{f['crew_id']}:{e['key']}"], "verify": alt["verify"]})

    if len(out) < 3:
        add("keep", "mental", 10, "Keep doing what works",
            "Everything is close to your own normal this week.",
            ["Keep your streak", "Try one new test on the Tests page", "Ask a crewmate how they are"],
            None, [])
    return sorted(out, key=lambda s: -s["priority"])[:6]


def build(crew_id: str) -> dict:
    f = facts(crew_id)
    items = candidates(f)
    provider = get_provider()
    mode = "rules"
    out = provider.complete(ProviderRequest(task="suggestions",
                                            system="Rephrase each 'why' warmly in one sentence. Use only the numbers given. Never diagnose.",
                                            question=json.dumps([{"id": s["id"], "why": s["why"]} for s in items]),
                                            context=[{"facts": f}]))
    if out.ok and out.answer:
        try:
            rewrites = {r["id"]: r["why"] for r in json.loads(out.answer)}
            blob = json.dumps(f)
            if all(not guard.unknown_numbers(t, blob) for t in rewrites.values()):
                for s in items:
                    s["why"] = rewrites.get(s["id"], s["why"])
                mode = "ai"
        except (ValueError, KeyError, TypeError):
            pass
    taken = {g["id"] for g in goals.suggested(crew_id, f["day"])}
    for s in items:
        s["accepted"] = f"sg_{s['id']}" in taken
    return {"mode": mode, "provider": provider.name, "day": f["day"], "items": items}


def accept(crew_id: str, sid: str) -> dict:
    f = facts(crew_id)
    s = next((x for x in candidates(f) if x["id"] == sid), None)
    if not s or not s["goal"]:
        raise ValueError("no such suggestion today")
    allg = db.get_setting("suggested_goals", {})
    mine = [g for g in allg.get(crew_id, []) if g["id"] != f"sg_{sid}"]
    mine.append({"id": f"sg_{sid}", "area": s["area"], "title": s["goal"], "from_day": f["day"], "to_day": f["day"] + 6,
                 "verify": s.get("verify")})
    allg[crew_id] = mine
    db.set_setting("suggested_goals", allg)
    advice.start(crew_id, f"sg_{sid}", "suggestion", s.get("verify"), f["day"])
    advice.sync(crew_id, f["day"])
    return build(crew_id)

