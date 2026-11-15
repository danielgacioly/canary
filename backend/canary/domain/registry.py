"""Who is flying and on what mission, as registered by Mission Control (Canary Control).

The crew is whoever is registered: one to six people, each with the id Mission Control gave them (the `id` column of
crew.csv in a mission package) or one generated for them (`c-` and six hex digits, never reused) when the form leaves it out.
Ground accounts (flight surgeons and MCC, ids `g-...`) are registered with them and sign in to the medical console and Canary
Control; the crew medical officer (`cmo`) signs in to the medical console with their crew id. A registered person
carries only what was registered: name, role, home, the record fields and a PIN. Nothing about them is borrowed from
a demo character, and with nothing registered the system has no crew at all. The demo crew is just what the
odyssey1 packages register through their crew.csv.

The rest of the code reads catalog.CREW / CREW_BY_ID / RECORDS; load() refreshes those objects in place, so every
module sees the registered crew without importing anything new. Age comes from the date of birth and the launch date,
sex (F or M) from the record; a person registered without a sex has none, and the population and laboratory ranges
that depend on sex simply do not apply to them.
"""
import re
import secrets
from datetime import date
from typing import Dict, List, Optional, Tuple

from .. import auth, db
from . import catalog, validation

MAX_CREW = catalog.MAX_CREW
RESERVED_IDS = ("cabin", "crew", "earth", "canary", "medical", "control")  # names the engine already uses as senders, recipients or sources
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,19}$")
GROUND_ROLES = ("flight_surgeon", "mcc")
MAX_GROUND = 12
GROUND_PREFIX = auth.GROUND_PREFIX
CMO_WORDS = re.compile(r"medical officer|\bcmo\b", re.I)
# What the mission looks like before anything is registered: no callsign, the launch date the clock counts from.
EMPTY_MISSION = {"callsign": None, "name": "Mission plan", "launch_date": "2035-06-01", "preset": "mars"}
RECORD_FIELDS = ["dob", "sex", "nationality", "languages", "agency", "flights", "days_in_space", "height_cm", "weight_kg",
                 "blood_type", "skin_type", "handedness", "vision", "allergies", "medications", "conditions", "diet",
                 "vaccinations", "emergency_contact", "eva", "prior_dose_msv"]


def stored() -> Optional[dict]:
    return db.get_setting("registry")


def mission_info() -> Optional[dict]:
    r = stored()
    return None if r is None else r.get("mission")


def registered() -> bool:
    r = stored()
    return bool(r and r.get("crew"))


def launch_date() -> str:
    m = mission_info()
    return (m or EMPTY_MISSION)["launch_date"]


def _initials(name: str) -> str:
    parts = [p for p in name.split() if p]
    return (parts[0][0] + (parts[-1][0] if len(parts) > 1 else "")).upper() if parts else "?"


def _sex(record_sex) -> Optional[str]:
    s = str(record_sex or "")[:1].upper()
    return s if s in ("F", "M") else None


def load() -> None:
    """Refresh catalog.CREW, CREW_BY_ID and RECORDS in place from what is registered (nothing registered: nobody)."""
    r = stored() or {}
    launch = date.fromisoformat(launch_date())
    crew, records = [], {}
    for p in r.get("crew", []):
        age = None
        try:
            age = validation.age_on(date.fromisoformat(p["dob"]), launch)
        except (KeyError, TypeError, ValueError):
            pass
        crew.append({"id": p["seat"], "name": p["name"], "role": p["role"], "initials": _initials(p["name"]),
                     "home": p.get("home", ""), "sex": _sex(p.get("sex")), "age": age})
        records[p["seat"]] = {k: p.get(k) for k in RECORD_FIELDS if k in p or k != "prior_dose_msv"}
    catalog.CREW[:] = crew
    catalog.CREW_BY_ID.clear()
    catalog.CREW_BY_ID.update({c["id"]: c for c in crew})
    catalog.RECORDS.clear()
    catalog.RECORDS.update(records)


def clear() -> None:
    db.set_setting("registry", {"crew": [], "mission": None, "ground": []})
    db.set_setting("pins", {})
    load()


# ---------------------------------------------------------------- accounts
def ground() -> List[dict]:
    return list((stored() or {}).get("ground") or [])


def has_mcc() -> bool:
    return any(g["role"] == "mcc" for g in ground())


def _is_cmo(p: dict) -> bool:
    flag = p.get("cmo")
    return bool(flag) if flag is not None else bool(CMO_WORDS.search(str(p.get("role", ""))))


def cmo_id() -> Optional[str]:
    """Id of the crew medical officer: the person registered with `cmo`, else (a registry made before the flag) the one whose
    role says so; None when nobody is."""
    people = (stored() or {}).get("crew", [])
    return next((p["seat"] for p in people if _is_cmo(p)), None)


def account(account_id: str) -> Optional[dict]:
    """{id, name, role, roles, kind} of a crew person or a ground account, or None. `kind` is "crew" or "ground"."""
    for p in (stored() or {}).get("crew", []):
        if p["seat"] == account_id:
            return {"id": account_id, "name": p["name"], "role": p["role"], "kind": "crew",
                    "roles": ["crew"] + (["cmo"] if _is_cmo(p) else [])}
    for g in ground():
        if g["id"] == account_id:
            return {"id": account_id, "name": g["name"], "role": g["role"], "kind": "ground", "roles": [g["role"]]}
    return None


def accounts_public() -> dict:
    """What a sign-in picker may show: names and roles, never a PIN."""
    people = (stored() or {}).get("crew", [])
    return {"crew": [{"id": p["seat"], "name": p["name"], "role": p["role"], "initials": _initials(p["name"]),
                      "cmo": _is_cmo(p)} for p in people],
            "ground": [{"id": g["id"], "name": g["name"], "role": g["role"]} for g in ground()]}


def new_id(prefix: str, taken: set) -> str:
    """A fresh id `prefix` + six hex digits, not in `taken` (and added to it)."""
    while True:
        i = prefix + secrets.token_hex(3)
        if i not in taken:
            taken.add(i)
            return i


def assign_ids(ids: List[Optional[str]], taken: Optional[set] = None) -> List[str]:
    """The id of each person in order: the one given, else a generated `c-xxxxxx` that nobody has (ids already registered
    and the ids given count as taken, so an id is never reused while it exists)."""
    taken = set(taken or ()) | {i for i in ids if i}
    return [i or new_id("c-", taken) for i in ids]


def used_ids() -> set:
    r = stored() or {}
    return {p["seat"] for p in r.get("crew", [])} | {g["id"] for g in r.get("ground", [])}


def normalize(crew: List[dict]) -> Tuple[List[dict], Dict[str, str]]:
    """Check a crew and settle it: returns (the people as they are stored, the PINs by id). Raises ValueError.

    One to six people; name and role required; ids unique (each given as `seat` or `id`, else generated) and plain
    (letters, digits, `-`, `_`, not starting with `g-`); PINs, when given, exactly four digits and unique; at most one
    crew medical officer (`cmo`, else from the role text)."""
    if not 1 <= len(crew) <= MAX_CREW:
        raise ValueError(f"register between 1 and {MAX_CREW} people")
    for p in crew:
        if not str(p.get("name", "")).strip() or not str(p.get("role", "")).strip():
            raise ValueError("every astronaut needs a name and a role")
    ids = assign_ids([(p.get("seat") or p.get("id") or None) for p in crew], used_ids())
    pins: Dict[str, str] = {}
    people: List[dict] = []
    seen_pin: Dict[str, str] = {}
    for p, i in zip(crew, ids):
        if not ID_RE.match(i) or i in RESERVED_IDS or i.startswith(GROUND_PREFIX):
            raise ValueError(f"'{i}' is not a valid id: use letters, digits, - and _ (at most 20), not starting with g-, and not {', '.join(RESERVED_IDS)}")
        if i in {x["seat"] for x in people}:
            raise ValueError(f"id {i} is used twice")
        pin = p.get("pin")
        if pin:
            if not auth.valid_pin(pin):
                raise ValueError("a PIN is exactly 4 digits")
            if pin in seen_pin:
                raise ValueError(f"PIN already used by {seen_pin[pin]}")
            seen_pin[pin] = i
            pins[i] = pin
        people.append({**{k: v for k, v in p.items() if k not in ("pin", "id", "seat", "cmo")}, "seat": i, "cmo": _is_cmo(p)})
    if sum(1 for p in people if p["cmo"]) > 1:
        raise ValueError("a crew has one crew medical officer")
    return people, pins


def normalize_ground(ground_in: List[dict], taken: Optional[set] = None) -> Tuple[List[dict], Dict[str, str]]:
    """Check the ground accounts: returns (the accounts as stored: id, name, role; the PINs by id). Raises ValueError.
    No ground account is required (without an MCC account the first-access PIN keeps Canary Control open); roles flight_surgeon or mcc; ids `g-...` unique (generated when left out); a PIN each."""
    if len(ground_in) > MAX_GROUND:
        raise ValueError(f"register at most {MAX_GROUND} ground accounts")
    taken = set(taken or ())
    ids = assign_ground_ids([g.get("id") or None for g in ground_in], taken)
    out: List[dict] = []
    pins: Dict[str, str] = {}
    seen_pin: Dict[str, str] = {}
    for g, i in zip(ground_in, ids):
        if not str(g.get("name", "")).strip():
            raise ValueError("every ground account needs a name")
        if g.get("role") not in GROUND_ROLES:
            raise ValueError("a ground account is flight_surgeon or mcc")
        if not re.match(r"^g-[A-Za-z0-9_-]{1,17}$", i):
            raise ValueError(f"'{i}' is not a valid ground id: start with g- and use letters, digits, - and _")
        if i in {x["id"] for x in out}:
            raise ValueError(f"id {i} is used twice")
        pin = g.get("pin") or ""
        if not auth.valid_pin(pin):
            raise ValueError("a PIN is exactly 4 digits")
        if pin in seen_pin:
            raise ValueError(f"PIN already used by {seen_pin[pin]}")
        seen_pin[pin] = i
        pins[i] = pin
        out.append({"id": i, "name": str(g["name"]).strip(), "role": g["role"]})
    return out, pins


def assign_ground_ids(ids: List[Optional[str]], taken: Optional[set] = None) -> List[str]:
    taken = set(taken or ()) | {i for i in ids if i}
    return [i or new_id(GROUND_PREFIX, taken) for i in ids]


def register(crew: List[dict], mission: dict, ground_in: Optional[List[dict]] = None) -> None:
    """Register the crew (one to six people), the ground accounts and the mission. PINs are stored hashed (auth), not in the
    registry. Ground accounts are optional; nothing is stored when any check fails."""
    people, pins = normalize(crew)
    ground_rows, ground_pins = normalize_ground(ground_in or [], {p["seat"] for p in people})
    db.set_setting("registry", {"crew": people, "mission": mission, "ground": ground_rows})
    db.set_setting("pins", auth.hashed_pins({**pins, **ground_pins}, keep=False))
    load()
