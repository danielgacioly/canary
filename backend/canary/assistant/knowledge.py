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
    "radiation": "Mission dose against the 600 mSv career limit (the same dose for everyone on board, simulated), the day the plan is projected to pass it, a storm in progress and a low lymphocyte count.",
    "sans": "Wavy lines on the Amsler grid and vision symptoms. The Amsler grid is a weak indicator: a clear grid does not rule out eye changes.",
    "nutrition": "Weight against the person's pre-flight weight, and fasting glucose against their normal.",
    "renal": "Water intake, the model's bone-loss rate, and creatinine and urine volume when an exam exists.",
    "immune": "Blood count outside its reference range (not counted when it was already outside before launch), temperature and the days after a storm.",
    "cardio": "Pulse, blood pressure and oxygen against the person's normal, including the re-adaptation pattern after the change to partial gravity.",
    "bone_muscle": "Bone density estimate, grip strength and exercise minutes against the person's normal.",
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
