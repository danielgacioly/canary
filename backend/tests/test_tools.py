"""Phase 1 tools: strict schemas, the bound ToolContext, the visibility rule, the envelope and route()."""
import json
import os
import tempfile
import time

os.environ.setdefault("CANARY_DB", os.path.join(tempfile.mkdtemp(), "test_tools.db"))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from canary import db  # noqa: E402
from canary.assistant import contracts as C  # noqa: E402
from canary.assistant import kb, tools  # noqa: E402
from canary.domain import catalog, mission, selftests  # noqa: E402
from canary.main import app  # noqa: E402

client = TestClient(app)
CREW_IDS = [c["id"] for c in catalog.CREW]

VALID_ARGS = {
    "get_status": {},
    "get_indicator": {"ind": "sleep"},
    "explain_system": {"sys": "brain"},
    "get_protocol": {"pid": "seizure"},
    "list_goals": {},
    "get_checkins": {"kind": "any", "days": 14},
    "get_weekly_summary": {},
    "search_knowledge": {"query": "why is my sleep worse", "kind": "any", "k": 4},
}


@pytest.fixture(autouse=True)
def fresh():
    client.post("/api/demo/reset")
    client.put("/api/mission", json={"step": 2})  # day 147, Helena's slide
    yield
    client.post("/api/demo/reset")


def ctx(cid="h", viewer=None, medical=False):
    return C.ToolContext(crew_id=cid, viewer=viewer or cid, medical=medical, mission=mission.state())


def add_checkin(cid, kind, payload, day=None):
    day = mission.state()["day"] if day is None else day
    db.x("INSERT INTO checkins(crew_id,day,kind,payload,created_at) VALUES(?,?,?,?,?)",
         (cid, day, kind, json.dumps(selftests.normalise(kind, payload)), time.time()))


# ---------------------------------------------------------------- schemas

def test_every_tool_has_a_valid_args_case():
    assert set(VALID_ARGS) == set(tools.TOOLS)


def test_anthropic_tools_are_strict_and_have_no_crew_id():
    rendered = tools.anthropic_tools()
    assert [t["name"] for t in rendered] == list(tools.TOOLS)
    for t in rendered:
        assert t["strict"] is True and t["description"]
        s = t["input_schema"]
        assert s["type"] == "object" and s["additionalProperties"] is False
        assert s["required"] == list(s["properties"])
        assert "crew_id" not in s["properties"] and "viewer" not in s["properties"]
        blob = json.dumps(s)
        for kw in ("minimum", "maximum", "maxLength"):
            assert f'"{kw}"' not in blob  # not in the strict grammar; enforced by validate_args


def test_enums_come_from_the_catalogue():
    props = {t["name"]: t["input_schema"]["properties"] for t in tools.anthropic_tools()}
    assert props["get_indicator"]["ind"]["enum"] == list(catalog.INDICATORS)
    assert props["explain_system"]["sys"]["enum"] == list(catalog.SYSTEMS)
    assert set(props["get_protocol"]["pid"]["enum"]) == {"cpr", "seizure", "choke", "chest", "allergy", "bleed", "eye", "crisis", "rad", "triage"}
    kinds = props["get_checkins"]["kind"]["enum"]
    assert len(kinds) == 14 and kinds[-1] == "any" and set(kinds[:-1]) == selftests.TEST_IDS
    assert set(props["search_knowledge"]["kind"]["enum"]) == {"protocol", "system_card", "location", "nasa_source",
                                                              "hazard", "privacy", "self_test", "any"}


@pytest.mark.parametrize("name", list(VALID_ARGS))
def test_valid_args_accepted(name):
    assert tools.validate_args(name, VALID_ARGS[name]) is None
    r = tools.run_tool(ctx(), name, VALID_ARGS[name])
    assert r.ok, r.error


@pytest.mark.parametrize("name", list(VALID_ARGS))
def test_unknown_keys_and_crew_ids_rejected(name):
    for extra in ({"crew_id": "k"}, {"viewer": "medical"}, {"nope": 1}):
        r = tools.run_tool(ctx(), name, {**VALID_ARGS[name], **extra})
        assert not r.ok and r.sources == [] and "unknown argument" in r.error


@pytest.mark.parametrize("name,args", [
    ("get_indicator", {"ind": "cholesterol"}), ("get_indicator", {}), ("explain_system", {"sys": 3}),
    ("get_protocol", {"pid": "surgery"}), ("get_checkins", {"kind": "iq", "days": 3}),
    ("get_checkins", {"kind": "kss", "days": 0}), ("get_checkins", {"kind": "kss", "days": 15}),
    ("get_checkins", {"kind": "kss", "days": True}), ("get_checkins", {"kind": "kss", "days": "3"}),
    ("search_knowledge", {"query": "x" * 201, "kind": "any", "k": 3}), ("search_knowledge", {"query": " ", "kind": "any", "k": 3}),
    ("search_knowledge", {"query": "sleep", "kind": "any", "k": 7}), ("search_knowledge", {"query": "sleep", "kind": "web", "k": 2}),
    ("get_status", ["h"]), ("no_such_tool", {}),
])
def test_bad_args_rejected(name, args):
    r = tools.run_tool(ctx(), name, args)
    assert not r.ok and r.sources == [] and r.data is None


# ---------------------------------------------------------------- envelope

def test_tools_never_raise(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("database is gone")
    monkeypatch.setattr(tools.health, "snapshot", boom)
    r = tools.run_tool(ctx(), "get_status", {})
    assert isinstance(r, C.ToolResult) and not r.ok and r.sources == [] and "database is gone" not in r.error
    assert not tools.run_tool(None, "get_status", {}).ok  # no context bound: error, not an exception


def test_results_are_envelopes():
    for name, args in VALID_ARGS.items():
        r = tools.run_tool(ctx(), name, args)
        dumped = r.model_dump()
        assert set(dumped) == {"data", "sources", "error"}
        C.ToolResult(**dumped)


# ---------------------------------------------------------------- visibility

@pytest.mark.parametrize("cid", CREW_IDS)
@pytest.mark.parametrize("medical", [False, True])
def test_no_result_reaches_another_person(cid, medical):
    for other in CREW_IDS:
        add_checkin(other, "kss", {"level": 8})
        add_checkin(other, "wellbeing", {"answers": [2, 2, 1, 1]})
    c = ctx(cid, viewer="medical" if medical else cid, medical=medical)
    others = [x for x in catalog.CREW if x["id"] != cid]
    for name, args in VALID_ARGS.items():
        r = tools.run_tool(c, name, args)
        assert r.ok, (name, r.error)
        for s in r.sources:
            parts = s.split(":")
            if parts[0] in ("telemetry", "status", "goals", "checkin", "summary"):
                assert parts[1] == cid, (name, s)
        blob = json.dumps(r.data)
        for o in others:
            assert f":{o['id']}:" not in blob and o["name"] not in blob, (name, o["name"])
        for word in ("average", "leaderboard", "rank", "xp", "points", "level_up"):
            assert f'"{word}"' not in blob.lower(), (name, word)
        for key in C.SETTINGS_NEVER_RETURNED:
            assert f'"{key}"' not in blob


def test_another_astronaut_cannot_bind_a_context():
    with pytest.raises(Exception):
        C.ToolContext(crew_id="h", viewer="k", medical=False)


def test_result_naming_someone_else_is_withheld(monkeypatch):
    monkeypatch.setitem(tools.TOOLS["list_goals"], "fn", lambda c: C.ToolResult(data=[], sources=["goals:k:day147"]))
    r = tools.run_tool(ctx("h"), "list_goals", {})
    assert not r.ok and r.sources == []


def test_settings_keys_are_stripped(monkeypatch):
    leak = {"ok": 1, "pins": {"h": "x"}, "nested": [{"photos": "data:", "suggested_goals": [], "keep": True}]}
    monkeypatch.setitem(tools.TOOLS["get_status"], "fn", lambda c: C.ToolResult(data=leak, sources=["status:h:day147"]))
    r = tools.run_tool(ctx("h"), "get_status", {})
    assert r.data == {"ok": 1, "nested": [{"keep": True}]}


# ---------------------------------------------------------------- tools

def test_get_checkins_kinds_journal_and_wellbeing():
    add_checkin("h", "kss", {"level": 8})
    add_checkin("h", "journal", {"lines": 3, "text": "a private thought"})
    add_checkin("h", "wellbeing", {"answers": [2, 2, 0, 1]})
    add_checkin("h", "mood", {"mood": 2, "stress": 4}, day=mission.state()["day"] - 20)  # outside 14 days
    add_checkin("k", "kss", {"level": 2})
    r = tools.run_tool(ctx("h"), "get_checkins", {"kind": "any", "days": 14})
    kinds = [x["kind"] for x in r.data["checkins"]]
    assert sorted(kinds) == ["journal", "kss", "wellbeing"]
    assert "private thought" not in json.dumps(r.data)
    j = next(x for x in r.data["checkins"] if x["kind"] == "journal")
    assert j["values"] == {"lines": 3}
    w = next(x for x in r.data["checkins"] if x["kind"] == "wellbeing")
    assert w["values"] == {"phq2": 4, "gad2": 1} and "answers" not in w["values"]
    assert "checkin:h:kss:day147" in r.sources
    only = tools.run_tool(ctx("h"), "get_checkins", {"kind": "kss", "days": 1})
    assert [x["kind"] for x in only.data["checkins"]] == ["kss"] and only.sources == ["checkin:h:kss:day147"]
    # the medical team may read wellbeing; another astronaut cannot even bind a context
    assert tools.run_tool(ctx("h", viewer="medical", medical=True), "get_checkins", {"kind": "wellbeing", "days": 14}).data["count"] == 1


def test_list_goals_has_no_xp_or_points():
    r = tools.run_tool(ctx("h"), "list_goals", {})
    assert r.data and all(set(g) == {"id", "area", "title", "by", "done"} for g in r.data)
    assert {g["by"] for g in r.data} <= {"routine", "alert", "medical", "suggestion"}
    assert any(g["id"] == "al_light" for g in r.data)
    assert r.sources == ["goals:h:day147"]


def test_weekly_summary_reuses_briefing_facts():
    from canary.assistant import briefing
    r = tools.run_tool(ctx("h"), "get_weekly_summary", {})
    assert r.data == briefing.facts("h") and r.sources == ["summary:h:day147:7d"]


def test_search_knowledge_passes_place_and_gravity(monkeypatch):
    seen = {}

    def fake(query, kind="any", k=4, gravity=None, place=None):
        seen.update(query=query, kind=kind, k=k, gravity=gravity, place=place)
        return [kb.Chunk(chunk_id="kb:CARD-BRAIN@1#summary", doc_id="CARD-BRAIN", version=1, title="Brain",
                         text="Isolation erodes sleep.", score=0.9, section="summary")] * 5
    monkeypatch.setattr(tools.kb, "search", fake)
    loc = mission.state()["location"]
    r = tools.run_tool(ctx("h"), "search_knowledge", {"query": "sleep", "kind": "system_card", "k": 2})
    assert seen == {"query": "sleep", "kind": "system_card", "k": 2, "place": loc,
                    "gravity": catalog.LOCATIONS[loc]["gravity_key"]}
    assert len(r.data["chunks"]) == 2 and r.sources == ["kb:CARD-BRAIN@1#summary"]


def test_search_knowledge_without_evidence(monkeypatch):
    monkeypatch.setattr(tools.kb, "search", lambda *a, **k: [])
    r = tools.run_tool(ctx("h"), "search_knowledge", {"query": "cholesterol", "kind": "any", "k": 3})
    assert r.ok and r.sources == [] and r.data["chunks"] == [] and r.data["evidence"] == "none"


# ---------------------------------------------------------------- route (no-model path)

def test_route_still_works_without_a_context():
    out = tools.route("h", "Why is my sleep so bad?")
    assert out and all(set(o) == {"tool", "args", "result"} for o in out)
    assert all("crew_id" not in o["args"] for o in out)
    sleep = next(o for o in out if o["tool"] == "get_indicator")
    assert sleep["args"] == {"ind": "sleep"} and sleep["result"]["sources"] == ["telemetry:h:sleep:day147"]
    assert set(sleep["result"]) == {"data", "sources", "error"}


def test_route_uses_the_given_context_only_for_its_person():
    assert tools.route("t", "how am I today? goals?", ctx("t"))
    assert tools.route("h", "how am I", ctx("t")) == []  # a context bound to someone else answers nothing
    out = tools.route("h", "status and my goals", ctx("h", viewer="medical", medical=True))
    assert [o["tool"] for o in out] == ["get_status", "list_goals"]


def test_schema_for_status_endpoint():
    s = tools.schema()
    assert [t["name"] for t in s] == list(tools.TOOLS) and all(t["description"] for t in s)
