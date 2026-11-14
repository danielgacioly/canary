"""Read-only tools the assistant may call. Each result says where every fact came from.

Contract (docs/ai/schema.md §5, assistant/contracts.py):

- Every call runs inside a `contracts.ToolContext`. `crew_id` and the viewer are bound by the server after
  `require_self` passed; they are never model arguments, so no schema below has a `crew_id`.
- Visibility (`contracts.VISIBILITY`): a tool returns only the bound person's own data, to that person or the
  medical team. No tool wraps crew-wide numbers (`goals.leaderboard`, `goals.crew_board`, `/api/crew` rows),
  so no result holds another crew member's data or a crew average. `settings` keys in
  `contracts.SETTINGS_NEVER_RETURNED` are stripped from every result.
- Every tool returns the `contracts.ToolResult` envelope `{data, sources, error}` and never raises: a failure
  becomes `error` with no sources.

Entry points:

- `anthropic_tools()` renders the strict JSON Schemas for the Messages API (`tools=`).
- `run_tool(ctx, name, args)` validates the arguments against the same schema and runs the tool.
- `route(crew_id, question, ctx=None)` is the deterministic no-model path (no provider, timeout, API down).
"""
import copy
import json
import re
from typing import Any, Dict, List, Optional

from .. import db
from ..domain import goals, health, mission, protocols, selftests, telemetry
from ..domain.catalog import INDICATORS, LOCATIONS, SYSTEMS
from .contracts import SETTINGS_NEVER_RETURNED, ToolContext, ToolResult
from . import kb

# ---------------------------------------------------------------- enums (from catalog / selftests / protocols)

INDICATOR_IDS = list(INDICATORS)
SYSTEM_IDS = list(SYSTEMS)
PROTOCOL_IDS = list(protocols.order())
CHECKIN_KINDS = [t["id"] for t in selftests.TESTS] + ["any"]
KNOWLEDGE_KINDS = ["protocol", "system_card", "location", "nasa_source", "hazard", "privacy", "self_test", "any"]
MAX_CHECKIN_DAYS = 14
MAX_KNOWLEDGE_K = 6
MAX_QUERY_CHARS = 200
MAX_CHECKIN_ROWS = 40

# Source prefixes whose second segment is a crew id (schema.md §2). Used to enforce VISIBILITY on every result.
_PERSONAL_PREFIXES = ("telemetry", "status", "goals", "checkin", "summary")
_MISSION_KEYS = ("day", "location", "learning", "storm")


def _ms(ctx: ToolContext) -> dict:
    """Mission state bound at the start of the question, or the live one if the context carries none."""
    m = ctx.mission or {}
    return m if all(k in m for k in _MISSION_KEYS) else mission.state()


# ---------------------------------------------------------------- the tools (crew_id always from ctx)

def get_status(ctx: ToolContext) -> ToolResult:
    ms = _ms(ctx)
    s = health.snapshot(ctx.crew_id, ms)
    top = s["alerts"][:3]
    data = {"areas": s["areas"],
            "alerts": [{"title": a["title"], "level": a["level"], "todo": a["todo"]} for a in top]}
    sources = [src for a in top for src in a.get("sources", [])] or [f"status:{ctx.crew_id}:day{ms['day']}"]
    return ToolResult(data=data, sources=sources)


def get_indicator(ctx: ToolContext, ind: str) -> ToolResult:
    ms = _ms(ctx)
    d = health.indicator(ctx.crew_id, ind, ms)
    trend = telemetry.series(ctx.crew_id, ind, ms["day"], 14)
    return ToolResult(data={**d, "trend_14d": trend}, sources=[d["source"]])


def explain_system(ctx: ToolContext, sys: str) -> ToolResult:
    ms = _ms(ctx)
    snap = health.snapshot(ctx.crew_id, ms)
    S = SYSTEMS[sys]
    inds = [snap["indicators"][i] for i in S["indicators"]]
    data = {"system": S["name"], "status": snap["systems"][sys]["status"], "note": snap["systems"][sys]["note"],
            "space": S["space"], "indicators": inds}
    return ToolResult(data=data, sources=[f"card:{sys}"] + [i["source"] for i in inds])


def get_protocol(ctx: ToolContext, pid: str) -> ToolResult:
    p = protocols.resolve(_ms(ctx)["location"])["protocols"][pid]
    first = p["steps"][0].get("t") or p["steps"][0].get("q")
    return ToolResult(data={"name": p["name"], "sign": p["sign"], "kit": p["kit"], "first_step": first},
                      sources=[p["source"]])


def list_goals(ctx: ToolContext) -> ToolResult:
    """Today's goals: id, area, title, by and done. No XP, levels or points."""
    ms = _ms(ctx)
    g = goals.personal_today(ctx.crew_id, ms)
    data = [{"id": x["id"], "area": x["area"], "title": x["title"], "by": x["by"], "done": bool(x["done"])} for x in g]
    return ToolResult(data=data, sources=[f"goals:{ctx.crew_id}:day{ms['day']}"])


def _checkin_values(kind: str, p: dict) -> dict:
    """What a check-in may tell the model. Journal: line count only. Wellbeing: the two scale totals only."""
    if kind == "journal":
        return {"lines": int(p.get("lines", 0) or 0)}
    if kind == "wellbeing":
        return {k: p[k] for k in ("phq2", "gad2") if k in p}
    return {k: v for k, v in p.items() if k not in ("text", "answers")}


def get_checkins(ctx: ToolContext, kind: str, days: int) -> ToolResult:
    ms = _ms(ctx)
    today = ms["day"]
    sql = "SELECT kind,day,payload FROM checkins WHERE crew_id=? AND day<=? AND day>?"
    params: List[Any] = [ctx.crew_id, today, today - days]
    if kind != "any":
        sql += " AND kind=?"
        params.append(kind)
    rows = db.q(sql + " ORDER BY id DESC LIMIT ?", tuple(params) + (MAX_CHECKIN_ROWS,))
    items, sources = [], []
    for r in rows:
        if r["kind"] not in selftests.TEST_IDS:
            continue
        try:
            p = json.loads(r["payload"]) or {}
        except (TypeError, ValueError):
            p = {}
        src = f"checkin:{ctx.crew_id}:{r['kind']}:day{r['day']}"
        items.append({"kind": r["kind"], "day": r["day"], "summary": selftests.summary(r["kind"], p),
                      "values": _checkin_values(r["kind"], p), "source": src})
        if src not in sources:
            sources.append(src)
    return ToolResult(data={"kind": kind, "days": days, "from_day": today - days + 1, "to_day": today,
                            "count": len(items), "checkins": items}, sources=sources)


def get_weekly_summary(ctx: ToolContext) -> ToolResult:
    from . import briefing  # imported here: briefing pulls in the provider layer

    f = briefing.facts(ctx.crew_id)
    return ToolResult(data=f, sources=[f"summary:{ctx.crew_id}:day{f['day']}:7d"])


NO_EVIDENCE = "No approved knowledge matched this question for the current place and gravity."


def search_knowledge(ctx: ToolContext, query: str, kind: str, k: int) -> ToolResult:
    loc = _ms(ctx)["location"]
    gravity = LOCATIONS[loc]["gravity_key"]
    chunks = kb.search(query, kind=kind, k=k, gravity=gravity, place=loc) or []
    chunks = list(chunks)[:k]
    if not chunks:
        return ToolResult(data={"chunks": [], "evidence": "none", "note": NO_EVIDENCE}, sources=[])
    return ToolResult(data={"chunks": [c.as_tool_data() for c in chunks], "evidence": "found"},
                      sources=[c.chunk_id for c in chunks])


# ---------------------------------------------------------------- schemas (the one place they live)

def _obj(props: Dict[str, dict]) -> dict:
    return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}


TOOLS: Dict[str, dict] = {
    "get_status": {
        "fn": get_status,
        "description": "Physical and mental readiness scores and the top 3 alerts for the person this question is about.",
        "input_schema": _obj({}),
    },
    "get_indicator": {
        "fn": get_indicator,
        "description": "One indicator against the person's own baseline (value, baseline, delta, level), with a 14-day trend.",
        "input_schema": _obj({"ind": {"type": "string", "enum": INDICATOR_IDS, "description": "Indicator id."}}),
    },
    "explain_system": {
        "fn": explain_system,
        "description": "What spaceflight does to a body system, and that system's current status for the person.",
        "input_schema": _obj({"sys": {"type": "string", "enum": SYSTEM_IDS, "description": "Body system id."}}),
    },
    "get_protocol": {
        "fn": get_protocol,
        "description": "Summary of a Guided Response protocol: name, warning sign, kit and first step. Never the full emergency flow.",
        "input_schema": _obj({"pid": {"type": "string", "enum": PROTOCOL_IDS, "description": "Protocol id."}}),
    },
    "list_goals": {
        "fn": list_goals,
        "description": "Today's goals for the person (id, area, title, who set it: routine, alert, medical or suggestion) and whether each is done.",
        "input_schema": _obj({}),
    },
    "get_checkins": {
        "fn": get_checkins,
        "description": ("The person's self-tests and logs over the last N days (1 to 14), newest first. "
                        "Journal entries give only a line count. Wellbeing (PHQ-2 / GAD-2) is screening data, never a diagnosis."),
        "input_schema": _obj({
            "kind": {"type": "string", "enum": CHECKIN_KINDS, "description": "Test or log id, or 'any' for all of them."},
            "days": {"type": "integer", "minimum": 1, "maximum": MAX_CHECKIN_DAYS, "description": "How many days back, 1 to 14."},
        }),
    },
    "get_weekly_summary": {
        "fn": get_weekly_summary,
        "description": "The person's last 7 days as computed by the backend: readiness, alerts, biggest changes vs baseline, what was tried, goal completion.",
        "input_schema": _obj({}),
    },
    "search_knowledge": {
        "fn": search_knowledge,
        "description": ("Search approved knowledge (protocols, body-system cards, places, NASA sources, hazards, the privacy contract, "
                        "self-test cards), filtered to the current place and gravity. Returns citable chunks, or none when nothing matches."),
        "input_schema": _obj({
            "query": {"type": "string", "maxLength": MAX_QUERY_CHARS, "description": "What to look up, in plain English (at most 200 characters)."},
            "kind": {"type": "string", "enum": KNOWLEDGE_KINDS, "description": "Document kind, or 'any'."},
            "k": {"type": "integer", "minimum": 1, "maximum": MAX_KNOWLEDGE_K, "description": "How many chunks, 1 to 6."},
        }),
    },
}

# Constraints the strict tool grammar does not accept. `validate_args` still enforces them on the server.
_NOT_IN_STRICT_GRAMMAR = ("minimum", "maximum", "minLength", "maxLength", "pattern")


def _for_api(prop: dict) -> dict:
    return {k: v for k, v in prop.items() if k not in _NOT_IN_STRICT_GRAMMAR}


def anthropic_tools() -> List[dict]:
    """Tool definitions for the Messages API: strict JSON Schemas, no crew_id anywhere."""
    out = []
    for name, t in TOOLS.items():
        schema = copy.deepcopy(t["input_schema"])
        schema["properties"] = {p: _for_api(s) for p, s in schema["properties"].items()}
        out.append({"name": name, "description": t["description"], "input_schema": schema, "strict": True})
    return out


def schema() -> List[dict]:
    """For /api/assistant/status: name, description and the full schema (bounds included)."""
    return [{"name": k, "description": v["description"], "params": copy.deepcopy(v["input_schema"])} for k, v in TOOLS.items()]


# ---------------------------------------------------------------- validation and running

def validate_args(name: str, args: Any) -> Optional[str]:
    """None when `args` match the tool's schema; otherwise a short reason. Rejects unknown keys (crew_id included)."""
    if name not in TOOLS:
        return f"unknown tool {name!r}"
    if not isinstance(args, dict):
        return "arguments must be a JSON object"
    sch = TOOLS[name]["input_schema"]
    props = sch["properties"]
    extra = sorted(set(args) - set(props))
    if extra:
        return f"unknown argument(s): {', '.join(extra)}"
    missing = [p for p in sch["required"] if p not in args]
    if missing:
        return f"missing argument(s): {', '.join(missing)}"
    for key, spec in props.items():
        v = args[key]
        if spec["type"] == "string":
            if not isinstance(v, str):
                return f"{key} must be a string"
            if "maxLength" in spec and len(v) > spec["maxLength"]:
                return f"{key} must be at most {spec['maxLength']} characters"
            if key == "query" and not v.strip():
                return f"{key} must not be empty"
        elif spec["type"] == "integer":
            if isinstance(v, bool) or not isinstance(v, int):
                return f"{key} must be an integer"
            if v < spec.get("minimum", v) or v > spec.get("maximum", v):
                return f"{key} must be between {spec['minimum']} and {spec['maximum']}"
        if "enum" in spec and v not in spec["enum"]:
            return f"{key} must be one of: {', '.join(map(str, spec['enum']))}"
    return None


def _strip_settings(node: Any) -> Any:
    if isinstance(node, dict):
        return {k: _strip_settings(v) for k, v in node.items() if k not in SETTINGS_NEVER_RETURNED}
    if isinstance(node, list):
        return [_strip_settings(v) for v in node]
    return node


def _visibility_error(ctx: ToolContext, sources: List[str]) -> Optional[str]:
    for s in sources:
        parts = s.split(":")
        if parts[0] in _PERSONAL_PREFIXES and (len(parts) < 2 or parts[1] != ctx.crew_id):
            return "result withheld: it would show data about someone other than the person asked about"
    return None


def run_tool(ctx: ToolContext, name: str, args: Optional[dict] = None) -> ToolResult:
    """Validate and run one tool for the bound person. Never raises: every failure is an error envelope."""
    try:
        if not isinstance(ctx, ToolContext):
            return ToolResult.fail("no tool context bound to this question")
        args = {} if args is None else args
        bad = validate_args(name, args)
        if bad:
            return ToolResult.fail(f"{name}: {bad}")
        res = TOOLS[name]["fn"](ctx, **args)
        if not isinstance(res, ToolResult):
            res = ToolResult(**res)
        vis = _visibility_error(ctx, res.sources)
        if vis:
            return ToolResult.fail(vis)
        return ToolResult(data=_strip_settings(res.data), sources=list(dict.fromkeys(res.sources)), error=None)
    except Exception as e:  # noqa: BLE001 - a tool must never raise into the loop
        return ToolResult.fail(f"{name} failed: {type(e).__name__}")


# ---------------------------------------------------------------- route(): the no-model path

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


def _bind(crew_id: str) -> ToolContext:
    """Context for callers that already passed `require_self` for `crew_id` (chat.ask today)."""
    return ToolContext(crew_id=crew_id, viewer=crew_id, medical=False, mission=mission.state())


def route(crew_id: str, question: str, ctx: Optional[ToolContext] = None) -> List[dict]:
    """Pick tools from the question's words and run them in `ctx` (built for `crew_id` when not given).

    Returns [{tool, args, result}] where `result` is a ToolResult dumped to a dict. Failed tools are left out,
    so the grounded answer only uses results that carry data and sources."""
    if ctx is None:
        ctx = _bind(crew_id)
    elif ctx.crew_id != crew_id:
        return []
    q = question.lower()
    calls: List[tuple] = []
    for ind, pat in _IND_WORDS.items():
        if re.search(pat, q):
            calls.append(("get_indicator", {"ind": ind}))
    for sys, pat in _SYS_WORDS.items():
        if re.search(pat, q) and not any(c[0] == "get_indicator" and c[1]["ind"] in SYSTEMS[sys]["indicators"] for c in calls):
            calls.append(("explain_system", {"sys": sys}))
    for pid, pat in _PROTO_WORDS.items():
        if re.search(pat, q):
            calls.append(("get_protocol", {"pid": pid}))
    if re.search(r"what (should|do) i do|what now|today|how am i|status|overall", q) or not calls:
        calls.insert(0, ("get_status", {}))
    if re.search(r"goal|task|plan", q):
        calls.append(("list_goals", {}))
    out, seen = [], set()
    for name, args in calls[:5]:
        key = (name, tuple(sorted(args.items())))
        if key in seen:
            continue
        seen.add(key)
        res = run_tool(ctx, name, args)
        if res.ok:
            out.append({"tool": name, "args": args, "result": res.model_dump()})
    return out

