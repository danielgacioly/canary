"""The audit trail: who did what, when, to what, with the value before and after. Insert-only and hash-chained.

Every row carries `hash = sha256(prev_hash + canonical JSON of the row's own fields)`, where `prev_hash` is the hash of the
row before it (the first row chains to 64 zeros). Editing or deleting any row breaks the chain from that row on, and
`verify()` finds the first row that no longer fits. This module has no update and no delete: the only way to empty the
log is the demo reset (db.reset), which wipes the whole database and starts the new log with its own entry.

What is never written here: PINs, tokens, keys. Health values go in `before`/`after` only where the change IS a medical
setting; Canary Control sees them redacted (`redact`).
"""
import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Union

from .. import db

GENESIS = "0" * 64
SYSTEM = {"id": "system", "role": "system"}
REDACT_KEYS = ("value", "values", "readings", "vitals", "log")  # keys whose content is health data
Actor = Union[dict, str, None]


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _canon(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def _digest(prev: str, row: dict) -> str:
    fields = {k: row[k] for k in ("id", "at", "actor_id", "actor_role", "action", "target", "before", "after")}
    return hashlib.sha256((prev + _canon(fields)).encode()).hexdigest()


def _who(actor: Actor) -> dict:
    if isinstance(actor, dict):
        return {"id": str(actor.get("id") or "unknown"), "role": str(actor.get("role") or "unknown")}
    if isinstance(actor, str):
        return {"id": actor, "role": "system" if actor == "system" else "unknown"}
    return SYSTEM


def record(actor: Actor, action: str, target: str = "", before: Any = None, after: Any = None) -> int:
    """Append one entry and return its id. `actor` is the dict of the signed-in person (`id`, `role`), or "system"."""
    who = _who(actor)
    with db._lock:
        c = db.connect()
        last = c.execute("SELECT id, hash FROM audit_log ORDER BY id DESC LIMIT 1").fetchone()
        prev, nid = (last["hash"], last["id"] + 1) if last else (GENESIS, 1)
        row = {"id": nid, "at": _now(), "actor_id": who["id"], "actor_role": who["role"], "action": action, "target": str(target),
               "before": None if before is None else _canon(before), "after": None if after is None else _canon(after)}
        c.execute("INSERT INTO audit_log(id,at,actor_id,actor_role,action,target,before,after,prev_hash,hash) VALUES(?,?,?,?,?,?,?,?,?,?)",
                  (nid, row["at"], row["actor_id"], row["actor_role"], row["action"], row["target"], row["before"], row["after"],
                   prev, _digest(prev, row)))
        c.commit()
        db._forget()
        return nid


def verify() -> Optional[int]:
    """Walk the chain from the first entry. Returns the id of the first entry that does not fit (its hash is wrong or it does
    not chain to the entry before it), or None when the whole log is intact."""
    with db._lock:
        rows = [dict(r) for r in db.connect().execute("SELECT * FROM audit_log ORDER BY id").fetchall()]
    prev = GENESIS
    for r in rows:
        if r["prev_hash"] != prev or _digest(prev, r) != r["hash"]:
            return r["id"]
        prev = r["hash"]
    return None


def redact(obj: Any) -> Any:
    """The same structure with the content of every health key replaced, for Canary Control."""
    if isinstance(obj, dict):
        return {k: ("[redacted]" if k in REDACT_KEYS else redact(v)) for k, v in obj.items()}
    if isinstance(obj, list):
        return [redact(x) for x in obj]
    return obj


def _load(text: Optional[str]) -> Any:
    return None if text is None else json.loads(text)


def entries(limit: int = 50, before_id: Optional[int] = None, redacted: bool = False) -> Dict[str, Any]:
    """A page of the log, newest first. `next` is the id to pass as `before_id` for the following page (None at the end)."""
    limit = max(1, min(int(limit), 200))
    with db._lock:
        args: tuple = (before_id, limit + 1) if before_id else (limit + 1,)
        rows = [dict(r) for r in db.connect().execute(
            "SELECT * FROM audit_log " + ("WHERE id<? " if before_id else "") + "ORDER BY id DESC LIMIT ?", args).fetchall()]
    more = len(rows) > limit
    rows = rows[:limit]
    out: List[dict] = []
    for r in rows:
        b, a = _load(r["before"]), _load(r["after"])
        out.append({"id": r["id"], "at": r["at"], "actor_id": r["actor_id"], "actor_role": r["actor_role"], "action": r["action"],
                    "target": r["target"], "before": redact(b) if redacted else b, "after": redact(a) if redacted else a,
                    "hash": r["hash"]})
    return {"entries": out, "next": rows[-1]["id"] if more and rows else None}


# ---------------------------------------------------------------- versioned medical settings
def set_versioned(key: str, value: Any, actor: Actor) -> int:
    """Store a medical setting as a new version in `medical_settings_history` (the previous ones stay) and make it current.
    Returns the new version number."""
    who = _who(actor)
    with db._lock:
        n = db.connect().execute("SELECT COALESCE(MAX(version),0) n FROM medical_settings_history WHERE key=?", (key,)).fetchone()["n"] + 1
    db.x("INSERT INTO medical_settings_history(key,version,value,actor_id,changed_at) VALUES(?,?,?,?,?)",
         (key, n, json.dumps(value), who["id"], _now()))
    db.set_setting(key, value)
    return n


def history(key: Optional[str] = None) -> List[dict]:
    rows = db.q("SELECT * FROM medical_settings_history " + ("WHERE key=? " if key else "") + "ORDER BY id", (key,) if key else ())
    return [{"key": r["key"], "version": r["version"], "value": json.loads(r["value"]), "by": r["actor_id"], "at": r["changed_at"]} for r in rows]
