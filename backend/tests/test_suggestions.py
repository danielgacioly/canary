"""Suggestions entry: per-item rewrite checks, fallback reasons and the metadata-only audit entry.
Scripted provider only: no network, no API key."""
import os
import tempfile

os.environ.setdefault("CANARY_DB", os.path.join(tempfile.mkdtemp(), "test_suggestions.db"))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import fakes  # noqa: E402
from fakes import ScriptedProvider, final, refusal  # noqa: E402

from canary import db  # noqa: E402
from canary.assistant import chat, providers, suggestions  # noqa: E402
from canary.config import settings  # noqa: E402
from canary.main import app  # noqa: E402

client = TestClient(app)
GENTLE = "A gentler way to say it."


@pytest.fixture(autouse=True)
def fresh():
    client.post("/api/demo/reset")
    client.put("/api/mission", json={"step": 2})  # day 147: Helena has several suggestions
    yield
    client.post("/api/demo/reset")


def helena():
    r = client.post("/api/crew/h/session", json={"pin": "1001"})
    return {"X-Canary-Viewer": r.json()["token"]}


def medical():
    r = client.post("/api/medical/session", json={"pin": settings.medical_pin})
    return {"Authorization": f"Bearer {r.json()['token']}"}


def use(monkeypatch, p):
    monkeypatch.setattr(suggestions, "get_provider", lambda: p)
    return p


def items():
    return suggestions.candidates(suggestions.facts("h"))


def get():
    return client.get("/api/suggestions/h", headers=helena()).json()


def test_all_rewrites_valid_is_ai(monkeypatch):
    its = items()
    use(monkeypatch, ScriptedProvider(messages=[final({"items": [{"id": s["id"], "why": GENTLE} for s in its]})]))
    s = get()
    assert s["mode"] == "ai" and s["configured"] is True and s["fallback_reason"] is None
    assert s["rewritten"] == len(its) == len(s["items"])
    assert all(x["why"] == GENTLE and x["source"] == "ai" for x in s["items"])


def test_one_bad_number_keeps_the_others(monkeypatch):
    its = items()
    assert len(its) >= 2
    rules = {s["id"]: s["why"] for s in its}
    bad = its[0]["id"]
    rw = [{"id": s["id"], "why": "You slept 2.17 h." if s["id"] == bad else GENTLE} for s in its]
    use(monkeypatch, ScriptedProvider(messages=[final({"items": rw})]))
    s = get()
    assert s["mode"] == "ai" and s["rewritten"] == len(its) - 1
    assert s["fallback_reason"] == "numbers_rejected" and "2.17" in s["rejected_numbers"]
    by = {x["id"]: x for x in s["items"]}
    assert by[bad]["why"] == rules[bad] and by[bad]["source"] == "rules"
    assert all(x["why"] == GENTLE and x["source"] == "ai" for k, x in by.items() if k != bad)


def test_empty_or_too_long_rewrites_keep_rule_text(monkeypatch):
    its = items()
    rw = [{"id": its[0]["id"], "why": "  "}, {"id": its[1]["id"], "why": "x" * 400}]
    use(monkeypatch, ScriptedProvider(messages=[final({"items": rw})]))
    s = get()
    assert s["mode"] == "rules" and s["rewritten"] == 0 and s["fallback_reason"] == "model:bad_output"


@pytest.mark.parametrize("turn,reason", [
    (fakes.api_timeout, "api:timeout"),
    (refusal, "model:refusal"),
    (lambda: final("not json"), "model:bad_output"),
])
def test_provider_failures_give_rules_with_reason(monkeypatch, turn, reason):
    use(monkeypatch, ScriptedProvider(messages=[turn()]))
    s = get()
    assert s["mode"] == "rules" and s["configured"] is True and s["fallback_reason"] == reason
    assert all(x["source"] == "rules" for x in s["items"])


def test_unparseable_list_is_parse_error(monkeypatch):
    use(monkeypatch, ScriptedProvider([providers.ProviderResult(ok=True, answer="{not a list", model="m1")]))
    s = get()
    assert s["mode"] == "rules" and s["fallback_reason"] == "parse_error" and s["model"] == "m1"


def test_provider_exception_is_api_error(monkeypatch):
    use(monkeypatch, ScriptedProvider([RuntimeError("bug")]))
    s = get()
    assert s["mode"] == "rules" and s["fallback_reason"] == "api:error"


def test_no_provider_is_rules_not_configured(monkeypatch):
    use(monkeypatch, providers.NullProvider())
    s = get()
    assert s["mode"] == "rules" and s["configured"] is False and s["fallback_reason"] is None
    assert s["provider"] == "none" and s["model"] is None and s["rewritten"] == 0


def test_audit_entry_has_metadata_but_no_item_text(monkeypatch):
    its = items()
    secret = "Only Helena should read this sentence."
    use(monkeypatch, ScriptedProvider(messages=[final({"items": [{"id": s["id"], "why": secret} for s in its]})]))
    s = get()
    assert s["mode"] == "ai"
    entry = next(e for e in client.get("/api/medical/assistant-audit", headers=medical()).json()
                 if e["question"] == "suggestions")
    assert entry["crew_id"] == "h" and entry["mode"] == "ai" and entry["provider"] == "scripted"
    row = db.q("SELECT * FROM assistant_log WHERE question='suggestions' ORDER BY id DESC LIMIT 1")[0]
    stored = " ".join(str(v) for v in dict(row).values())
    for x in s["items"]:
        assert x["why"] not in stored and x["title"] not in stored
        assert all(step not in stored for step in x["steps"])
    assert secret not in str(entry)
    # the astronaut's chat history does not show suggestions builds
    assert all(h["question"] != "suggestions" for h in chat.history("h"))


def test_failure_reason_is_logged(monkeypatch):
    use(monkeypatch, ScriptedProvider(messages=[fakes.api_timeout()]))
    get()
    row = db.q("SELECT outcome, guard_flags FROM assistant_log WHERE question='suggestions' ORDER BY id DESC LIMIT 1")[0]
    assert row["outcome"] == "rules" and "api:timeout" in row["guard_flags"]
