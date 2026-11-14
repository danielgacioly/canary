"""Safety rules around the assistant. They run with or without a model.

1. Emergencies go to Guided Response, never to a chat answer.
2. No diagnosis and no medication doses: those belong to the medical officer.
3. A claim survives only if it cites sources returned by tools in the same turn.
4. Every number the assistant states must exist in the tool data (or the computed facts of a briefing).
5. Nothing about another crew member's health, no crew averages, and a wellbeing check-in is never a diagnosis.

The patterns live in data/guard_rules.json so the medical team can review them like protocols. Every rule
has an id (G-EMERG-01, G-DOSE-01, ...) that shows in the precheck result, the postcheck report and the log.

Public API:
- precheck(question) -> None or {mode, answer, rule_id}            before any model call
- postcheck(response, allowed_sources, tool_data_blob, ctx=..., goal_ids=...) -> PostcheckResult
                                                                    on every AssistantResponse (plan.md Phase 4)
- validate_claims(claims, allowed) -> (kept, dropped)               legacy {text, source_ids} claims
- unknown_numbers(text, facts_blob) -> [number, ...]                briefing and suggestions entries
"""
import json
import pathlib
import re
import unicodedata
from decimal import ROUND_HALF_EVEN, ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any, Dict, Iterable, List, NamedTuple, Optional, Sequence, Tuple, Union

from pydantic import ValidationError

from ..domain.catalog import CREW
from .contracts import (DATA_SOURCE_PREFIXES, FIXED_ACTIONS, AssistantResponse, Explanation, Observation,
                        ToolContext, is_data_source, is_knowledge_source, source_prefix)

RULES_PATH = pathlib.Path(__file__).resolve().parents[1] / "data" / "guard_rules.json"
RULES: Dict[str, Any] = json.loads(RULES_PATH.read_text())


def _fold(text: str) -> str:
    """Lower-case, accents removed and curly apostrophes straightened, so 'Tomás' matches 'tomas'."""
    t = unicodedata.normalize("NFKD", text.replace("’", "'"))
    return "".join(ch for ch in t if not unicodedata.combining(ch)).lower()


def _compile(patterns: Iterable[str]) -> List[re.Pattern]:
    return [re.compile(p, re.I) for p in patterns]


# Context word lists (medication, radiation) used by gated patterns, so "radiation dose" is mission data while
# "a dose of melatonin" is dosing (plan.md W1-1).
_CONTEXTS: Dict[str, List[re.Pattern]] = {k: _compile(v) for k, v in RULES.get("contexts", {}).items()
                                          if not k.startswith("_")}


class _Gated(NamedTuple):
    patterns: List[re.Pattern]
    when: Optional[str]       # fire only when this context is present
    unless: Optional[str]     # fire unless this context is present ...
    override: Optional[str]   # ... or this one is present as well


def _gated(rule: dict) -> List[_Gated]:
    out = []
    for g in rule.get("gated", []):
        for key in ("when", "unless", "override"):
            if g.get(key) and g[key] not in _CONTEXTS:
                raise ValueError(f"{rule['id']}: unknown context {g[key]!r}")
        out.append(_Gated(_compile(g["patterns"]), g.get("when"), g.get("unless"), g.get("override")))
    return out


def _context(name: str, folded: str) -> bool:
    return any(p.search(folded) for p in _CONTEXTS[name])


def _gated_hit(gated: Iterable[_Gated], folded: str) -> bool:
    for g in gated:
        if not any(p.search(folded) for p in g.patterns):
            continue
        if g.when and not _context(g.when, folded):
            continue
        if g.unless and _context(g.unless, folded) and not (g.override and _context(g.override, folded)):
            continue
        return True
    return False


_PRE: List[Tuple[dict, List[re.Pattern], List[_Gated]]] = [(r, _compile(r["patterns"]), _gated(r)) for r in RULES["precheck"]]
_POST: Dict[str, dict] = {r["id"]: r for r in RULES["postcheck"]}
_POST_RE: Dict[str, List[re.Pattern]] = {rid: _compile(r.get("patterns", [])) for rid, r in _POST.items()}
_POST_GATED: Dict[str, List[_Gated]] = {rid: _gated(r) for rid, r in _POST.items()}
_HEALTH_RE = _compile(_POST["G-PRIV-01"]["health_patterns"])
_CONTACT_RE = _compile(_POST["G-PRIV-01"]["contact_patterns"])

RULE_IDS: Tuple[str, ...] = tuple(r["id"] for r in RULES["precheck"]) + tuple(_POST)


def _matches(patterns: Iterable[re.Pattern], text: str) -> bool:
    folded = _fold(text)
    return any(p.search(folded) for p in patterns)


# ---------------------------------------------------------------- before the model

def precheck(question: str) -> Optional[dict]:
    """None when the question may go to the tools and the model; otherwise the fixed answer.

    Rules run in file order: emergencies first (a question that also tries to bypass the rules still gets
    Guided Response), then ignore-the-rules attempts, dosing and diagnosis."""
    folded = _fold(question)
    for rule, pats, gated in _PRE:
        if any(p.search(folded) for p in pats) or _gated_hit(gated, folded):
            return {"mode": rule["mode"], "answer": RULES["answers"][rule["answer"]], "rule_id": rule["id"]}
    return None


# ---------------------------------------------------------------- citations (legacy claims)

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


# ---------------------------------------------------------------- numbers (unit-aware)

# Units the assistant writes after a number, normalised. "/5" style scales are units too, so "4.1/5" is one
# number (4.1, unit /5) and the 5 is not checked on its own.
_UNITS = {
    "h": "h", "hr": "h", "hrs": "h", "hour": "h", "hours": "h",
    "min": "min", "mins": "min", "minute": "min", "minutes": "min",
    "ms": "ms", "s": "s", "sec": "s", "secs": "s", "seconds": "s",
    "bpm": "bpm", "mmhg": "mmHg", "%": "%", "percent": "%",
    "°c": "°C", "ºc": "°C", "c": "°C", "mg/dl": "mg/dL", "mg": "mg",
    "l": "L", "litre": "L", "litres": "L", "liter": "L", "liters": "L",
    "kg": "kg", "msv": "mSv", "msv/day": "mSv/day", "mg/dl.": "mg/dL",
}
_UNIT_ALT = r"mSv/day|mg/dL|mmHg|°C|ºC|bpm|hours?|hrs?|h|minutes?|mins?|min|ms|seconds?|secs?|s|percent|%|mSv|mg|kg|litres?|liters?|L|C"
# In the assistant's text a number glued to letters (SpO2, PHQ-2, day147, kb:...@1) is a name, not a value.
_TEXT_NUM = re.compile(r"(?<![\w.\-/@#:])(?P<num>-?\d+(?:\.\d+)?)(?:\s?(?P<unit>/\s?\d+|(?:" + _UNIT_ALT + r"))(?![A-Za-z]))?")
# In tool data every digit run counts (ids such as telemetry:h:sleep:day147 hold the day).
_BLOB_NUM = re.compile(r"(?P<num>\d+(?:\.\d+)?)(?:\s?(?P<unit>/\s?\d+|(?:" + _UNIT_ALT + r"))(?![A-Za-z]))?")


def _unit(u: Optional[str]) -> Optional[str]:
    if not u:
        return None
    u = u.replace(" ", "")
    if u.startswith("/"):
        return u
    return _UNITS.get(u.lower(), _UNITS.get(u, u))


def _dec(s: Any) -> Optional[Decimal]:
    try:
        return abs(Decimal(str(s)))
    except (InvalidOperation, ValueError):
        return None


def _blob_values(blob: str) -> List[Tuple[Decimal, Optional[str]]]:
    """(value, unit) pairs found in tool data. A JSON number gets the unit of a sibling "unit" key."""
    out: List[Tuple[Decimal, Optional[str]]] = []

    def walk(x: Any) -> None:
        if isinstance(x, dict):
            u = _unit(x["unit"]) if isinstance(x.get("unit"), str) else None
            for v in x.values():
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    d = _dec(v)
                    if d is not None:
                        out.append((d, u))
                else:
                    walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
        elif isinstance(x, (int, float)) and not isinstance(x, bool):
            d = _dec(x)
            if d is not None:
                out.append((d, None))
        elif isinstance(x, str):
            scan(x)

    def scan(s: str) -> None:
        for m in _BLOB_NUM.finditer(s):
            d = _dec(m.group("num"))
            if d is not None:
                out.append((d, _unit(m.group("unit"))))
                if m.group("unit") and m.group("unit").startswith("/"):
                    out.append((_dec(m.group("unit")[1:].strip()), None))

    try:
        walk(json.loads(blob))
    except (ValueError, TypeError):
        scan(blob)
    return out


def _places(num: str) -> int:
    return len(num.split(".", 1)[1]) if "." in num else 0


def _known(num: str, unit: Optional[str], have: Sequence[Tuple[Decimal, Optional[str]]]) -> bool:
    """A stated number is known when a tool value rounds to it (6.08 -> "6.1"; sign ignored, so a -1.3 delta
    supports "1.3 h below"). With a unit, a value tagged with a different unit does not count, so "104 bpm"
    is rejected when 104 exists only as "104 ms". A whole number only rounds from a value tagged with the
    same unit ("104 bpm" from 104.37 bpm); otherwise it must match exactly."""
    v = _dec(num)
    if v is None:
        return True
    q = Decimal(1).scaleb(-_places(num))
    for b, bu in have:
        if unit and bu and bu != unit:
            continue
        if b == v:
            return True
        if _places(num) == 0 and not (unit and bu == unit):
            continue
        if b.quantize(q, ROUND_HALF_UP) == v or b.quantize(q, ROUND_HALF_EVEN) == v:
            return True
    return False


def _unknown(text: str, blob: str) -> List[Tuple[str, Optional[str]]]:
    have = _blob_values(blob)
    out = []
    for m in _TEXT_NUM.finditer(text):
        num, unit = m.group("num"), _unit(m.group("unit"))
        if not _known(num.lstrip("-"), unit, have):
            out.append((num, unit))
    return out


def unknown_numbers(text: str, facts_blob: str) -> List[str]:
    """Numbers in `text` that do not appear in the facts (a briefing must not invent numbers). Unit-aware:
    "6.1 h" and "6.1 hours" are the same value, and a rounded tool value counts."""
    return [n for n, _ in _unknown(text, facts_blob)]


# ---------------------------------------------------------------- after the model

class PostcheckResult(NamedTuple):
    """`response` is the cleaned answer (None when the schema check failed). `hard_fail` means: do not show
    it, use the safe fallback (grounded route() answer or UNKNOWN) with mode "fallback" and report["reason"].
    `report` is the `guard` key of the API response: {dropped_claims, rejected_numbers, reason, rule_ids}."""
    response: Optional[AssistantResponse]
    report: Dict[str, Any]
    hard_fail: bool


_SENTENCE = re.compile(r"(?<=[.!?])\s+")
_PERSONAL_PREFIXES = tuple(p for p in DATA_SOURCE_PREFIXES if p != "nasa")  # {prefix}:{crew}:...


def _other_people(bound: str) -> List[Tuple[str, re.Pattern]]:
    """(crew id, name pattern) for everyone but the bound person: full, first and last name, accents folded."""
    out = []
    for c in CREW:
        if c["id"] == bound:
            continue
        parts = [_fold(c["name"])] + _fold(c["name"]).split()
        alt = "|".join(re.escape(p) for p in sorted(set(parts), key=len, reverse=True))
        out.append((c["id"], re.compile(rf"\b(?:{alt})\b")))
    return out


def _mentions_other_health(text: str, others: List[Tuple[str, re.Pattern]]) -> bool:
    folded = _fold(text)
    for _, name in others:
        hits = list(name.finditer(folded))
        if not hits:
            continue
        # "talk to Kenji Mori" names the medical officer as a contact, not as a patient
        if all(any(c.search(folded[:h.start()]) for c in _CONTACT_RE) for h in hits):
            continue
        if any(p.search(folded) for p in _HEALTH_RE):
            return True
    return False


def _foreign_source(source_id: str, bound: str) -> bool:
    parts = source_id.split(":")
    return source_prefix(source_id) in _PERSONAL_PREFIXES and len(parts) > 1 and parts[1] != bound


def _is_wellbeing(source_id: str) -> bool:
    parts = source_id.split(":")
    return len(parts) > 2 and parts[0] == "checkin" and parts[2] == "wellbeing"


_WORDING = ("G-OUT-DOSE-01", "G-OUT-DIAG-01", "G-OUT-SAFE-01")


def _wording_rule(text: str) -> Optional[str]:
    for rid in _WORDING:
        if _matches(_POST_RE[rid], text) or _gated_hit(_POST_GATED[rid], _fold(text)):
            return rid
    return None


def _privacy_rule(text: str, others) -> Optional[str]:
    if _mentions_other_health(text, others):
        return "G-PRIV-01"
    if _matches(_POST_RE["G-PRIV-02"], text):
        return "G-PRIV-02"
    return None


def _parse(response: Union[AssistantResponse, dict, str]) -> AssistantResponse:
    if isinstance(response, AssistantResponse):
        return AssistantResponse.model_validate(response.model_dump())
    if isinstance(response, (str, bytes)):
        return AssistantResponse.model_validate_json(response)
    return AssistantResponse.model_validate(response)


def _allowed_actions(goal_ids: Iterable[str], protocol_ids: Optional[Iterable[str]], medical: bool = False) -> set:
    if protocol_ids is None:
        from ..domain import protocols
        protocol_ids = protocols.resolve("earth")["protocols"].keys()
    goals = {g if g.startswith("goal:") else f"goal:{g}" for g in goal_ids}
    if medical:  # goals from accepted suggestions are astronaut-only (plan.md W1-2)
        goals = {g for g in goals if not g.startswith("goal:sg_")}
    protos = {p if p.startswith("protocol:") else f"protocol:{p}" for p in protocol_ids}
    return goals | protos | set(FIXED_ACTIONS)


def postcheck(response: Union[AssistantResponse, dict, str],
              allowed_sources: Iterable[str],
              tool_data_blob: Union[str, Any],
              *,
              ctx: ToolContext,
              goal_ids: Iterable[str] = (),
              protocol_ids: Optional[Iterable[str]] = None) -> PostcheckResult:
    """Check a model's final answer (plan.md Phase 4, "After the model").

    - response: the AssistantResponse (model, dict or raw JSON text).
    - allowed_sources: every source id the tools returned in this turn.
    - tool_data_blob: the tool results of this turn (JSON text, or any JSON-serialisable value).
    - ctx: the turn's ToolContext; ctx.crew_id is the bound person (the only crew member who may be named
      with health wording; a medical viewer is bound to whoever they asked about).
    - goal_ids: ids of today's goals for the bound person (`water`, `al_light`, `med_3`, `sg_x1`; with or
      without the `goal:` prefix); for a medical viewer `goal:sg_*` is never allowed. protocol_ids: defaults
      to the protocol bank.

    Checks, in order: schema (G-SCHEMA-01), sources exist (G-SRC-01), sources fit the claim type (G-SRC-02),
    numbers exist (G-NUM-01), forbidden wording (G-OUT-*), action allow-list (G-ACT-01), other people's
    health and crew averages (G-PRIV-01/02), wellbeing never a diagnosis (G-WELL-01), then honest status
    (G-STATUS-01) last, so every drop before it counts.

    A bad claim or limitation is dropped; a bad sentence about another person is cut from the answer; a bad
    action becomes null. Hard failures (use the fallback): invalid schema; an unknown number, dose, diagnosis,
    "this is safe" or wellbeing-diagnosis wording in the answer; an answer left empty after cuts.
    """
    report: Dict[str, Any] = {"dropped_claims": [], "rejected_numbers": [], "reason": None, "rule_ids": []}
    hits: List[str] = []

    def hit(rid: str) -> None:
        if rid not in hits:
            hits.append(rid)

    def fail(rid: str, reason: str) -> PostcheckResult:
        hit(rid)
        report["reason"] = reason
        report["rule_ids"] = hits
        return PostcheckResult(None if rid == "G-SCHEMA-01" else resp, report, True)

    # 1. schema
    resp: Optional[AssistantResponse] = None
    try:
        resp = _parse(response)
    except (ValidationError, ValueError, TypeError) as e:
        return fail("G-SCHEMA-01", f"G-SCHEMA-01: the answer is not a valid AssistantResponse ({type(e).__name__})")

    allowed = set(allowed_sources)
    blob = tool_data_blob if isinstance(tool_data_blob, str) else json.dumps(tool_data_blob, ensure_ascii=False, default=str)
    bound = ctx.crew_id
    others = _other_people(bound)

    def drop(field: str, statement: str, rid: str) -> None:
        hit(rid)
        report["dropped_claims"].append({"field": field, "statement": statement, "rule_id": rid})

    def check_claim(field: str, c: Union[Observation, Explanation]) -> Optional[dict]:
        ids = list(c.source_ids)
        # 2. sources exist
        if not ids or any(s not in allowed for s in ids):
            return drop(field, c.statement, "G-SRC-01")
        # 3. sources fit the claim type
        fits = is_data_source if field == "observations" else is_knowledge_source
        ids = [s for s in ids if fits(s)]
        if not ids:
            return drop(field, c.statement, "G-SRC-02")
        # 4. numbers exist (observations; explanations restate approved knowledge)
        if field == "observations":
            bad = _unknown(c.statement, blob)
            if bad:
                report["rejected_numbers"] += [f"{n} {u}" if u else n for n, u in bad]
                return drop(field, c.statement, "G-NUM-01")
        # 5. forbidden wording
        rid = _wording_rule(c.statement)
        if rid:
            return drop(field, c.statement, rid)
        # 8. other people's health / crew averages (by name or by another person's data id)
        if any(_foreign_source(s, bound) for s in c.source_ids):
            return drop(field, c.statement, "G-PRIV-01")
        rid = _privacy_rule(c.statement, others)
        if rid:
            return drop(field, c.statement, rid)
        # 9. wellbeing is never a diagnosis
        if any(_is_wellbeing(s) for s in c.source_ids) and _matches(_POST_RE["G-WELL-01"], c.statement):
            return drop(field, c.statement, "G-WELL-01")
        return {"statement": c.statement, "source_ids": ids}

    observations = [o for o in (check_claim("observations", c) for c in resp.observations) if o]
    explanations = [e for e in (check_claim("explanations", c) for c in resp.explanations) if e]

    limitations = []
    for text in resp.limitations:
        rid = _wording_rule(text) or _privacy_rule(text, others) or (
            "G-WELL-01" if _matches(_POST_RE["G-WELL-01"], text) else None)
        if rid:
            drop("limitations", text, rid)
        else:
            limitations.append(text)

    # answer: cut sentences about other people (8), then hard checks on what is left (4, 5, 9)
    kept = []
    for sentence in _SENTENCE.split(resp.answer.strip()):
        rid = _privacy_rule(sentence, others) if sentence else None
        if rid:
            drop("answer", sentence, rid)
        elif sentence:
            kept.append(sentence)
    answer = " ".join(kept)
    if resp.answer.strip() and not answer:
        return fail(hits[-1], f"{hits[-1]}: the whole answer was about another crew member or the crew")
    bad = _unknown(answer, blob)
    if bad:
        report["rejected_numbers"] += [f"{n} {u}" if u else n for n, u in bad]
        return fail("G-NUM-01", "G-NUM-01: the answer states numbers that no tool returned: "
                    + ", ".join(f"{n} {u}" if u else n for n, u in bad))
    rid = _wording_rule(answer)
    if rid:
        return fail(rid, f"{rid}: {_POST[rid]['description']}")
    if _matches(_POST_RE["G-WELL-01"], answer):
        return fail("G-WELL-01", f"G-WELL-01: {_POST['G-WELL-01']['description']}")

    # 6. action allow-list
    action = resp.recommended_action_id
    if action is not None and action not in _allowed_actions(goal_ids, protocol_ids, ctx.medical):
        hit("G-ACT-01")
        action = None

    # 7. honest status
    status = resp.status
    if status == "supported" and not observations:
        hit("G-STATUS-01")
        status = "insufficient_evidence"

    cleaned = AssistantResponse(status=status, answer=answer, observations=observations, explanations=explanations,
                                limitations=limitations, recommended_action_id=action)
    report["rule_ids"] = hits
    if hits:
        n = len(report["dropped_claims"])
        report["reason"] = "; ".join(filter(None, [
            f"{n} item(s) dropped" if n else "",
            "action not allowed, set to null" if "G-ACT-01" in hits else "",
            "no surviving observation, status set to insufficient_evidence" if "G-STATUS-01" in hits else "",
        ]))
    return PostcheckResult(cleaned, report, False)
