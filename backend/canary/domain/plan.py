"""Mission plan: the itinerary of places over mission days.

Everything that depends on where the crew is (gravity, radiation, communication
delay, goals, alert rules, bone loss, Guided Response variants) asks this module
`location_at(day)`, so changing the plan re-adapts the whole system.
Day 0 is launch; negative days are pre-flight on Earth.
"""
import copy
from typing import List, Optional

from .. import db
from .catalog import LOCATIONS

PRESETS = {
    "mars": {"name": "Mars reference mission", "legs": [
        {"location": "earth", "start": -60, "end": -1, "label": "Pre-flight training and baseline"},
        {"location": "rocket", "start": 0, "end": 3, "label": "Launch and first 72 hours"},
        {"location": "transit", "start": 4, "end": 209, "label": "Cruise to Mars"},
        {"location": "mars", "start": 210, "end": 720, "label": "Surface stay, Gale crater"},
    ]},
    "iss": {"name": "Six months on the ISS", "legs": [
        {"location": "earth", "start": -60, "end": -1, "label": "Pre-flight training and baseline"},
        {"location": "rocket", "start": 0, "end": 1, "label": "Launch and docking"},
        {"location": "iss", "start": 2, "end": 181, "label": "Expedition on the station"},
        {"location": "rocket", "start": 182, "end": 182, "label": "Undocking and landing"},
        {"location": "earth", "start": 183, "end": 270, "label": "Recovery and rehabilitation"},
    ]},
    "moon": {"name": "Lunar surface mission", "legs": [
        {"location": "earth", "start": -60, "end": -1, "label": "Pre-flight training and baseline"},
        {"location": "rocket", "start": 0, "end": 4, "label": "Launch and lunar transit"},
        {"location": "moon", "start": 5, "end": 34, "label": "Surface stay, south pole"},
        {"location": "rocket", "start": 35, "end": 39, "label": "Return to Earth"},
        {"location": "earth", "start": 40, "end": 120, "label": "Recovery"},
    ]},
}
DEFAULT = "mars"

_cache: dict = {"plan": None, "version": 0}


def get() -> dict:
    if _cache["plan"] is None:
        _cache["plan"] = db.get_setting("plan") or {**copy.deepcopy(PRESETS[DEFAULT]), "preset": DEFAULT}
    return _cache["plan"]


def version() -> int:
    return _cache["version"]


def validate(name: str, legs: List[dict]) -> dict:
    if not 1 <= len(legs) <= 20:
        raise ValueError("a plan needs 1 to 20 legs")
    legs = sorted(({"location": l["location"], "start": int(l["start"]), "end": int(l["end"]), "label": str(l.get("label") or "")[:80]}
                   for l in legs), key=lambda l: l["start"])
    for i, l in enumerate(legs):
        if l["location"] not in LOCATIONS:
            raise ValueError(f"unknown place: {l['location']}")
        if l["end"] < l["start"]:
            raise ValueError(f"leg {i + 1} ends before it starts")
        if i and l["start"] <= legs[i - 1]["end"]:
            raise ValueError(f"leg {i + 1} overlaps leg {i}")
    return {"name": (name or "Mission plan")[:80], "legs": legs}


def save(plan: dict, preset: Optional[str] = None) -> dict:
    plan = {**plan, "preset": preset}
    db.set_setting("plan", plan)
    _cache.update(plan=plan, version=_cache["version"] + 1)
    return plan


def use_preset(key: str) -> dict:
    if key not in PRESETS:
        raise ValueError(f"unknown preset {key}")
    return save(copy.deepcopy(PRESETS[key]), key)


def reset_cache() -> None:
    _cache.update(plan=None, version=_cache["version"] + 1)


def leg_index(day: int) -> int:
    """Index of the leg in force on `day` (gaps keep the previous leg; before the plan is the first leg)."""
    legs = get()["legs"]
    idx = 0
    for i, l in enumerate(legs):
        if day >= l["start"]:
            idx = i
    return idx


def location_at(day: int) -> str:
    legs = get()["legs"]
    if day < legs[0]["start"]:
        return "earth"
    return legs[leg_index(day)]["location"]


def leg_at(day: int) -> dict:
    legs = get()["legs"]
    i = leg_index(day)
    l = legs[i]
    nxt = legs[i + 1] if i + 1 < len(legs) else None
    return {**l, "index": i, "day_in_leg": day - l["start"] + 1, "length": l["end"] - l["start"] + 1,
            "next": nxt, "days_to_next": (nxt["start"] - day) if nxt else None}


def days_since_gravity_change(day: int) -> Optional[int]:
    """Days since arriving in partial gravity after a 0 g leg, or None."""
    legs = get()["legs"]
    i = leg_index(day)
    if i == 0 or LOCATIONS[legs[i]["location"]]["gravity_key"] != "gp":
        return None
    if LOCATIONS[legs[i - 1]["location"]]["gravity_key"] != "g0":
        return None
    return day - legs[i]["start"]
