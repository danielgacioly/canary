"""Read-only tools the assistant may call. Each result says where every fact came from.

`TOOLS` doubles as the function-calling schema a provider can hand to a model.
`route` is the deterministic stand-in for the model's tool choice, used when
no provider is connected.
"""
import re
from typing import Callable, Dict, List

from ..domain import goals, health, mission, protocols, telemetry
from ..domain.catalog import INDICATORS, SYSTEMS


def _ms() -> dict:
    return mission.state()


def get_status(crew_id: str) -> dict:
    ms = _ms()
    s = health.snapshot(crew_id, ms)
    return {"data": {"areas": s["areas"], "alerts": [{"title": a["title"], "level": a["level"], "todo": a["todo"]} for a in s["alerts"][:3]]},
            "sources": [src for a in s["alerts"][:3] for src in a.get("sources", [])] or [f"status:{crew_id}:day{ms['day']}"]}


def get_indicator(crew_id: str, ind: str) -> dict:
    ms = _ms()
    d = health.indicator(crew_id, ind, ms)
    trend = telemetry.series(crew_id, ind, ms["day"], 14)
    return {"data": {**d, "trend_14d": trend}, "sources": [d["source"]]}


def explain_system(crew_id: str, sys: str) -> dict:
    ms = _ms()
    snap = health.snapshot(crew_id, ms)
    S = SYSTEMS[sys]
    inds = [snap["indicators"][i] for i in S["indicators"]]
    return {"data": {"system": S["name"], "status": snap["systems"][sys]["status"], "note": snap["systems"][sys]["note"],
                     "space": S["space"], "indicators": inds},
            "sources": [f"card:{sys}"] + [i["source"] for i in inds]}


def get_risks(crew_id: str) -> dict:
    """Each risk with its level, trend, the day it started and the evidence behind it. Read-only; the rules decide, not a model."""
    ms = _ms()
    risks = health.snapshot(crew_id, ms)["risks"]
    srcs = [e["source"] for r in risks for e in r["evidence"]]
    return {"data": risks, "sources": list(dict.fromkeys(srcs)) or [f"risk:{crew_id}:day{ms['day']}"]}


def get_protocol(pid: str) -> dict:
    p = protocols.resolve(_ms()["location"])["protocols"][pid]
    return {"data": {"name": p["name"], "sign": p["sign"], "kit": p["kit"], "first_step": p["steps"][0].get("t") or p["steps"][0].get("q")},
            "sources": [p["source"]]}


def list_goals(crew_id: str) -> dict:
    ms = _ms()
    g = goals.personal_today(crew_id, ms)
    return {"data": [{"title": x["title"], "area": x["area"], "done": x["done"], "by": x["by"]} for x in g],
            "sources": [f"goals:{crew_id}:day{ms['day']}"]}


TOOLS: Dict[str, dict] = {
    "get_status": {"fn": get_status, "description": "Physical and mental readiness and the top alerts for a crew member.",
                   "params": {"crew_id": "string"}},
    "get_indicator": {"fn": get_indicator, "description": "One indicator against the person's own baseline, with a 14-day trend.",
                      "params": {"crew_id": "string", "ind": "|".join(INDICATORS)}},
    "explain_system": {"fn": explain_system, "description": "What spaceflight does to a body system and its current status.",
                       "params": {"crew_id": "string", "sys": "|".join(SYSTEMS)}},
    "get_risks": {"fn": get_risks, "description": "Risk levels (for now behavioural health and performance) with trend, start day and evidence.",
                  "params": {"crew_id": "string"}},
    "get_protocol": {"fn": get_protocol, "description": "Summary of a Guided Response protocol (never the full emergency flow).",
                     "params": {"pid": "string"}},
    "list_goals": {"fn": list_goals, "description": "Today's goals for a crew member and whether they are done.",
                   "params": {"crew_id": "string"}},
}

_IND_WORDS = {
    "hr": r"pulse|heart ?rate|heartbeat", "bp": r"blood pressure|pressure", "sleep": r"sleep|tired|insomnia",
    "mood": r"mood|sad|down|happy", "stress": r"stress|anxious|anxiety", "react": r"reaction|focus|concentrat|slow",
    "water": r"water|thirst|hydrat", "spo2": r"oxygen|spo2|breath", "temp": r"temperature|fever",
    "gluc": r"glucose|sugar", "exer": r"exercise|workout|training", "bone": r"bone", "grip": r"grip|strength",
    "social": r"lonely|alone|crew time|social|friends",
}
_SYS_WORDS = {"eyes": r"eye|vision|see|amsler", "skin": r"radiation|storm|dose|sievert", "immune": r"immun|blood count|lymph",
              "kidneys": r"kidney|stone|urine", "heart": r"heart", "brain": r"brain|mind|mental", "skeleton": r"bone",
              "muscles": r"muscle", "lungs": r"lung", "gut": r"gut|stomach|food|appetite|nutrition"}
_PROTO_WORDS = {"seizure": r"seizure|convuls", "choke": r"chok", "bleed": r"bleed", "chest": r"chest pain",
                "allergy": r"allerg", "cpr": r"cpr|not breathing", "crisis": r"panic|crisis", "rad": r"radiation storm|shelter"}


def route(crew_id: str, question: str) -> List[dict]:
    """Pick tools from the question's words. Returns [{tool, args, result}]."""
    q = question.lower()
    calls: List[tuple] = []
    for ind, pat in _IND_WORDS.items():
        if re.search(pat, q):
            calls.append(("get_indicator", {"crew_id": crew_id, "ind": ind}))
    for sys, pat in _SYS_WORDS.items():
        if re.search(pat, q) and not any(c[0] == "get_indicator" and c[1]["ind"] in SYSTEMS[sys]["indicators"] for c in calls):
            calls.append(("explain_system", {"crew_id": crew_id, "sys": sys}))
    for pid, pat in _PROTO_WORDS.items():
        if re.search(pat, q):
            calls.append(("get_protocol", {"pid": pid}))
    if re.search(r"what (should|do) i do|what now|today|how am i|status|overall", q) or not calls:
        calls.insert(0, ("get_status", {"crew_id": crew_id}))
    if re.search(r"risk|fatigue|exhaust|burn ?out|worn out", q):
        calls.append(("get_risks", {"crew_id": crew_id}))
    if re.search(r"goal|task|plan", q):
        calls.append(("list_goals", {"crew_id": crew_id}))
    out, seen = [], set()
    for name, args in calls[:5]:
        key = (name, tuple(sorted(args.items())))
        if key in seen:
            continue
        seen.add(key)
        fn: Callable = TOOLS[name]["fn"]
        out.append({"tool": name, "args": args, "result": fn(**args)})
    return out


def schema() -> List[dict]:
    return [{"name": k, "description": v["description"], "params": v["params"]} for k, v in TOOLS.items()]
