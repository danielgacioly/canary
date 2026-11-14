"""Mission clock and place. The demo story sets both; the crew can change the place."""
from typing import Optional

from .. import db
from .catalog import LOCATIONS, STORY, day_label


def state() -> dict:
    s = db.get_setting("mission", {"step": 0, "location": None})
    step = STORY[s["step"]]
    loc = s.get("location") or step["loc"]
    L = LOCATIONS[loc]
    return {
        "step": s["step"],
        "steps": len(STORY),
        "story": step,
        "day": step["day"],
        "day_label": day_label(step["day"], loc),
        "location": loc,
        "place": {"id": loc, **L},
        "storm": step["storm"],
        "suggested_user": step["me"],
        "learning": loc == "earth",
    }


def set_step(step: int) -> dict:
    step = max(0, min(len(STORY) - 1, step))
    db.set_setting("mission", {"step": step, "location": None})
    return state()


def set_location(location: Optional[str]) -> dict:
    if location is not None and location not in LOCATIONS:
        raise ValueError(f"unknown location {location}")
    s = db.get_setting("mission", {"step": 0, "location": None})
    s["location"] = location
    db.set_setting("mission", s)
    return state()
