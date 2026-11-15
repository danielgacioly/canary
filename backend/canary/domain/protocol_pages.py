"""The Protocols page: every protocol as a reference page, and which of them are in force now.

Crew-wide and public: it carries the place, the storm, the dose of the mission and the rules, never anyone's health.
The one exception is the care window, which is listed only for the medical team (a count, never a name), because
being inside a window says that person had an emergency.

Emergency protocols come from data/protocols.json (their steps start in Guided Response). Operational protocols
(`operational` in the same file) are reference pages for what Canary does around them: EVA, dose, the care window,
space sickness, return to gravity, the closed environment, signal delay. Where Canary has a rule for something (an alert,
a NASA-STD-3001 limit) the page repeats it; the rest is illustrative and says so.
"""
from typing import List, Optional

from . import care, plan, protocols, standards
from .catalog import CREW, LOCATIONS
from .privacy import E_LEVEL

LIVE_TITLES = {"rad": "Radiation storm"}
READAPT_DAYS = 30  # privacy.RIDGE_CUTS["G"]["readapt_days"]


def _standard(p: Optional[dict]) -> Optional[dict]:
    if not p:
        return None
    return {"text": p["text"], "items": p["items"], "name": standards.DOC["name"], "url": standards.DOC["url"], "checked": standards.DOC["checked"]}


def _emergency(pid: str, place: str) -> dict:
    raw = protocols.bank()["protocols"][pid]
    res = protocols.resolve(place)["protocols"][pid]
    return {"id": pid, "kind": "emergency", "name": raw["n"], "sign": raw["s"], "audience": "everyone", "guided": True,
            "when": raw.get("when") or [raw["s"] + "."],
            "steps": [{"t": s.get("t"), "variant": s.get("variant"), "q": s.get("q")} for s in res["steps"] if s.get("t") or s.get("q")],
            "watch": raw.get("watch") or raw["after"], "kit": raw["kit"],
            "window_days": res["window_days"], "ops": res["ops"],
            "standard": _standard(raw.get("standard")), "links": raw.get("links", []),
            "source": "Illustrative first aid adapted to spaceflight, not clinically reviewed"}


def _operational(pid: str) -> dict:
    raw = protocols.bank()["operational"]["protocols"][pid]
    return {"id": pid, "kind": "operational", "name": raw["n"], "sign": None, "audience": raw.get("audience", "everyone"), "guided": False,
            "when": raw["when"], "steps": [{"t": t, "variant": None, "q": None} for t in raw["steps"]], "watch": raw["watch"],
            "kit": [], "window_days": 0, "ops": None, "standard": _standard(raw.get("standard")), "links": raw.get("links", []),
            "source": "Illustrative: built from what Canary already does, not clinically reviewed" if raw.get("illustrative") else None}


def in_force(ms: dict, dose: dict, medical: bool = False) -> List[dict]:
    """The protocols that apply to the crew today, each with the reason in plain words. `level` colours the dot (2 act, 1 watch, 0 on)."""
    loc, day = ms["location"], ms["day"]
    place = LOCATIONS[loc]
    out: List[dict] = []
    if ms["learning"]:
        return out
    if ms["storm"]:
        mars = ms["storm"] == "mars"
        out.append({"id": "rad", "level": 2, "reason": "Radiation is far above normal on the surface. Everyone stays inside." if mars
                    else "A solar particle storm is hitting. Everyone goes to the shelter until the alert ends."})
    if loc != "earth":
        if ms["storm"]:
            out.append({"id": "eva", "level": 2, "reason": "EVA is suspended for everyone while the storm lasts."})
        elif place.get("eva", "none") == "none":
            out.append({"id": "eva", "level": 1, "reason": f"No EVA at this place ({place['name']})."})
        else:
            out.append({"id": "eva", "level": 0, "reason": "EVA is open. The medical team clears each person."})
        out.append({"id": "dose", "level": 0, "reason": f"Mission dose {dose['mission_msv']} mSv, {dose['pct_of_limit']}% of the career limit. Background {place['dose_rate']} mSv a day here."})
    if loc == "rocket":
        out.append({"id": "sickness", "level": 1, "reason": "First hours in 0 g: space sickness is common and usually passes in 2 to 3 days."})
    since = plan.days_since_gravity_change(day)
    if since is not None and since < READAPT_DAYS:
        out.append({"id": "regravity", "level": 1, "reason": f"Day {since + 1} in {place['gravity']} after months in 0 g. The body is relearning weight."})
    if E_LEVEL.get(loc, 0) >= 2:
        out.append({"id": "air", "level": 1, "reason": "Sealed habitat with recycled air and constant noise."})
    if place["delay_s"] > 60:
        out.append({"id": "delay", "level": 1, "reason": f"Earth replies in {place['reply']}. The crew handles emergencies on its own."})
    if medical:
        n = sum(1 for c in CREW if care.active(c["id"], day))
        if n:
            out.append({"id": "care", "level": 1, "reason": f"{n} care {'window is' if n == 1 else 'windows are'} open. Details are in the medical console.", "audience": "medical team"})
    return out


def live(pid: str, ms: dict, dose: dict) -> List[str]:
    """Lines about now that belong to a page (shown above its steps): facts of the place, the same for everyone."""
    place = LOCATIONS[ms["location"]]
    if pid == "rad":
        v = protocols.resolve(ms["location"])["protocols"]["rad"]["steps"][0]["variant"]
        return [v] if v else []
    if pid == "dose":
        return [f"Mission dose {dose['mission_msv']} mSv, {dose['pct_of_limit']}% of the {dose['career_limit_msv']} mSv career limit.",
                f"Background dose here: {place['dose_rate']} mSv a day."]
    if pid == "delay":
        return [f"Earth replies in {place['reply'].lower()} each way." if place["delay_s"] else "Earth replies live here."]
    if pid == "care":
        c = care.sensitivity()
        return [f"Alert thresholds are {round(100 * (1 - c['factor']))}% tighter during a window ({c['source']})."]
    return []


def library(ms: dict, dose: dict, medical: bool = False) -> dict:
    place = ms["location"]
    forced = in_force(ms, dose, medical)
    emergency = [_emergency(p, place) for p in protocols.order() if p != "triage"]
    operational = [_operational(p) for p in protocols.bank()["operational"]["order"]]
    for p in emergency + operational:
        p["live"] = live(p["id"], ms, dose)
    care_table = [{"id": p["id"], "name": p["name"], "window_days": p["window_days"], "ops": p["ops"]} for p in emergency if p["window_days"]]
    return {"in_force": forced, "emergency": emergency, "operational": operational, "care_table": care_table,
            "place": {"id": place, "name": LOCATIONS[place]["name"]}, "reviewed": False,
            "note": protocols.bank()["operational"]["note"]}


def page_for(protocol_id: Optional[str]) -> Optional[str]:
    """The Protocols page that answers a protocol id (all ids are page ids today)."""
    return protocol_id
