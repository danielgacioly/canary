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


def all_cards(location: str) -> List[dict]:
    return system_cards() + protocol_cards(location)


def by_id(location: str) -> Dict[str, dict]:
    return {c["id"]: c for c in all_cards(location)}
