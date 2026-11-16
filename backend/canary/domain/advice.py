"""The advice loop: every advice the person accepts becomes a small experiment.

trigger (an alert or a suggestion) -> action (a goal) -> check (the indicator it should move, after N days)
-> outcome ("improved", "same" or "worse", against the person's own normal).

Nothing here uses a clock: an outcome is a function of the mission day asked about, so the demo can jump anywhere
and the same day always gives the same answer. Rows are written only by routes that change something (ticking a
goal, accepting a suggestion), never by a GET.

Two rounds in a row without improvement for the same risk escalate: a different suggestion for the person, and one
message for the crew medical officer (or the substitute), once. Canary never prescribes: the alternatives below are
the same kind of everyday step the suggestions already offer.
"""
import math
import time
from typing import Dict, List, Optional

from .. import db
from . import assumptions as A
from . import risk, telemetry
from .catalog import CREW_BY_ID

# Prototype assumptions (no published rule says how much a number must move for an advice to have "worked").
MARGIN = A.value("advice.margin")  # personal spreads: the average deviation must move by at least this much to count as improved or worse
SOURCE = {"source": "prototype assumption", "verified": False}
# Adherence: the goal must have been ticked on at least this share of the days between the start and the check.
# Prototype assumption. Without it, a change in a number says nothing about the advice, so no outcome is given.
ADHERENCE_MIN = 0.7

ALTERNATIVES: Dict[str, List[dict]] = {
    "fatigue": [
        {"title": "Change one thing in your day, not three", "area": "mental",
         "steps": ["Pick the one habit most likely to help (lights-out time, a rest block, or a meal with the crew)",
                   "Keep it for 5 days before judging it", "Tell the medical officer which one you picked"],
         "goal": "Keep one change in your day for 5 days", "verify": {"indicator": "sleep", "after_days": 5}},
        {"title": "Add short rest breaks between tasks", "area": "mental",
         "steps": ["Five minutes, eyes away from screens, between long tasks", "Same times each day",
                   "Log how sleepy you feel at the end of the shift"],
         "goal": "Five-minute rest breaks between tasks today", "verify": {"indicator": "kss", "after_days": 5}},
        {"title": "Ask for your workload to be reviewed", "area": "mental",
         "steps": ["Write down the three tasks that cost the most energy", "Talk to the medical officer and the commander about them",
                   "Agree what can wait this week"],
         "goal": "Talk about your workload with the medical officer", "verify": {"indicator": "tlx", "after_days": 5}},
    ],
}


def _bad(crew_id: str, ind: str, day: int) -> Optional[float]:
    """How far the indicator is from the person's normal around `day`, in personal spreads (higher is worse):
    the mean of the last three days' values, so one noisy day cannot decide an outcome. Days with no current reading, or
    with no normal of their own to compare with yet, do not count; None when no day counts."""
    from . import health
    vals = [b for b in (health.indicator(crew_id, ind, risk._day_ms(d))["bad"] for d in (day, day - 1, day - 2)) if b is not None]
    return sum(vals) / len(vals) if vals else None


def risk_of(indicator: str) -> Optional[str]:
    """The risk an indicator feeds, if any (for now only fatigue)."""
    return "fatigue" if indicator in risk.FATIGUE["weights"] else None


def start(crew_id: str, goal_id: str, origin: str, verify: Optional[dict], day: int) -> Optional[int]:
    """Open an advice the first time the person ticks an alert goal or accepts a suggestion. One active row per goal."""
    if not verify:
        return None
    if db.q("SELECT id FROM advice WHERE crew_id=? AND goal_id=? AND start_day<=? AND check_day>?", (crew_id, goal_id, day, day)):
        return None
    ind = verify["indicator"]
    start_bad = _bad(crew_id, ind, day)
    if start_bad is None:  # nothing to compare with later: no experiment without a starting number
        return None
    return db.x("INSERT INTO advice(crew_id,goal_id,origin,indicator,risk,start_day,check_day,start_bad,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                (crew_id, goal_id, origin, ind, risk_of(ind), day, day + int(verify["after_days"]), start_bad, time.time()))


def _adhered(row: dict) -> bool:
    """Was the goal ticked often enough between the start and the check day? Read from the goal log. A goal that was never
    ticked has no adherence, so it gets no outcome (`no_adherence`). A suggestion's goal (sg_<id>) is ticked on the daily
    goal of the same id (sg_sleep -> sleep), and both count."""
    span = max(1, int(row["check_day"]) - int(row["start_day"]))
    ids = sorted({row["goal_id"], row["goal_id"][3:] if row["goal_id"].startswith("sg_") else row["goal_id"]})
    marks = ",".join("?" * len(ids))
    n = db.q(f"SELECT COUNT(DISTINCT day) n FROM goal_log WHERE crew_id=? AND goal_id IN ({marks}) AND day>=? AND day<? AND done=1",
             (row["crew_id"], *ids, row["start_day"], row["check_day"]))[0]["n"]
    return n >= math.ceil(ADHERENCE_MIN * span)


def outcome(row: dict, day: int) -> str:
    """pending until check_day. Then: no_data when nothing was measured around check_day; no_adherence when the goal was
    not done often enough in between; otherwise improved / same / worse from how far the indicator moved. The outcome
    compares the numbers before and after. It never says the advice caused the change."""
    if day < row["check_day"]:
        return "pending"
    end = _bad(row["crew_id"], row["indicator"], row["check_day"])
    if end is None:
        return "no_data"
    if not _adhered(row):
        return "no_adherence"
    delta = end - row["start_bad"]
    return "improved" if delta <= -MARGIN else "worse" if delta >= MARGIN else "same"


def _item(row: dict, day: int) -> dict:
    st = outcome(row, day)
    out = {"goal_id": row["goal_id"], "origin": row["origin"], "indicator": row["indicator"], "risk": row["risk"],
           "start_day": row["start_day"], "check_day": row["check_day"], "start_bad": round(row["start_bad"], 2), "status": st}
    if st != "pending":
        end = _bad(row["crew_id"], row["indicator"], row["check_day"])
        out["bad_at_check"] = None if end is None else round(end, 2)
    return out


def rows(crew_id: str, day: int) -> List[dict]:
    """Advice that had started by `day` (the demo clock may move back), oldest first."""
    return db.q("SELECT * FROM advice WHERE crew_id=? AND start_day<=? ORDER BY start_day, id", (crew_id, day))


def for_crew(crew_id: str, day: int) -> dict:
    items = [_item(r, day) for r in rows(crew_id, day)]
    return {"active": [i for i in items if i["status"] == "pending"], "done": [i for i in items if i["status"] != "pending"]}


def by_goal(crew_id: str, day: int) -> Dict[str, dict]:
    """Latest advice per goal id, for the goal list: {goal_id: {status, check_day}}."""
    out: Dict[str, dict] = {}
    for r in rows(crew_id, day):
        out[r["goal_id"]] = {"status": outcome(r, day), "check_day": r["check_day"]}
    return out


def _rounds(crew_id: str, rid: str, day: int) -> List[dict]:
    """Concluded advice for one risk, grouped by the day it started (one round = what was tried together)."""
    groups: Dict[int, List[dict]] = {}
    for r in rows(crew_id, day):
        if r["risk"] == rid and r["check_day"] <= day:
            groups.setdefault(r["start_day"], []).append(r)
    out = []
    for start_day, rs in groups.items():
        sts = [outcome(r, day) for r in rs]
        if not any(x in ("improved", "same", "worse", "no_adherence") for x in sts):  # a round nobody could measure says nothing
            continue
        out.append({"start_day": start_day, "check_day": max(r["check_day"] for r in rs),
                    "improved": "improved" in sts, "indicators": sorted({r["indicator"] for r in rs}),
                    "results": dict(zip([r["indicator"] for r in rs], sts))})
    return sorted(out, key=lambda g: (g["check_day"], g["start_day"]))


def escalation(crew_id: str, day: int) -> List[dict]:
    """Risks whose last two concluded rounds both brought no improvement. Pure: a function of the day."""
    out = []
    for rid in sorted(ALTERNATIVES):
        last = _rounds(crew_id, rid, day)[-2:]
        if len(last) == 2 and not any(g["improved"] for g in last):
            key = f"{rid}:{last[1]['check_day']}"
            alts = ALTERNATIVES[rid]
            pick = alts[int(telemetry.h01(f"alt:{crew_id}:{key}") * len(alts)) % len(alts)]
            out.append({"risk": rid, "key": key, "rounds": last, "alternative": {**pick, "id": f"alt_{rid}"}})
    return out


def sync(crew_id: str, day: int) -> None:
    """Tell the medical officer, once per escalation. Called only by routes that write (never by a GET)."""
    from . import privacy
    done = db.get_setting("advice_escalated", [])
    new = [e for e in escalation(crew_id, day) if f"{crew_id}:{e['key']}" not in done]
    for e in new:
        to = privacy.alerts_to(crew_id)
        now = time.time()
        db.x("INSERT INTO messages(sender,recipient,kind,text,sent_at,deliver_at) VALUES(?,?,?,?,?,?)",
             ("canary", to, "advice", f"Advice review for {CREW_BY_ID[crew_id]['name'].split(' ')[0]}: two rounds of advice in a row did not move the numbers. "
                                      "A different step was offered. Details are in the medical console.", now, now))
        done.append(f"{crew_id}:{e['key']}")
    if new:
        db.set_setting("advice_escalated", done)


def sync_all(day: int) -> None:
    from .catalog import CREW
    for c in CREW:
        sync(c["id"], day)
