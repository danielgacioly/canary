"""Phase 2: the provider loop with a scripted fake model. No network, no API key.

Covers the manual tool loop (validate -> run_tool -> log -> all results in one message), every loop guard
(rounds, tool budget, repeats, deadline), every exit to the grounded fallback (guard hard fail, refusal,
max_tokens, bad output, API errors, timeout), the briefing and suggestions entries, the request settings
sent to the Messages API, and the medical audit route.
"""
import json
import os
import tempfile
import time

os.environ.setdefault("CANARY_DB", os.path.join(tempfile.mkdtemp(), "test_chat_loop.db"))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import fakes  # noqa: E402
from fakes import ScriptedProvider, final, refusal, response, tool_use  # noqa: E402

from canary import db  # noqa: E402
from canary.assistant import briefing, chat, providers, suggestions, tools  # noqa: E402
from canary.assistant.contracts import ToolContext  # noqa: E402
from canary.config import settings  # noqa: E402
from canary.domain import mission  # noqa: E402
from canary.main import app  # noqa: E402

client = TestClient(app)
PINS = {"h": "1001", "k": "1002", "a": "1003", "t": "1004"}
QUESTION = "Why is my sleep worse?"


@pytest.fixture(autouse=True)
def fresh():
    client.post("/api/demo/reset")
    client.put("/api/mission", json={"step": 2})  # day 147, Helena's slide
    yield
    client.post("/api/demo/reset")


def as_(cid):
    return {"X-Canary-Viewer": client.post(f"/api/crew/{cid}/session", json={"pin": PINS[cid]}).json()["token"]}


def medical():
    r = client.post("/api/medical/session", json={"pin": settings.medical_pin})
    return {"Authorization": f"Bearer {r.json()['token']}"}


def use(monkeypatch, p, *modules):
    for m in modules or (chat,):
        monkeypatch.setattr(m, "get_provider", lambda: p)
    return p


def ctx(cid="h"):
    return ToolContext(crew_id=cid, viewer=cid, medical=False, mission=mission.state())


def sleep_obs():
    """A true observation about Helena's sleep, built from the real tool result."""
    r = tools.run_tool(ctx(), "get_indicator", {"ind": "sleep"})
    d = r.data
    return f"Sleep {d['value']:.{d['dp']}f} h, normal {d['baseline']:.{d['dp']}f} h.", r.sources


def good_answer(**kw):
    s, src = sleep_obs()
    return response("Your sleep is below your own normal this week.", observations=[(s, src)],
                    limitations=["The data does not show the cause."], **kw)


def ask(monkeypatch, messages, question=QUESTION):
    p = use(monkeypatch, ScriptedProvider(messages=messages))
    return p, client.post("/api/assistant/ask", json={"crew_id": "h", "question": question}, headers=as_("h")).json()


def log_row(rid):
    return db.q("SELECT * FROM assistant_log WHERE id=?", (rid,))[0]


# ---------------------------------------------------------------- the happy path

def test_tool_use_then_supported_answer(monkeypatch):
    p, r = ask(monkeypatch, [tool_use(("get_indicator", {"ind": "sleep"}), ("list_goals", {})),
                             final(good_answer(action="goal:al_light"))])
    assert r["mode"] == "ai" and r["status"] == "supported" and r["provider"] == "scripted"
    _, src = sleep_obs()
    assert r["observations"][0]["source_ids"] == src and r["claims"][0]["source_ids"] == src
    assert r["explanations"] == [] and r["limitations"] == ["The data does not show the cause."]
    assert r["recommended_action"]["id"] == "goal:al_light" and r["recommended_action"]["label"]
    assert r["guard"]["reason"] is None and r["guard"]["dropped_claims"] == []
    assert [t["tool"] for t in r["tools_used"]] == ["get_indicator", "list_goals"]
    assert r["prompt_version"] == "system_v1" and r["source_meta"] == {}
    for key in ("answer", "claims", "sources", "tools_used", "dropped", "provider", "provider_error", "id"):
        assert key in r

    row = log_row(r["id"])
    assert row["provider"] == "scripted" and row["model"] == "claude-sonnet-5-5" and row["outcome"] == "ai"
    assert row["input_tokens"] == 200 and row["output_tokens"] == 100 and row["latency_ms"] >= 0
    assert json.loads(row["guard_flags"]) == []
    turns = db.q("SELECT step,tool,args,sources,ok FROM assistant_turns WHERE log_id=? ORDER BY id", (r["id"],))
    assert [(t["step"], t["tool"], t["ok"]) for t in turns] == [(1, "get_indicator", 1), (1, "list_goals", 1)]
    assert json.loads(turns[0]["args"]) == {"ind": "sleep"} and json.loads(turns[0]["sources"]) == src

    # second call: the assistant turn passed back unchanged, then ALL tool results in ONE user message
    second = p.api_calls[1]["messages"]
    assert [m["role"] for m in second] == ["user", "assistant", "user"]
    assert second[1]["content"][0].type == "thinking" and second[1]["content"][0].signature.startswith("sig-")
    results = second[2]["content"]
    asked = [b.id for b in second[1]["content"] if b.type == "tool_use"]
    assert [b["type"] for b in results] == ["tool_result", "tool_result"]
    assert [b["tool_use_id"] for b in results] == asked
    assert not any(b.get("is_error") for b in results)
    assert json.loads(results[0]["content"])["sources"] == src


def test_request_settings(monkeypatch):
    p, _ = ask(monkeypatch, [final(good_answer())])
    kw = p.api_calls[0]
    assert kw["model"] == settings.llm_model and kw["max_tokens"] == 2000
    assert kw["thinking"] == {"type": "adaptive"}
    assert kw["output_config"]["effort"] == settings.llm_effort
    assert kw["output_config"]["format"]["type"] == "json_schema"
    assert set(kw["output_config"]["format"]["schema"]["properties"]) >= {"status", "observations", "recommended_action_id"}
    assert kw["tool_choice"] == {"type": "auto"}
    assert all(t["strict"] for t in kw["tools"]) and len(kw["tools"]) == len(tools.TOOLS)
    assert kw["system"][0]["cache_control"] == {"type": "ephemeral"} and "Canary" in kw["system"][0]["text"]
    assert kw["betas"] == ["server-side-fallback-2026-07-01"] and kw["fallbacks"] == "default"
    assert 0 < kw["timeout"] <= settings.llm_timeout_s
    assert not {"temperature", "top_p", "top_k"} & set(kw)
    first = kw["messages"][0]["content"]
    assert "Helena" in first and "their own data" in first and QUESTION in first


def test_system_prompt_rules():
    text = chat.SYSTEM_PROMPT.lower()
    assert "never talk about another crew member" in text and "xp, levels, points" in text
    assert "insufficient_evidence" in text and "emergency" in text


def test_kb_source_meta(monkeypatch):
    c = ctx()
    kb = tools.run_tool(c, "search_knowledge", {"query": "sleep isolation light", "kind": "any", "k": 2})
    if not kb.sources:
        pytest.skip("knowledge base not built")
    chunk = kb.data["chunks"][0]
    s, src = sleep_obs()
    resp = response("Your sleep is below your own normal.", observations=[(s, src)],
                    explanations=[("Light and isolation can shift sleep.", [chunk["chunk_id"]])])
    _, r = ask(monkeypatch, [tool_use(("get_indicator", {"ind": "sleep"}),
                                      ("search_knowledge", {"query": "sleep isolation light", "kind": "any", "k": 2})),
                             final(resp)])
    assert r["mode"] == "ai" and r["explanations"]
    meta = r["source_meta"][chunk["chunk_id"]]
    assert meta["title"] == chunk["title"] and meta["text"] == chunk["text"] and isinstance(meta["version"], int)
    assert set(r["source_meta"]) == {chunk["chunk_id"]}


def test_failed_tool_gets_is_error_and_is_logged(monkeypatch):
    p, r = ask(monkeypatch, [tool_use(("get_indicator", {"ind": "nope"}), ("get_indicator", {"ind": "sleep"})),
                             final(good_answer())])
    results = p.api_calls[1]["messages"][2]["content"]
    assert results[0]["is_error"] is True and "must be one of" in json.loads(results[0]["content"])["error"]
    assert "is_error" not in results[1]
    turns = db.q("SELECT tool,ok FROM assistant_turns WHERE log_id=? ORDER BY id", (r["id"],))
    assert [t["ok"] for t in turns] == [0, 1]
    assert r["mode"] == "ai"


def test_crew_id_argument_is_rejected(monkeypatch):
    p, r = ask(monkeypatch, [tool_use(("get_status", {"crew_id": "k"})), final(good_answer())])
    res = p.api_calls[1]["messages"][2]["content"][0]
    assert res["is_error"] and "crew_id" in json.loads(res["content"])["error"]
    # the sleep source was never returned, so the claim is dropped and the status downgraded
    assert r["mode"] == "ai" and r["status"] == "insufficient_evidence" and r["observations"] == []
    assert {"G-SRC-01", "G-STATUS-01"} <= set(r["guard"]["rule_ids"])


# ---------------------------------------------------------------- loop guards

def test_max_steps(monkeypatch):
    msgs = [tool_use(("get_indicator", {"ind": i})) for i in ("sleep", "mood", "stress")]
    p, r = ask(monkeypatch, msgs)
    assert len(p.api_calls) == settings.llm_max_steps == 3
    assert r["mode"] == "fallback" and r["guard"]["reason"].startswith("loop:max_steps")
    assert r["claims"] and "loop:max_steps" in json.loads(log_row(r["id"])["guard_flags"])
    assert len(db.q("SELECT id FROM assistant_turns WHERE log_id=?", (r["id"],))) == 3


def test_tool_budget(monkeypatch):
    inds = ["sleep", "react", "mood", "stress", "social", "hr", "bp", "temp"]
    p, r = ask(monkeypatch, [tool_use(*[("get_indicator", {"ind": i}) for i in inds]), final(good_answer())])
    results = p.api_calls[1]["messages"][2]["content"]
    assert len(results) == 8
    assert [bool(b.get("is_error")) for b in results] == [False] * 6 + [True] * 2
    assert "budget" in json.loads(results[-1]["content"])["error"]
    assert len(db.q("SELECT id FROM assistant_turns WHERE log_id=?", (r["id"],))) == settings.llm_max_tool_calls
    assert r["mode"] == "ai" and "loop:max_tool_calls" in json.loads(log_row(r["id"])["guard_flags"])


def test_repeated_call_is_not_run_again(monkeypatch):
    p, r = ask(monkeypatch, [tool_use(("get_indicator", {"ind": "sleep"})), tool_use(("get_indicator", {"ind": "sleep"})),
                             final(good_answer())])
    again = json.loads(p.api_calls[2]["messages"][4]["content"][0]["content"])
    assert "Repeated call" in again["note"] and again["sources"] == sleep_obs()[1]
    assert len(db.q("SELECT id FROM assistant_turns WHERE log_id=?", (r["id"],))) == 1
    assert r["mode"] == "ai" and "loop:repeat" in json.loads(log_row(r["id"])["guard_flags"])


def test_deadline_is_checked_before_each_round(monkeypatch):
    monkeypatch.setattr(settings, "llm_timeout_s", 0.05)

    def slow(kwargs):
        time.sleep(0.08)
        return tool_use(("get_indicator", {"ind": "sleep"}))
    p, r = ask(monkeypatch, [slow, final(good_answer())])
    assert len(p.api_calls) == 1
    assert r["mode"] == "fallback" and r["guard"]["reason"].startswith("loop:timeout") and r["claims"]


def test_api_timeout(monkeypatch):
    _, r = ask(monkeypatch, [fakes.api_timeout()])
    assert r["mode"] == "fallback" and r["guard"]["reason"].startswith("api:timeout")
    assert r["provider_error"] and r["claims"]


@pytest.mark.parametrize("err,exit_", [(lambda: fakes.api_status(429), "api:rate_limit"),
                                       (lambda: fakes.api_status(500), "api:status"),
                                       (lambda: fakes.api_connection(), "api:connection")])
def test_api_errors_fall_back(monkeypatch, err, exit_):
    _, r = ask(monkeypatch, [err()])
    assert r["mode"] == "fallback" and r["guard"]["reason"].startswith(exit_)
    assert exit_ in json.loads(log_row(r["id"])["guard_flags"])


def test_non_sdk_errors_are_not_swallowed(monkeypatch):
    p = ScriptedProvider(messages=[RuntimeError("bug")])
    with pytest.raises(RuntimeError):
        p.complete(providers.ProviderRequest(task="chat", system="s", question="q", ctx=ctx()))


# ---------------------------------------------------------------- model stop reasons

def test_refusal(monkeypatch):
    _, r = ask(monkeypatch, [refusal()])
    assert r["mode"] == "fallback" and r["guard"]["reason"].startswith("model:refusal")


def test_max_tokens(monkeypatch):
    _, r = ask(monkeypatch, [tool_use(("get_indicator", {"ind": "sleep"})), fakes.cut_off()])
    assert r["mode"] == "fallback" and r["guard"]["reason"].startswith("model:max_tokens")
    assert len(db.q("SELECT id FROM assistant_turns WHERE log_id=?", (r["id"],))) == 1


def test_not_json(monkeypatch):
    _, r = ask(monkeypatch, [final("Your sleep is fine.")])
    assert r["mode"] == "fallback" and r["guard"]["reason"].startswith("model:bad_output")


# ---------------------------------------------------------------- guard exits (postcheck)

def test_schema_failure(monkeypatch):
    _, r = ask(monkeypatch, [final({"answer": "hi"})])
    assert r["mode"] == "fallback" and "G-SCHEMA-01" in r["guard"]["rule_ids"]


def test_invented_number_in_answer(monkeypatch):
    bad = good_answer()
    bad["answer"] = "You slept 3.2 h last night."
    _, r = ask(monkeypatch, [tool_use(("get_indicator", {"ind": "sleep"})), final(bad)])
    assert r["mode"] == "fallback" and "G-NUM-01" in r["guard"]["rule_ids"] and r["guard"]["rejected_numbers"]
    assert "3.2" not in r["answer"]
    assert "G-NUM-01" in json.loads(log_row(r["id"])["guard_flags"])


def test_dose_wording_in_answer(monkeypatch):
    bad = good_answer()
    bad["answer"] = "Take 5 mg of melatonin tonight."
    _, r = ask(monkeypatch, [tool_use(("get_indicator", {"ind": "sleep"})), final(bad)])
    assert r["mode"] == "fallback" and r["guard"]["reason"] and "melatonin" not in r["answer"]


def test_answer_about_another_crew_member(monkeypatch):
    bad = good_answer()
    bad["answer"] = "Kenji Mori is also sleeping badly and seems depressed."
    _, r = ask(monkeypatch, [tool_use(("get_indicator", {"ind": "sleep"})), final(bad)])
    assert r["mode"] == "fallback" and "G-PRIV-01" in r["guard"]["rule_ids"]


def test_soft_drops_keep_the_answer(monkeypatch):
    resp = good_answer(action="goal:not_a_goal")
    resp["observations"].append({"statement": "Mood is low.", "source_ids": ["telemetry:h:mood:day999"]})
    _, r = ask(monkeypatch, [tool_use(("get_indicator", {"ind": "sleep"})), final(resp)])
    assert r["mode"] == "ai" and r["dropped"] == 1 and r["recommended_action"] is None
    assert {"G-SRC-01", "G-ACT-01"} <= set(r["guard"]["rule_ids"])


def test_supported_without_tools_is_downgraded(monkeypatch):
    _, r = ask(monkeypatch, [final(good_answer())])  # cites a source no tool returned this turn
    assert r["mode"] == "ai" and r["status"] == "insufficient_evidence" and r["claims"] == []


# ---------------------------------------------------------------- before the model and without one

def test_precheck_never_calls_the_model(monkeypatch):
    p, r = ask(monkeypatch, [], question="Tomás is having a seizure")
    assert r["mode"] == "emergency" and p.api_calls == [] and p.calls == 0
    assert r["guard"]["rule_ids"] and log_row(r["id"])["outcome"] == "emergency"


def test_no_provider_is_grounded():
    r = client.post("/api/assistant/ask", json={"crew_id": "h", "question": QUESTION}, headers=as_("h")).json()
    assert r["provider"] == "none" and r["mode"] == "grounded" and r["status"] == "supported"
    assert r["observations"] and r["guard"]["reason"] is None and r["model"] is None


def test_viewer_binds_the_tool_context(monkeypatch):
    p = use(monkeypatch, ScriptedProvider(messages=[final(good_answer())]))
    r = client.post("/api/assistant/ask", json={"crew_id": "h", "question": QUESTION}, headers=medical())
    assert r.status_code == 200
    req = p.requests[0]
    assert req.ctx.crew_id == "h" and req.ctx.viewer == "medical" and req.ctx.medical
    assert "medical team about Helena" in req.question
    assert client.post("/api/assistant/ask", json={"crew_id": "h", "question": QUESTION}, headers=as_("k")).status_code == 403
    assert p.calls == 1


def test_context_for():
    assert chat.context_for("h", {"id": "h", "medical": False}).viewer == "h"
    m = chat.context_for("h", {"id": None, "medical": True})
    assert m.viewer == "medical" and m.medical
    with pytest.raises(ValueError):
        chat.context_for("h", {"id": "k", "medical": False})


# ---------------------------------------------------------------- briefing and suggestions

def _draft(f, allowed, text=None):
    return {"sections": [
        {"heading": "What worries", "lines": [{"text": text or f"Sleep is {f['movers'][0]['value']} against normal.",
                                               "source_ids": [allowed[0]]}]},
        {"heading": "What changed", "lines": []},
        {"heading": "What was tried", "lines": []}],
        "missing_information": [], "needs_medical_review": []}


def test_briefing_uses_a_valid_draft(monkeypatch):
    f = briefing.facts("h")
    allowed = briefing.allowed_sources("h", f)
    p = use(monkeypatch, ScriptedProvider(messages=[final(_draft(f, allowed))]), briefing)
    b = client.post("/api/briefings", json={"crew_id": "h"}, headers=as_("h")).json()
    assert b["mode"] == "ai" and "1 WHAT WORRIES" in b["text"]
    kw = p.api_calls[0]
    assert "tools" not in kw and "tool_choice" not in kw
    assert "sections" in kw["output_config"]["format"]["schema"]["properties"]
    assert p.requests[0].task == "briefing"


@pytest.mark.parametrize("bad", ["number", "source", "shape"])
def test_briefing_keeps_the_template_on_a_bad_draft(monkeypatch, bad):
    f = briefing.facts("h")
    allowed = briefing.allowed_sources("h", f)
    d = _draft(f, allowed, text="Sleep is 1.234 h." if bad == "number" else None)
    if bad == "source":
        d["sections"][0]["lines"][0]["source_ids"] = ["telemetry:k:sleep:day147"]
    if bad == "shape":
        d = {"text": "free prose"}
    use(monkeypatch, ScriptedProvider(messages=[final(d)]), briefing)
    b = client.post("/api/briefings", json={"crew_id": "h"}, headers=as_("h")).json()
    assert b["mode"] == "template" and "WHAT WORRIES" in b["text"]


def test_briefing_survives_api_errors(monkeypatch):
    use(monkeypatch, ScriptedProvider(messages=[fakes.api_timeout()]), briefing)
    assert client.post("/api/briefings", json={"crew_id": "h"}, headers=as_("h")).json()["mode"] == "template"


def test_suggestions_rewrite(monkeypatch):
    items = suggestions.candidates(suggestions.facts("h"))
    rewrites = {"items": [{"id": s["id"], "why": "A gentler way to say it."} for s in items]}
    p = use(monkeypatch, ScriptedProvider(messages=[final(rewrites)]), suggestions)
    s = client.get("/api/suggestions/h", headers=as_("h")).json()
    assert s["mode"] == "ai" and all(x["why"] == "A gentler way to say it." for x in s["items"])
    kw = p.api_calls[0]
    assert "tools" not in kw and kw["output_config"]["format"]["schema"]["required"] == ["items"]


def test_suggestions_keep_rules_on_invented_numbers(monkeypatch):
    items = suggestions.candidates(suggestions.facts("h"))
    rewrites = {"items": [{"id": s["id"], "why": "You slept 2.17 h."} for s in items]}
    use(monkeypatch, ScriptedProvider(messages=[final(rewrites)]), suggestions)
    assert client.get("/api/suggestions/h", headers=as_("h")).json()["mode"] == "rules"


@pytest.mark.parametrize("turn", [refusal, fakes.api_timeout, lambda: final("not json")])
def test_suggestions_keep_rules_on_failure(monkeypatch, turn):
    use(monkeypatch, ScriptedProvider(messages=[turn()]), suggestions)
    assert client.get("/api/suggestions/h", headers=as_("h")).json()["mode"] == "rules"


# ---------------------------------------------------------------- the real SDK, offline

def test_sdk_accepts_the_request_shape():
    """The installed SDK builds the request (betas header, fallbacks, output_config) against a mock transport."""
    import anthropic
    import httpx2
    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        seen["beta"] = request.headers.get("anthropic-beta")
        return httpx2.Response(200, json={
            "id": "msg_1", "type": "message", "role": "assistant", "model": "claude-sonnet-5-5",
            "stop_reason": "end_turn", "stop_sequence": None,
            "content": [{"type": "text", "text": json.dumps({"items": [{"id": "sleep", "why": "Rest more."}]})}],
            "usage": {"input_tokens": 10, "output_tokens": 5}})
    sdk = anthropic.Anthropic(api_key="test-not-a-key", max_retries=0,
                              http_client=httpx2.Client(transport=httpx2.MockTransport(handler)))
    out = providers.AnthropicProvider(client=sdk).complete(
        providers.ProviderRequest(task="suggestions", system="rules", question="[]"))
    assert out.ok and json.loads(out.answer) == [{"id": "sleep", "why": "Rest more."}]
    body = seen["body"]
    assert body["fallbacks"] == "default" and "server-side-fallback-2026-07-01" in seen["beta"]
    assert body["thinking"] == {"type": "adaptive"} and body["output_config"]["format"]["type"] == "json_schema"
    assert not {"temperature", "top_p", "top_k"} & set(body)


def test_status_lists_entries():
    s = client.get("/api/assistant/status").json()
    assert s["entries"] == ["chat", "briefing", "suggestions"] and s["limits"]["max_steps"] == settings.llm_max_steps


# ---------------------------------------------------------------- medical audit route (W1-4)

AUDIT_KEYS = {"id", "crew_id", "question", "created_at", "mode", "status", "provider", "model", "kb_version",
              "tools", "guard_flags", "latency_ms"}


def test_audit_route(monkeypatch):
    assert client.get("/api/medical/assistant-audit").status_code == 401
    assert client.get("/api/medical/assistant-audit", headers=as_("h")).status_code == 401
    ask(monkeypatch, [tool_use(("get_indicator", {"ind": "sleep"})), final(good_answer())])
    ask(monkeypatch, [refusal()])
    rows = client.get("/api/medical/assistant-audit?limit=30", headers=medical()).json()
    assert len(rows) == 2 and all(set(r) == AUDIT_KEYS for r in rows)
    newest, older = rows
    assert newest["mode"] == "fallback" and "model:refusal" in newest["guard_flags"]
    assert older["mode"] == "ai" and older["tools"] == ["get_indicator"] and older["status"] == "supported"
    assert older["provider"] == "scripted" and older["model"] == "claude-sonnet-5-5"
    assert isinstance(older["latency_ms"], int)
    assert len(client.get("/api/medical/assistant-audit?limit=1", headers=medical()).json()) == 1
