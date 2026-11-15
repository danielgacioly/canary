"""PINs, lockout and session tokens for every person who signs in: crew, medical (the crew medical officer and ground
flight surgeons) and Canary Control (MCC accounts).

- Every account has a 4-digit PIN, stored salted and hashed (PBKDF2-SHA256) in the settings table when Canary Control
  registers it (or a package imports it) and again when the person changes it. Crew ids and ground ids (`g-...`) share the
  one table of PINs and never collide. CANARY_CREW_PINS (config) is only a fallback for a crew id with no stored PIN, and
  is empty in flight mode.
- Signing in returns a signed token `{kind}.{account_id}.{roles}.{exp}.{jti}.{sig}`; `sig` is an HMAC over everything
  before it with the token secret. `kind` is `crew`, `medical` or `control`, one per header (X-Canary-Viewer,
  Authorization: Bearer, X-Canary-Control), and a token only counts in its own header. Logging out revokes the `jti`
  (table `revoked_tokens`, pruned when expired).
- Wrong PINs lock an account and a client address, stored in SQLite so a restart does not clear them: after every 5
  failures the wait grows 1, 5, 15, then 60 minutes.
"""
import hashlib
import hmac
import os
import secrets
import time
from typing import Dict, Optional, Sequence

from . import db
from .config import PIN_RE, settings

FAILS_PER_STEP = 5
WAITS_MIN = (1, 5, 15, 60)  # wait after the 5th, 10th, 15th and every later batch of 5 failures
DECAY_S = 24 * 3600         # a quiet day forgets the failures that did not lock anything
GROUND_PREFIX = "g-"


def _hash(pin: str, salt: bytes) -> str:
    return hashlib.pbkdf2_hmac("sha256", pin.encode(), salt, settings.pin_iterations).hex()


def valid_pin(pin: str) -> bool:
    return bool(PIN_RE.match(pin or ""))


def check_pin(account_id: str, pin: str) -> bool:
    """The PIN of a crew id or a ground id (`g-...`). Ground accounts have no fallback: only a stored PIN counts."""
    stored = (db.get_setting("pins") or {}).get(account_id)
    if stored:
        return hmac.compare_digest(_hash(pin, bytes.fromhex(stored["salt"])), stored["hash"])
    if account_id.startswith(GROUND_PREFIX):
        return False
    return hmac.compare_digest(pin, settings.crew_pins.get(account_id, ""))


def set_pin(crew_id: str, pin: str) -> None:
    if not valid_pin(pin):
        raise ValueError("a PIN is exactly 4 digits")
    salt = os.urandom(16)
    pins = db.get_setting("pins") or {}
    pins[crew_id] = {"salt": salt.hex(), "hash": _hash(pin, salt)}
    db.set_setting("pins", pins)


def hashed_pins(pins: Dict[str, str], keep: bool = True) -> dict:
    """The `pins` setting with these PINs (salted and hashed), for callers that write settings themselves. `keep`: add to
    the PINs already stored; False: only these (a registration replaces everybody's)."""
    out = dict(db.get_setting("pins") or {}) if keep else {}
    for crew_id, pin in pins.items():
        if not valid_pin(pin):
            raise ValueError("a PIN is exactly 4 digits")
        salt = os.urandom(16)
        out[crew_id] = {"salt": salt.hex(), "hash": _hash(pin, salt)}
    return out


# ---------------------------------------------------------------- lockout (persistent)
def remaining(*keys: str) -> int:
    """Seconds until the longest wait among these keys ends; 0 when none is locked."""
    now = time.time()
    wait = 0.0
    for k in keys:
        rows = db.q("SELECT until FROM auth_failures WHERE key=?", (k,))
        if rows:
            wait = max(wait, rows[0]["until"] - now)
    return max(0, int(wait + 0.999)) if wait > 0 else 0


def locked(*keys: str) -> bool:
    return remaining(*keys) > 0


def fail(key: str) -> Optional[int]:
    """Count a wrong PIN against `key`. Returns the new wait in minutes when this failure locked the key, else None."""
    now = time.time()
    rows = db.q("SELECT count, until, last FROM auth_failures WHERE key=?", (key,))
    count, until, last = (rows[0]["count"], rows[0]["until"], rows[0]["last"]) if rows else (0, 0.0, now)
    if now - last > DECAY_S and now > until:
        count = 0
    count += 1
    wait = None
    if count % FAILS_PER_STEP == 0:
        wait = WAITS_MIN[min(count // FAILS_PER_STEP, len(WAITS_MIN)) - 1]
        until = now + wait * 60
    db.x("INSERT INTO auth_failures(key,count,until,last) VALUES(?,?,?,?) "
         "ON CONFLICT(key) DO UPDATE SET count=excluded.count, until=excluded.until, last=excluded.last", (key, count, until, now))
    return wait


def succeed(key: str) -> None:
    """A right PIN: forget the failures of this account."""
    if db.q("SELECT 1 FROM auth_failures WHERE key=?", (key,)):
        db.x("DELETE FROM auth_failures WHERE key=?", (key,))


def clear_failures() -> None:
    db.x("DELETE FROM auth_failures")


# ---------------------------------------------------------------- tokens
KINDS = ("crew", "medical", "control")


def _sig(body: str) -> str:
    return hmac.new(settings.token_secret.encode(), body.encode(), hashlib.sha256).hexdigest()[:32]


def issue(kind: str, account_id: str, roles: Sequence[str], ttl_s: Optional[int] = None) -> dict:
    exp = int(time.time() + (ttl_s or settings.token_ttl_s))
    body = f"{kind}.{account_id}.{'+'.join(roles)}.{exp}.{secrets.token_hex(8)}"
    out = {"token": f"{body}.{_sig(body)}", "expires_at": exp, "account_id": account_id, "roles": list(roles)}
    if kind == "crew":
        out["crew_id"] = account_id
    return out


def _parse(token: Optional[str]) -> Optional[dict]:
    """The claims of a token whose signature and expiry are right (revocation is checked by `verify`)."""
    parts = (token or "").split(".")
    if len(parts) != 6:
        return None
    kind, account_id, roles, exp_s, jti, sig = parts
    try:
        exp = int(exp_s)
    except ValueError:
        return None
    if kind not in KINDS or exp < time.time() or not hmac.compare_digest(sig, _sig(".".join(parts[:5]))):
        return None
    return {"kind": kind, "id": account_id, "roles": [r for r in roles.split("+") if r], "exp": exp, "jti": jti}


def revoked(jti: str) -> bool:
    return bool(db.q("SELECT 1 FROM revoked_tokens WHERE jti=?", (jti,)))


def verify(token: Optional[str], kind: str) -> Optional[dict]:
    """{kind, id, roles, exp, jti} of a valid, unexpired, unrevoked token of this kind, else None."""
    c = _parse(token)
    if c is None or c["kind"] != kind or revoked(c["jti"]):
        return None
    return c


def revoke(token: Optional[str]) -> bool:
    """Log out: the token stops working at once. False when it was not a valid token."""
    c = _parse(token)
    if c is None:
        return False
    db.x("DELETE FROM revoked_tokens WHERE exp < ?", (time.time(),))
    db.x("INSERT OR IGNORE INTO revoked_tokens(jti,exp) VALUES(?,?)", (c["jti"], c["exp"]))
    return True
