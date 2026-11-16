"""Assessment state, kept apart from severity.

Severity (`level`: 0 on track, 1 watch, 2 act) says how far a measured value is from the person's own normal or a NASA
limit. Assessment says whether there was anything to assess at all:

  - assessed:          a current reading is held against a reference (own normal, population range or NASA limit);
  - insufficient_data: nothing current, and no earlier reading either (never measured, or not yet enough to learn from);
  - stale_data:        nothing current, but an earlier reading exists (its age is in `last_measured_day`);
  - not_applicable:    the measure is not taken on board by design (a DXA bone scan in flight: the estimate is labelled).

A system, an area or a person is assessed when at least one of its indicators is. Otherwise it is stale if any of them
is stale, not applicable if all of them are, and insufficient data in every other case. A level of 0 with a state other
than assessed is never a normal look: the screens show "No data" or "Stale" instead.

`limits()` is the one place the read route takes the NASA limits, units and sources from for the screens.
"""
from typing import Iterable

from . import standards
from .catalog import INDICATORS

ASSESSED = "assessed"
INSUFFICIENT = "insufficient_data"
STALE = "stale_data"
NOT_APPLICABLE = "not_applicable"
STATES = (ASSESSED, INSUFFICIENT, STALE, NOT_APPLICABLE)


def indicator_state(i: dict) -> str:
    """The assessment state of one indicator as health.indicator() returns it."""
    if i.get("value") is not None and i.get("status") != "no_data":
        return ASSESSED
    if i.get("scan") and i.get("estimate") is not None:  # a scan that cannot be taken on board: an estimate, never assessed
        return NOT_APPLICABLE
    if i.get("last_measured_day") is not None:  # an earlier reading exists but is no longer current
        return STALE
    return INSUFFICIENT


def group_state(states: Iterable[str]) -> str:
    """The state of a system, an area or a person from the states of the indicators (or groups) it holds."""
    s = list(states)
    if not s:
        return INSUFFICIENT
    if ASSESSED in s:
        return ASSESSED
    if STALE in s:
        return STALE
    if all(x == NOT_APPLICABLE for x in s):
        return NOT_APPLICABLE
    return INSUFFICIENT


def annotate(snap: dict) -> dict:
    """Add `assessment` to every indicator, system, area and to the person as a whole (in place, and returned)."""
    inds = snap.get("indicators", {})
    for i in inds.values():
        i["assessment"] = indicator_state(i)
    systems = snap.get("systems", {})
    for s in systems.values():
        s["assessment"] = group_state(inds[k]["assessment"] for k in s.get("indicators", []) if k in inds)
    for area, a in snap.get("areas", {}).items():
        a["assessment"] = group_state([s["assessment"] for s in systems.values() if s.get("area") == area]
                                      + [i["assessment"] for i in inds.values() if i.get("area") == area])
    snap["assessment"] = group_state(i["assessment"] for i in inds.values())
    return snap


def limits() -> dict:
    """NASA-STD-3001 limits, early-warning steps, units and sources for the screens (served by GET /api/catalog)."""
    L, R = standards.LIMITS, standards.RADIATION
    return {
        "document": standards.DOC,
        "vo2": {"unit": "mL/kg/min", "items": {"microgravity": "V1 4001", "surface": "V1 4002"}, "microgravity": L["vo2"]["microgravity"],
                "surface": L["vo2"]["surface"], "verified": L["vo2"]["verified"], "text": L["vo2"]["text"]},
        "grip": {"unit": "%", "of": "pre-flight", "items": L["grip"]["items"], "limit_pct": L["grip"]["limit_pct"],
                 "early_pct": L["grip"]["early_pct"], "early_source": L["grip"]["early_source"], "verified": L["grip"]["verified"], "text": L["grip"]["text"]},
        "bone": {"unit": "%", "of": "pre-flight", "items": L["bone"]["items"], "limit_pct": L["bone"]["limit_pct"],
                 "limit_loss_pct": L["bone"]["limit_loss_pct"], "early_loss_pct": L["bone"]["early_loss_pct"],
                 "early_source": L["bone"]["early_source"], "verified": L["bone"]["verified"], "text": L["bone"]["text"]},
        "radiation": {"unit": "mSv", "items": R["items"], "career_msv": R["career_msv"], "spe_msv": R["spe_msv"],
                      "tracked_no_limit": R["tracked_no_limit"], "verified": R["verified"], "text": R["text"]},
        "units": {k: {"unit": v["unit"], "dp": v["dp"]} for k, v in INDICATORS.items()},
    }
