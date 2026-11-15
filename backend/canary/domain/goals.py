"""Goals, streaks, patches, crew missions and the ranking.

The ranking counts effort (goals done, check-ins sent), never health numbers:
nobody climbs by looking healthy, and reporting a bad day counts the same as a good one.

The history comes from the goal log only (the `goal_log` table): rows loaded from a mission package and goals the
crew ticks in the app. A goal with no row was not done. A row counts on a past day; on the current mission day it
counts only when it was done at or before the current mission time (mission.mission_time(): the simulated time, or the
current UTC time on the real date), so a package can say "Helena did her exercise at 09:40" and the goal turns done when
the mission clock passes that time. A goal ticked in the app is stored with the current mission time, so it counts at once.

A person's history starts on their first day with any row in the goal log (their first logged goal); with no row at all it
starts on the first day of the plan. Completion and streak count only from there.
"""
from typing import Dict, List, Optional

from .. import db
from . import advice, health, mission, plan, risk
from .catalog import (BADGES, CREW, EXERCISE_BY_PLACE, LOCATIONS, PERSONAL_BY_ID, PERSONAL_GOALS, TEAM_GOALS,
                      WINDOW_BY_PLACE)

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


_log_cache: Dict[str, tuple] = {}


def _log(crew_id: str) -> Dict[tuple, tuple]:
    """The person's goal log: (day, goal id) -> (done, done_at_time or None). A package brings thousands of rows, so it is
    read once per change of the database (callers only read it)."""
    stamp = (db.epoch, db.writes)
    hit = _log_cache.get(crew_id)
    if hit is None or hit[0] != stamp:
        with db._lock:
            rows = db.connect().execute("SELECT day,goal_id,done,done_at_time FROM goal_log WHERE crew_id=?", (crew_id,)).fetchall()
        hit = _log_cache[crew_id] = (stamp, {(r[0], r[1]): (r[2], r[3]) for r in rows})
    return hit[1]


def is_done(crew_id: str, goal_id: str, day: int, today: int, log: Optional[Dict[tuple, tuple]] = None,
            now: Optional[str] = None) -> bool:
    """Was the goal done on `day`, looking from mission day `today`? On `today` itself only a row done by the current
    mission time counts (a row without a time counts)."""
    log = _log(crew_id) if log is None else log
    row = log.get((day, goal_id))
    if row is None or not row[0]:
        return False
    if day == today and row[1] is not None and row[1] > (now or mission.mission_time()):
        return False
    return True


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
    db.x("INSERT INTO goal_log(crew_id,day,goal_id,done,updated_at,done_at_time) VALUES(?,?,?,?,?,?) "
         "ON CONFLICT(crew_id,day,goal_id) DO UPDATE SET done=excluded.done, updated_at=excluded.updated_at, "
         "done_at_time=excluded.done_at_time",
         (crew_id, day, goal_id, int(done), time.time(), mission.mission_time()))


# ---------------------------------------------------------------- history-based numbers
def _start(crew_id: str, today: int) -> int:
    """First day of the person's history: their first day with a row in the goal log, else the first day of the plan; never
    after `today` (a clock set before the history starts shows `today` alone)."""
    first = min((d for d, _ in _log(crew_id)), default=plan.get()["legs"][0]["start"])
    return min(first, today)


def _history(crew_id: str, today: int) -> dict:
    """Per-day completions from the first history day to today, routine goals only. `today` is always a key."""
    log = _log(crew_id)
    now = mission.mission_time()
    extra_by_day: Dict[int, int] = {}  # goals added by an alert, the medical team or a suggestion, done
    for (ld, gid), v in log.items():
        if v[0] and gid.startswith(("al_", "med_", "sg_")):
            extra_by_day[ld] = extra_by_day.get(ld, 0) + 1
    days = {}
    for d in range(_start(crew_id, today), today + 1):
        ids = daily_goal_ids(plan.location_at(d))
        done = [gid for gid in ids if is_done(crew_id, gid, d, today, log, now)]
        extra = extra_by_day.get(d, 0)
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


def crew_quorum(n: Optional[int] = None) -> int:
    """How many people make a crew day: three quarters of the crew, rounded up (3 of 4, and everybody in a crew of one to three)."""
    n = len(CREW) if n is None else n
    return max(1, -(-3 * n // 4))


def team_target(t: dict, n: Optional[int] = None) -> int:
    """The week's target of a crew goal for a crew of n (default: the registered crew). A count goal scales with the crew."""
    n = max(1, len(CREW) if n is None else n)
    return t["per_person"] * n if "per_person" in t else t["target"]


def _team_title(t: dict, target: int) -> str:
    return t["title"].format(target=target, hours=f"{target / 60:g}") if "{" in t["title"] else t["title"]


def team_progress(today: int, histories: Optional[Dict[str, dict]] = None, window_end: Optional[int] = None) -> List[dict]:
    histories = histories or {c["id"]: _history(c["id"], today) for c in CREW}
    end = today if window_end is None else window_end
    days = list(range(end - 6, end + 1))  # a day before someone's history counts as nothing done
    done_on = lambda cid, d: histories[cid][d]["done"] if d in histories[cid] else []  # noqa: E731
    out = []
    quorum = crew_quorum()
    for t in TEAM_GOALS:
        kind, _, gid = t["metric"].partition(":")
        target = team_target(t)
        if kind == "all_done":  # a crew day: at least 3 of the 4 did it (three quarters of the crew)
            val = sum(1 for d in days if sum(gid in done_on(c["id"], d) for c in CREW) >= quorum)
        elif kind == "count":
            val = sum(1 for c in CREW for d in days if gid in done_on(c["id"], d))
        else:  # count20
            val = 20 * sum(1 for c in CREW for d in days if gid in done_on(c["id"], d))
        val = round(val)
        # `personal_ids`: which routine personal goal counts toward the mission (catalog data, the same for everyone;
        # the person's own goals come from their own goals endpoint). No per-person numbers leave here.
        out.append({**{k: v for k, v in t.items() if k != "per_person"}, "title": _team_title(t, target), "target": target,
                    "value": val, "pct": min(100, round(100 * val / target)), "done": val >= target, "personal_ids": [gid]})
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
            "daily_done": [[d, days[d]["count"], days[d]["total"]] for d in range(max(min(days), today - 13), today + 1)]}


def crew_streak(today: int, histories: Dict[str, dict]) -> int:
    """Shared streak: consecutive days on which at least three quarters of the crew (3 of 4) kept their routine."""
    if not CREW:
        return 0
    quorum = crew_quorum()

    def ok(d: int) -> bool:
        return sum(1 for c in CREW if d in histories[c["id"]] and histories[c["id"]][d]["total"]
                   and len(histories[c["id"]][d]["done"]) / histories[c["id"]][d]["total"] >= STREAK_RATE) >= quorum
    n = 1 if ok(today) else 0
    d = today - 1
    while ok(d):
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


PUBLIC_ROW = ("crew_id", "goals_week", "completion_7d", "streak", "badges_earned", "patches")


def public_row(crew_id: str, today: int, histories: Dict[str, dict]) -> dict:
    """What the crew may see of one person in the ranking: routine goals only, the numbers the page shows.

    Goals added by an alert, the medical team or a health-based suggestion are left out of the count, so a jump in
    someone's total never tells the crew they have an alert or a prescription. The split by area, the day-by-day
    counts and the patch progress stay in the person's own space. The earned patches are public: every patch is
    earned by effort (a goal done N times, a streak, taking part in a guided response), never by a health number.
    """
    days = histories[crew_id]
    p = profile(crew_id, today, histories)
    p["goals_week"] = sum(len(days[d]["done"]) for d in range(today - 6, today + 1) if d in days)
    p["patches"] = [{"id": b["id"], "name": b["name"]} for b in p["badges"] if b["earned"]]
    return {k: p[k] for k in PUBLIC_ROW}


def leaderboard(today: int, public: bool = True) -> dict:
    """The ranking. `public` (the crew's view) keeps only PUBLIC_ROW; the medical console asks for full profiles."""
    histories = {c["id"]: _history(c["id"], today) for c in CREW}
    rows = [public_row(c["id"], today, histories) if public else profile(c["id"], today, histories) for c in CREW]
    rows.sort(key=lambda r: (-r["goals_week"], -r["completion_7d"], -r["streak"]))
    for i, r in enumerate(rows):
        r["rank"] = i + 1
    team = team_progress(today, histories)
    return {"rows": rows, "team": team, "crew_goals_week": sum(r["goals_week"] for r in rows),
            "team_done": sum(1 for t in team if t["done"]), "team_total": len(team)}
