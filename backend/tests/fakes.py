"""Test doubles for the AI layer. No network, no API key.

Two ways to script a model:

1. `ScriptedProvider(turns)`: each turn is a `ProviderResult` to return from `complete()` or an exception
   instance to raise. For entries that do not need the tool loop (or for testing callers in isolation).

2. `ScriptedProvider(messages=[...])`: Scripted messages (`tool_use(...)`, `final(...)`, `refusal()`,
   `cut_off()`) or exceptions (e.g. `api_timeout()`), replayed one per Gemini API call by `FakeClient`.
   `complete()` then runs the real `GeminiProvider` loop on that fake client, so loop guards, tool
   validation, run_tool, dedupe and the functionResponse shape are all exercised. `api_calls` records the JSON body
   of every API call (a deep copy of `contents` included).

A message turn may also be a callable `fn(kwargs) -> message` (e.g. to sleep and test the deadline).
"""
import copy
import itertools
import json
from types import SimpleNamespace
from typing import Any, Callable, List, Optional, Sequence, Union

from canary.assistant.providers import GeminiProvider, ProviderRequest, ProviderResult

Turn = Union[ProviderResult, BaseException]
_ids = itertools.count(1)


# ---------------------------------------------------------------- Scripted messages

def _usage(i: int = 100, o: int = 50) -> SimpleNamespace:
    return SimpleNamespace(input_tokens=i, output_tokens=o, cache_read_input_tokens=0, cache_creation_input_tokens=0)


def message(stop_reason: str, content: list, model: str = "gemini-3.8-flash") -> SimpleNamespace:
    return SimpleNamespace(type="message", role="assistant", stop_reason=stop_reason, content=content,
                           model=model, usage=_usage(), stop_details=None)


def thinking(text: str = "") -> SimpleNamespace:
    return SimpleNamespace(type="thinking", thinking=text, signature=f"sig-{next(_ids)}")


def text(t: str) -> SimpleNamespace:
    return SimpleNamespace(type="text", text=t)


def call(name: str, args: Optional[dict] = None) -> SimpleNamespace:
    return SimpleNamespace(type="tool_use", id=f"toolu_{next(_ids):04d}", name=name, input=args or {})


def tool_use(*calls: Union[SimpleNamespace, tuple]) -> SimpleNamespace:
    """An assistant turn asking for one or more tools: tool_use(("get_indicator", {"ind": "sleep"}), ...)."""
    blocks = [c if isinstance(c, SimpleNamespace) else call(*c) for c in calls]
    return message("tool_use", [thinking()] + blocks)


def final(resp: Union[dict, str]) -> SimpleNamespace:
    """The final assistant turn: an AssistantResponse (dict) or raw text."""
    return message("end_turn", [thinking(), text(resp if isinstance(resp, str) else json.dumps(resp))])


def refusal() -> SimpleNamespace:
    m = message("refusal", [])
    m.stop_details = SimpleNamespace(type="refusal", category="bio", explanation="declined")
    return m


def cut_off() -> SimpleNamespace:
    return message("max_tokens", [thinking(), text('{"status": "supp')])


def response(answer: str, observations=(), explanations=(), status: str = "supported", limitations=(),
             action: Optional[str] = None) -> dict:
    """An AssistantResponse dict. observations/explanations: (statement, [source ids]) pairs."""
    return {"status": status, "answer": answer,
            "observations": [{"statement": s, "source_ids": list(ids)} for s, ids in observations],
            "explanations": [{"statement": s, "source_ids": list(ids)} for s, ids in explanations],
            "limitations": list(limitations), "recommended_action_id": action}


# ---------------------------------------------------------------- transport errors without a network

def _request():
    import httpx
    return httpx.Request("POST", "https://generativelanguage.googleapis.com/v1beta/models/test:generateContent")


def api_timeout():
    import httpx
    return httpx.ReadTimeout("timeout", request=_request())


def api_connection():
    import httpx
    return httpx.ConnectError("connection", request=_request())


def api_status(code: int = 500):
    import httpx
    resp = httpx.Response(code, request=_request(), json={"error": {"message": "x"}})
    return httpx.HTTPStatusError("error", request=_request(), response=resp)


# ---------------------------------------------------------------- fake HTTP client

class FakeClient:
    """Replay turns at the HTTP boundary so the real Gemini serialization is exercised."""

    def __init__(self, turns: Sequence[Any]):
        self.turns = list(turns)
        self.api_calls: List[dict] = []

    def post(self, url, **kwargs):
        import httpx
        self.api_calls.append({**copy.deepcopy(kwargs["json"]), "timeout": kwargs["timeout"]})
        if len(self.api_calls) > len(self.turns):
            raise AssertionError(f"FakeClient ran out of messages after {len(self.turns)} call(s)")
        turn = self.turns[len(self.api_calls) - 1]
        if isinstance(turn, BaseException):
            raise turn
        if callable(turn):
            turn = turn(self.api_calls[-1])
        if isinstance(turn, dict):
            body = turn
        else:
            parts = []
            for block in turn.content:
                if block.type == "thinking":
                    parts.append({"text": block.thinking, "thought": True, "thoughtSignature": block.signature})
                elif block.type == "text":
                    parts.append({"text": block.text})
                else:
                    parts.append({"functionCall": {"id": block.id, "name": block.name, "args": block.input},
                                  "thoughtSignature": "signature-for-" + block.id})
            body = {"modelVersion": turn.model,
                    "usageMetadata": {"promptTokenCount": turn.usage.input_tokens,
                                      "candidatesTokenCount": turn.usage.output_tokens},
                    "candidates": [{"finishReason": {"refusal": "SAFETY", "max_tokens": "MAX_TOKENS"}.get(turn.stop_reason, "STOP"),
                                    "content": {"role": "model", "parts": parts}}]}
        return httpx.Response(200, request=httpx.Request("POST", url), json=body)


# ---------------------------------------------------------------- the provider double

class ScriptedProvider:
    name = "scripted"

    def __init__(self, turns: Sequence[Turn] = (), configured: bool = True, name: Optional[str] = None,
                 messages: Optional[Sequence[Any]] = None):
        self.turns: List[Turn] = list(turns)
        self.configured = configured
        if name:
            self.name = name
        self.requests: List[ProviderRequest] = []
        self.results: List[ProviderResult] = []
        self.client: Optional[FakeClient] = FakeClient(messages) if messages is not None else None

    @property
    def calls(self) -> int:
        return len(self.requests)

    @property
    def api_calls(self) -> List[dict]:
        return self.client.api_calls if self.client else []

    @property
    def exhausted(self) -> bool:
        if self.client is not None:
            return len(self.client.api_calls) >= len(self.client.turns)
        return self.calls >= len(self.turns)

    def complete(self, req: ProviderRequest) -> ProviderResult:
        self.requests.append(req)
        if self.client is not None:
            out = GeminiProvider(client=self.client).complete(req)
            self.results.append(out)
            return out
        if len(self.requests) > len(self.turns):
            raise AssertionError(f"ScriptedProvider ran out of turns after {len(self.turns)} call(s)")
        turn = self.turns[len(self.requests) - 1]
        if isinstance(turn, BaseException):
            raise turn
        self.results.append(turn)
        return turn


def answer(text: str, claims: Optional[list] = None) -> ProviderResult:
    """Shortcut for a successful final turn in the legacy ProviderResult shape."""
    return ProviderResult(ok=True, answer=text, claims=claims or [])


Sleeper = Callable[[dict], Any]
