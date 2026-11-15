"""Entry 3 of the AI slot: personal suggestions in My space.

Every suggestion balances two sides. OUTSIDE is the environment, the same for everyone on board: the place, the gravity,
a storm, the mission phase, the signal delay, the protocols in force, the time of day. INSIDE is the person's own state:
indicators off their normal, goals, check-ins. A suggestion carries one short line for each (`because_outside`,
`because_inside`, either may be empty) and the Protocols page it relates to (`protocol`). Ranking is transparent
(see `rank_of`): the rule's own priority, a bonus when it speaks to both sides, and a small weight learned from what this
person accepted or dismissed before (table suggestion_feedback; the AI slot may replace the weight later).

Code gathers the facts (each indicator against the person's own normal, how often each goal was
done this week, recent self-tests, the next leg of the mission plan). Rules turn them into
suggestions that carry the numbers behind them. A connected model may only rephrase the "why" of
each suggestion. Each rewrite is checked on its own (guard.unknown_numbers against the facts, non-empty,
not too long); the ones that pass are used and the rest keep the rule text. The response says how many were
rewritten and, when the model was not used or only partly used, why (`fallback_reason`). With no model, the
rule text is shown as it is. Every build is logged in assistant_log with metadata only: the medical audit
sees that suggestions were built and how, never what they say.
"""
import json
import time
from typing import Any, Dict, List, Optional, Tuple


from .. import db
from ..domain import advice, goals, health, mission, plan, privacy, protocol_pages, risk, telemetry
from ..domain.catalog import CREW, CREW_BY_ID, EXERCISE_BY_PLACE, LOCATIONS, RECORDS
from . import chat, guard
from .providers import ProviderRequest, get_provider

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


def _known(d: dict) -> bool:
    """A reading and a normal of the person's own: the only case a sentence may quote both numbers."""
    return d.get("value") is not None and d.get("normal") is not None


def _language(crew_id: str) -> Optional[str]:
    """A language a person speaks besides English, first of their registered languages (None when they list none)."""
    langs = (RECORDS.get(crew_id) or {}).get("languages") or []
    return next((x for x in langs if x.strip().lower() != "english"), None)


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
    dose = health.dose(ms)
    mine = health.dose(ms, crew_id)  # this person's own career dose: inside, never shown to anyone else
    iso = next(h for h in privacy.ridge(ms["location"], ms["storm"], ms["day"]) if h["id"] == "I")
    outside = {"place": place["name"], "gravity": place["gravity"], "storm": ms["storm"], "time": mission.mission_time(),
               "leg_label": leg.get("label") or place["name"], "leg_day": leg["day_in_leg"], "leg_length": leg["length"],
               "since_change": plan.days_since_gravity_change(ms["day"]),
               "isolation": {"level": iso["level"], "label": iso["label"], "here": iso["here"]},
               "in_force": [i["id"] for i in protocol_pages.in_force(ms, dose)]}
    return {
        "outside": outside, "career": {"msv": mine["career_msv"], "pct": mine["career_pct_of_limit"]},
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


BOTH_BONUS = 20   # a suggestion that speaks to the environment and to the person ranks above one that speaks to one side
LEARN_MAX = 10    # the most a person's past choices can move a suggestion up or down


def _outside(f: dict, sid: str) -> tuple:
    """(line, protocol id) of what in the environment makes this suggestion fit today, or ("", None). Same for everyone aboard."""
    o, rep = f["outside"], f["reply"]
    iso = o["isolation"]
    storm = ("A solar particle storm is hitting and the crew is in the shelter", "rad") if o["storm"] else None
    delay = (f"Earth replies in {rep} each way", "delay") if rep != "Live" else None
    isolation = (f"Isolation is {iso['label'].lower()} here: {iso['here'].lower()}", None) if iso["level"] >= 1 and not f["learning"] else None
    hour = int(o["time"][:2]) if o.get("time") else 12
    leg = (f"Day {o['leg_day']} of {o['leg_length']} on {o['leg_label']}", None) if o["leg_length"] >= 14 and not f["learning"] else None
    g = f["gravity_key"]
    pick = {
        "sleep": (f"It is {o['time']} on board, in the hours NASA says to avoid critical tasks (V1 6001)", None) if 1 <= hour < 7 else None,
        "nap": (f"It is {o['time']} on board, in the hours NASA says to avoid critical tasks (V1 6001)", None) if 1 <= hour < 7 else None,
        "social": isolation or leg,
        "exercise": (f"The target at {o['place']} is {f['exercise_target']} min a day in {o['gravity']}", None) if not f["learning"] else None,
        "bone": (f"In {o['gravity']} bones lose load every day without exercise", None) if g in ("g0", "gp") else None,
        "breathe": storm or isolation,
        "water": ("Thirst fades in 0 g", "sickness" if f["location"] == "rocket" else None) if g == "g0" else None,
        "read": storm and ("The storm keeps everyone indoors today", "rad") or leg,
        "hobby": storm and ("The storm keeps everyone indoors today", "rad") or leg,
        "home": delay,
        "talk": delay or isolation,
    }.get(sid)
    return pick or ("", None)


def candidates(f: dict) -> List[dict]:
    i, w, out, o = f["ind"], f["week"], [], f["outside"]
    fat = f["risk"]["fatigue"]  # the same layer the alerts use: no limits of our own in this file
    src = lambda *ks: [i[k]["source"] for k in ks if k in i]  # noqa: E731

    def add(sid, area, priority, title, why, steps, goal, sources, inside="", outside=None):
        line, proto = outside if outside is not None else _outside(f, sid)
        out.append({"id": sid, "area": area, "priority": priority, "title": title, "why": why, "steps": steps,
                    "goal": goal, "sources": sources, "verify": VERIFY.get(sid),
                    "because_outside": line, "because_inside": inside, "protocol": proto})

    # ---- from the environment first: what the place and the phase ask of everyone, with what the person's own numbers say about it
    if o["storm"] and not f["learning"]:
        add("storm", "physical", 97, "Follow the radiation storm protocol",
            "A particle storm is hitting: the shelter and your dosimeter come first.",
            ["Go to the shelter and stay until the alert ends", "Write down your dosimeter reading", "Bring water, food and the medical kit in with you"],
            "Write down your dosimeter reading today", [],
            inside=f"Your career dose is {f['career']['msv']} mSv, {f['career']['pct']}% of NASA's 600 mSv",
            outside=("A solar particle storm is hitting and EVA is suspended for everyone" if "eva" in o["in_force"] else "A solar particle storm is hitting", "rad"))
    if f["location"] == "rocket":
        hr, wa = i["hr"], i["water"]
        add("firstdays", "physical", 88, "Go easy on the first days in 0 g",
            "Space sickness is common in the first hours and usually passes in 2 to 3 days.",
            ["Take a small sip of water every 15 minutes", "Move your head slowly and fix your eyes on one point", "Tell the medical officer if you vomit more than twice"],
            "A sip of water every 15 minutes until dinner", src("hr", "water"),
            inside=(f"Your pulse is {hr['value']} against your normal {hr['normal']} and you have barely had water" if hr["level"] and wa["level"] and None not in (hr["value"], hr["normal"]) else ""),
            outside=("The first hours in 0 g: space sickness is common", "sickness"))
    if o["since_change"] is not None and o["since_change"] < 30 and not f["learning"]:
        bp, hr = i["bp"], i["hr"]
        add("readapt", "physical", 84, "Stand up slowly while your body relearns weight",
            "Lower pressure and a faster pulse than your normal when you stand are expected in the first weeks after 0 g.",
            ["Stand up in two steps: sit, wait, then stand", "500 mL of salted water on waking", "No solo suited walks this week"],
            "500 mL of salted water on waking", src("bp", "hr"),
            inside=("Your pressure or pulse is off your normal" if bp["level"] or hr["level"] else ""),
            outside=(f"Day {o['since_change'] + 1} in {o['gravity']} after months in 0 g", "regravity"))

    wb = f["wellbeing"]
    if wb and "wellbeing" in fat["signals"]:
        add("talk", "mental", 95, "Talk to someone this week",
            "Your wellbeing answers showed low mood or worry on more than half the days of the last two weeks.",
            ["Book 15 minutes with the medical officer", "Record a private message for the mission psychologist", "Tell one crewmate how you really are"],
            "Book 15 minutes with the medical officer", [f"checkin:{f['crew_id']}:wellbeing:day{wb['day']}"],
            inside="Your wellbeing answers were low on more than half the days of the last two weeks")

    s = i["sleep"]
    if s["level"] or "sleep" in fat["signals"]:
        known = _known(s)
        add("sleep", "mental", 90, "Protect your sleep window",
            f"You are sleeping {s['value']} h against your normal {s['normal']} h." if known else
            "Protecting your sleep window helps, and there is no reading of your sleep yet to compare with your normal.",
            ["Same lights-out time every night, within 30 minutes", "Amber light only, 2 hours before bed", "No screens after 21:00"],
            "Lights out at the same time tonight", src("sleep"),
            inside=f"You sleep {s['value']} h against your normal {s['normal']} h" if known else "")

    k = f["kss"]
    if k and i["kss"]["level"]:
        add("nap", "mental", 85, "Take a short nap before precise work",
            f"You rated your sleepiness {k['level']} of 9 today.",
            ["20 minutes, no longer, with an alarm", "Retake the reaction test after it", "Hand over precise tasks until then"],
            "A 20-minute nap before your next precise task", [f"checkin:{f['crew_id']}:kss:day{k['day']}"],
            inside=f"You rated your sleepiness {k['level']} of 9 today")

    soc = i["social"]
    if soc["level"] or w.get("social", 0) <= 3:
        add("social", "mental", 80, "More time with the crew, off duty",
            (f"Time with the crew is {soc['value']} min a day against your normal {soc['normal']} min, and " if soc["level"] and _known(soc) else "")
            + f"you met the crew-time goal on {w.get('social', 0)} of the last 7 days.",
            ["Ask someone to share a meal today", "Suggest a film or game night this week", "Ten minutes of talk that is not about work"],
            "Share one meal with someone today", src("social"),
            inside=(f"Crew time is {soc['value']} min a day against your normal {soc['normal']}" if soc["level"] and _known(soc) else f"You met the crew-time goal on {w.get('social', 0)} of the last 7 days"))

    ex = i["exer"]
    if not f["learning"] and ex["level"]:
        add("exercise", "physical", 78, "Win back your exercise minutes",
            f"You average {ex['value']} min a day; the target here is {f['exercise_target']} min.",
            ["Book your exercise slot first thing in the day", "Split it in two blocks if the schedule is tight", "Resistance first, cardio second"],
            "Exercise in two blocks today", src("exer"),
            inside=f"You average {ex['value']} min a day")

    bone = i.get("bone")
    if bone and bone["level"] and bone["value"] is not None:
        add("bone", "physical", 74, "Load your bones every day",
            f"Your estimated bone density is {100 + bone['value']:.1f}% of its pre-flight value; NASA asks for 95% or more.",
            ["Heavy resistance on the squat and deadlift", "Calcium and vitamin D with breakfast", "Impact work on the treadmill harness"],
            "Resistance session with squats and deadlifts", src("bone"),
            inside=f"Estimated bone density is {100 + bone['value']:.1f}% of pre-flight; NASA asks for 95%")

    st, md = i["stress"], i["mood"]
    if st["level"] or md["level"]:
        add("breathe", "mental", 70, "Ten minutes of slow breathing after shift",
            (f"Stress is {st['value']} of 5 against your normal {st['normal']}, mood {md['value']} against {md['normal']}."
             if None not in (st["value"], st["normal"], md["value"], md["normal"]) else
             "Stress or mood is outside the range that is safe, or away from your normal."),
            ["Breathe in for 4, out for 6, for 10 minutes", "Same time and place each day", "Log your mood afterwards"],
            "10 minutes of slow breathing after shift", src("stress", "mood"),
            inside=(f"Stress is {st['value']} of 5 against your normal {st['normal']}" if None not in (st["value"], st["normal"]) else "Stress or mood is off your normal"))

    wa = i["water"]
    if wa["level"] and _known(wa):
        add("water", "physical", 65, "Drink before you are thirsty",
            f"You drink {wa['value']} L a day against your normal {wa['normal']} L. Thirst fades in space.",
            ["A full bag with every meal", "One more between meals, at a set time", "Watch urine colour"],
            "Drink 2.5 L today", src("water"),
            inside=f"You drink {wa['value']} L a day against your normal {wa['normal']} L")

    r = f["reading"]
    if w.get("read", 0) <= 3 or r:
        title = r.get("title") if r else None
        add("read", "mental", 60, f"Keep going with {title}" if title else "Read more, for yourself",
            (f"You last logged {r.get('minutes')} min of {title}. " if title else "") + f"You met the reading goal on {w.get('read', 0)} of the last 7 days.",
            ["20 minutes before lights out", "Keep the book where you sleep", "Log it on the Tests page"],
            "Read 20 minutes before lights out", [f"checkin:{f['crew_id']}:reading:day{r['day']}"] if r else [],
            inside=f"You met the reading goal on {w.get('read', 0)} of the last 7 days")

    nx = f["next_leg"]
    if nx and nx["in_days"] is not None and nx["in_days"] <= 90 and nx["gravity_key"] != f["gravity_key"]:
        to_weight = nx["gravity_key"] in ("gp", "g1")
        add("prepare", "physical", 55, f"Get ready for the next leg, in {nx['in_days']} days",
            f"{nx['label']} starts in {nx['in_days']} days. The body needs weeks to prepare for {'weight again' if to_weight else '0 g'}.",
            (["Add leg and balance work three times a week", "Practise standing up in two steps", "Rehearse the fluid and salt loading plan"]
             if to_weight else ["Practise moving slowly with head still", "Pack motion-sickness medication you know works", "Hydrate well the day before"]),
            "Leg and balance work today", [],
            inside=(f"You average {ex['value']} min of exercise a day" if ex["value"] is not None else ""),
            outside=(f"{nx['label']} starts in {nx['in_days']} days and gravity changes", "regravity" if nx["gravity_key"] == "gp" else "sickness" if nx["location"] == "rocket" else None))

    if w.get("leisure", 0) <= 3 or md["level"]:
        others = [c for c in CREW if c["id"] != f["crew_id"]]
        mates = [c for c in others if _language(c["id"])]  # crewmates who speak something besides English
        options = list(HOBBIES[f["gravity_key"]])
        if mates:
            mate = mates[int(telemetry.h01(f"mate:{f['crew_id']}:{f['day'] // 7}") * len(mates)) % len(mates)]
            options.append(f"Learn ten words of {_language(mate['id'])} a day with {mate['name'].split(' ')[0]}")
        hobby = _pick(options, f["crew_id"], f["day"])
        add("hobby", "mental", 50, "Start something just for you",
            f"You made time for something you enjoy on {w.get('leisure', 0)} of the last 7 days. A small hobby gives the week a shape.",
            [hobby, "Fifteen minutes is enough", "Tell someone about it at dinner"],
            hobby, [],
            inside=f"You made time for something you enjoy on {w.get('leisure', 0)} of the last 7 days")

    if w.get("home", 0) <= 2 and f["reply"] != "Live":
        add("home", "mental", 45, "Stay close to home",
            f"You called or recorded for home on {w.get('home', 0)} of the last 7 days. Messages take {f['reply']} each way, so record, do not wait.",
            ["Record a two-minute message tonight", "Ask a question they can answer at length", "Save the replies to play on hard days"],
            "Record a message for home", [],
            inside=f"You called or recorded for home on {w.get('home', 0)} of the last 7 days")

    for e in f["escalation"]:  # two rounds of advice in a row did not move the numbers: offer a different step
        alt = e["alternative"]
        out.append({"id": alt["id"], "area": alt["area"], "priority": 92, "title": alt["title"],
                    "why": "The last two pieces of advice did not change your numbers, so here is a different kind of step.",
                    "steps": alt["steps"], "goal": alt["goal"], "sources": [f"advice:{f['crew_id']}:{e['key']}"], "verify": alt["verify"],
                    "because_outside": "", "because_inside": "The last two pieces of advice did not change your numbers", "protocol": None})

    if len(out) < 3:
        add("keep", "mental", 10, "Keep doing what works",
            "Everything is close to your own normal this week.",
            ["Keep your streak", "Try one new test on the Tests page", "Ask a crewmate how they are"],
            None, [], inside="Everything is close to your own normal this week", outside=("", None))
    return sorted(out, key=lambda s: -s["priority"])


# ---------------------------------------------------------------- what this person chose before (the learning seam)
def record_choice(crew_id: str, sid: str, action: str, day: int) -> None:
    """Remember that this person accepted or dismissed a kind of suggestion. Private to them: never read for anyone else."""
    db.x("INSERT INTO suggestion_feedback(crew_id,sid,action,day,created_at) VALUES(?,?,?,?,?)", (crew_id, sid, action, day, time.time()))


def choices(crew_id: str) -> Dict[str, dict]:
    out: Dict[str, dict] = {}
    for r in db.q("SELECT sid, action, COUNT(*) n FROM suggestion_feedback WHERE crew_id=? GROUP BY sid, action", (crew_id,)):
        out.setdefault(r["sid"], {"accepted": 0, "dismissed": 0})["accepted" if r["action"] == "accept" else "dismissed"] = r["n"]
    return out


def learned_weight(accepted: int, dismissed: int) -> float:
    """Learned from your choices: from -LEARN_MAX (always dismissed) to +LEARN_MAX (always accepted), shrunk towards 0 while
    there is little to learn from (the +2 in the denominator). A plain count, so it can be read and replaced."""
    return round(LEARN_MAX * (accepted - dismissed) / (accepted + dismissed + 2), 1)


def rank_of(s: dict, chosen: Dict[str, dict]) -> dict:
    """The score of a suggestion and where each point comes from: its rule's priority, a bonus for speaking to both the
    environment and the person, and the weight learned from this person's own choices."""
    c = chosen.get(s["id"], {"accepted": 0, "dismissed": 0})
    both = BOTH_BONUS if (s["because_outside"] and s["because_inside"]) else 0
    learned = learned_weight(c["accepted"], c["dismissed"])
    return {"priority": s["priority"], "both": both, "learned": learned, "score": round(s["priority"] + both + learned, 1),
            "accepted": c["accepted"], "dismissed": c["dismissed"]}


def ranked(crew_id: str, f: dict) -> List[dict]:
    chosen = choices(crew_id)
    gone = {r["sid"] for r in db.q("SELECT sid FROM suggestion_feedback WHERE crew_id=? AND action='dismiss' AND day=?", (crew_id, f["day"]))}
    items = [{**s, "rank": rank_of(s, chosen)} for s in candidates(f) if s["id"] not in gone]
    return sorted(items, key=lambda s: -s["rank"]["score"])[:6]


MAX_WHY = 300  # a rewritten "why" longer than this is not one warm sentence: keep the rule text


def _rewrite(provider, f: dict, items: List[dict]) -> Tuple[Dict[str, str], Optional[str], List[str], Any, List[str]]:
    """Ask the model to rephrase each "why". Returns (accepted rewrites by id, fallback reason or None, rejected numbers,
    the ProviderResult or None, rejected rule ids). Each item is checked on its own: a rewrite with an invented number
    or with wording/privacy rule violations (guard.text_violations) keeps the rule text."""
    try:
        out = provider.complete(ProviderRequest(task="suggestions",
                                                system="Rephrase each 'why' warmly in one sentence. Use only the numbers given. Never diagnose.",
                                                question=json.dumps([{"id": s["id"], "why": s["why"]} for s in items]),
                                                context=[{"facts": f}]))
    except Exception:  # noqa: BLE001 - a provider bug must not break the page; the rule text stays
        return {}, "api:error", [], None, []
    if not out.ok:
        return {}, out.guard_exit or ("api:error" if provider.configured else None), [], out, []
    try:
        raw = json.loads(out.answer)
        pairs = [(r["id"], r["why"]) for r in raw]
    except (ValueError, KeyError, TypeError):
        return {}, "parse_error", [], out, []
    ids, blob = {s["id"] for s in items}, json.dumps(f)
    accepted: Dict[str, str] = {}
    rejected: List[str] = []
    rules: List[str] = []
    for sid, why in pairs:
        if sid not in ids or not isinstance(why, str):
            continue
        why = why.strip()
        if not why or len(why) > MAX_WHY:
            continue
        unknown = guard.unknown_numbers(why, blob)
        if unknown:
            rejected += unknown
            continue
        broken = guard.text_violations(why, subject_crew_id=f["crew_id"])
        if broken:
            rules += broken
            continue
        accepted[sid] = why
    reason = None
    if len(accepted) < len(items):
        reason = "numbers_rejected" if rejected else "rules_rejected" if rules else "model:bad_output"  # else: missing, empty or too long
    return accepted, reason, list(dict.fromkeys(rejected)), out, list(dict.fromkeys(rules))


def build(crew_id: str) -> dict:
    t0 = time.monotonic()
    f = facts(crew_id)
    items = ranked(crew_id, f)
    provider = get_provider()
    configured = bool(getattr(provider, "configured", False))
    rewrites, reason, rejected, out, rules = _rewrite(provider, f, items)
    for s in items:
        if s["id"] in rewrites:
            s["why"], s["source"] = rewrites[s["id"]], "ai"
        else:
            s["source"] = "rules"
    n = len(rewrites)
    mode = "ai" if n else "rules"
    model = (out.model if out and out.model else getattr(provider, "model", None)) if configured else None
    taken = {g["id"] for g in goals.suggested(crew_id, f["day"])}
    for s in items:
        s["accepted"] = f"sg_{s['id']}" in taken
    # The medical audit sees that a build happened and how, never what the suggestions say (astronaut-only).
    flags = ([reason] if reason else []) + rules + (list(out.notes) if out else [])
    chat.record(crew_id, chat.SUGGESTIONS_LOG,
                {"mode": mode, "status": "suggestions", "provider": provider.name, "model": model,
                 "rewritten": n, "total": len(items), "fallback_reason": reason, "rejected_rules": rules},
                provider.name, model, mode, flags, t0,
                out.input_tokens if out else 0, out.output_tokens if out else 0)
    return {"mode": mode, "provider": provider.name, "model": model, "configured": configured, "rewritten": n,
            "fallback_reason": reason, "rejected_numbers": rejected, "rejected_rules": rules, "day": f["day"], "items": items,
            "context": {"place": f["outside"]["place"], "in_force": f["outside"]["in_force"]}}


def dismiss(crew_id: str, sid: str) -> dict:
    f = facts(crew_id)
    if not any(x["id"] == sid for x in candidates(f)):
        raise ValueError("no such suggestion today")
    record_choice(crew_id, sid, "dismiss", f["day"])
    return build(crew_id)


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
    record_choice(crew_id, sid, "accept", f["day"])
    advice.start(crew_id, f"sg_{sid}", "suggestion", s.get("verify"), f["day"])
    advice.sync(crew_id, f["day"])
    return build(crew_id)
