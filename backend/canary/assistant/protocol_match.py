"""Entry 4 of the AI slot: from what a person says they see to the closest protocols.

Rules decide (domain/protocol_match.py) and are always the default. A connected model may only re-order the protocols the rules
found, or add one the rules missed, by id from the protocol bank: it cannot write text, steps or advice, and the person
always starts the protocol themselves. If the provider fails, answers anything else, or names an unknown id, the rules stand.
Emergencies never wait for a model: with no provider (the default) this is the rule matcher and nothing else.
"""
import json

from ..domain import protocol_match, protocols
from .providers import ProviderRequest, get_provider


def match(text: str) -> dict:
    res = protocol_match.match(text)
    provider = get_provider()
    mode = "rules"
    out = provider.complete(ProviderRequest(
        task="protocol_match",
        system="Name the protocol ids, best first, that fit what the person describes. Only ids from the list. No advice.",
        question=text[:500],
        context=[{"protocols": [{"id": p, "name": protocols.name(p)} for p in protocols.order() if p != "triage"], "rules": res["matches"]}]))
    if out.ok and out.answer:
        try:
            ids = [i for i in json.loads(out.answer) if isinstance(i, str) and i in protocols.bank()["protocols"] and i != "triage"][:protocol_match.LIMIT]
            if ids:
                by = {m["id"]: m for m in res["matches"]}
                bank = protocols.bank()["protocols"]
                res = {"matches": [by.get(i) or {"id": i, "name": bank[i]["n"], "sign": bank[i]["s"], "score": 0, "matched": []} for i in ids],
                       "fallback": None}
                mode = "ai"
        except (ValueError, TypeError):
            pass
    return {"mode": mode, "provider": provider.name, **res}
