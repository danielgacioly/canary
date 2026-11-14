"""Safety rules around the assistant. They run with or without a model.

1. Emergencies go to Guided Response, never to a chat answer.
2. No diagnosis and no medication doses: those belong to the medical officer.
3. A claim survives only if it cites sources returned by tools in the same turn.
4. In a briefing, every number in the text must exist in the computed facts.
"""
import re
from typing import Iterable, List, Optional, Tuple

_EMERGENCY = re.compile(r"\b(seizure|convuls\w*|not breathing|unconscious|passed out|choking|can'?t breathe|heavy bleeding|"
                        r"chest pain (now|right now)|having a heart attack|anaphyla\w*|hurt (myself|himself|herself)|suicid\w*)\b", re.I)
_DIAGNOSIS = re.compile(r"\b(do i have|have i got|is (it|this) (cancer|a tumou?r|a stroke|serious)|diagnos\w*|what disease|what illness)\b", re.I)
_DOSING = re.compile(r"\b(\d+\s?mg|dose|dosage|how many (pills|tablets)|should i take|which (medication|medicine|drug|pill))\b", re.I)


def precheck(question: str) -> Optional[dict]:
    if _EMERGENCY.search(question):
        return {"mode": "emergency", "answer": "This sounds like an emergency. Hold the EMERGENCY button now: Guided Response "
                                               "will take you through it step by step and alert the crew and Earth."}
    if _DOSING.search(question):
        return {"mode": "refused", "answer": "I can't advise on medication or doses. The crew medical officer decides that, "
                                             "with the flight surgeon. I can send them a message with your recent data."}
    if _DIAGNOSIS.search(question):
        return {"mode": "refused", "answer": "I can't diagnose. I can show what your numbers did against your own normal, "
                                             "and the medical officer can take it from there."}
    return None


def validate_claims(claims: Iterable[dict], allowed: Iterable[str]) -> Tuple[List[dict], int]:
    allowed = set(allowed)
    kept, dropped = [], 0
    for c in claims:
        ids = [s for s in c.get("source_ids", []) if s in allowed]
        if ids and len(ids) == len(c.get("source_ids", [])):
            kept.append({"text": c["text"], "source_ids": ids})
        else:
            dropped += 1
    return kept, dropped


_NUM = re.compile(r"-?\d+(?:\.\d+)?")


def unknown_numbers(text: str, facts_blob: str) -> List[str]:
    """Numbers in `text` that do not appear in the facts (a briefing must not invent numbers)."""
    have = set(_NUM.findall(facts_blob))
    return [n for n in _NUM.findall(text) if n not in have]
