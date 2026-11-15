"""NASA-STD-3001: the third reference, next to the personal baseline and the population range.

Three references, three jobs:
  - personal baseline (health.baseline): "different from your own normal", the early warning;
  - population range (reference.py): "outside what is usual for an adult";
  - NASA-STD-3001 Volume 1 (this module): "past a limit NASA sets for crew health in flight".

Only the limits the app can actually check are here, each with the item of the standard it comes from. Every
number was read in NASA-STD-3001 Volume 1, Revision C (2023) on 2026-11-14 (`verified: True`). The early-warning
steps before each limit (level 1) are prototype assumptions and say so. A limit never lowers a level: the indicator
takes the highest of the three references.

What the standard sets and Canary cannot check is listed in `NOT_CHECKED`, so nobody reads silence as compliance.
"""
from typing import Optional

from .catalog import CREW_BY_ID, LOCATIONS, RECORDS

DOC = {"id": "nasa:std3001v1", "name": "NASA-STD-3001 Volume 1, Revision C (2023)",
       "url": "https://www.nasa.gov/wp-content/uploads/2023/11/nasa-std-3001-vol-1-rev-c-with-signature.pdf",
       "checked": "2026-11-14"}
EARLY = "prototype assumption: an early warning before the NASA limit"

LIMITS = {
    "vo2": {"items": ["V1 4001", "V1 4002"], "verified": True,
            "microgravity": 32.9, "surface": 36.5, "unit": "mL/kg/min",
            "text": "In-mission VO2max at or above 32.9 mL/kg/min for missions with microgravity EVAs (V1 4001) and "
                    "36.5 for missions with extraterrestrial surface EVAs (V1 4002)."},
    "grip": {"items": ["V1 4024"], "verified": True, "limit_pct": 80, "early_pct": 90, "early_source": EARLY,
             "text": "Countermeasures shall maintain in-mission skeletal muscle strength at or above 80% of baseline values (V1 4024). "
                     "Grip strength stands in for whole-body strength here."},
    "bone": {"items": ["V1 4027"], "verified": True, "limit_loss_pct": 5.0, "early_loss_pct": 3.0, "early_source": EARLY,
             "text": "Bone mineral density of the hip and spine at or above 95% of pre-mission values, and the femoral neck at or "
                     "above 90% (V1 4027). Canary's bone row is an estimate of weight-bearing bone, held to the 95% line."},
}
RADIATION = {"items": ["V1 4029", "V1 4030", "V1 4031"], "verified": True, "career_msv": 600, "spe_msv": 250,
             "text": "Career effective dose below 600 mSv, the same for all ages and sexes, counting every earlier flight (V1 4030); "
                     "the design solar particle event below 250 mSv (V1 4031); every exposure as low as reasonably achievable (V1 4029)."}
SLEEP = {"items": ["V1 6001"], "verified": True,
         "text": "Crew schedules include a recommended 8.5 h sleep period (plus 2 h before and 1.5 h after) and avoid critical "
                 "tasks during the circadian low, typically 1 to 7 AM of one's own sleep schedule (V1 6001)."}
NOT_CHECKED = [
    {"items": ["V1 4015", "V1 4016", "V1 4017"], "why": "Blood and immunity within the normal range of the healthy population, away from "
     "critical values: Canary reads the blood count against the laboratory's own ranges (population layer), not a NASA number."},
    {"items": ["V1 4020"], "why": "100% of each person's calculated energy and nutrient needs: Canary has no food log yet."},
    {"items": ["Table 4.8-1"], "why": "Organ dose limits (blood-forming organs, heart, lens, brain) are in mGy-Eq, an organ dose; "
     "Canary only has an effective dose in mSv, which cannot be compared with them."},
]
# Prior career dose when a record gives none: days already flown at the station's daily dose. An estimate, labelled so.
PRIOR_DOSE_SOURCE = "estimate: days already in space x the station's daily dose in the catalog (to verify against the person's dosimetry)"


def eva_role(crew_id: str) -> str:
    """'surface', 'microgravity' or 'none'. Unknown means 'surface': the stricter limit, on purpose."""
    return (RECORDS.get(crew_id) or {}).get("eva") or "surface"


def prior_dose_of(r: dict) -> dict:
    """Career dose before this mission (mSv) of one personal record: its own number, or an estimate from the days in space."""
    if r.get("prior_dose_msv") is not None:
        return {"msv": float(r["prior_dose_msv"]), "estimate": False, "source": "personal record"}
    days = float(r.get("days_in_space") or 0)
    return {"msv": round(days * LOCATIONS["iss"]["dose_rate"], 1), "estimate": True, "source": PRIOR_DOSE_SOURCE}


def prior_dose(crew_id: str) -> dict:
    """Career dose before this mission (mSv): the record's own number, or an estimate from the days already in space."""
    return prior_dose_of(RECORDS.get(crew_id) or {})


def _out(level: int, limit_text: str, item: str, early: bool = False) -> dict:
    return {"level": level, "status": "limit" if level == 2 else "near" if level == 1 else "in", "text": limit_text,
            "item": item, "source": EARLY if early else DOC["name"], "url": DOC["url"], "verified": not early}


def check(ind: str, crew_id: str, location: str, value: Optional[float], baseline: Optional[float]) -> Optional[dict]:
    """The NASA limit for one indicator today: {"level", "status" (in / near / limit), "text", "item", "source", "url",
    "verified"}, or None when the standard sets no number Canary can check for it."""
    if value is None:  # no current reading: nothing to hold against a limit
        return None
    if ind == "vo2":
        role, place = eva_role(crew_id), LOCATIONS[location].get("eva", "none")
        if role == "none" or place == "none":
            return None
        L = LIMITS["vo2"]
        need = L["surface"] if place == "surface" else L["microgravity"]
        if value < need:
            return _out(2, f"VO2max {value:.1f} is below {need} mL/kg/min, the minimum for {place} EVAs",
                        "V1 4002" if place == "surface" else "V1 4001")
        if place == "microgravity" and role == "surface" and value < L["surface"]:
            return _out(1, f"VO2max {value:.1f} is enough for microgravity EVAs but below {L['surface']} mL/kg/min, "
                           "the minimum for surface EVAs ahead", "V1 4002")
        return _out(0, f"VO2max {value:.1f} meets the {need} mL/kg/min minimum for {place} EVAs",
                    "V1 4002" if place == "surface" else "V1 4001")
    if ind == "grip" and baseline:
        L, pct = LIMITS["grip"], 100 * value / baseline
        if pct < L["limit_pct"]:
            return _out(2, f"Strength at {pct:.0f}% of your pre-flight value, below NASA's 80%", "V1 4024")
        if pct < L["early_pct"]:
            return _out(1, f"Strength at {pct:.0f}% of your pre-flight value, close to NASA's 80%", "V1 4024", early=True)
        return _out(0, f"Strength at {pct:.0f}% of your pre-flight value (NASA keeps it at 80% or more)", "V1 4024")
    if ind == "bone":
        L, loss = LIMITS["bone"], -value  # the bone row is the % change since launch
        if loss >= L["limit_loss_pct"]:
            return _out(2, f"Estimated bone density {100 - loss:.1f}% of pre-flight, below NASA's 95%", "V1 4027")
        if loss >= L["early_loss_pct"]:
            return _out(1, f"Estimated bone density {100 - loss:.1f}% of pre-flight, approaching NASA's 95%", "V1 4027", early=True)
        return _out(0, f"Estimated bone density {100 - loss:.1f}% of pre-flight (NASA keeps it at 95% or more)", "V1 4027")
    return None


def summary() -> dict:
    """What the app checks against the standard and what it does not, for the API and the README."""
    return {"document": DOC, "checked": {**LIMITS, "radiation": RADIATION, "sleep": SLEEP}, "not_checked": NOT_CHECKED}


def crew_profile(crew_id: str) -> dict:
    c = CREW_BY_ID[crew_id]
    return {"eva": eva_role(crew_id), "prior_dose": prior_dose(crew_id), "sex": c.get("sex")}
