"""Who is flying and on what mission, as registered by Mission Control (Canary Control).

Mission Control registers four crew seats and the mission; nothing is created on board.
With no registration stored, the demo crew and mission apply (so a demo reset brings them
back). Mission Control can also clear everything and register from zero.

The rest of the code reads catalog.CREW / CREW_BY_ID / RECORDS; load() refreshes those
objects in place, so every module sees the registered crew without importing anything new.
Seats keep their ids (h, k, a, t) so the simulated readings and the demo story still work:
a newly registered astronaut takes over the seat's simulated pre-flight baseline.
"""
import copy
from typing import List, Optional

from .. import db
from . import catalog

SEATS = ["h", "k", "a", "t"]
SEED_KEYS = ("cbc_subject", "age", "base")  # what a seat carries for data/generate_dataset.py only
DEMO_CREW = copy.deepcopy(catalog.CREW)
DEMO_RECORDS = copy.deepcopy(catalog.RECORDS)
DEMO_MISSION = {"callsign": "Odyssey 1", "name": "Mars reference mission", "launch_date": "2035-06-01", "preset": "mars"}
RECORD_FIELDS = ["dob", "sex", "nationality", "languages", "agency", "flights", "days_in_space", "height_cm", "weight_kg",
                 "blood_type", "skin_type", "handedness", "vision", "allergies", "medications", "conditions", "diet",
                 "vaccinations", "emergency_contact", "eva", "prior_dose_msv"]


def stored() -> Optional[dict]:
    return db.get_setting("registry")


def mission_info() -> Optional[dict]:
    r = stored()
    return DEMO_MISSION if r is None else r.get("mission")


def registered() -> bool:
    r = stored()
    return r is None or bool(r.get("crew"))


def launch_date() -> str:
    m = mission_info()
    return (m or DEMO_MISSION)["launch_date"]


def demo_form() -> List[dict]:
    """The demo crew as Mission Control's form fills it (the 'fill with demo crew' button)."""
    pins = {"h": "1001", "k": "1002", "a": "1003", "t": "1004"}
    return [{"seat": c["id"], "name": c["name"], "role": c["role"], "home": c["home"], "pin": pins[c["id"]],
             "prior_dose_msv": None,  # empty: the form shows the estimate from days in space
             **DEMO_RECORDS[c["id"]]} for c in DEMO_CREW]


def _initials(name: str) -> str:
    parts = [p for p in name.split() if p]
    return (parts[0][0] + (parts[-1][0] if len(parts) > 1 else "")).upper() if parts else "?"


def load() -> None:
    """Refresh catalog.CREW, CREW_BY_ID and RECORDS in place from what is registered."""
    r = stored()
    if r is None:
        crew, records = copy.deepcopy(DEMO_CREW), copy.deepcopy(DEMO_RECORDS)
    else:
        demo_by_id = {c["id"]: c for c in DEMO_CREW}
        crew, records = [], {}
        for p in r.get("crew", []):
            seat = demo_by_id[p["seat"]]
            reg = str(p.get("sex") or "")[:1].upper()  # the registered sex picks the reference range; else the seat's
            crew.append({"id": p["seat"], "name": p["name"], "role": p["role"], "initials": _initials(p["name"]),
                         "home": p["home"], "sex": reg if reg in ("F", "M") else seat["sex"],
                         **{k: seat[k] for k in SEED_KEYS}})  # the seat's seed for the sheet generator; the engine never reads it
            records[p["seat"]] = {k: p.get(k) for k in RECORD_FIELDS if k in p or k != "prior_dose_msv"}
    catalog.CREW[:] = crew
    catalog.CREW_BY_ID.clear()
    catalog.CREW_BY_ID.update({c["id"]: c for c in crew})
    catalog.RECORDS.clear()
    catalog.RECORDS.update(records)


def clear() -> None:
    db.set_setting("registry", {"crew": [], "mission": None})
    load()


def register(crew: List[dict], mission: dict) -> None:
    seats = [p["seat"] for p in crew]
    if sorted(seats) != sorted(SEATS):
        raise ValueError("register all four seats")
    for p in crew:
        if not p.get("name", "").strip() or not p.get("role", "").strip():
            raise ValueError("every astronaut needs a name and a role")
    db.set_setting("registry", {"crew": crew, "mission": mission})
    load()
