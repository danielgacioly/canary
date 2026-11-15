"""Who is flying and on what mission, as registered by Mission Control (Canary Control).

The crew is whoever is registered: one to six people, each with the id Mission Control gave them (the `id` column of
crew.csv in a mission package) or one generated for them (s1 to s6) when the form leaves it out. A registered person
carries only what was registered: name, role, home, the record fields and a PIN. Nothing about them is borrowed from
a demo character, and with nothing registered the system has no crew at all. The demo crew is just what the
odyssey1 packages register through their crew.csv.

The rest of the code reads catalog.CREW / CREW_BY_ID / RECORDS; load() refreshes those objects in place, so every
module sees the registered crew without importing anything new. Age comes from the date of birth and the launch date,
sex (F or M) from the record; a person registered without a sex has none, and the population and laboratory ranges
that depend on sex simply do not apply to them.
"""
import re
from datetime import date
from typing import Dict, List, Optional, Tuple

from .. import auth, db
from . import catalog, validation

MAX_CREW = catalog.MAX_CREW
RESERVED_IDS = ("cabin", "crew", "earth", "canary", "medical", "control")  # names the engine already uses as senders, recipients or sources
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,19}$")
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
    db.set_setting("registry", {"crew": [], "mission": None})
    db.set_setting("pins", {})
    load()


def assign_ids(ids: List[Optional[str]]) -> List[str]:
    """The id of each person in order: the one given, else the first of s1, s2... not taken by someone else. The same
    order gives the same ids, so registering again keeps everybody's id."""
    taken = {i for i in ids if i}
    out, k = [], 1
    for i in ids:
        if not i:
            while f"s{k}" in taken:
                k += 1
            i = f"s{k}"
            taken.add(i)
        out.append(i)
    return out


def normalize(crew: List[dict]) -> Tuple[List[dict], Dict[str, str]]:
    """Check a crew and settle it: returns (the people as they are stored, the PINs by id). Raises ValueError.

    One to six people; name and role required; ids unique (each given as `seat` or `id`, else generated) and plain
    (letters, digits, `-`, `_`); PINs, when given, exactly four digits and unique."""
    if not 1 <= len(crew) <= MAX_CREW:
        raise ValueError(f"register between 1 and {MAX_CREW} people")
    for p in crew:
        if not str(p.get("name", "")).strip() or not str(p.get("role", "")).strip():
            raise ValueError("every astronaut needs a name and a role")
    ids = assign_ids([(p.get("seat") or p.get("id") or None) for p in crew])
    pins: Dict[str, str] = {}
    people: List[dict] = []
    seen_pin: Dict[str, str] = {}
    for p, i in zip(crew, ids):
        if not ID_RE.match(i) or i in RESERVED_IDS:
            raise ValueError(f"'{i}' is not a valid id: use letters, digits, - and _ (at most 20), and not {', '.join(RESERVED_IDS)}")
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
        people.append({**{k: v for k, v in p.items() if k not in ("pin", "id", "seat")}, "seat": i})
    return people, pins


def register(crew: List[dict], mission: dict) -> None:
    """Register the crew (one to six people) and the mission. A person's `pin` is stored hashed (auth), not in the registry."""
    people, pins = normalize(crew)
    db.set_setting("registry", {"crew": people, "mission": mission})
    db.set_setting("pins", auth.hashed_pins(pins, keep=False))
    load()
