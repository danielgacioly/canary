"""Rate limits for the assistant's paid calls, and the suggestions cache (item 10).

A token bucket per crew member and kind: 10 questions, 3 briefing builds and 6 suggestion builds a minute. Over the limit
the API answers 429 with the same {detail: [{field, message}]} shape as the other input errors. The clock is injected, so
nothing sleeps. Repeated GETs of the suggestions reuse the last build (same day, same inputs): no provider call, no new log row.
"""
import os
import tempfile

os.environ["CANARY_DB"] = os.path.join(tempfile.mkdtemp(), "test_rate_limit.db")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from canary import db  # noqa: E402
from canary.assistant import limits, suggestions  # noqa: E402
from canary.config import settings  # noqa: E402
from canary.main import app  # noqa: E402
from tests.golden_capture import control_headers  # noqa: E402

from fakes import ScriptedProvider  # noqa: E402

client = TestClient(app)
PINS = {"h": "1001", "k": "1002", "a": "1003", "t": "1004"}


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    client.post("/api/demo/reset", headers=control_headers(client))
    client.put("/api/mission", json={"step": 2}, headers=control_headers(client))
    clock = Clock()
    monkeypatch.setattr(limits, "LIMITS", limits.Limiter(clock=clock))
    suggestions._cache.clear()
    yield clock
    client.post("/api/demo/reset", headers=control_headers(client))


def as_(cid):
    return {"Authorization": "Bearer " + client.post(f"/api/crew/{cid}/session", json={"pin": PINS[cid]}).json()["token"]}


def ask(cid="h", q="How am I today?"):
    return client.post("/api/assistant/ask", json={"crew_id": cid, "question": q}, headers=as_(cid))


# ---------------------------------------------------------------- the bucket (no HTTP, no sleeping)

def test_bucket_allows_the_quota_then_refuses_with_a_wait():
    clock = Clock()
    lim = limits.Limiter(rates={"ask": 10}, clock=clock)
    assert all(lim.allow("ask", "h") is None for _ in range(10))
    wait = lim.allow("ask", "h")
    assert wait is not None and 1 <= wait <= 6


def test_bucket_refills_with_time_and_is_per_crew_member():
    clock = Clock()
    lim = limits.Limiter(rates={"ask": 10}, clock=clock)
    for _ in range(10):
        lim.allow("ask", "h")
    assert lim.allow("ask", "h") is not None
    assert lim.allow("ask", "k") is None          # another crew member has their own bucket
    clock.now += 6                                 # one token every 6 seconds at 10 a minute
    assert lim.allow("ask", "h") is None
    assert lim.allow("ask", "h") is not None


def test_a_clock_that_goes_back_does_not_give_extra_calls():
    clock = Clock()
    lim = limits.Limiter(rates={"briefing": 3}, clock=clock)
    for _ in range(3):
        lim.allow("briefing", "h")
    clock.now -= 500
    assert lim.allow("briefing", "h") is not None


# ---------------------------------------------------------------- the API answers 429 in the crew error shape

def test_the_eleventh_question_in_a_minute_is_refused_with_429():
    for _ in range(10):
        assert ask().status_code == 200
    r = ask()
    assert r.status_code == 429
    body = r.json()
    assert body["detail"][0]["field"] == "question" and "Wait" in body["detail"][0]["message"]
    assert int(r.headers["Retry-After"]) >= 1


def test_a_refused_question_writes_no_log_row(fresh):
    for _ in range(10):
        ask()
    before = len(db.q("SELECT id FROM assistant_log"))
    assert ask().status_code == 429
    assert len(db.q("SELECT id FROM assistant_log")) == before


def test_the_fourth_briefing_build_in_a_minute_is_refused(fresh):
    statuses = [client.post("/api/briefings", json={"crew_id": "h"}, headers=as_("h")).status_code for _ in range(4)]
    assert statuses == [200, 200, 200, 429]
    assert client.post("/api/briefings", json={"crew_id": "h"}, headers=as_("h")).json()["detail"][0]["field"] == "briefing"


def test_a_minute_later_the_briefing_quota_is_back(fresh):
    for _ in range(3):
        client.post("/api/briefings", json={"crew_id": "h"}, headers=as_("h"))
    assert client.post("/api/briefings", json={"crew_id": "h"}, headers=as_("h")).status_code == 429
    fresh.now += 21                                # 3 a minute: one every 20 seconds
    assert client.post("/api/briefings", json={"crew_id": "h"}, headers=as_("h")).status_code == 200


# ---------------------------------------------------------------- suggestions: cached per day and inputs

def _suggestion_logs():
    return len(db.q("SELECT id FROM assistant_log WHERE question=?", (suggestions_log(),)))


def suggestions_log():
    from canary.assistant import chat
    return chat.SUGGESTIONS_LOG


def test_repeated_suggestion_gets_reuse_the_build(monkeypatch):
    p = ScriptedProvider(turns=[])          # any model call is counted and fails: the rules text is shown
    monkeypatch.setattr(suggestions, "get_provider", lambda: p)
    first = client.get("/api/suggestions/h", headers=as_("h")).json()
    second = client.get("/api/suggestions/h", headers=as_("h")).json()
    assert first == second
    assert p.calls == 1                      # the second GET made no model call
    assert _suggestion_logs() == 1           # and wrote no new assistant_log row


def test_a_changed_input_rebuilds_the_suggestions(monkeypatch):
    p = ScriptedProvider(turns=[])
    monkeypatch.setattr(suggestions, "get_provider", lambda: p)
    first = client.get("/api/suggestions/h", headers=as_("h")).json()
    sid = first["items"][0]["id"]
    assert client.post(f"/api/suggestions/h/{sid}/dismiss", headers=as_("h")).status_code == 200  # a choice is an input
    client.get("/api/suggestions/h", headers=as_("h"))
    assert _suggestion_logs() == 2   # the first build and the dismissal's own build; the GET after it is served from the cache


def test_a_suggestions_build_refused_by_the_limit_is_429_and_writes_nothing(monkeypatch, fresh):
    p = ScriptedProvider(turns=[])
    monkeypatch.setattr(suggestions, "get_provider", lambda: p)
    monkeypatch.setattr(limits, "LIMITS", limits.Limiter(rates={"suggestions": 1}, clock=fresh))
    assert client.get("/api/suggestions/h", headers=as_("h")).status_code == 200
    suggestions._cache.clear()               # force a miss: a build now needs a token
    r = client.get("/api/suggestions/h", headers=as_("h"))
    assert r.status_code == 429 and r.json()["detail"][0]["field"] == "suggestions"
    assert _suggestion_logs() == 1


def test_cache_hit_does_not_spend_a_suggestions_token(monkeypatch, fresh):
    p = ScriptedProvider(turns=[])
    monkeypatch.setattr(suggestions, "get_provider", lambda: p)
    monkeypatch.setattr(limits, "LIMITS", limits.Limiter(rates={"suggestions": 1}, clock=fresh))
    for _ in range(5):
        assert client.get("/api/suggestions/h", headers=as_("h")).status_code == 200
