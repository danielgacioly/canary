"""The only knowledge the assistant may use. Small enough to fit in a cached prompt: no vector database."""
from typing import Dict, List

from ..domain import protocols
from ..domain.catalog import INDICATORS, SYSTEMS


def system_cards() -> List[dict]:
    return [{"id": f"card:{sid}", "kind": "system", "title": s["name"], "text": s["space"], "hazard": s["hazard"],
             "indicators": [INDICATORS[i]["name"] for i in s["indicators"]]} for sid, s in SYSTEMS.items()]


def protocol_cards(location: str) -> List[dict]:
    P = protocols.resolve(location)["protocols"]
    return [{"id": p["source"], "kind": "protocol", "title": p["name"], "text": p["sign"]} for p in P.values()]


RISK_CARDS = {
    "fatigue": "Adds up sleep, reaction time, mood, stress, time with the crew, the cognition tests and the wellbeing answers against the person's own normal. Level 2 needs several signals together.",
    "radiation": "Career dose against NASA's 600 mSv limit (NASA-STD-3001 V1 4030): the mission dose, the same for everyone on board and simulated, plus the person's earlier flights. Also the day the plan is projected to pass the limit, a storm in progress (NASA keeps a solar event below 250 mSv) and a low lymphocyte count.",
    "sans": "Wavy lines on the Amsler grid and vision symptoms. The Amsler grid is a weak indicator: a clear grid does not rule out eye changes.",
    "nutrition": "Weight against the person's pre-flight weight, and fasting glucose against their normal.",
    "renal": "Water intake, the model's bone-loss rate, and creatinine, calcium (real Inspiration4 values) and urine volume when an exam exists, against the laboratory range for the person's sex.",
    "immune": "Blood count outside the laboratory range for the person's sex (not counted when it was already outside before launch), C-reactive protein well above the person's pre-flight values, temperature and the days after a storm.",
    "cardio": "Pulse, blood pressure, oxygen and aerobic capacity against the person's normal, NASA's aerobic minimum for the EVAs done where the crew is (32.9 mL/kg/min in 0 g, 36.5 on a surface), potassium against its range, and the re-adaptation pattern after the change to partial gravity.",
    "bone_muscle": "Bone density estimate, grip strength and exercise minutes against the person's normal, with NASA's limits as a floor: bone at 95% and strength at 80% of the pre-flight values.",
}


def risk_cards() -> List[dict]:
    from ..domain.risk import SPECS
    names = {"fatigue": "Behavioural health and performance", **{k: v["name"] for k, v in SPECS.items()}}
    return [{"id": f"card:risk:{rid}", "kind": "risk", "title": names[rid], "text": text} for rid, text in RISK_CARDS.items()]


def hazard_cards() -> List[dict]:
    from ..domain.privacy import RIDGE
    return [{"id": f"card:hazard:{h['id']}", "kind": "hazard", "title": h["name"],
             "text": h["what"] + " Hazards are possible factors for a signal, never a proven cause."} for h in RIDGE]


def all_cards(location: str) -> List[dict]:
    return system_cards() + protocol_cards(location) + risk_cards() + hazard_cards()


def by_id(location: str) -> Dict[str, dict]:
    return {c["id"]: c for c in all_cards(location)}
