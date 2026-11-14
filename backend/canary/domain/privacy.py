"""Who sees what. Follows the team's data-use draft: a visibility contract signed on day 0.

- The astronaut and the medical team see everything about that astronaut.
- Operational status ("fit for EVA", "off critical tasks") is a medical matter: only the astronaut
  and the medical team see it. The crew sees environment hazards, crew goals and each person's
  goal participation. Raw data and history only if the astronaut chooses to share.
- Earth gets operational status through the medical team and, after a critical event, a delayed briefing.
- Crew views show states, never averages: with four people an average reveals individuals.
- If the medical officer is the patient, their alerts go to a substitute.
"""
from typing import Optional

from .. import db
from .catalog import CREW_BY_ID, LOCATIONS, SYSTEMS

MEDICAL_OFFICER = "k"
SUBSTITUTE = "h"

OPS = {
    "full": {"label": "Fit for all duties", "level": 0},
    "limited": {"label": "Fit for duty, no EVA", "level": 1},
    "rest": {"label": "Off critical tasks", "level": 2},
}

CONTRACT = [
    {"info": "Raw data and history", "self": "Yes", "doctor": "Yes", "crew": "Only if you share", "earth": "No"},
    {"info": "Personal risks and advice", "self": "Yes", "doctor": "Yes", "crew": "No", "earth": "No"},
    {"info": "Operational status (e.g. fit for EVA)", "self": "Yes", "doctor": "Yes", "crew": "No", "earth": "Via the medical team"},
    {"info": "Critical alert", "self": "Immediately", "doctor": "Immediately", "crew": "No", "earth": "Delayed briefing"},
    {"info": "Hazards and crew goals", "self": "Yes", "doctor": "Yes", "crew": "Yes", "earth": "Yes"},
]

HAZARD_BY_GRAVITY = {
    "g0": ("Microgravity", "Bone and muscle loss, fluid shift towards the head."),
    "gp": ("Partial gravity", "Re-adaptation, dust, suited work outside."),
    "g1": None,
}


# Watch-level alerts that change what a person may do. A slow trend (bone, grip, sleep) is
# followed in private and does not take anyone off EVA on its own.
LIMITING = {"sickness", "regravity", "amsler", "ind_hr", "ind_bp", "ind_spo2", "ind_temp", "ind_react"}


def operational(snap: dict) -> dict:
    """Operational status: for the astronaut and the medical team only. Built from personal alerts; environment alerts are crew hazards."""
    personal = [a for a in snap["alerts"] if not a.get("env")]
    if any(a["level"] == 2 for a in personal):
        key = "rest"
    elif any(a["id"] in LIMITING for a in personal):
        key = "limited"
    else:
        key = "full"
    return {"key": key, **OPS[key]}


def care_by(crew_id: str) -> str:
    """Who receives this person's alerts on board."""
    who = SUBSTITUTE if crew_id == MEDICAL_OFFICER else MEDICAL_OFFICER
    c = CREW_BY_ID[who]
    return f"{c['name']} ({'substitute medical officer' if who == SUBSTITUTE else 'medical officer'})"


def shared(crew_id: str) -> bool:
    return bool(db.get_setting("share", {}).get(crew_id, False))


def set_shared(crew_id: str, value: bool) -> None:
    s = db.get_setting("share", {})
    s[crew_id] = bool(value)
    db.set_setting("share", s)


def can_see_details(viewer: Optional[str], crew_id: str, medical: bool) -> bool:
    return medical or viewer == crew_id or shared(crew_id)


def hazards(ms: dict, env_alerts: list) -> list:
    """Environment hazards: the same for everyone, so they are public."""
    place = LOCATIONS[ms["location"]]
    out = [{"title": a["title"], "level": a["level"], "what": "; ".join(a["todo"][:2]) + ".", "sources": a.get("sources", [])}
           for a in env_alerts]
    g = HAZARD_BY_GRAVITY.get(place["gravity_key"])
    if ms["location"] == "rocket":
        out.append({"title": "Launch and flight loads", "level": 0, "what": "Space sickness is common in the first days.", "sources": []})
    elif g:
        out.append({"title": g[0], "level": 0, "what": g[1], "sources": []})
    if ms["location"] != "earth":
        out.append({"title": f"Radiation {place['dose_rate']} mSv/day", "level": 0,
                    "what": "Background dose for this place. Storms add to it.", "sources": []})
    if place["delay_s"] > 60:
        out.append({"title": f"Earth replies in {place['reply']}", "level": 0,
                    "what": "The crew handles emergencies on its own.", "sources": []})
    return out


# ---------------------------------------------------------------- NASA's five hazards of spaceflight (RIDGE)
# Simplified from the public pages of the NASA Human Research Program. Levels per place are a
# prototype judgement; a solar storm raises radiation to high wherever there is no magnetic shield.
RIDGE = [
    {"id": "R", "name": "Radiation", "what": "Particles from the Sun and deep space damage cells and DNA.",
     "systems": ["skin", "immune"]},
    {"id": "I", "name": "Isolation & confinement", "what": "Months in a small space with the same few people.",
     "systems": ["brain"]},
    {"id": "D", "name": "Distance from Earth", "what": "Help, supplies and replies take longer the farther you go.",
     "systems": ["gut"]},
    {"id": "G", "name": "Gravity", "what": "0 g on the way, 1/6 g on the Moon, 3/8 g on Mars. The body adapts in ways that hurt.",
     "systems": ["skeleton", "muscles", "heart", "eyes", "kidneys"]},
    {"id": "E", "name": "Hostile, closed environment", "what": "Recycled air, noise, shared surfaces and no way to step outside.",
     "systems": ["lungs"]},
]
RIDGE_LEVEL = {
    "earth": {"R": 0, "I": 0, "D": 0, "G": 0, "E": 0},
    "rocket": {"R": 1, "I": 1, "D": 0, "G": 2, "E": 1},
    "iss": {"R": 1, "I": 1, "D": 0, "G": 2, "E": 1},
    "moon": {"R": 2, "I": 1, "D": 1, "G": 1, "E": 2},
    "transit": {"R": 2, "I": 2, "D": 2, "G": 2, "E": 1},
    "mars": {"R": 1, "I": 2, "D": 2, "G": 1, "E": 2},
}
LEVEL_LABEL = ["Low", "Moderate", "High"]


def _here(hid: str, location: str) -> str:
    p = LOCATIONS[location]
    return {
        "R": f"{p['dose_rate']} mSv a day here",
        "I": "Training with family nearby" if location == "earth" else "Four people, no leave",
        "D": f"Earth replies {'live' if p['reply'] == 'Live' else 'in ' + p['reply']} · hospital: {p['hospital'].lower()}",
        "G": f"{p['gravity']} here",
        "E": "Open air" if location == "earth" else "Recycled air and constant noise",
    }[hid]


def ridge(location: str, storm: Optional[str] = None) -> list:
    out = []
    for h in RIDGE:
        lv = RIDGE_LEVEL[location][h["id"]]
        if h["id"] == "R" and storm and location != "earth":
            lv = 2
        out.append({**h, "level": lv, "label": LEVEL_LABEL[lv], "here": _here(h["id"], location),
                    "system_names": [SYSTEMS[s]["name"] for s in h["systems"]]})
    return out
