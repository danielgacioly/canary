"""Goals, streaks, patches, crew missions and the ranking.

The ranking counts effort (goals done, check-ins sent), never health numbers:
nobody climbs by looking healthy, and reporting a bad day counts the same as a good one.

Past days use a simulated completion history so the demo has a lived-in crew;
anything the crew ticks in the app is stored and wins over the simulation.
"""
from typing import Dict, List, Optional

from .. import db
from . import advice, health, plan, risk, telemetry
from .catalog import (BADGES, CREW, EXERCISE_BY_PLACE, LOCATIONS, PERSONAL_BY_ID, PERSONAL_GOALS, TEAM_GOALS,
                      WINDOW_BY_PLACE)

HISTORY_START = -30  # first day with goals (pre-flight training)
STREAK_RATE = 0.7    # a day counts for the streak when 70% of goals are done


def _title(g: dict, location: str) -> str:
    if g["id"] == "exercise":
        return EXERCISE_BY_PLACE[location][0]
    if g["id"] == "window":
        return WINDOW_BY_PLACE[location]
    if g["id"] == "home":
        delay = LOCATIONS[location]["delay_s"]
        return f"Record a message home (arrives in {round(delay / 60)} min)" if delay > 60 else "Talk to someone at home"
    return g["title"]


def daily_goal_ids(location: str) -> List[str]:
    return [g["id"] for g in PERSONAL_GOALS if not (g.get("space_only") and location == "earth")]


def _log(crew_id: str) -> Dict[tuple, int]:
    return {(r["day"], r["goal_id"]): r["done"] for r in db.q("SELECT day,goal_id,done FROM goal_log WHERE crew_id=?", (crew_id,))}


def _sim_done(crew_id: str, goal_id: str, day: int, today: int) -> bool:
    p = {"h": 0.86, "k": 0.84, "a": 0.9, "t": 0.74}[crew_id]
    g = PERSONAL_BY_ID.get(goal_id)
    if crew_id == "h" and 132 <= day <= 153 and g and g["area"] == "mental":
        p = 0.35  # the slide the alert catches
    if crew_id == "t" and 1 <= day <= 4:
        p = 0.3
    if day == today:
        p *= 0.45  # the day is not over
    return telemetry.h01(f"goal:{crew_id}:{goal_id}:{day}") < p


def is_done(crew_id: str, goal_id: str, day: int, today: int, log: Optional[Dict[tuple, int]] = None) -> bool:
    log = _log(crew_id) if log is None else log
    if (day, goal_id) in log:
        return bool(log[(day, goal_id)])
    if goal_id.startswith(("al_", "med_", "sg_")):
        return False
    return _sim_done(crew_id, goal_id, day, today)


def medical_goals(crew_id: str, day: int) -> List[dict]:
    rows = db.q("SELECT * FROM medical_goals WHERE (who=? OR who='all') AND from_day<=? AND to_day>=?", (crew_id, day, day))
    return [{"id": f"med_{r['id']}", "area": r["area"], "title": r["title"], "why": r["why"],
             "by": "medical"} for r in rows]


# The medical team sets how much the day's exercise may be lightened while the fatigue risk is up. Never above max_pct.
# Prototype assumption: the percentages are placeholders for the flight surgeon to set.
EXERCISE_ADJUST = {"max_pct": 30, "by_level": {"1": 15, "2": 30}, "source": "prototype assumption", "verified": False}


def exercise_adjust() -> dict:
    return {**EXERCISE_ADJUST, **db.get_setting("exercise_adjust", {})}


def _exercise_goal(g: dict, loc: str, fatigue_level: int) -> dict:
    """The routine exercise goal; lighter, and says why, when the fatigue risk is at watch or act (within the medical limit)."""
    base = {"title": _title(g, loc), "why": g["why"]}
    cfg = exercise_adjust()
    pct = min(int(cfg["by_level"].get(str(fatigue_level), 0)), int(cfg["max_pct"]))
    if not fatigue_level or pct <= 0:
        return base
    target = EXERCISE_BY_PLACE[loc][1]
    minutes = int(round(target * (100 - pct) / 100))
    return {"title": f"{base['title']} (lighter today: about {minutes} min instead of {target})",
            "why": f"Your fatigue risk is up, so today's load is {pct}% lower, within the {cfg['max_pct']}% limit your medical team set. Rest is part of training.",
            "adjusted": {"pct": pct, "minutes": minutes, "target": target, "reason": "fatigue", "max_pct": int(cfg["max_pct"])}}


def suggested(crew_id: str, day: int) -> List[dict]:
    """Suggestions the person turned into goals (see assistant/suggestions.py). They last a week."""
    return [g for g in db.get_setting("suggested_goals", {}).get(crew_id, []) if g["from_day"] <= day <= g["to_day"]]


def personal_today(crew_id: str, ms: dict, snap: Optional[dict] = None) -> List[dict]:
    day, loc = ms["day"], ms["location"]
    log = _log(crew_id)
    out = []
    snap = snap or health.snapshot(crew_id, ms)
    by_adv = advice.by_goal(crew_id, day)
    fat = risk.get(snap.get("risks", []), "fatigue")
    for gid in daily_goal_ids(loc):
        g = PERSONAL_BY_ID[gid]
        text = _exercise_goal(g, loc, fat["level"] if fat else 0) if gid == "exercise" else {"title": _title(g, loc), "why": g["why"]}
        out.append({"id": gid, "area": g["area"], **text,
                    "sys": g.get("sys"), "action": g.get("action"), "by": "routine",
                    "done": is_done(crew_id, gid, day, day, log)})
    for a in snap["alerts"]:
        for g in a.get("goals", []):
            out.append({**g, "why": f"Added by the alert: {a['title']}", "by": "alert", "sys": a.get("sys"),
                        "done": is_done(crew_id, g["id"], day, day, log)})
    for g in medical_goals(crew_id, day):
        out.append({**g, "done": is_done(crew_id, g["id"], day, day, log)})
    for g in suggested(crew_id, day):
        out.append({"id": g["id"], "area": g["area"], "title": g["title"], "why": "You added this from Suggestions.",
                    "by": "suggestion", "done": is_done(crew_id, g["id"], day, day, log),
                    **({"verify": g["verify"]} if g.get("verify") else {})})
    for g in out:  # the experiment behind a goal: pending until its check day, then improved / same / worse
        a = by_adv.get(g["id"])
        if a:
            g["advice"] = a
    return out


def set_done(crew_id: str, goal_id: str, day: int, done: bool) -> None:
    import time
    db.x("INSERT INTO goal_log(crew_id,day,goal_id,done,updated_at) VALUES(?,?,?,?,?) "
         "ON CONFLICT(crew_id,day,goal_id) DO UPDATE SET done=excluded.done, updated_at=excluded.updated_at",
         (crew_id, day, goal_id, int(done), time.time()))


# ---------------------------------------------------------------- history-based numbers
def _start(today: int) -> int:
    """First day with history: HISTORY_START, or earlier when the clock is set before it."""
    return min(HISTORY_START, today)


def _history(crew_id: str, today: int) -> dict:
    """Per-day completions from the first history day to today, routine goals only. `today` is always a key."""
    log = _log(crew_id)
    days = {}
    for d in range(_start(today), today + 1):
        ids = daily_goal_ids(plan.location_at(d))
        done = [gid for gid in ids if is_done(crew_id, gid, d, today, log)]
        extra = sum(1 for (ld, gid), v in log.items() if ld == d and v and gid.startswith(("al_", "med_", "sg_")))
        days[d] = {"done": done, "total": len(ids), "count": len(done) + extra}
    return days


def _streak(days: dict, today: int) -> int:
    n, d = 0, today - 1
    if days[today]["total"] and len(days[today]["done"]) / days[today]["total"] >= STREAK_RATE:
        n += 1
    while d in days and len(days[d]["done"]) / days[d]["total"] >= STREAK_RATE:
        n += 1
        d -= 1
    return n


def team_progress(today: int, histories: Optional[Dict[str, dict]] = None, window_end: Optional[int] = None) -> List[dict]:
    histories = histories or {c["id"]: _history(c["id"], today) for c in CREW}
    end = today if window_end is None else window_end
    days = [d for d in range(end - 6, end + 1) if d >= _start(today)]
    out = []
    for t in TEAM_GOALS:
        kind, _, gid = t["metric"].partition(":")
        if kind == "sum_exer":
            val = sum(telemetry.SOURCE.value(c["id"], "exer", d) for c in CREW for d in days)
        elif kind == "all_done":  # a crew day: at least 3 of the 4 did it
            val = sum(1 for d in days if sum(gid in histories[c["id"]][d]["done"] for c in CREW) >= 3)
        elif kind == "count":
            val = sum(1 for c in CREW for d in days if gid in histories[c["id"]][d]["done"])
        else:  # count20
            val = 20 * sum(1 for c in CREW for d in days if gid in histories[c["id"]][d]["done"])
        val = round(val)
        contrib = {}
        if kind != "sum_exer":
            for c in CREW:
                contrib[c["id"]] = sum(1 for d in days if (gid or "") in histories[c["id"]][d]["done"])
        else:
            for c in CREW:
                contrib[c["id"]] = round(sum(telemetry.SOURCE.value(c["id"], "exer", d) for d in days))
        out.append({**t, "value": val, "pct": min(100, round(100 * val / t["target"])), "done": val >= t["target"],
                    "contrib": contrib})
    return out


def badges_for(crew_id: str, days: dict, streak: int) -> List[dict]:
    counts: Dict[str, int] = {}
    for d in days.values():
        for g in d["done"]:
            counts[g] = counts.get(g, 0) + 1
    responded = db.q("SELECT COUNT(*) n FROM emergencies WHERE responder=?", (crew_id,))[0]["n"]
    out = []
    for b in BADGES:
        if "goal" in b:
            have, need = counts.get(b["goal"], 0), b["count"]
        elif "streak" in b:
            have, need = streak, b["streak"]
        else:
            have, need = responded, 1
        out.append({**b, "progress": min(have, need), "need": need, "earned": have >= need})
    return out


def profile(crew_id: str, today: int, histories: Optional[Dict[str, dict]] = None) -> dict:
    histories = histories or {c["id"]: _history(c["id"], today) for c in CREW}
    days = histories[crew_id]
    week = sum(days[d]["count"] for d in range(today - 6, today + 1) if d in days)
    streak = _streak(days, today)
    b = badges_for(crew_id, days, streak)
    last7 = [d for d in range(today - 6, today + 1) if d in days]
    rate = round(100 * sum(len(days[d]["done"]) for d in last7) / max(1, sum(days[d]["total"] for d in last7)))
    by_area = {a: sum(1 for d in last7 for g in days[d]["done"] if PERSONAL_BY_ID[g]["area"] == a)
               for a in ("physical", "mental")}
    return {"crew_id": crew_id, "goals_week": week, "goals_week_by_area": by_area, "streak": streak, "completion_7d": rate,
            "badges": b, "badges_earned": sum(1 for x in b if x["earned"]),
            "daily_done": [[d, days[d]["count"], days[d]["total"]] for d in range(max(_start(today), today - 13), today + 1)]}


def crew_streak(today: int, histories: Dict[str, dict]) -> int:
    """Shared streak: consecutive days on which at least 3 of the 4 kept their routine."""
    def ok(d: int) -> bool:
        return sum(1 for c in CREW if histories[c["id"]][d]["total"]
                   and len(histories[c["id"]][d]["done"]) / histories[c["id"]][d]["total"] >= STREAK_RATE) >= 3
    n = 1 if ok(today) else 0
    d = today - 1
    while d >= _start(today) and ok(d):
        n += 1
        d -= 1
    return n


def crew_board(today: int) -> dict:
    """Participation only, for the public crew view: no scores, no vitals."""
    histories = {c["id"]: _history(c["id"], today) for c in CREW}
    people = {c["id"]: {"done": len(histories[c["id"]][today]["done"]), "total": histories[c["id"]][today]["total"],
                        "streak": _streak(histories[c["id"]], today)} for c in CREW}
    team = team_progress(today, histories)
    return {"people": people, "team": team, "crew_streak": crew_streak(today, histories),
            "team_done": sum(1 for t in team if t["done"]), "team_total": len(team)}


def leaderboard(today: int) -> dict:
    histories = {c["id"]: _history(c["id"], today) for c in CREW}
    rows = [profile(c["id"], today, histories) for c in CREW]
    rows.sort(key=lambda r: (-r["goals_week"], -r["completion_7d"], -r["streak"]))
    for i, r in enumerate(rows):
        r["rank"] = i + 1
    team = team_progress(today, histories)
    return {"rows": rows, "team": team, "crew_goals_week": sum(r["goals_week"] for r in rows),
            "team_done": sum(1 for t in team if t["done"]), "team_total": len(team)}
