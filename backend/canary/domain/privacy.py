"""Who sees what. Follows the team's data-use draft: a visibility contract signed on day 0.

- The astronaut and the medical team see everything about that astronaut.
- Operational status ("fit for EVA", "off critical tasks") is a medical matter: only the astronaut
  and the medical team see it. The crew sees environment hazards, crew goals and each person's
  goal participation and profile photo. Raw data and history never leave the person and the medical team.
- Earth gets operational status through the medical team and, after a critical event, a delayed briefing.
- Crew views show states, never averages: with four people an average reveals individuals.
- If the medical officer is the patient, their alerts go to a substitute.
"""
from typing import Optional

from .. import db
from . import care, plan
from .catalog import CREW, CREW_BY_ID, LOCATIONS, SYSTEMS


def medical_officer() -> Optional[str]:
    """Id of the crew member whose role is medical officer; None when nobody on board has that role."""
    return next((c["id"] for c in CREW if "medical officer" in c["role"].lower()), None)


def substitute() -> Optional[str]:
    """Id of who receives the medical officer's own alerts: the commander, else the first other person, else the officer.
    Without a medical officer it is the same choice among everybody (None only when nobody is registered)."""
    mo = medical_officer()
    others = [c for c in CREW if c["id"] != mo]
    return next((c["id"] for c in others if "commander" in c["role"].lower()), others[0]["id"] if others else mo)


OPS = {
    "full": {"label": "Fit for all duties", "level": 0},
    "limited": {"label": "Fit for duty, no EVA", "level": 1},
    "rest": {"label": "Off critical tasks", "level": 2},
}

CONTRACT = [
    {"info": "Raw data and history", "self": "Yes", "doctor": "Yes", "crew": "No", "earth": "No"},
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
    """Operational status: for the astronaut and the medical team only. Built from personal alerts; environment alerts are crew hazards.

    Inside the care window of a closed emergency the status is at least the protocol's `ops`; the answer then says why
    (`reason`) and on which day the restriction ends (`until_day`, the last restricted day)."""
    personal = [a for a in snap["alerts"] if not a.get("env")]
    if any(a["level"] == 2 for a in personal):
        key = "rest"
    elif any(a["id"] in LIMITING for a in personal):
        key = "limited"
    else:
        key = "full"
    out = {"key": key, **OPS[key]}
    w = care.active(snap["crew_id"], snap["day"]) if snap.get("day") is not None else None
    if w and care.LEVEL[w["ops"]] > 0:
        if care.LEVEL[w["ops"]] > OPS[key]["level"]:
            out = {"key": w["ops"], **OPS[w["ops"]]}
        if care.LEVEL[w["ops"]] >= out["level"]:
            out.update(reason=f"After Guided Response ({w['name']}) on day {w['day']}: {OPS[w['ops']]['label'].lower()} until day {w['until_day']}.",
                       until_day=w["until_day"], care={k: w[k] for k in ("protocol", "name", "ops", "day", "until_day")})
    return out


def alerts_to(crew_id: str) -> Optional[str]:
    """Id of who receives this person's alerts on board: the medical officer, or the substitute for the officer's own.
    With no medical officer on board, the substitute (the commander, else the first other person, else the person)."""
    mo = medical_officer()
    if mo is None:
        return next((c["id"] for c in CREW if c["id"] != crew_id and "commander" in c["role"].lower()),
                    next((c["id"] for c in CREW if c["id"] != crew_id), crew_id if crew_id in CREW_BY_ID else None))
    return substitute() if crew_id == mo else mo


def care_by(crew_id: str) -> str:
    """Who receives this person's alerts on board."""
    who = alerts_to(crew_id)
    if who is None:
        return "Nobody on board"
    c = CREW_BY_ID[who]
    mo = medical_officer()
    if mo is None:
        return f"{c['name']} (no medical officer on board)"
    return f"{c['name']} ({'substitute medical officer' if who == substitute() and who != mo else 'medical officer'})"


PHOTO_PREFIXES = ("data:image/jpeg;base64,", "data:image/png;base64,", "data:image/webp;base64,")


def photos() -> dict:
    return db.get_setting("photos", {})


def set_photo(crew_id: str, data_url: Optional[str]) -> None:
    if data_url is not None and not data_url.startswith(PHOTO_PREFIXES):
        raise ValueError("a photo must be a JPEG, PNG or WebP image")
    p = photos()
    if data_url is None:
        p.pop(crew_id, None)
    else:
        p[crew_id] = data_url
    db.set_setting("photos", p)


def can_see_details(viewer: Optional[str], crew_id: str, medical: bool) -> bool:
    return medical or viewer == crew_id


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
# The environment (E) is the one hazard still set per place: recycled air, noise and shared surfaces are not in the plan.
# Prototype assumption.
E_LEVEL = {"earth": 0, "rocket": 1, "iss": 1, "moon": 2, "transit": 1, "mars": 2, "moon_rover": 2, "mars_rover": 2}
# Cuts that turn the plan into a level (0 low, 1 moderate, 2 high). Prototype assumptions: no published rule maps these
# numbers to a level. They keep the old fixed table's levels for the reference mission and let time and place move them.
RIDGE_CUTS = {
    "source": "prototype assumption", "verified": False,
    "R": {"moderate_msv_day": 0.1, "high_msv_day": 1.0},                    # dose rate of the place; a storm away from Earth is high
    "I": {"moderate_until_day": 90, "large_crew": 6},                       # days since launch; a crew above `large_crew` is one level lower
    "D": {"high_delay_s": 60, "moderate_hospital_days": 2},                 # one-way delay; days to a hospital
    "G": {"readapt_days": 30},                                              # days after a change of gravity
    "hospital_days": {"earth": 0, "rocket": 0, "iss": 1, "moon": 3, "transit": 9999, "mars": 500,
                      "moon_rover": 3, "mars_rover": 500},  # read from the `hospital` text of each place
}
LEVEL_LABEL = ["Low", "Moderate", "High"]


def _since_change(day: int) -> Optional[int]:
    """Days since the crew changed gravity (0 g to partial, or back to 1 g), None before the first leg change."""
    legs = plan.get()["legs"]
    i = plan.leg_index(day)
    if i == 0:
        return None
    if LOCATIONS[legs[i]["location"]]["gravity_key"] == LOCATIONS[legs[i - 1]["location"]]["gravity_key"]:
        return None
    return day - legs[i]["start"]


def _here(hid: str, location: str) -> str:
    p = LOCATIONS[location]
    return {
        "R": f"{p['dose_rate']} mSv a day here",
        "I": "Training with family nearby" if location == "earth" else "Four people, no leave",
        "D": f"Earth replies {'live' if p['reply'] == 'Live' else 'in ' + p['reply']} · hospital: {p['hospital'].lower()}",
        "G": f"{p['gravity']} here",
        "E": "Open air" if location == "earth" else "Recycled air and constant noise",
    }[hid]


def _level(hid: str, location: str, storm: Optional[str], day: Optional[int]) -> tuple:
    """(level, basis) of one hazard, from the plan: the place, the mission day and the crew."""
    p, C = LOCATIONS[location], RIDGE_CUTS
    if hid == "R":
        c = C["R"]
        lv = 0 if p["dose_rate"] < c["moderate_msv_day"] else 1 if p["dose_rate"] < c["high_msv_day"] else 2
        if storm and location != "earth":
            return 2, f"a solar storm is in progress away from Earth's magnetic shield (dose {p['dose_rate']} mSv/day)"
        return lv, f"dose rate {p['dose_rate']} mSv/day (moderate from {c['moderate_msv_day']}, high from {c['high_msv_day']})"
    if hid == "I":
        c = C["I"]
        if location == "earth" or day is None or day < 0:
            return 0, "pre-flight, close to home" if location == "earth" else "no launch day to count from"
        lv = 1 if day <= c["moderate_until_day"] else 2
        if len(CREW) > c["large_crew"]:
            lv = max(0, lv - 1)
        return lv, f"day {day} since launch with {len(CREW)} people (high after day {c['moderate_until_day']})"
    if hid == "D":
        c = C["D"]
        hosp = C["hospital_days"][location]
        lv = 2 if p["delay_s"] >= c["high_delay_s"] else 1 if hosp >= c["moderate_hospital_days"] else 0
        return lv, f"Earth replies in {p['reply'].lower()}; hospital {p['hospital'].lower()}"
    if hid == "G":
        lv = {"g0": 2, "gp": 1, "g1": 0}[p["gravity_key"]]
        since = _since_change(day) if day is not None else None
        if since is not None and since < C["G"]["readapt_days"]:
            lv = max(lv, 2 if p["gravity_key"] == "gp" else 1)
            return lv, f"{p['gravity']}, day {since + 1} after the change of gravity (readapting for {C['G']['readapt_days']} days)"
        return lv, f"{p['gravity']} here"
    return E_LEVEL[location], "recycled air, noise and shared surfaces; set per place (assumption)"


def ridge(location: str, storm: Optional[str] = None, day: Optional[int] = None) -> list:
    """The five hazards for a place, computed from the mission plan (`day` is the mission day; without it only the
    place counts). Same shape as before, plus `basis` (why this level) and `assumption` (E is set per place)."""
    out = []
    for h in RIDGE:
        lv, basis = _level(h["id"], location, storm, day)
        out.append({**h, "level": lv, "label": LEVEL_LABEL[lv], "here": _here(h["id"], location), "basis": basis,
                    "assumption": h["id"] == "E", "system_names": [SYSTEMS[s]["name"] for s in h["systems"]]})
    return out
