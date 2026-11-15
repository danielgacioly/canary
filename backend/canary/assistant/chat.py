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
            if a["physical"]["score"] is None and a["mental"]["score"] is None:
                claims.append({"text": "There is no data for this person yet, so there is no readiness to report.", "source_ids": src[:1]})
            else:
                part = lambda k: f"{a[k]['score']}/100 ({a[k]['status'].lower()})" if a[k]["score"] is not None else "no data yet"  # noqa: E731
                claims.append({"text": f"Physical readiness {part('physical')}, mental {part('mental')}.", "source_ids": src[:1]})
            for al in d["alerts"][:2]:
                claims.append({"text": f"{al['title']} First step: {al['todo'][0].lower()}.", "source_ids": src})
        elif r["tool"] == "get_indicator":
            if d["value"] is None:
                last = f" The last reading was on day {d['last_measured_day']}." if d.get("last_measured_day") is not None else ""
                claims.append({"text": f"There is no current reading of {d['name'].lower()}.{last}", "source_ids": src})
                continue
            if d["delta"] is None:
                claims.append({"text": f"{d['name']} is {_fmt(d['value'], d['dp'])} {d['unit']}. Canary is still learning your normal, "
                                       "so it can only compare this with the usual adult range.", "source_ids": src})
                continue
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
        elif r["tool"] == "get_risks":
            active = [k for k in d if k["level"]]
            if not active:
                claims.append({"text": "No risk is active at the moment.", "source_ids": src[:3] or src})
            for k in active:
                # Plain words, same facts: "Radiation is at the watch level and stable since day 109 (simulated data)."
                since = f" since day {k['since_day']}" if k["since_day"] is not None else ""
                data = {"real": "measured data", "partial": "part measured, part simulated", "simulated": "simulated data", "none": "no data yet"}[k["data"]]
                claims.append({"text": f"{k['name']} is at the {'watch' if k['level'] == 1 else 'act'} level and {k['trend']}{since} ({data}).",
                               "source_ids": src[:3] or src})
                if k["hazards"]:
                    claims.append({"text": k["hazard_note"], "source_ids": [s for s in src if s.startswith("card:hazard:")] or src[:3] or src})
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
