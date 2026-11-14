"""Contracts shared by the AI layer: tool context and results, the model's final answer and the briefing draft.

The source of truth for every shape here is docs/ai/schema.md (§2 source ids, §5 tool envelope,
§6 AssistantResponse, §7 BriefingDraft). When one changes, update the other in the same change.

Visibility (domain/privacy.py, main.py `require_self`): the AI layer answers only about the person bound to
the question, and only to that person or the medical team. See VISIBILITY below.

What these models check is the *shape*. The *meaning* (an id was returned by a tool in this turn,
an observation cites data and not knowledge, every number appears in tool results) is guard.py's
job, so the guard can drop a single bad claim instead of rejecting the whole answer.
"""
import copy
import re
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# ---------------------------------------------------------------- AI entries (schema.md §6, plan.md Phase 2)

# Every way the backend calls a model, as `ProviderRequest.task`. Only "chat" gets tools; "briefing" rewrites
# computed facts (BriefingDraft) and "suggestions" rephrases each suggestion's "why" as a JSON list
# [{id, why}], checked with guard.unknown_numbers. Suggestions are astronaut-only, never for the medical team.
AI_ENTRIES = ("chat", "briefing", "suggestions")
ENTRIES_WITH_TOOLS = ("chat",)

# `settings` keys the AI layer may read through domain code but no tool ever returns (schema.md §4).
SETTINGS_NEVER_RETURNED = ("suggested_goals", "pins", "photos")

# ---------------------------------------------------------------- source ids (schema.md §2)

# Facts from data: allowed in `observations`.
DATA_SOURCE_PREFIXES = ("telemetry", "status", "goals", "checkin", "nasa", "summary")
# Approved knowledge: allowed in `explanations`. `card` and `protocol` are legacy aliases of `kb` documents.
KNOWLEDGE_SOURCE_PREFIXES = ("kb",)
LEGACY_KNOWLEDGE_PREFIXES = ("card", "protocol")
ALL_SOURCE_PREFIXES = DATA_SOURCE_PREFIXES + KNOWLEDGE_SOURCE_PREFIXES + LEGACY_KNOWLEDGE_PREFIXES

# kb:{doc_id}@{version}#{chunk}, e.g. kb:PROTO-NEURO-001@1#s2 (always versioned).
KB_SOURCE_RE = re.compile(r"^kb:[A-Z0-9]+(?:-[A-Z0-9]+)*@\d+#[a-z0-9]+(?:-[a-z0-9]+)*$")


def source_prefix(source_id: str) -> str:
    """'telemetry:h:sleep:day147' -> 'telemetry'."""
    return source_id.split(":", 1)[0]


def is_data_source(source_id: str) -> bool:
    return source_prefix(source_id) in DATA_SOURCE_PREFIXES


def is_knowledge_source(source_id: str) -> bool:
    """True for a well-formed versioned `kb:` id or a legacy `card:` / `protocol:` alias."""
    p = source_prefix(source_id)
    if p == "kb":
        return bool(KB_SOURCE_RE.match(source_id))
    return p in LEGACY_KNOWLEDGE_PREFIXES


# ---------------------------------------------------------------- action allow-list format (schema.md §6)

# Allowed formats of `recommended_action_id`. `goal:` / `protocol:` ids are further checked by the guard
# against today's goals and the protocol catalogue; this only fixes the format. null means no action.
# Goal ids include routine ids (`water`), alert goals (`al_light`), medical goals (`med_3`) and accepted
# suggestions (`sg_{sid}`, domain/goals.py).
ACTION_ID_RE = re.compile(r"^(?:goal:[A-Za-z0-9_\-]+|protocol:[a-z0-9_]+|contact_cmo|send_briefing)$")
FIXED_ACTIONS = ("contact_cmo", "send_briefing")


def is_valid_action_id(action_id: Optional[str]) -> bool:
    return action_id is None or bool(ACTION_ID_RE.match(action_id))


# ---------------------------------------------------------------- tools (schema.md §5)

VISIBILITY = (
    "Tools return only the bound person's own data (ToolContext.crew_id), and only when the viewer is that "
    "person or the medical team. They never return another crew member's data, status, indicators or scores, "
    "and never crew averages (with four people an average reveals individuals). Wellbeing check-ins "
    "(PHQ-2 / GAD-2) are mental-health data: self or medical only, never phrased as a diagnosis."
)

MEDICAL_VIEWER = "medical"


class ToolContext(BaseModel):
    """Server-side context every tool call runs in, built from `main.viewer` after `require_self` passed.

    `crew_id` is the person the question is about, bound by the server and never a model argument, so the
    model cannot read another astronaut's data. `viewer` is who is asking: the signed-in astronaut's crew id,
    or "medical" for the medical team (who may ask about anyone). A viewer who is not medical must be the
    bound person (VISIBILITY)."""
    model_config = ConfigDict(frozen=True)

    crew_id: str
    viewer: str
    medical: bool
    mission: Dict[str, Any] = Field(default_factory=dict)  # mission.state() at the start of the question

    @model_validator(mode="after")
    def _viewer_may_see(self) -> "ToolContext":
        if not self.medical and self.viewer != self.crew_id:
            raise ValueError("only the person or the medical team may ask about this person's data")
        if self.viewer == MEDICAL_VIEWER and not self.medical:
            raise ValueError('viewer "medical" requires medical=True')
        return self


class ToolResult(BaseModel):
    """Envelope of every tool result: {data, sources, error}. A tool that fails returns `error` and no
    sources; it never raises into the loop. `data` follows VISIBILITY: only the bound person's own data."""
    model_config = ConfigDict(extra="forbid")

    data: Any = None
    sources: List[str] = Field(default_factory=list)
    error: Optional[str] = None

    @model_validator(mode="after")
    def _error_has_no_sources(self) -> "ToolResult":
        if self.error is not None and self.sources:
            raise ValueError("a failed tool result must not carry sources")
        return self

    @property
    def ok(self) -> bool:
        return self.error is None

    @classmethod
    def fail(cls, error: str) -> "ToolResult":
        return cls(data=None, sources=[], error=error)


# ---------------------------------------------------------------- final answer (schema.md §6)

class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Observation(_Strict):
    """A fact from data. The guard requires data source ids (DATA_SOURCE_PREFIXES) and checks numbers."""
    statement: str = Field(min_length=1)
    source_ids: List[str] = Field(min_length=1)


class Explanation(_Strict):
    """A possible explanation from approved knowledge. The guard requires `kb:` (or legacy) ids."""
    statement: str = Field(min_length=1)
    source_ids: List[str] = Field(min_length=1)


Status = Literal["supported", "insufficient_evidence", "out_of_scope"]


class AssistantResponse(_Strict):
    """What the model must return for a chat question (requested with `output_config.format`)."""
    status: Status
    answer: str = Field(max_length=600)
    observations: List[Observation]
    explanations: List[Explanation]
    limitations: List[str]
    recommended_action_id: Optional[str]

    @field_validator("recommended_action_id")
    @classmethod
    def _action_format(cls, v: Optional[str]) -> Optional[str]:
        if not is_valid_action_id(v):
            raise ValueError(f"recommended_action_id {v!r} is not an allowed action format")
        return v


# ---------------------------------------------------------------- briefing (schema.md §7)

class BriefingLine(_Strict):
    text: str = Field(min_length=1)
    source_ids: List[str] = Field(min_length=1)


class BriefingSection(_Strict):
    heading: str = Field(min_length=1)
    lines: List[BriefingLine]


class BriefingDraft(_Strict):
    """The model rewrites computed facts as prose; sections stay in priority order."""
    sections: List[BriefingSection]
    missing_information: List[str]
    needs_medical_review: List[str]


# ---------------------------------------------------------------- JSON Schema for structured outputs

# Keywords the structured-outputs grammar does not accept. Pydantic still enforces them when the backend
# re-validates the answer, so dropping them from the request schema loses nothing.
_UNSUPPORTED_KEYWORDS = ("minLength", "maxLength", "minItems", "maxItems", "pattern", "minimum", "maximum",
                         "exclusiveMinimum", "exclusiveMaximum", "multipleOf", "default", "title")


def _strictify(node: Any) -> Any:
    if isinstance(node, dict):
        out = {}
        for k, v in node.items():
            if k in ("properties", "$defs"):  # maps of names -> schemas: keep every name
                out[k] = {name: _strictify(sub) for name, sub in v.items()}
            elif k not in _UNSUPPORTED_KEYWORDS:
                out[k] = _strictify(v)
        if out.get("type") == "object" or "properties" in out:
            out["type"] = "object"
            props = out.setdefault("properties", {})
            out["required"] = list(props)  # nullable fields stay required, typed as anyOf [..., null]
            out["additionalProperties"] = False
        return out
    if isinstance(node, list):
        return [_strictify(v) for v in node]
    return node


def json_schema(model: type) -> Dict[str, Any]:
    """The model's JSON Schema for structured model outputs: every object has
    `additionalProperties: false` and lists all its properties as required; unsupported constraints
    (lengths, patterns, defaults) are removed and enforced by pydantic on the way back instead.

    Use as: generationConfig={"responseMimeType": "application/json",
    "responseJsonSchema": json_schema(AssistantResponse)}.
    """
    return _strictify(copy.deepcopy(model.model_json_schema()))


def output_format(model: type) -> Dict[str, Any]:
    """`output_config.format` value for a contract model."""
    return {"type": "json_schema", "schema": json_schema(model)}


STRUCTURED_MODELS = (AssistantResponse, BriefingDraft)
