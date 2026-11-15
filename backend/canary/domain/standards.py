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

from . import assumptions as A
from .catalog import CREW_BY_ID, LOCATIONS, RECORDS

DOC = {"id": "nasa:std3001v1", "name": "NASA-STD-3001 Volume 1, Revision C (2023)",
       "url": "https://www.nasa.gov/wp-content/uploads/2023/11/nasa-std-3001-vol-1-rev-c-with-signature.pdf",
       "checked": "2026-11-14"}
EARLY = "prototype assumption: an early warning before the NASA limit"
NOT_ASSESSABLE = "no pre-flight baseline: a percent-of-baseline limit is never computed against an in-flight value"

LIMITS = {
    "vo2": {"items": ["V1 4001", "V1 4002"], "verified": True,
            "microgravity": A.value("nasa.vo2_microgravity"), "surface": A.value("nasa.vo2_surface"), "unit": "mL/kg/min",
            "text": "In-mission VO2max at or above 32.9 mL/kg/min for missions with microgravity EVAs (V1 4001) and "
                    "36.5 for missions with extraterrestrial surface EVAs (V1 4002)."},
    "grip": {"items": ["V1 4024"], "verified": True, "limit_pct": A.value("nasa.grip_limit_pct"), "early_pct": A.value("early.grip_pct"), "early_source": EARLY,
             "text": "Countermeasures shall maintain in-mission skeletal muscle strength at or above 80% of baseline values (V1 4024). "
                     "Grip strength stands in for whole-body strength here."},
    "bone": {"items": ["V1 4027"], "verified": True, "limit_pct": A.value("nasa.bone_limit_pct"), "limit_loss_pct": 100 - A.value("nasa.bone_limit_pct"),
             "early_loss_pct": A.value("early.bone_loss_pct"), "early_source": EARLY,
             "text": "Bone mineral density of the hip and spine at or above 95% of pre-mission values, and the femoral neck at or "
                     "above 90% (V1 4027). Bone density is measured by DXA before launch and after landing, never on board: the "
                     "limit is read against the pre-flight scan only. In flight Canary shows an estimate (exercise and time in "
                     "microgravity), labelled as one, and applies no limit to it."},
}
RADIATION = {"items": ["V1 4029", "V1 4030", "V1 4031"], "verified": True,
             "career_msv": A.value("nasa.career_effective_dose_msv"), "spe_msv": A.value("nasa.spe_design_effective_dose_msv"),
             "text": "Career effective dose below 600 mSv, the same for all ages and sexes, counting every earlier flight (NASA-STD-3001 Vol 1, 4.2.10 [V1 4030]); "
                     "the design reference solar particle event below 250 mSv effective dose (V1 4031), a vehicle and shielding design requirement, "
                     "so it is compared with an event's estimated dose and is not a personal limit; every exposure as low as reasonably achievable (V1 4029). "
                     "Organ short-term limits (30-day and 1-year, lens, skin, blood-forming organs, heart, central nervous system) could not be verified "
                     "and Canary applies none: it tracks the 30-day and 365-day dose totals and labels them 'tracked, no limit applied by Canary'.",
             "tracked_no_limit": "tracked, no limit applied by Canary",
             "model": A.value("dose.model_note")}
SLEEP = {"items": ["V1 6001"], "verified": True,
         "text": "Crew schedules include a recommended 8.5 h sleep period (plus 2 h before and 1.5 h after) and avoid critical "
                 "tasks during the circadian low, typically 1 to 7 AM of one's own sleep schedule (V1 6001)."}
NOT_CHECKED = [
    {"items": ["V1 4015", "V1 4016", "V1 4017"], "why": "Blood and immunity within the normal range of the healthy population, away from "
     "critical values: Canary reads the blood count against the laboratory's own ranges (population layer), not a NASA number."},
    {"items": ["V1 4020"], "why": "100% of each person's calculated energy and nutrient needs: Canary has no food log yet."},
    {"items": ["Table 4.8-1"], "why": "Organ dose limits (blood-forming organs, heart, lens, brain) are organ doses and their numbers "
     "could not be verified here; Canary only has an effective-dose estimate in mSv and applies none of them. The 30-day and 365-day totals are tracked only."},
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
    if ind in ("grip", "bone") and not baseline:  # no pre-flight baseline: never fall back to an in-flight one
        L = LIMITS[ind]
        return {"level": 0, "status": "not_assessable", "text": f"{ind.capitalize()} limit not assessable: {NOT_ASSESSABLE}",
                "item": L["items"][0], "source": DOC["name"], "url": DOC["url"], "verified": True}
    if ind == "grip":
        L, pct = LIMITS["grip"], 100 * value / baseline
        if pct < L["limit_pct"]:
            return _out(2, f"Strength at {pct:.0f}% of your pre-flight value, below NASA's 80%", "V1 4024")
        if pct < L["early_pct"]:
            return _out(1, f"Strength at {pct:.0f}% of your pre-flight value, close to NASA's 80%", "V1 4024", early=True)
        return _out(0, f"Strength at {pct:.0f}% of your pre-flight value (NASA keeps it at 80% or more)", "V1 4024")
    if ind == "bone":
        L = LIMITS["bone"]
        pct = 100 * value / baseline  # the scan against the pre-flight scan
        loss = 100 - pct
        if loss >= L["limit_loss_pct"]:
            return _out(2, f"Bone density {pct:.1f}% of the pre-flight scan, below NASA's 95%", "V1 4027")
        if loss >= L["early_loss_pct"]:
            return _out(1, f"Bone density {pct:.1f}% of the pre-flight scan, approaching NASA's 95%", "V1 4027", early=True)
        return _out(0, f"Bone density {pct:.1f}% of the pre-flight scan (NASA keeps it at 95% or more)", "V1 4027")
    return None


def summary() -> dict:
    """What the app checks against the standard and what it does not, for the API and the README."""
    return {"document": DOC, "checked": {**LIMITS, "radiation": RADIATION, "sleep": SLEEP}, "not_checked": NOT_CHECKED}


def crew_profile(crew_id: str) -> dict:
    c = CREW_BY_ID[crew_id]
    return {"eva": eva_role(crew_id), "prior_dose": prior_dose(crew_id), "sex": c.get("sex")}
