"""Wave 0 contracts: AssistantResponse / BriefingDraft shapes, their structured-output schemas, the action
id format, the kb stub, the scripted provider and the assistant_log migration (docs/ai/schema.md)."""
import os
import sqlite3
import tempfile

import pytest
from pydantic import ValidationError

from canary import db
from canary.assistant import contracts as C
from canary.assistant import kb
from canary.assistant.providers import ProviderRequest
from fakes import ScriptedProvider, answer

# schema.md §6
GOOD_RESPONSE = {
    "status": "supported",
    "answer": "Your sleep is 1.3 h below your normal this week.",
    "observations": [{"statement": "Sleep 6.1 h, normal 7.4 h", "source_ids": ["telemetry:h:sleep:day147"]}],
    "explanations": [{"statement": "Isolation and shifted light cycles commonly erode sleep on long missions.",
                      "source_ids": ["kb:CARD-BRAIN@1#summary"]}],
    "limitations": ["The data does not show the cause of the change."],
    "recommended_action_id": "goal:al_light",
}

# schema.md §7
GOOD_BRIEFING = {
    "sections": [
        {"heading": "What worries", "lines": [{"text": "Sleep, mood and focus dropping together.",
                                               "source_ids": ["telemetry:h:sleep:day147"]}]},
        {"heading": "What changed", "lines": []},
        {"heading": "What was tried", "lines": []},
    ],
    "missing_information": ["No blood pressure reading in the last 3 days."],
    "needs_medical_review": ["Reaction time 2.6 sigma above normal."],
}


def with_(base, **kw):
    return {**base, **kw}


def test_good_examples_validate():
    r = C.AssistantResponse.model_validate(GOOD_RESPONSE)
    assert r.status == "supported" and r.observations[0].source_ids == ["telemetry:h:sleep:day147"]
    b = C.BriefingDraft.model_validate(GOOD_BRIEFING)
    assert [s.heading for s in b.sections] == ["What worries", "What changed", "What was tried"]


@pytest.mark.parametrize("bad", [
    with_(GOOD_RESPONSE, status="maybe"),
    with_(GOOD_RESPONSE, observations=[{"statement": "Sleep 6.1 h", "source_ids": []}]),
    with_(GOOD_RESPONSE, observations=[{"statement": "Sleep 6.1 h"}]),
    with_(GOOD_RESPONSE, explanations=[{"statement": "x", "source_ids": [], "extra": 1}]),
    with_(GOOD_RESPONSE, answer="x" * 601),
    with_(GOOD_RESPONSE, recommended_action_id="launch_rocket"),
    with_(GOOD_RESPONSE, recommended_action_id="goal:"),
    with_(GOOD_RESPONSE, recommended_action_id="protocol:Seizure; drop"),
    with_(GOOD_RESPONSE, surprise="extra key"),
    {k: v for k, v in GOOD_RESPONSE.items() if k != "recommended_action_id"},
])
def test_bad_responses_rejected(bad):
    with pytest.raises(ValidationError):
        C.AssistantResponse.model_validate(bad)


@pytest.mark.parametrize("action", [None, "goal:al_light", "goal:sg_x1", "goal:med_3", "goal:water",
                                    "protocol:seizure", "contact_cmo", "send_briefing"])
def test_allowed_action_formats(action):
    assert C.AssistantResponse.model_validate(with_(GOOD_RESPONSE, recommended_action_id=action))


def test_bad_briefing_rejected():
    bad = {**GOOD_BRIEFING, "sections": [{"heading": "What worries", "lines": [{"text": "x", "source_ids": []}]}]}
    with pytest.raises(ValidationError):
        C.BriefingDraft.model_validate(bad)
    with pytest.raises(ValidationError):
        C.BriefingDraft.model_validate({"sections": []})


def test_source_prefixes():
    assert C.is_data_source("telemetry:h:sleep:day147") and C.is_data_source("summary:h:day147:7d")
    assert not C.is_data_source("kb:CARD-BRAIN@1#summary")
    assert C.is_knowledge_source("kb:PROTO-NEURO-001@1#s2") and C.is_knowledge_source("kb:PROTO-NEURO-001@1#s2-g0")
    assert C.is_knowledge_source("card:brain") and C.is_knowledge_source("protocol:seizure")
    assert not C.is_knowledge_source("kb:CARD-BRAIN#summary")  # unversioned
    assert not C.is_knowledge_source("telemetry:h:sleep:day147")
    assert not set(C.DATA_SOURCE_PREFIXES) & set(C.KNOWLEDGE_SOURCE_PREFIXES + C.LEGACY_KNOWLEDGE_PREFIXES)


def test_tool_result_envelope():
    ok = C.ToolResult(data={"v": 1}, sources=["status:h:day2"])
    assert ok.ok and ok.model_dump() == {"data": {"v": 1}, "sources": ["status:h:day2"], "error": None}
    assert not C.ToolResult.fail("boom").ok
    with pytest.raises(ValidationError):
        C.ToolResult(data=None, sources=["status:h:day2"], error="boom")
    ctx = C.ToolContext(crew_id="h", viewer="h", medical=False, mission={"day": 2})
    with pytest.raises(ValidationError):
        ctx.crew_id = "k"  # frozen: the bound person cannot change mid-question


def test_tool_context_binds_viewer():
    assert C.ToolContext(crew_id="h", viewer="medical", medical=True).medical
    assert C.ToolContext(crew_id="h", viewer="k", medical=True)  # a medical-team session may ask about anyone
    with pytest.raises(ValidationError):
        C.ToolContext(crew_id="h")  # viewer and medical are required
    with pytest.raises(ValidationError):
        C.ToolContext(crew_id="h", viewer="h")
    with pytest.raises(ValidationError):
        C.ToolContext(crew_id="h", viewer="k", medical=False)  # another astronaut never sees Helena's data
    with pytest.raises(ValidationError):
        C.ToolContext(crew_id="h", viewer="medical", medical=False)
    assert "never crew averages" in C.VISIBILITY


def test_ai_entries():
    assert C.AI_ENTRIES == ("chat", "briefing", "suggestions")
    assert C.ENTRIES_WITH_TOOLS == ("chat",)
    assert set(C.SETTINGS_NEVER_RETURNED) == {"suggested_goals", "pins", "photos"}


def _walk_objects(node):
    if isinstance(node, dict):
        if node.get("type") == "object":
            yield node
        for v in node.values():
            yield from _walk_objects(v)
    elif isinstance(node, list):
        for v in node:
            yield from _walk_objects(v)


@pytest.mark.parametrize("model", C.STRUCTURED_MODELS)
def test_json_schemas_are_strict(model):
    schema = C.json_schema(model)
    objects = list(_walk_objects(schema))
    assert len(objects) >= 2
    for obj in objects:
        assert obj["additionalProperties"] is False
        assert sorted(obj["required"]) == sorted(obj["properties"])
    text = repr(schema)
    for kw in ("maxLength", "minItems", "pattern", "default"):
        assert f"'{kw}'" not in text
    assert C.output_format(model) == {"type": "json_schema", "schema": schema}


def test_nullable_action_is_required_but_nullable():
    s = C.json_schema(C.AssistantResponse)
    assert "recommended_action_id" in s["required"]
    assert {"type": "null"} in s["properties"]["recommended_action_id"]["anyOf"]


def test_kb_stub():
    hits = kb.search("seizure", kind="protocol", k=3, gravity="g0", place="transit")
    assert isinstance(hits, list) and len(hits) <= 3
    assert all(isinstance(h, kb.Chunk) and h.chunk_id.startswith("kb:") and "@" in h.chunk_id for h in hits)
    c = kb.Chunk(chunk_id="kb:PROTO-NEURO-001@1#s2", doc_id="PROTO-NEURO-001", version=1, title="Seizure",
                 text="Protect the head.", score=0.5, section="step", gravity="g0")
    assert c.as_tool_data() == {"chunk_id": c.chunk_id, "title": "Seizure", "text": "Protect the head.", "score": 0.5}


def test_scripted_provider_replays_turns():
    p = ScriptedProvider([answer("hi"), TimeoutError("slow")])
    req = ProviderRequest(task="chat", system="s", question="q")
    assert p.complete(req).answer == "hi"
    with pytest.raises(TimeoutError):
        p.complete(req)
    assert p.calls == 2 and p.exhausted
    with pytest.raises(AssertionError):
        p.complete(req)


def test_migration_adds_columns_to_old_assistant_log():
    path = os.path.join(tempfile.mkdtemp(), "old.db")
    old = sqlite3.connect(path)
    old.execute("CREATE TABLE assistant_log (id INTEGER PRIMARY KEY AUTOINCREMENT, crew_id TEXT NOT NULL, "
                "question TEXT NOT NULL, response TEXT NOT NULL, created_at REAL NOT NULL)")
    old.execute("INSERT INTO assistant_log(crew_id,question,response,created_at) VALUES('h','q','{}',1.0)")
    old.commit()
    old.close()

    conn = sqlite3.connect(path)
    conn.executescript(db.SCHEMA)  # what connect() does, on a separate connection
    db.migrate(conn)
    db.migrate(conn)  # idempotent
    cols = {r[1] for r in conn.execute("PRAGMA table_info(assistant_log)")}
    assert {name for name, _ in db.ADDED_COLUMNS["assistant_log"]} <= cols
    assert conn.execute("SELECT question, outcome FROM assistant_log").fetchall() == [("q", None)]
    turns = {r[1] for r in conn.execute("PRAGMA table_info(assistant_turns)")}
    assert turns == {"id", "log_id", "step", "tool", "args", "sources", "ok"}
    conn.close()
