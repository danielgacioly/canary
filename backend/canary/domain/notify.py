"""A critical alert reaches the medical officer, once per episode.

For every crew member with a personal level-2 alert, `sync` writes one message for the crew medical officer (the
substitute when the patient is the medical officer) and queues one delayed note for Earth. An episode is
(crew_id, alert_id, since_day), the same key `health.alerts` uses, and the `notices` table has it as primary key:
calling `sync` again, from any route, never repeats a notice. Only routes that write call it (never a GET).

A stretch of the same alert longer than the alert lookback (health.ALERT_LOOKBACK) has a `since_day` that moves
every day; it counts as the episode already noticed if the person was told inside the stretch.
"""
import time
from typing import List, Optional

from .. import db
from . import health, privacy
from .catalog import CREW, CREW_BY_ID, LOCATIONS


def _first(crew_id: str) -> str:
    return CREW_BY_ID[crew_id]["name"].split(" ")[0]


def _new(crew_id: str, ms: dict) -> List[dict]:
    out = []
    for a in health.snapshot(crew_id, ms)["alerts"]:
        if a["level"] < 2 or a.get("env") or a.get("data"):
            continue
        if db.q("SELECT 1 FROM notices WHERE crew_id=? AND alert_id=? AND since_day=?", (crew_id, a["id"], a["since_day"])):
            continue
        if a["days_active"] >= health.ALERT_LOOKBACK and db.q(
                "SELECT 1 FROM notices WHERE crew_id=? AND alert_id=? AND day>=?", (crew_id, a["id"], a["since_day"])):
            continue
        out.append(a)
    return out


def sync(ms: dict, crew_ids: Optional[List[str]] = None) -> int:
    """Notify for every new critical episode of the given people (everyone by default). Returns how many episodes."""
    from ..assistant import briefing  # late import: the text for Earth is the weekly briefing's
    from ..config import settings
    total, day = 0, ms["day"]
    for c in CREW:
        if crew_ids is not None and c["id"] not in crew_ids:
            continue
        new = _new(c["id"], ms)
        if not new:
            continue
        to = privacy.SUBSTITUTE if c["id"] == privacy.MEDICAL_OFFICER else privacy.MEDICAL_OFFICER
        now = time.time()
        titles = " ".join(a["title"] for a in new)
        for a in new:
            db.x("INSERT OR IGNORE INTO notices(crew_id,alert_id,since_day,day,level,title,to_id,created_at) VALUES(?,?,?,?,?,?,?,?)",
                 (c["id"], a["id"], a["since_day"], day, a["level"], a["title"], to, now))
        db.x("INSERT INTO messages(sender,recipient,kind,text,sent_at,deliver_at) VALUES(?,?,?,?,?,?)",
             ("canary", to, "alert", f"Critical alert for {_first(c['id'])} on day {day}: {titles} Details are in the medical console.", now, now))
        delay = LOCATIONS[ms["location"]]["delay_s"] / settings.delay_speedup
        db.x("INSERT INTO messages(sender,recipient,kind,text,sent_at,deliver_at) VALUES(?,?,?,?,?,?)",
             ("canary", "earth", "alert_earth", briefing.template(briefing.facts(c["id"])), now, now + delay))
        total += len(new)
    return total


def list_for(day: int) -> List[dict]:
    """Notices sent up to `day`, newest first, for the medical console."""
    rows = db.q("SELECT * FROM notices WHERE since_day<=? ORDER BY created_at DESC, rowid DESC LIMIT 30", (day,))
    return [{"crew_id": r["crew_id"], "name": CREW_BY_ID[r["crew_id"]]["name"], "alert_id": r["alert_id"], "title": r["title"],
             "since_day": r["since_day"], "day": r["day"], "level": r["level"], "to": r["to_id"],
             "to_name": CREW_BY_ID[r["to_id"]]["name"]} for r in rows if r["crew_id"] in CREW_BY_ID and r["to_id"] in CREW_BY_ID]
