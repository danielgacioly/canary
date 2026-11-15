"""Read-only tools the assistant may call. Each result says where every fact came from.

Contract (docs/ai/schema.md §5, assistant/contracts.py):

- Every call runs inside a `contracts.ToolContext`. `crew_id` and the viewer are bound by the server after
  `require_self` passed; they are never model arguments, so no schema below has a `crew_id`.
- Visibility (`contracts.VISIBILITY`): a tool returns only the bound person's own data, to that person or the
  medical team. No tool wraps crew-wide numbers (`goals.leaderboard`, `goals.crew_board`, `/api/crew` rows),
  so no result holds another crew member's data or a crew average. `settings` keys in
  `contracts.SETTINGS_NEVER_RETURNED` are stripped from every result, and so are check-in photos
  (`contracts.FIELDS_NEVER_RETURNED` and any image data URL).
- Every tool returns the `contracts.ToolResult` envelope `{data, sources, error}` and never raises: a failure
  becomes `error` with no sources.

Entry points:

- `gemini_tools()` renders JSON Schemas for the Gemini function declarations.
- `run_tool(ctx, name, args)` validates the arguments against the same schema and runs the tool.
- `route(crew_id, question, ctx=None)` is the deterministic no-model path (no provider, timeout, API down).
"""
import copy
import json
import re
from typing import Any, Dict, List, Optional

from .. import db
from ..domain import goals, health, mission, privacy, protocols, selftests, standards, telemetry
from ..domain.catalog import INDICATORS, LOCATIONS, SYSTEMS
from .contracts import (FIELDS_NEVER_RETURNED, PERSONAL_SOURCE_PREFIXES, SCOPED_SOURCE_PREFIXES, SETTINGS_NEVER_RETURNED,
                        ToolContext, ToolResult)
from . import kb

# ---------------------------------------------------------------- enums (from catalog / selftests / protocols)

INDICATOR_IDS = list(INDICATORS)
SYSTEM_IDS = list(SYSTEMS)
PROTOCOL_IDS = list(protocols.order())
CHECKIN_KINDS = [t["id"] for t in selftests.TESTS] + ["any"]
KNOWLEDGE_KINDS = list(kb.KINDS)
MAX_CHECKIN_DAYS = 14
MAX_KNOWLEDGE_K = 6
MAX_QUERY_CHARS = 200
MAX_CHECKIN_ROWS = 40

# Source prefixes whose second segment is a crew id (schema.md §2). Used to enforce VISIBILITY on every result.
_PERSONAL_PREFIXES = PERSONAL_SOURCE_PREFIXES
_MISSION_KEYS = ("day", "location", "learning", "storm")


def _is_suggestion_goal(node: Any) -> bool:
    """A goal the person created from an accepted suggestion: `by == "suggestion"` or an `sg_*` id."""
    if not isinstance(node, dict):
        return False
    gid = node.get("id") or node.get("goal_id")
    return node.get("by") == "suggestion" or (isinstance(gid, str) and gid.removeprefix("goal:").startswith("sg_"))


_SG_REF = re.compile(r"\b(?:goal:)?sg_\w+")


def _hide_suggestions(node: Any) -> Any:
    """For a medical viewer: drop every suggestion goal from a result, wherever it sits (plan.md W1-2)."""
    if isinstance(node, dict):
        return {k: _hide_suggestions(v) for k, v in node.items()}
    if isinstance(node, list):
        return [_hide_suggestions(v) for v in node
                if not _is_suggestion_goal(v) and not (isinstance(v, str) and _SG_REF.search(v))]
    return node


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


_RISK_INTERNAL = ("points", "floor")


def get_risks(ctx: ToolContext) -> ToolResult:
    """Each risk with its level, trend, the day it started, the evidence behind it, where its data comes from (`data`) and
    the hazards that are possible factors. Read-only; the rules decide, not a model."""
    ms = _ms(ctx)
    risks = health.snapshot(ctx.crew_id, ms)["risks"]
    # Scoring weights stay in the rules: the model gets the evidence, never the points behind a level.
    risks = [{**r, "evidence": [{k: v for k, v in e.items() if k not in _RISK_INTERNAL} for e in r["evidence"]]} for r in risks]
    srcs = [e["source"] for r in risks for e in r["evidence"]]
    srcs += [f"card:risk:{r['id']}" for r in risks if r["level"]] + [f"card:hazard:{h}" for r in risks for h in r["hazards"]]
    return ToolResult(data=risks, sources=list(dict.fromkeys(srcs)) or [f"risk:{ctx.crew_id}:day{ms['day']}"])


def get_protocol(ctx: ToolContext, pid: str) -> ToolResult:
    p = protocols.resolve(_ms(ctx)["location"])["protocols"][pid]
    first = p["steps"][0].get("t") or p["steps"][0].get("q")
    return ToolResult(data={"name": p["name"], "sign": p["sign"], "kit": p["kit"], "first_step": first},
                      sources=[p["source"]])


def list_goals(ctx: ToolContext) -> ToolResult:
    """Today's goals: id, area, title, by and done. No XP, levels or points. A medical viewer does not see
    goals the person added from Suggestions (astronaut-only, plan.md W1-2)."""
    ms = _ms(ctx)
    g = [x for x in goals.personal_today(ctx.crew_id, ms) if not (ctx.medical and _is_suggestion_goal(x))]
    data = [{"id": x["id"], "area": x["area"], "title": x["title"], "by": x["by"], "done": bool(x["done"])} for x in g]
    return ToolResult(data=data, sources=[f"goals:{ctx.crew_id}:day{ms['day']}"])


# Vital signs: the four numbers only. The photo of the display lives apart (checkin_photos) and never reaches a tool.
_VITALS_KEYS = tuple(selftests.VITALS_LIMITS)


def _checkin_values(kind: str, p: dict) -> dict:
    """What a check-in may tell the model. Journal: line count only. Wellbeing: the two scale totals only.
    Vitals: the allow-listed numbers only."""
    if kind == "vitals":
        return {k: p[k] for k in _VITALS_KEYS if k in p}
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
        if r["kind"] == "vitals":  # the summary lists every payload key: give it the allow-listed numbers only
            p = _checkin_values("vitals", p)
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


# "Ready for EVA?" (frontend components/EvaReadiness.tsx): the verdict is the highest NASA-STD-3001 level among the
# rows the card shows, read from `health.indicator(...)["standard"]` (domain/standards.check). Same labels as the card.
EVA_VERDICT = ("Ready", "Close to a limit", "Below a limit")
EVA_ROWS = (("vo2", "VO2max"), ("grip", "Grip strength"), ("bone", "Bone density"))


def _std_source(item: str) -> str:
    return f"nasa:std3001v1:{item.replace(' ', '')}"


def _eva(ctx: ToolContext, ms: dict, snap: dict) -> tuple:
    """The EVA card for the bound person, from the domain: (data, sources). Nothing re-derived but the label."""
    role, place = standards.eva_role(ctx.crew_id), LOCATIONS[ms["location"]]
    who = "your" if ctx.viewer == ctx.crew_id else "this person's"
    out = {"role": role, "place_eva": place.get("eva", "none"), "checked": False, "level": None, "verdict": None,
           "note": None, "rows": []}
    if role == "none":
        return {**out, "note": f"No EVA in {who} role."}, []
    if ms["learning"]:
        return {**out, "note": "Nothing to check before launch: NASA's limits apply in flight."}, []
    lim = standards.LIMITS
    need = lim["vo2"].get(place.get("eva", "none"))
    inds, rows, srcs = snap["indicators"], [], []
    unit = lambda iid, d: d["unit"] if iid == "vo2" else "% of pre-flight"  # noqa: E731
    for iid, name in EVA_ROWS:
        d, std = inds[iid], inds[iid].get("standard")
        # No reading (or, for grip and bone, no normal to compare with yet): the row says so, with no number and no level.
        if d["value"] is None or (iid == "grip" and d["baseline"] is None):
            text = "No current reading yet." if d["value"] is None else "Still learning your normal, so this cannot be compared with pre-flight yet."
            rows.append({"id": iid, "name": name, "now": None, "unit": unit(iid, d), "limit": None, "level": None, "status": None,
                         "text": text, "item": None, "verified": False})
            continue
        if iid == "vo2" and not (std and need):
            rows.append({"id": iid, "name": name, "now": round(d["value"], 1), "unit": d["unit"], "limit": None, "level": None,
                         "text": f"No EVA at {place['name']}, so NASA sets no minimum here."})
            continue
        if not std:
            continue
        if iid == "vo2":
            now, limit = round(d["value"], 1), f"{need} {lim['vo2']['unit']}"
        elif iid == "grip":
            now, limit = round(100 * d["value"] / d["baseline"], 0), f"{lim['grip']['limit_pct']}% of pre-flight"
        else:
            now, limit = round(100 + d["value"], 1), f"{100 - lim['bone']['limit_loss_pct']:g}% of pre-flight"
        rows.append({"id": iid, "name": name, "now": now, "unit": unit(iid, d),
                     "limit": limit, "level": std["level"], "status": std["status"], "text": std["text"], "item": std["item"],
                     "verified": std["verified"]})
        srcs += [d["source"], _std_source(std["item"])]
    scored = [r["level"] for r in rows if r["level"] is not None]
    if not scored:  # nothing to check against NASA's limits: no verdict, not "Ready"
        return {**out, "note": "No current readings to check against NASA's limits yet.", "rows": rows}, srcs
    level = max(scored)
    return {**out, "checked": True, "level": level, "verdict": EVA_VERDICT[level], "rows": rows}, srcs


def get_dose_and_eva(ctx: ToolContext) -> ToolResult:
    """Mission and career dose against NASA's limit, today's dose rate and place, the EVA role and the "Ready for
    EVA?" verdict with its reasons. Self or medical only (operational status never goes to the crew or Earth)."""
    if not (ctx.medical or ctx.viewer == ctx.crew_id):
        return ToolResult.fail("dose and EVA readiness are private: only the person and the medical team")
    ms = _ms(ctx)
    snap = health.snapshot(ctx.crew_id, ms)
    d = snap["dose"]  # health.dose(ms, crew_id): the numbers the radiation bar shows
    place = LOCATIONS[ms["location"]]
    dose = {"mission_msv": d["mission_msv"], "career_msv": d["career_msv"], "prior_msv": d["prior_msv"],
            "prior": "estimated" if d["prior_estimate"] else "recorded", "prior_source": d["prior_source"],
            "career_limit_msv": d["career_limit_msv"], "career_pct_of_limit": d["career_pct_of_limit"],
            "mission_pct_of_limit": d["pct_of_limit"], "limit_source": d["limit_source"],
            "rate_msv_day": d["rate_msv_day"], "storm": ms["storm"], "simulated": d["simulated"]}
    eva, eva_srcs = _eva(ctx, ms, snap)
    ops = privacy.operational(snap)
    duty = {"label": ops["label"], **({"reason": ops["reason"]} if ops.get("reason") else {})}
    data = {"day": ms["day"], "place": {"id": ms["location"], "name": place["name"]}, "dose": dose, "eva": eva, "duty": duty}
    day = ms["day"]
    sources = [f"dose:{ctx.crew_id}:day{day}", _std_source(standards.RADIATION["items"][1])] + eva_srcs + [f"status:{ctx.crew_id}:day{day}"]
    return ToolResult(data=data, sources=list(dict.fromkeys(sources)))


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
    "get_risks": {
        "fn": get_risks,
        "description": ("Every risk for the person (behavioural health, radiation, vision, nutrition, kidneys, immunity, heart, bone and muscle) "
                        "with level, trend, start day, evidence, data origin (real, partial or simulated), the NASA red-risk mark and the "
                        "hazards that are possible factors, never proven causes."),
        "input_schema": _obj({}),
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
    "get_dose_and_eva": {
        "fn": get_dose_and_eva,
        "description": ("The person's radiation dose and EVA readiness: mission and career dose (mSv), dose before this mission "
                        "(recorded or estimated), % of NASA's career limit and its source, today's dose rate and place, EVA role, "
                        "and the 'Ready for EVA?' verdict with the NASA-STD-3001 reasons behind it."),
        "input_schema": _obj({}),
    },
    "search_knowledge": {
        "fn": search_knowledge,
        "description": ("Search approved knowledge (protocols, body-system cards, places, NASA sources, hazards, the privacy contract, "
                        "self-test cards, risk cards, care windows after an emergency), filtered to the current place and gravity. Returns citable chunks, or none when nothing matches."),
        "input_schema": _obj({
            "query": {"type": "string", "maxLength": MAX_QUERY_CHARS, "description": "What to look up, in plain English (at most 200 characters)."},
            "kind": {"type": "string", "enum": KNOWLEDGE_KINDS, "description": "Document kind, or 'any'."},
            "k": {"type": "integer", "minimum": 1, "maximum": MAX_KNOWLEDGE_K, "description": "How many chunks, 1 to 6."},
        }),
    },
}

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


def gemini_tools() -> List[dict]:
    """Gemini function declarations; the same schemas are enforced again before execution."""
    return [{"name": name, "description": t["description"],
             "parametersJsonSchema": copy.deepcopy(t["input_schema"])} for name, t in TOOLS.items()]


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


_NEVER = set(SETTINGS_NEVER_RETURNED) | set(FIELDS_NEVER_RETURNED)


def _is_image(v: Any) -> bool:
    return isinstance(v, str) and v[:11].lower() == "data:image/"


def _strip_settings(node: Any) -> Any:
    if isinstance(node, dict):
        return {k: _strip_settings(v) for k, v in node.items() if k not in _NEVER and not _is_image(v)}
    if isinstance(node, list):
        return [_strip_settings(v) for v in node if not _is_image(v)]
    return node


def _visibility_error(ctx: ToolContext, sources: List[str]) -> Optional[str]:
    for s in sources:
        parts = s.split(":")
        if parts[0] in _PERSONAL_PREFIXES and (len(parts) < 2 or parts[1] != ctx.crew_id):
            return "result withheld: it would show data about someone other than the person asked about"
        if parts[0] in SCOPED_SOURCE_PREFIXES and len(parts) > 2 and parts[1] != ctx.crew_id:
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
        if not res.ok:  # a tool's own refusal stays a refusal
            return ToolResult.fail(res.error)
        vis = _visibility_error(ctx, res.sources)
        if vis:
            return ToolResult.fail(vis)
        data = _strip_settings(res.data)
        if ctx.medical:
            data = _hide_suggestions(data)
        return ToolResult(data=data, sources=list(dict.fromkeys(res.sources)), error=None)
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


_DOSE_EVA_WORDS = r"\beva\b|\bevas\b|space ?walk|extravehicular|\bdose\b|radiation|sievert|\bmsv\b"


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
    if re.search(_DOSE_EVA_WORDS, q):
        calls.append(("get_dose_and_eva", {}))
    if re.search(r"what (should|do) i do|what now|today|how am i|status|overall", q) or not calls:
        calls.insert(0, ("get_status", {}))
    if re.search(r"risk|fatigue|exhaust|burn ?out|worn out|radiation|vision|sans|nutrition|kidney|immun|heart|cardio|bone|muscle|hazard|ridge|why", q):
        calls.append(("get_risks", {}))
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

