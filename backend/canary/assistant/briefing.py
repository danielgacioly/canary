"""Entry 2: a one-page weekly briefing for the flight surgeon.

Code computes the facts; the model (when connected) only writes the prose, and
guard.unknown_numbers rejects any text with numbers that are not in the facts.
Sections are in priority order so the first lines are enough on a slow link.
The astronaut sees the briefing and approves it before it is queued for Earth.
"""
import json
import time
from typing import List

from .. import db
from ..config import settings
from ..domain import goals, health, mission
from ..domain.catalog import CREW_BY_ID, LOCATIONS
from . import guard
from .providers import ProviderRequest, get_provider


def facts(crew_id: str) -> dict:
    ms = mission.state()
    snap = health.snapshot(crew_id, ms)
    prof = goals.profile(crew_id, ms["day"])
    movers = sorted((i for i in snap["indicators"].values() if i["bad"] is not None), key=lambda i: -i["bad"])[:4]  # no data, no mover
    tried = []
    for r in db.q("SELECT goal_id,day FROM goal_log WHERE crew_id=? AND done=1 AND day>? ORDER BY day", (crew_id, ms["day"] - 7)):
        if r["goal_id"].startswith(("al_", "med_")):
            tried.append(f"day {r['day']}: goal {r['goal_id']}")
    for r in db.q("SELECT kind,day FROM checkins WHERE crew_id=? AND day>? ORDER BY day", (crew_id, ms["day"] - 7)):
        tried.append(f"day {r['day']}: {r['kind']} check-in")
    for r in db.q("SELECT protocol,day,outcome FROM emergencies WHERE patient=? AND day>?", (crew_id, ms["day"] - 7)):
        tried.append(f"day {r['day']}: guided response ({r['protocol']}), {r['outcome'] or 'open'}")
    return {
        "crew": CREW_BY_ID[crew_id]["name"], "day": ms["day"], "day_label": ms["day_label"], "place": LOCATIONS[ms["location"]]["name"],
        "physical": snap["areas"]["physical"], "mental": snap["areas"]["mental"],
        "alerts": [{"title": a["title"], "level": a["level"]} for a in snap["alerts"]],
        "movers": [{"name": i["name"], "value": round(i["value"], i["dp"]), "baseline": i["baseline"], "unit": i["unit"], "z": i["z"]} for i in movers],
        "completion_7d": prof["completion_7d"], "streak": prof["streak"],
        "tried": tried or ["No alert or medical goals completed this week"],
        "dose_msv": snap["dose"]["mission_msv"],
    }


def template(f: dict) -> str:
    lines: List[str] = [f"BRIEFING {f['crew'].upper()} · {f['day_label']} · {f['place']}"]
    lines.append("1 WHAT WORRIES")
    lines += [f"- [{['ok', 'WATCH', 'ACT'][a['level']]}] {a['title']}" for a in f["alerts"][:3]] or ["- Nothing outside personal normal."]
    lines.append("2 WHAT CHANGED (vs own baseline)")
    lines += [f"- {m['name']}: {m['value']} {m['unit']} (normal {m['baseline']}, z {m['z']})" for m in f["movers"]]
    sc = lambda area: "no data yet" if f[area]["score"] is None else f[area]["score"]  # noqa: E731
    lines.append(f"- Readiness: physical {sc('physical')}, mental {sc('mental')}. Mission dose {f['dose_msv']} mSv (simulated).")
    lines.append("3 WHAT WAS TRIED")
    lines += [f"- {t}" for t in f["tried"][:6]]
    lines.append(f"- Goals done last 7 days: {f['completion_7d']}%, streak {f['streak']} days.")
    return "\n".join(lines)


def build(crew_id: str) -> dict:
    f = facts(crew_id)
    provider = get_provider()
    out = provider.complete(ProviderRequest(task="briefing", system="Write a flight-surgeon briefing from these facts only.",
                                            question="weekly briefing", context=[{"facts": f}]))
    text, mode = template(f), "template"
    if out.ok and out.answer and not guard.unknown_numbers(out.answer, json.dumps(f)):
        text, mode = out.answer, "ai"
    bid = db.x("INSERT INTO briefings(crew_id,day,status,facts,text,mode,created_at) VALUES(?,?,?,?,?,?,?)",
               (crew_id, f["day"], "draft", json.dumps(f), text, mode, time.time()))
    return get(bid)


def approve(bid: int) -> dict:
    b = get(bid)
    delay = LOCATIONS[mission.state()["location"]]["delay_s"] / settings.delay_speedup
    now = time.time()
    db.x("UPDATE briefings SET status='queued', sent_at=?, deliver_at=? WHERE id=?", (now, now + delay, bid))
    db.x("INSERT INTO messages(sender,recipient,kind,text,sent_at,deliver_at) VALUES(?,?,?,?,?,?)",
         (b["crew_id"], "earth", "briefing", b["text"], now, now + delay))
    return get(bid)


def get(bid: int) -> dict:
    r = db.q("SELECT * FROM briefings WHERE id=?", (bid,))[0]
    return {**r, "facts": json.loads(r["facts"]), "bytes": len(r["text"].encode())}


def list_for(crew_id: str) -> List[dict]:
    return [get(r["id"]) for r in db.q("SELECT id FROM briefings WHERE crew_id=? ORDER BY id DESC LIMIT 10", (crew_id,))]
