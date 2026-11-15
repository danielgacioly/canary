"""PINs and session tokens for the private spaces.

- Every registered crew member has a 4-digit PIN, stored salted and hashed (PBKDF2-SHA256) in the settings table
  when they are registered or imported, and again when they change it in the app. CANARY_CREW_PINS (config) is only a
  fallback default for an id that has no stored PIN.
- Signing in returns a short-lived token `{crew_id}.{exp}.{sig}`; `sig` is an HMAC over `crew:{crew_id}:{exp}`.
  The X-Canary-Viewer header carries that token, never a bare id.
- Failed attempts are rate-limited per person: 5 in 60 seconds.
"""
import hashlib
import hmac
import os
import time
from typing import Dict, List, Optional

from . import db
from .config import PIN_RE, settings

MAX_FAILS = 5
WINDOW_S = 60

_failed: Dict[str, List[float]] = {}


def _hash(pin: str, salt: bytes) -> str:
    return hashlib.pbkdf2_hmac("sha256", pin.encode(), salt, settings.pin_iterations).hex()


def valid_pin(pin: str) -> bool:
    return bool(PIN_RE.match(pin or ""))


def check_pin(crew_id: str, pin: str) -> bool:
    stored = (db.get_setting("pins") or {}).get(crew_id)
    if stored:
        return hmac.compare_digest(_hash(pin, bytes.fromhex(stored["salt"])), stored["hash"])
    return hmac.compare_digest(pin, settings.crew_pins.get(crew_id, ""))


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


# ---------------------------------------------------------------- rate limit
def locked(key: str) -> bool:
    now = time.time()
    _failed[key] = [t for t in _failed.get(key, []) if now - t < WINDOW_S]
    return len(_failed[key]) >= MAX_FAILS


def fail(key: str) -> None:
    _failed.setdefault(key, []).append(time.time())


def clear_failures() -> None:
    _failed.clear()


# ---------------------------------------------------------------- crew tokens
def _sig(crew_id: str, exp: int) -> str:
    return hmac.new(settings.token_secret.encode(), f"crew:{crew_id}:{exp}".encode(), hashlib.sha256).hexdigest()[:32]


def issue(crew_id: str) -> dict:
    exp = int(time.time() + settings.token_ttl_s)
    return {"token": f"{crew_id}.{exp}.{_sig(crew_id, exp)}", "expires_at": exp, "crew_id": crew_id}


def verify(token: Optional[str]) -> Optional[str]:
    """The crew id a valid, unexpired token belongs to, else None."""
    try:
        crew_id, exp_s, sig = (token or "").split(".")
        exp = int(exp_s)
    except ValueError:
        return None
    if exp < time.time() or not hmac.compare_digest(sig, _sig(crew_id, exp)):
        return None
    return crew_id
