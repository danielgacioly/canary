"""Entry 1: an astronaut asks a question in plain language.

Flow: guard.precheck -> tools (chosen by the model, or by tools.route without one)
-> provider -> guard.validate_claims -> log. Without a provider the answer is
built from the tool results only, so it is grounded but plain.
"""
import json
import time
from typing import List

from .. import db
from ..domain import mission
from . import guard, knowledge, tools
from .providers import ProviderRequest, get_provider

SYSTEM_PROMPT = (
    "You are Canary, the health assistant on board a crewed spacecraft. Answer only from the tool results and "
    "knowledge cards provided. Cite the source ids for every claim. Never diagnose, never suggest medication or "
    "doses. If the data does not answer the question, say you don't know and suggest calling the crew medical "
    "officer. Be short, calm and concrete. Reply as JSON: {answer, claims:[{text, source_ids}]}."
)

UNKNOWN = ("I don't know that from the data on board. The crew medical officer can help, "
           "and I can prepare a message for the flight surgeon.")


def _fmt(v: float, dp: int) -> str:
    return f"{v:.{dp}f}"


def _grounded(results: List[dict]) -> List[dict]:
    """Rule-based sentences from tool results. Every sentence cites what it used."""
    claims = []
    for r in results:
        d, src = r["result"]["data"], r["result"]["sources"]
        if r["tool"] == "get_status":
            a = d["areas"]
            claims.append({"text": f"Physical readiness {a['physical']['score']}/100 ({a['physical']['status'].lower()}), "
                                   f"mental {a['mental']['score']}/100 ({a['mental']['status'].lower()}).", "source_ids": src[:1]})
            for al in d["alerts"][:2]:
                claims.append({"text": f"{al['title']} First step: {al['todo'][0].lower()}.", "source_ids": src})
        elif r["tool"] == "get_indicator":
            sign = "above" if d["delta"] > 0 else "below"
            claims.append({"text": f"{d['name']} is {_fmt(d['value'], d['dp'])} {d['unit']}, "
                                   f"{_fmt(abs(d['delta']), d['dp'])} {d['unit']} {sign} your normal of {_fmt(d['baseline'], d['dp'])}. "
                                   + ("That is within your usual range." if d["level"] == 0 else
                                      "That is outside your usual range." if d["level"] == 2 else "Worth watching."),
                           "source_ids": src})
        elif r["tool"] == "explain_system":
            claims.append({"text": f"{d['system']}: {d['space']}", "source_ids": src[:1]})
            if d["note"]:
                claims.append({"text": d["note"], "source_ids": src[:1]})
        elif r["tool"] == "get_protocol":
            claims.append({"text": f"For {d['name'].lower()}, Guided Response starts with: {d['first_step']} "
                                   "In a real emergency, hold the EMERGENCY button.", "source_ids": src})
        elif r["tool"] == "list_goals":
            left = [g["title"] for g in d if not g["done"]][:3]
            if left:
                claims.append({"text": "Still open today: " + "; ".join(left) + ".", "source_ids": src})
    return claims


def ask(crew_id: str, question: str) -> dict:
    question = question.strip()[:500]
    provider = get_provider()
    pre = guard.precheck(question)
    if pre:
        resp = {**pre, "provider": provider.name, "claims": [], "sources": [], "tools_used": [], "dropped": 0}
        return _log(crew_id, question, resp)

    results = tools.route(crew_id, question)
    allowed = [s for r in results for s in r["result"]["sources"]] + [c["id"] for c in knowledge.all_cards(mission.state()["location"])]
    req = ProviderRequest(task="chat", system=SYSTEM_PROMPT, question=question,
                          context=[{"tool": r["tool"], "args": r["args"], **r["result"]} for r in results],
                          knowledge=knowledge.all_cards(mission.state()["location"]))
    out = provider.complete(req)
    if out.ok:
        claims, dropped = guard.validate_claims(out.claims, allowed)
        mode, answer = ("ai", out.answer) if claims else ("unknown", UNKNOWN)
    else:
        claims, dropped = _grounded(results), 0
        mode = "grounded" if claims else "unknown"
        answer = " ".join(c["text"] for c in claims) if claims else UNKNOWN
    used = sorted({s for c in claims for s in c["source_ids"]})
    resp = {"mode": mode, "provider": provider.name, "provider_error": out.error, "answer": answer, "claims": claims,
            "sources": used, "tools_used": [{"tool": r["tool"], "args": r["args"]} for r in results], "dropped": dropped}
    return _log(crew_id, question, resp)


def _log(crew_id: str, question: str, resp: dict) -> dict:
    resp["id"] = db.x("INSERT INTO assistant_log(crew_id,question,response,created_at) VALUES(?,?,?,?)",
                      (crew_id, question, json.dumps(resp), time.time()))
    return resp


def history(crew_id: str, limit: int = 20) -> List[dict]:
    rows = db.q("SELECT id,question,response,created_at FROM assistant_log WHERE crew_id=? ORDER BY id DESC LIMIT ?", (crew_id, limit))
    return [{"id": r["id"], "question": r["question"], "created_at": r["created_at"], **json.loads(r["response"])} for r in rows][::-1]
