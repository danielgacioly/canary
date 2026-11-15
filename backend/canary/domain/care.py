"""What follows a closed emergency: a care window for the patient.

Closing a Guided Response on day D with a protocol that has `window_days` = N opens a window from D to D+N
inclusive (the hours in the protocol's `after` text start during D and end during D+N, rounded up to whole days; the
mission clock has a resolution of one day). During the window:

- the patient's operational status is at least the protocol's `ops` (see privacy.operational),
- the patient's alert thresholds are tighter by `factor` (health.indicator reports `sensitive_until`),
- the event is on record as an observation of the patient, origin "user" (measured in the app).

Everything here is a function of the day asked about, so the demo clock can jump anywhere and the same day gives the
same answer. The only write is `open_window`, called when an emergency closes (never from a GET).
"""
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


def open_window(emergency: dict, day: int, outcome: str) -> Optional[dict]:
    """Record the end of an emergency for its patient. One row per emergency; closing twice changes nothing."""
    pid, who = emergency.get("protocol"), emergency.get("patient")
    if not pid or not who:
        return None
    c = protocols.care(pid)
    db.x("INSERT OR IGNORE INTO care_events(emergency_id,crew_id,protocol,outcome,from_day,until_day,ops,created_at) VALUES(?,?,?,?,?,?,?,?)",
         (emergency["id"], who, pid, outcome, day, day + c["window_days"], c["ops"], time.time()))
    return next(iter(db.q("SELECT * FROM care_events WHERE emergency_id=?", (emergency["id"],))), None)


def _rows(crew_id: str) -> List[dict]:
    return db.q("SELECT * FROM care_events WHERE crew_id=? ORDER BY id", (crew_id,))


def active(crew_id: str, day: int) -> Optional[dict]:
    """The window the person is inside on `day`: the most restrictive, then the one that ends last."""
    hits = [r for r in _rows(crew_id) if r["until_day"] > r["from_day"] and r["from_day"] <= day <= r["until_day"]]
    if not hits:
        return None
    r = max(hits, key=lambda r: (LEVEL[r["ops"]], r["until_day"]))
    return {**_item(r), "sensitive_until": max(h["until_day"] for h in hits)}


def _item(r: dict) -> dict:
    return {"emergency_id": r["emergency_id"], "protocol": r["protocol"], "name": protocols.name(r["protocol"]),
            "outcome": r["outcome"], "day": r["from_day"], "until_day": r["until_day"], "ops": r["ops"],
            "origin": "user", "source": f"emergency:{r['emergency_id']}"}


def events(crew_id: str, day: int) -> List[dict]:
    """The person's closed emergencies up to `day`, newest first, as observations (origin "user")."""
    return [_item(r) for r in reversed(_rows(crew_id)) if r["from_day"] <= day]


def token(crew_id: str) -> tuple:
    """For the alert caches: everything about the person's windows that can change without the day changing."""
    r = db.q("SELECT COUNT(*) n, COALESCE(MAX(id),0) m, COALESCE(SUM(until_day),0) u FROM care_events WHERE crew_id=?", (crew_id,))[0]
    return (r["n"], r["m"], r["u"], sensitivity()["factor"])
