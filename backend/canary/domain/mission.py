"""Mission clock and place.

The day comes from the demo story step, or from a day picked on the mission
plan. The place comes from the mission plan for that day, unless the crew
overrides it ("Where are you?").
"""
from typing import Optional

from .. import db
from . import plan
from .catalog import LOCATIONS, STORY, day_label

DEFAULT = {"step": 0, "day": None, "location": None}


def _get() -> dict:
    return {**DEFAULT, **(db.get_setting("mission") or {})}


def state() -> dict:
    s = _get()
    step = STORY[s["step"]]
    day = step["day"] if s["day"] is None else s["day"]
    leg = plan.leg_at(day)
    loc = s["location"] or plan.location_at(day)
    return {
        "step": s["step"],
        "steps": len(STORY),
        "story": step,
        "day": day,
        "day_label": day_label(day, loc, leg["start"] if loc == leg["location"] else 0),
        "location": loc,
        "place": {"id": loc, **LOCATIONS[loc]},
        "storm": step["storm"] if day == step["day"] else None,
        "suggested_user": step["me"],
        "learning": loc == "earth" and day < 0,
        "leg": leg,
        "custom_day": s["day"] is not None,
        "location_override": s["location"] is not None,
        "plan_name": plan.get()["name"],
    }


def set_step(step: int) -> dict:
    db.set_setting("mission", {**DEFAULT, "step": max(0, min(len(STORY) - 1, step))})
    return state()


def set_day(day: Optional[int]) -> dict:
    s = _get()
    db.set_setting("mission", {**s, "day": day, "location": None})
    return state()


def set_location(location: Optional[str]) -> dict:
    if location is not None and location not in LOCATIONS:
        raise ValueError(f"unknown location {location}")
    db.set_setting("mission", {**_get(), "location": location})
    return state()
