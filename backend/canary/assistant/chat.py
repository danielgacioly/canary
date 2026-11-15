"""Entry 1: a question in plain language, from the astronaut or the medical team about one astronaut.

Flow (docs/ai/plan.md Phase 2):

    guard.precheck ──► emergency / refused (no model call)
    provider.complete(task="chat")  the model picks tools; each call runs for the bound person only
    guard.postcheck                 sources by type, numbers, wording, action allow-list, privacy
      ├─ pass → mode "ai"
      └─ hard fail, loop guard, timeout, refusal, API error → grounded route() answer, mode "fallback"

Without a provider the answer is built from route()'s tool results (mode "grounded"). Every question is
logged in assistant_log (provider, model, kb_version, outcome, guard_flags, latency, tokens) and every
tool call of the model in assistant_turns.
"""
import json
import os
import pathlib
import re
import sqlite3
import time
from typing import Any, Dict, List, Optional

from .. import db
from ..config import settings
from ..domain import mission, protocols
from ..domain.catalog import CREW_BY_ID, LOCATIONS
from . import guard, tools
from .contracts import MEDICAL_VIEWER, ToolContext, is_data_source
from .providers import GUARD_EXITS, ProviderRequest, ProviderResult, get_provider

PROMPTS = pathlib.Path(__file__).resolve().parent / "prompts"
PROMPT_VERSION = "system_v3"
SYSTEM_PROMPT = (PROMPTS / f"{PROMPT_VERSION}.md").read_text()

UNKNOWN = ("I don't know that from the data on board. The crew medical officer can help, "
           "and I can prepare a message for the flight surgeon.")
GROUNDED_LIMITATION = "Built from rules over your data, without the AI model."
NO_MATCH_LIMITATION = "No approved knowledge or data on board matched this question."

SUGGESTIONS_LOG = "suggestions"  # assistant_log.question of a suggestions build (not a chat turn)
BRIEFING_LOG = "briefing"        # assistant_log.question of a briefing draft build (not a chat turn)

FIXED_LABELS = {"contact_cmo": "Talk to the crew medical officer",
                "send_briefing": "Prepare a message for the flight surgeon"}


# ---------------------------------------------------------------- context

def context_for(crew_id: str, viewer: Optional[dict] = None) -> ToolContext:
    """ToolContext from main.viewer() after require_self passed. viewer None means the person themself
    (direct callers and older tests). Raises ValueError when the viewer may not ask about crew_id."""
    ms = mission.state()
    if viewer is None:
        return ToolContext(crew_id=crew_id, viewer=crew_id, medical=False, mission=ms)
    medical = bool(viewer.get("medical"))
    who = viewer.get("id") if viewer.get("id") == crew_id else MEDICAL_VIEWER
    return ToolContext(crew_id=crew_id, viewer=who, medical=medical, mission=ms)


def _user_message(ctx: ToolContext, question: str) -> str:
    name = CREW_BY_ID[ctx.crew_id]["name"]
    ms = ctx.mission
    place = LOCATIONS.get(ms.get("location"), {}).get("name", ms.get("location"))
    who = (f"Asked by {name} (crew id {ctx.crew_id}) about their own data." if ctx.viewer == ctx.crew_id
           else f"Asked by the medical team about {name} (crew id {ctx.crew_id}).")
    return f"{who}\nMission day {ms.get('day')}, place: {place}.\n\nQuestion: {question}"


_kb_cache: Dict[str, Any] = {}


def kb_version() -> Optional[str]:
    """kb_meta.corpus_hash of the knowledge base file (None when it is not built)."""
    path = settings.kb_path
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return None
    if _kb_cache.get("key") == (path, mtime):
        return _kb_cache["value"]
    value = None
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            row = conn.execute("SELECT value FROM kb_meta WHERE key='corpus_hash'").fetchone()
            value = row[0] if row else None
        finally:
            conn.close()
    except sqlite3.Error:
        value = None
    _kb_cache.update(key=(path, mtime), value=value)
    return value


# ---------------------------------------------------------------- grounded answer (no model)

def _fmt(v: float, dp: int) -> str:
    return f"{v:.{dp}f}"


def _grounded(results: List[dict]) -> List[dict]:
    """Rule-based sentences from tool results. Every sentence cites what it used."""
    claims = []
    for r in results:
        d, src = r["result"]["data"], r["result"]["sources"]
        if r["tool"] == "get_status":
            a = d["areas"]
            claims += _duty_claims(d, src)  # a restriction comes first: readiness scores never read as "all clear"
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
                since = f", since day {k['since_day']}" if k["since_day"] is not None else ""
                data = {"real": "from measured data", "partial": "from a mix of measured and simulated data", "simulated": "from simulated data", "none": "with no data yet"}[k["data"]]
                claims.append({"text": f"{k['name']}: {'watch' if k['level'] == 1 else 'act'} level, {k['trend']}{since}, {data}.",
                               "source_ids": src[:3] or src})
                if k["hazards"]:
                    claims.append({"text": k["hazard_note"], "source_ids": [s for s in src if s.startswith("card:hazard:")] or src[:3] or src})
        elif r["tool"] == "get_protocol":
            claims.append({"text": f"For {d['name'].lower()}, Guided Response starts with: {d['first_step']} "
                                   "In a real emergency, hold the EMERGENCY button.", "source_ids": src})
        elif r["tool"] == "get_dose_and_eva":
            claims += _dose_and_eva_claims(d, src)
        elif r["tool"] == "list_goals":
            left = [g["title"] for g in d if not g["done"]][:3]
            if left:
                claims.append({"text": "Still open today: " + "; ".join(left) + ".", "source_ids": src})
    return claims


DUTY_PHRASE = {"rest": "off critical tasks", "limited": "fit for duty but not for EVA"}


def _duty_claims(d: dict, src: List[str]) -> List[dict]:
    """The operational status when it is restricted, with the care window that caused it, citing the status and the emergency."""
    duty = d.get("duty") or {}
    if duty.get("key") in (None, "full") or duty["key"] not in DUTY_PHRASE:
        return []
    status_id = next((s for s in src if s.startswith("status:")), None)
    cite = [s for s in (status_id, (d.get("care") or {}).get("source")) if s]
    if not cite:
        return []
    phrase = DUTY_PHRASE[duty["key"]]
    if "until_day" in duty and duty.get("care"):
        c = duty["care"]
        return [{"text": f"You are {phrase} until day {duty['until_day']} because of the Guided Response ({c['name']}) on day {c['day']}.",
                 "source_ids": cite}]
    return [{"text": f"You are {phrase} because of your current alerts.", "source_ids": cite}]


def _dose_and_eva_claims(d: dict, src: List[str]) -> List[dict]:
    """Dose against the career limit and the EVA verdict with its reasons, only the tool's own numbers and texts.
    Every sentence cites the person's `dose:{crew}:day{n}` id plus the ids behind that sentence."""
    dose_id = next((s for s in src if s.startswith("dose:")), None)
    if not dose_id:
        return []

    def cite(*ids: Optional[str]) -> List[str]:
        return list(dict.fromkeys([dose_id] + [s for s in ids if s in src]))

    def row_ids(row: dict) -> List[str]:  # the row's own telemetry id and its NASA-STD-3001 item
        own = [s for s in src if s.startswith("telemetry:") and s.split(":")[2:3] == [row["id"]]]
        return own + ([tools._std_source(row["item"])] if row.get("item") else [])

    x = d["dose"]
    limit_id = next((s for s in src if s.startswith("nasa:") and s != dose_id), None)
    claims = [{"text": f"Mission dose {x['mission_msv']:g} mSv; career dose {x['career_msv']:g} mSv "
                       f"({x['prior']} {x['prior_msv']:g} mSv from earlier flights), {x['career_pct_of_limit']:g}% of "
                       f"NASA's {x['career_limit_msv']:g} mSv career limit ({x['limit_source']}).",
               "source_ids": cite(limit_id)}]
    eva = d["eva"]
    if not eva["checked"]:
        if eva.get("note"):
            claims.append({"text": f"EVA readiness: {eva['note']}", "source_ids": cite()})
        # a row without a reading still says so, with no number, as the checked branch does
        claims += [{"text": f"{r['name']}: {r['text'].rstrip('.')}.", "source_ids": cite(*row_ids(r))} for r in eva["rows"] if r["now"] is None]
        return claims
    claims.append({"text": f"EVA readiness: {eva['verdict']}, checked against NASA's limits.",
                   "source_ids": cite(*[s for r in eva["rows"] for s in row_ids(r)])})
    for r in eva["rows"]:
        claims.append({"text": f"{r['name']}: {r['text'].rstrip('.')}.", "source_ids": cite(*row_ids(r))})
    return claims


def _split(claims: List[dict]) -> Dict[str, List[dict]]:
    obs, expl = [], []
    for c in claims:
        item = {"statement": c["text"], "source_ids": c["source_ids"]}
        (obs if all(is_data_source(s) for s in c["source_ids"]) else expl).append(item)
    return {"observations": obs, "explanations": expl}


# ---------------------------------------------------------------- actions and source metadata

def _goals(ctx: ToolContext) -> List[dict]:
    res = tools.run_tool(ctx, "list_goals", {})
    return list(res.data or []) if res.ok else []


def _action(action_id: Optional[str], goals: List[dict], location: str) -> Optional[dict]:
    if not action_id:
        return None
    if action_id in FIXED_LABELS:
        return {"id": action_id, "label": FIXED_LABELS[action_id]}
    kind, _, ref = action_id.partition(":")
    if kind == "goal":
        g = next((g for g in goals if g["id"] == ref), None)
        return {"id": action_id, "label": g["title"] if g else ref}
    if kind == "protocol":
        p = protocols.resolve(location)["protocols"].get(ref)
        return {"id": action_id, "label": f"Open Guided Response: {p['name']}" if p else ref}
    return None


_KB_VERSION = re.compile(r"@(\d+)#")


def _source_meta(tool_data: List[dict], cited: List[str]) -> Dict[str, dict]:
    """{kb id: {title, version, text}} for kb: ids search_knowledge returned this turn and the answer cites."""
    meta = {}
    for t in tool_data:
        if t.get("tool") != "search_knowledge" or t.get("error") or not isinstance(t.get("data"), dict):
            continue
        for c in t["data"].get("chunks", []):
            cid = c.get("chunk_id", "")
            if cid in cited and cid not in meta:
                m = _KB_VERSION.search(cid)
                meta[cid] = {"title": c.get("title", ""), "version": int(m.group(1)) if m else None, "text": c.get("text")}
    return meta


def _guard(reason: Optional[str] = None, rule_ids: Optional[List[str]] = None, dropped: Optional[list] = None,
           numbers: Optional[list] = None) -> dict:
    return {"dropped_claims": dropped or [], "rejected_numbers": numbers or [], "reason": reason,
            "rule_ids": rule_ids or []}


# ---------------------------------------------------------------- the entry

def ask(crew_id: str, question: str, viewer: Optional[dict] = None) -> dict:
    """Answer `question` about `crew_id`. `viewer` is main.viewer() ({"id", "medical"}) after require_self."""
    t0 = time.monotonic()
    question = question.strip()[:500]
    provider = get_provider()
    ctx = context_for(crew_id, viewer)
    base = {"provider": provider.name, "provider_error": None, "prompt_version": PROMPT_VERSION,
            "claims": [], "sources": [], "tools_used": [], "dropped": 0, "observations": [], "explanations": [],
            "limitations": [], "recommended_action": None, "source_meta": {}}

    pre = guard.precheck(question, medical=bool(viewer and viewer.get("medical")))
    if pre:
        rid = pre.get("rule_id")
        # An emergency answer opens the protocol its words matched, so the astronaut lands on the right page.
        action = _action(f"protocol:{pre['protocol']}", [], ctx.mission["location"]) if pre.get("protocol") else None
        if pre.get("answer_key") in ("dosing", "diagnosis"):  # the refusal offers the message the medical officer will read
            action = _action("send_briefing", [], ctx.mission["location"])
        resp = {**base, "mode": pre["mode"], "answer": pre["answer"], "status": "out_of_scope",
                "recommended_action": action, "guard": _guard(rid, [rid] if rid else [])}
        return _log(ctx, question, resp, provider, None, t0, flags=[rid] if rid else [])

    try:
        out = provider.complete(ProviderRequest(task="chat", system=SYSTEM_PROMPT, question=_user_message(ctx, question),
                                                ctx=ctx, deadline=t0 + settings.llm_timeout_s))
    except Exception:  # noqa: BLE001 - a provider bug is an API failure: the grounded answer is used, the text is never shown
        out = ProviderResult(ok=False, guard_exit="api:error", error=GUARD_EXITS["api:error"])
    flags = list(out.notes)
    if out.ok:
        goals = _goals(ctx)
        check = guard.postcheck(out.data if out.data is not None else out.answer, out.sources,
                                json.dumps(out.tool_data, ensure_ascii=False, default=str), ctx=ctx,
                                goal_ids=[g["id"] for g in goals],
                                protocol_ids=list(protocols.resolve(ctx.mission["location"])["protocols"]))
        flags += check.report.get("rule_ids", [])
        if not check.hard_fail and check.response is not None:
            r = check.response
            obs = [o.model_dump() for o in r.observations]
            expl = [e.model_dump() for e in r.explanations]
            claims = [{"text": c["statement"], "source_ids": c["source_ids"]} for c in obs + expl]
            used = sorted({s for c in claims for s in c["source_ids"]})
            resp = {**base, "mode": "ai", "answer": r.answer, "status": r.status, "claims": claims, "sources": used,
                    "tools_used": [{"tool": t["tool"], "args": t["args"]} for t in out.turns],
                    "dropped": len(check.report.get("dropped_claims", [])),
                    "observations": obs, "explanations": expl, "limitations": list(r.limitations),
                    "recommended_action": _action(r.recommended_action_id, goals, ctx.mission["location"]),
                    "guard": {**_guard(), **check.report}, "source_meta": _source_meta(out.tool_data, used)}
            return _log(ctx, question, resp, provider, out, t0, flags=flags)
        report = {**_guard(), **check.report}
        return _fallback(ctx, question, base, provider, out, t0, flags, report)

    if out.guard_exit is None:  # no provider connected: grounded answer, as before
        return _fallback(ctx, question, base, provider, out, t0, flags, _guard(), mode="grounded")
    flags.append(out.guard_exit)
    report = _guard(f"{out.guard_exit}: {GUARD_EXITS.get(out.guard_exit, out.error)}", [out.guard_exit])
    return _fallback(ctx, question, base, provider, out, t0, flags, report)


def _top_alert_action(ctx: ToolContext, results: List[dict]) -> Optional[dict]:
    """The action of the top alert in this answer: its first goal (goal:<id>), else its protocol. Only when the allow-list
    allows it for this viewer (today's goals, no suggestion goal for the medical team; protocols from the bank)."""
    st = next((r for r in results if r["tool"] == "get_status"), None)
    alerts = (st["result"]["data"].get("alerts") or []) if st else []
    if not alerts:
        return None
    goals = _goals(ctx)
    goal_ids = [g["id"] for g in goals]
    top = alerts[0]
    action_id = None
    if top.get("goal") in goal_ids:
        action_id = f"goal:{top['goal']}"
    elif top.get("protocol"):
        action_id = f"protocol:{top['protocol']}"
    if action_id is None or action_id not in guard._allowed_actions(goal_ids, protocols.resolve(ctx.mission["location"])["protocols"].keys(), ctx.medical):
        return None
    return _action(action_id, goals, ctx.mission["location"])


def _fallback(ctx: ToolContext, question: str, base: dict, provider: Any, out: ProviderResult, t0: float,
              flags: List[str], report: dict, mode: str = "fallback") -> dict:
    """Grounded answer from route() (the deterministic tools), never from the model's text."""
    results = tools.route(ctx.crew_id, question, ctx)
    claims = _grounded(results)
    used = sorted({s for c in claims for s in c["source_ids"]})
    if not claims:
        mode = "unknown" if mode == "grounded" else mode
    resp = {**base, "mode": mode, "provider_error": out.error,
            "answer": " ".join(c["text"] for c in claims) if claims else UNKNOWN,
            "status": "supported" if claims else "insufficient_evidence", "claims": claims, "sources": used,
            "tools_used": [{"tool": r["tool"], "args": r["args"]} for r in results], **_split(claims),
            "limitations": [GROUNDED_LIMITATION] if claims else [NO_MATCH_LIMITATION],
            "recommended_action": _top_alert_action(ctx, results) if claims else None, "guard": report}
    return _log(ctx, question, resp, provider, out, t0, flags=flags)


def _log(ctx: ToolContext, question: str, resp: dict, provider: Any, out: Optional[ProviderResult], t0: float,
         flags: List[str]) -> dict:
    model = (out.model if out and out.model else None) if provider.name != "none" else None
    resp["model"] = model
    asked_by = "medical" if ctx.viewer == MEDICAL_VIEWER else "self"
    resp["asked_by"] = asked_by
    resp["id"] = record(ctx.crew_id, question, resp, provider.name, model, resp["mode"], flags, t0,
                        out.input_tokens if out else 0, out.output_tokens if out else 0, asked_by=asked_by)
    for t in (out.turns if out else []):
        db.x("INSERT INTO assistant_turns(log_id,step,tool,args,sources,ok) VALUES(?,?,?,?,?,?)",
             (resp["id"], t["step"], t["tool"], json.dumps(t["args"], default=str), json.dumps(t["sources"]),
              1 if t["ok"] else 0))
    return resp


def record(crew_id: str, question: str, stored: dict, provider: str, model: Optional[str], outcome: str,
           flags: List[str], t0: float, input_tokens: int = 0, output_tokens: int = 0, asked_by: Optional[str] = None) -> int:
    """One assistant_log row. Shared by chat and suggestions (which stores metadata only in `stored`). `asked_by` is set for
    a chat question: "self" or "medical" (who was signed in), so the astronaut can see when the medical team asked."""
    flags = list(dict.fromkeys(f for f in flags if f))
    return db.x(
        "INSERT INTO assistant_log(crew_id,question,response,created_at,provider,model,kb_version,outcome,guard_flags,"
        "latency_ms,input_tokens,output_tokens,asked_by) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (crew_id, question, json.dumps(stored, ensure_ascii=False, default=str), time.time(), provider, model,
         kb_version(), outcome, json.dumps(flags), int((time.monotonic() - t0) * 1000), input_tokens, output_tokens, asked_by))


# ---------------------------------------------------------------- reading the log

def history(crew_id: str, limit: int = 20) -> List[dict]:
    rows = db.q("SELECT id,question,response,created_at,asked_by FROM assistant_log WHERE crew_id=? AND question NOT IN (?,?) "
                "ORDER BY id DESC LIMIT ?", (crew_id, SUGGESTIONS_LOG, BRIEFING_LOG, limit))
    return [{"id": r["id"], "question": r["question"], "created_at": r["created_at"], "asked_by": r["asked_by"] or "self",
             **json.loads(r["response"])} for r in rows][::-1]


def audit(limit: int = 30) -> List[dict]:
    """AssistantAuditEntry[] for the medical team (plan.md W1-4), newest first."""
    limit = max(1, min(int(limit), 200))
    rows = db.q("SELECT id,crew_id,question,response,created_at,provider,model,kb_version,outcome,guard_flags,latency_ms,asked_by "
                "FROM assistant_log ORDER BY id DESC LIMIT ?", (limit,))
    out = []
    for r in rows:
        try:
            resp = json.loads(r["response"]) or {}
        except (TypeError, ValueError):
            resp = {}
        turns = db.q("SELECT tool FROM assistant_turns WHERE log_id=? ORDER BY step, id", (r["id"],))
        names = [t["tool"] for t in turns] or [t.get("tool") for t in resp.get("tools_used", []) if t.get("tool")]
        try:
            flags = json.loads(r["guard_flags"]) if r["guard_flags"] else []
        except (TypeError, ValueError):
            flags = []
        # what the row is: a chat question, a suggestions build or a briefing draft build (the UI tells them apart by this)
        kind = {SUGGESTIONS_LOG: "suggestions", BRIEFING_LOG: "briefing"}.get(r["question"], "chat")
        out.append({"id": r["id"], "crew_id": r["crew_id"], "question": r["question"], "created_at": r["created_at"],
                    "kind": kind, "mode": r["outcome"] or resp.get("mode"), "status": resp.get("status"),
                    "provider": r["provider"] or resp.get("provider"), "model": r["model"], "kb_version": r["kb_version"],
                    "tools": names, "guard_flags": [str(f) for f in flags], "latency_ms": r["latency_ms"],
                    "asked_by": r["asked_by"] or "self"})
    return out
