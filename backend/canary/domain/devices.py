"""Devices that send readings (a wearable, a sensor, a lab analyser, a dosimeter) and the key each one signs with.

Canary Control registers a device and sees its key once, in the answer to the registration; only the SHA-256 of the key is
stored, so nobody (nor a database dump) can read a key back. A revoked device stops working at once. A device may be bound to one
crew member: it can then send only that person's readings. The old shared key (CANARY_INGEST_KEY) still works in demo mode, as the
device `legacy`; in flight mode only device keys count.
"""
import hashlib
import hmac
import secrets
from datetime import datetime, timezone
from typing import List, Optional

from .. import db
from ..config import settings
from . import catalog

KINDS = ("wearable", "sensor", "lab", "dosimeter", "environment", "manual", "other")
LEGACY_ID = "legacy"


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _hash(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def create(name: str, kind: str, crew_id: Optional[str]) -> dict:
    """Register a device. Returns its fields and the key, which is never available again."""
    key = "ck_" + secrets.token_urlsafe(24)
    did = "dev-" + secrets.token_hex(3)
    while db.q("SELECT 1 FROM devices WHERE id=?", (did,)):
        did = "dev-" + secrets.token_hex(3)
    db.x("INSERT INTO devices(id,name,kind,crew_id,key_hash,created_at) VALUES(?,?,?,?,?,?)", (did, name, kind, crew_id, _hash(key), _now()))
    return {**public(did), "key": key}


def public(device_id: str) -> dict:
    r = db.q("SELECT id,name,kind,crew_id,created_at,revoked_at FROM devices WHERE id=?", (device_id,))
    return r[0] if r else {}


def listing() -> List[dict]:
    """Every device without its key; `last_received_at` is the newest reading it sent."""
    out = []
    for r in db.q("SELECT id,name,kind,crew_id,created_at,revoked_at FROM devices ORDER BY created_at, id"):
        last = db.q("SELECT MAX(received_at) m FROM observations WHERE device_id=?", (r["id"],))[0]["m"]
        out.append({**r, "active": r["revoked_at"] is None, "last_received_at": last})
    return out


def revoke(device_id: str) -> Optional[dict]:
    if not db.q("SELECT 1 FROM devices WHERE id=?", (device_id,)):
        return None
    db.x("UPDATE devices SET revoked_at=? WHERE id=? AND revoked_at IS NULL", (_now(), device_id))
    return public(device_id)


def ever_registered() -> bool:
    return bool(db.q("SELECT 1 FROM devices LIMIT 1"))


def legacy_on() -> bool:
    return bool(settings.ingest_key) and settings.mode == "demo"


def authenticate(key: Optional[str]) -> Optional[dict]:
    """{id, crew_id} of the device this key belongs to (an active device, or the legacy key in demo mode), else None."""
    if not key:
        return None
    rows = db.q("SELECT id,crew_id,revoked_at FROM devices WHERE key_hash=?", (_hash(key),))
    if rows:
        return {"id": rows[0]["id"], "crew_id": rows[0]["crew_id"]} if rows[0]["revoked_at"] is None else None
    if legacy_on() and hmac.compare_digest(key.encode(), settings.ingest_key.encode()):
        return {"id": LEGACY_ID, "crew_id": None}
    return None
