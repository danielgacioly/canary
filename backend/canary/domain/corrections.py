"""Corrections to what is on record. Medical team and Canary Control may correct a person's height, the mission name and a
measurement; every correction is one audit entry that says who, the old value, the new value and why. The old value of a
measurement stays in the database (superseded), as the ingest already keeps it. Crew cannot change a record: they ask for a
correction, and the request waits for the medical team or Canary Control to act on it."""
import time
from typing import Any, Optional

from .. import db
from . import audit, data, plan, registry
from .validation import FieldError

REASON_MIN, REASON_MAX = 3, 300
HEIGHT_RANGE = (140, 210)  # the same range the registration form accepts
FIELDS = ("height_cm", "mission_name", "measurement")


def _reason(text: Any) -> str:
    s = str(text or "").strip()
    if not REASON_MIN <= len(s) <= REASON_MAX:
        raise FieldError("reason", f"Say why ({REASON_MIN} to {REASON_MAX} characters)")
    return s


def correct_height(crew_id: str, value: Any, reason: Any, actor: dict) -> dict:
    why = _reason(reason)
    try:
        new = round(float(value), 1)
    except (TypeError, ValueError):
        raise FieldError("value", "Height is a number in cm")
    if not HEIGHT_RANGE[0] <= new <= HEIGHT_RANGE[1]:
        raise FieldError("value", f"Height must be between {HEIGHT_RANGE[0]} and {HEIGHT_RANGE[1]} cm")
    reg = registry.stored() or {}
    person = next((p for p in reg.get("crew", []) if p["seat"] == crew_id), None)
    if person is None:
        raise FieldError("crew_id", "Pick a registered crew member")
    old = person.get("height_cm")
    person["height_cm"] = new
    with db.transaction():
        db.set_setting("registry", reg)
    registry.load()
    audit.record(actor, "crew.height_correct", f"crew:{crew_id}", before={"height_cm": old}, after={"height_cm": new, "reason": why})
    return {"crew_id": crew_id, "height_cm": new}


def correct_mission_name(name: Any, reason: Any, actor: dict) -> dict:
    why = _reason(reason)
    new = str(name or "").strip()[:80]
    if not new:
        raise FieldError("value", "The mission needs a name")
    current = plan.get()
    old = current.get("name")
    reg = registry.stored()
    with db.transaction():
        if reg and reg.get("mission"):
            db.set_setting("registry", {**reg, "mission": {**reg["mission"], "name": new}})
        plan.save({**current, "name": new}, current.get("preset"))
    registry.load()
    audit.record(actor, "mission.name_correct", "mission", before={"name": old}, after={"name": new, "reason": why})
    return {"name": new}


def correct_measurement(obs_id: int, value: Any, reason: Any, actor: dict, now, flight: bool) -> dict:
    why = _reason(reason)
    try:
        new = float(value)
    except (TypeError, ValueError):
        raise FieldError("value", "The value is a number")
    rows = db.q("SELECT * FROM observations WHERE id=?", (obs_id,))
    if not rows:
        raise FieldError("obs_id", "No such measurement")
    o = rows[0]
    if o["superseded_by"] is not None:
        raise FieldError("obs_id", "That measurement was already corrected: correct the newest one")
    row = {"crew_id": o["crew_id"], "indicator": o["indicator"], "value": new, "unit": o["unit"], "origin": o["origin"],
           "method": o["method"], "source": o["source"], "note": o["note"], "supersedes": obs_id, "reason": why}
    if o["measured_at"]:
        row["measured_at"] = o["measured_at"]
    else:
        row["day"] = o["day"]
    data.add_observations([row], None, now, flight)  # the same rules as an ingest correction: the old reading stays, marked
    new_id = db.q("SELECT id FROM observations WHERE supersedes=? ORDER BY id DESC LIMIT 1", (obs_id,))
    nid = new_id[0]["id"] if new_id else None
    audit.record(actor, "observation.correct", f"observation:{obs_id}", before={"value": o["value"], "indicator": o["indicator"],
                 "crew_id": o["crew_id"]}, after={"value": new, "reason": why, "id": nid})
    return {"id": nid, "supersedes": obs_id, "value": new}


def request(crew_id: str, field: str, target: Optional[str], proposed: Any, reason: Any, actor: dict) -> int:
    if field not in FIELDS:
        raise FieldError("field", "Pick what to correct: " + ", ".join(FIELDS))
    why = _reason(reason)
    text = str(proposed if proposed is not None else "")[:200]
    rid = db.x("INSERT INTO correction_requests(crew_id,field,target,proposed,reason,requested_at) VALUES(?,?,?,?,?,?)",
               (crew_id, field, None if target is None else str(target)[:40], text, why, time.time()))
    audit.record(actor, "correction.request", f"crew:{crew_id}", after={"id": rid, "field": field, "target": target, "reason": why})
    return rid


def open_requests() -> list:
    return db.q("SELECT id,crew_id,field,target,proposed,reason,requested_at FROM correction_requests WHERE status='open' ORDER BY id")
