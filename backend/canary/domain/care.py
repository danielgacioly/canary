"""What follows a closed emergency: a care window for the patient.

Closing a Guided Response on day D with a protocol that has `window_days` = N opens a window from D to D+N
inclusive (the hours in the protocol's `after` text start during D and end during D+N, rounded up to whole days; the
mission clock has a resolution of one day). During the window:

- the patient's operational status is at least the protocol's `ops` (see privacy.operational),
- the patient's alert thresholds are tighter by `factor` (health.indicator reports `sensitive_until`),
- the event is on record as an observation of the patient, origin "user" (measured in the app).

A window does not end by itself. After its last day it stays "awaiting review" (and keeps its restrictions) until the
medical team records a review (`record_review`); the review ends it on the day it is recorded, or on its last day if
that came first. The first review stands.

Everything here is a function of the day asked about, so the demo clock can jump anywhere and the same day gives the
same answer. The writes are `open_window`, called when an emergency closes, and `record_review`, called by the medical
team (never from a GET).
"""
import json
import time
from typing import List, Optional

from .. import db
from . import assumptions as A
from . import protocols

LEVEL = {"full": 0, "limited": 1, "rest": 2}
# Prototype assumption: no published rule says how much tighter a recovering patient should be watched.
SENSITIVITY = {"factor": A.value("care.sensitivity_factor"), "source": "prototype assumption", "verified": False}
FACTOR_RANGE = (0.5, 1.0)


def sensitivity() -> dict:
    return {**SENSITIVITY, **db.get_setting("care_sensitivity", {})}


def open_window(emergency: dict, day: int, outcome: str, in_transaction: bool = False) -> Optional[dict]:
    """Record the end of an emergency for its patient. One row per emergency; closing twice changes nothing.
    Called inside db.transaction() by the close route (in_transaction=True: the block commits)."""
    pid, who = emergency.get("protocol"), emergency.get("patient")
    if not pid or not who:
        return None
    c = protocols.care(pid)
    db.x("INSERT OR IGNORE INTO care_events(emergency_id,crew_id,protocol,outcome,from_day,until_day,ops,created_at) VALUES(?,?,?,?,?,?,?,?)",
         (emergency["id"], who, pid, outcome, day, day + c["window_days"], c["ops"], time.time()))
    return None if in_transaction else next(iter(db.q("SELECT * FROM care_events WHERE emergency_id=?", (emergency["id"],))), None)


def review(emergency_id: int) -> Optional[dict]:
    """The medical review that ends the window: {day, by, resolution}. None while the window awaits review."""
    return db.get_setting(f"care_review:{emergency_id}")


def record_review(emergency_id: int, day: int, by: str, resolution: str) -> bool:
    """Medical closes the window. Once only: returns False when a review is already recorded."""
    return db.write("INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)",
                    (f"care_review:{emergency_id}", json.dumps({"day": day, "by": by, "resolution": resolution}))) == 1


def status(emergency_id: int, day: int) -> Optional[dict]:
    rows = db.q("SELECT * FROM care_events WHERE emergency_id=?", (emergency_id,))
    return _item(rows[0], day) if rows else None


def _rows(crew_id: str) -> List[dict]:
    return db.q("SELECT * FROM care_events WHERE crew_id=? ORDER BY id", (crew_id,))


def _last_day(r: dict, day: int) -> int:
    """The last day this window restricts, as known on `day`: its end while awaiting review, else the earlier of its end
    and the day medical reviewed it."""
    rv = review(r["emergency_id"])
    if rv is None:
        return max(r["until_day"], day)
    return min(r["until_day"], rv["day"])


def _in_window(r: dict, day: int) -> bool:
    return r["until_day"] > r["from_day"] and r["from_day"] <= day <= _last_day(r, day)


def active(crew_id: str, day: int) -> Optional[dict]:
    """The window the person is inside on `day`: the most restrictive, then the one that ends last."""
    hits = [r for r in _rows(crew_id) if _in_window(r, day)]
    if not hits:
        return None
    r = max(hits, key=lambda r: (LEVEL[r["ops"]], r["until_day"]))
    return {**_item(r, day), "sensitive_until": max(_last_day(h, day) for h in hits)}


def _item(r: dict, day: int) -> dict:
    awaiting = review(r["emergency_id"]) is None and day > r["until_day"]
    return {"emergency_id": r["emergency_id"], "protocol": r["protocol"], "name": protocols.name(r["protocol"]),
            "outcome": r["outcome"], "day": r["from_day"], "until_day": r["until_day"], "ops": r["ops"],
            "status": "awaiting review" if awaiting else "active" if review(r["emergency_id"]) is None else "reviewed",
            "origin": "user", "source": f"emergency:{r['emergency_id']}"}


def events(crew_id: str, day: int) -> List[dict]:
    """The person's closed emergencies up to `day`, newest first, as observations (origin "user")."""
    return [_item(r, day) for r in reversed(_rows(crew_id)) if r["from_day"] <= day]


def token(crew_id: str) -> tuple:
    """For the alert caches: everything about the person's windows that can change without the day changing."""
    r = db.q("SELECT COUNT(*) n, COALESCE(MAX(id),0) m, COALESCE(SUM(until_day),0) u FROM care_events WHERE crew_id=?", (crew_id,))[0]
    reviewed = sum(1 for w in _rows(crew_id) if review(w["emergency_id"]) is not None)
    return (r["n"], r["m"], r["u"], reviewed, sensitivity()["factor"])
