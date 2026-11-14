"""LLM provider interface. Pick one with CANARY_LLM_PROVIDER (none | anthropic | local).

Three AI entries share `complete(ProviderRequest)` (contracts.AI_ENTRIES, docs/ai/plan.md Phase 2):

- "chat": a manual tool loop. The model picks tools; every call is validated (tools.validate_args), run for the
  bound person (tools.run_tool with the request's ToolContext), recorded for assistant_turns, and its sources
  are added to the allowed set of the turn. The final message is an AssistantResponse as JSON text.
- "briefing": no tools, structured output in the BriefingDraft shape.
- "suggestions": no tools, structured output {items: [{id, why}]}, returned as the JSON list text
  suggestions.py already parses.

The provider never decides what is shown: chat.py runs guard.postcheck on the answer, briefing.py and
suggestions.py check numbers and sources. A failure of any kind (API error, timeout, refusal, a loop guard)
comes back as ok=False with `guard_exit` naming what fired, so the caller can use its grounded fallback.
"""
import json
import os
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol, Tuple

from ..config import settings
from . import contracts, tools
from .contracts import ToolContext, ToolResult


@dataclass
class ProviderRequest:
    task: str                      # "chat" | "briefing" | "suggestions" (contracts.AI_ENTRIES)
    system: str                    # stable rules for the model (prompts/*.md), sent with cache_control
    question: str                  # the user message: question plus who asks, or the briefing/suggestions input
    context: List[dict] = field(default_factory=list)  # chat: unused (tools fetch data); others: computed facts
    knowledge: List[dict] = field(default_factory=list)  # legacy: cards pasted in the prompt (not sent any more)
    ctx: Optional[ToolContext] = None        # chat: the bound person and viewer every tool call runs in
    deadline: Optional[float] = None         # time.monotonic() value; default now + settings.llm_timeout_s
    output_schema: Optional[Dict[str, Any]] = None  # JSON Schema for output_config.format (default per task)


@dataclass
class ProviderResult:
    ok: bool
    answer: str = ""                # final text (chat / briefing: the JSON text; suggestions: JSON list text)
    claims: List[dict] = field(default_factory=list)  # legacy {text, source_ids} claims (unused by the loop)
    error: Optional[str] = None
    data: Any = None                # `answer` parsed as JSON, when it parses
    guard_exit: Optional[str] = None  # loop guard or API condition that ended the call (see GUARD_EXITS)
    notes: List[str] = field(default_factory=list)  # guards that fired without ending the loop
    turns: List[dict] = field(default_factory=list)  # chat: [{step, tool, args, sources, ok}] for assistant_turns
    sources: List[str] = field(default_factory=list)  # chat: every source id the tools returned
    tool_data: List[dict] = field(default_factory=list)  # chat: [{tool, args, data, sources, error}]
    model: Optional[str] = None
    input_tokens: int = 0
    output_tokens: int = 0
    steps: int = 0


# What `guard_exit` / `notes` may hold. Shown in the API `guard.reason` and logged in assistant_log.guard_flags.
GUARD_EXITS = {
    "loop:max_steps": "the model needed more rounds than allowed",
    "loop:max_tool_calls": "the tool-call budget was used up",
    "loop:repeat": "a repeated tool call got the earlier result",
    "loop:timeout": "the answer took longer than the time limit",
    "model:refusal": "the model declined to answer",
    "model:max_tokens": "the answer was cut off",
    "model:bad_output": "the model did not return the expected JSON",
    "api:timeout": "the AI service did not answer in time",
    "api:rate_limit": "the AI service is busy",
    "api:connection": "no link to the AI service",
    "api:status": "the AI service returned an error",
    "api:error": "the AI service could not be used",
}


class LLMProvider(Protocol):
    name: str
    configured: bool

    def complete(self, req: ProviderRequest) -> ProviderResult: ...


class NullProvider:
    """No model connected. The assistant falls back to grounded rule-based answers."""
    name = "none"
    configured = False

    def complete(self, req: ProviderRequest) -> ProviderResult:
        return ProviderResult(ok=False, error="No AI provider connected")


# ---------------------------------------------------------------- output schemas per task

SUGGESTIONS_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {"items": {"type": "array", "items": {
        "type": "object",
        "properties": {"id": {"type": "string"}, "why": {"type": "string"}},
        "required": ["id", "why"], "additionalProperties": False}}},
    "required": ["items"], "additionalProperties": False,
}


def default_schema(task: str) -> Optional[Dict[str, Any]]:
    if task == "chat":
        return contracts.json_schema(contracts.AssistantResponse)
    if task == "briefing":
        return contracts.json_schema(contracts.BriefingDraft)
    if task == "suggestions":
        return SUGGESTIONS_SCHEMA
    return None


# ---------------------------------------------------------------- Anthropic

FALLBACK_BETA = "server-side-fallback-2026-07-01"
MAX_TOKENS = 2000
REPEAT_NOTE = "Repeated call: this is the same result as before. Use it instead of calling again."
BUDGET_NOTE = "Tool budget used up for this question: answer from the results you already have."


def _get(obj: Any, key: str, default: Any = None) -> Any:
    """Attribute or key access, so SDK objects and plain dicts (tests) both work."""
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _final_text(content: List[Any]) -> str:
    return "".join(_get(b, "text", "") or "" for b in content if _get(b, "type") == "text").strip()


def _parse_json(text: str) -> Any:
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        return None


class AnthropicProvider:
    """Claude through the Anthropic API (ground segment, or a demo with internet).

    The SDK reads ANTHROPIC_API_KEY (or another configured credential) from the environment itself; this
    class never reads, logs or stores it. `client` may be injected (tests use a scripted fake client)."""
    name = "anthropic"

    def __init__(self, client: Any = None):
        self._client = client

    @property
    def configured(self) -> bool:
        if self._client is not None:
            return True
        try:
            import anthropic  # noqa: F401
        except ImportError:
            return False
        return bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))

    def _sdk(self) -> Any:
        if self._client is None:
            import anthropic
            # No SDK retries: the question has one deadline, and a failure falls back to the grounded answer.
            self._client = anthropic.Anthropic(max_retries=0)
        return self._client

    # -- one Messages API call

    def _call(self, req: ProviderRequest, messages: List[dict], with_tools: bool, timeout: float) -> Any:
        schema = req.output_schema or default_schema(req.task)
        output_config: Dict[str, Any] = {"effort": settings.llm_effort}
        if schema:
            output_config["format"] = {"type": "json_schema", "schema": schema}
        kwargs: Dict[str, Any] = dict(
            model=settings.llm_model,
            max_tokens=MAX_TOKENS,
            thinking={"type": "adaptive"},
            output_config=output_config,
            system=[{"type": "text", "text": req.system, "cache_control": {"type": "ephemeral"}}],
            messages=messages,
            betas=[FALLBACK_BETA],
            fallbacks="default",
            timeout=max(timeout, 0.1),
        )
        if with_tools:
            kwargs["tools"] = tools.anthropic_tools()
            kwargs["tool_choice"] = {"type": "auto"}
        return self._sdk().beta.messages.create(**kwargs)

    @staticmethod
    def _api_error(e: BaseException) -> Optional[Tuple[str, str]]:
        """(guard_exit, error text) for an SDK error, or None when `e` is not one."""
        try:
            import anthropic
        except ImportError:
            return None
        if isinstance(e, anthropic.APITimeoutError):
            return "api:timeout", "AI service timed out"
        if isinstance(e, anthropic.RateLimitError):
            return "api:rate_limit", "AI service rate limit"
        if isinstance(e, anthropic.APIConnectionError):
            return "api:connection", "no connection to the AI service"
        if isinstance(e, anthropic.APIStatusError):
            return "api:status", f"AI service error {e.status_code}"
        if isinstance(e, anthropic.AnthropicError):  # missing credentials and other client-side errors
            return "api:error", f"AI service unavailable ({type(e).__name__})"
        return None

    @staticmethod
    def _usage(out: ProviderResult, msg: Any) -> None:
        u = _get(msg, "usage")
        if u is not None:
            out.input_tokens += sum(int(_get(u, k, 0) or 0) for k in
                                    ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"))
            out.output_tokens += int(_get(u, "output_tokens", 0) or 0)
        out.model = _get(msg, "model") or out.model

    def complete(self, req: ProviderRequest) -> ProviderResult:
        deadline = req.deadline if req.deadline is not None else time.monotonic() + settings.llm_timeout_s
        out = ProviderResult(ok=False, model=settings.llm_model)
        if req.task not in contracts.AI_ENTRIES:
            out.error, out.guard_exit = f"unknown task {req.task!r}", "api:error"
            return out
        if req.task in contracts.ENTRIES_WITH_TOOLS:
            if req.ctx is None:
                out.error, out.guard_exit = "no tool context bound to this question", "api:error"
                return out
            return self._loop(req, deadline, out)
        return self._single(req, deadline, out)

    def _fail(self, out: ProviderResult, exit_: str, error: Optional[str] = None) -> ProviderResult:
        out.ok, out.guard_exit, out.error = False, exit_, error or GUARD_EXITS[exit_]
        return out

    def _stop(self, out: ProviderResult, msg: Any) -> Optional[ProviderResult]:
        """Handle the stop reasons that end a call before content is read."""
        reason = _get(msg, "stop_reason")
        if reason == "refusal":
            return self._fail(out, "model:refusal")
        if reason == "max_tokens":
            return self._fail(out, "model:max_tokens")
        return None

    def _finish(self, out: ProviderResult, msg: Any, task: str) -> ProviderResult:
        text = _final_text(_get(msg, "content", []) or [])
        data = _parse_json(text)
        if data is None:
            out.answer = text
            return self._fail(out, "model:bad_output")
        out.ok, out.answer, out.data = True, text, data
        if task == "suggestions":  # the [{id, why}] list text suggestions.py parses
            if not isinstance(data, dict) or not isinstance(data.get("items"), list):
                return self._fail(out, "model:bad_output")
            out.answer = json.dumps(data["items"], ensure_ascii=False)
        return out

    # -- briefing / suggestions: one call, no tools

    def _single(self, req: ProviderRequest, deadline: float, out: ProviderResult) -> ProviderResult:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return self._fail(out, "loop:timeout")
        user = req.question
        if req.context:
            user += "\n\nComputed facts (JSON):\n" + json.dumps(req.context, ensure_ascii=False, default=str)
        out.steps = 1
        try:
            msg = self._call(req, [{"role": "user", "content": user}], with_tools=False, timeout=remaining)
        except Exception as e:  # noqa: BLE001 - only SDK errors are swallowed, see _api_error
            err = self._api_error(e)
            if err is None:
                raise
            return self._fail(out, *err)
        self._usage(out, msg)
        stopped = self._stop(out, msg)
        if stopped:
            return stopped
        return self._finish(out, msg, req.task)

    # -- chat: the manual tool loop with its guards

    def _loop(self, req: ProviderRequest, deadline: float, out: ProviderResult) -> ProviderResult:
        ctx = req.ctx
        messages: List[dict] = [{"role": "user", "content": req.question}]
        seen: Dict[Tuple[str, str], dict] = {}   # (tool, canonical args) -> tool_result payload
        calls = 0
        while True:
            if out.steps >= settings.llm_max_steps:
                return self._fail(out, "loop:max_steps")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return self._fail(out, "loop:timeout")
            out.steps += 1
            try:
                msg = self._call(req, messages, with_tools=True, timeout=remaining)
            except Exception as e:  # noqa: BLE001 - only SDK errors are swallowed, see _api_error
                err = self._api_error(e)
                if err is None:
                    raise
                return self._fail(out, *err)
            self._usage(out, msg)
            stopped = self._stop(out, msg)
            if stopped:
                return stopped
            content = list(_get(msg, "content", []) or [])
            uses = [b for b in content if _get(b, "type") == "tool_use"]
            if _get(msg, "stop_reason") != "tool_use" or not uses:
                return self._finish(out, msg, req.task)

            # Pass the assistant turn back unchanged (thinking blocks included), then ALL results in ONE message.
            messages.append({"role": "assistant", "content": content})
            results = []
            for b in uses:
                name, args = _get(b, "name"), _get(b, "input")
                if isinstance(args, str):
                    args = _parse_json(args)
                key = (str(name), json.dumps(args, sort_keys=True, default=str))
                if key in seen:
                    payload = {**seen[key], "note": REPEAT_NOTE}
                    if "loop:repeat" not in out.notes:
                        out.notes.append("loop:repeat")
                    results.append(self._result_block(b, payload))
                    continue
                if calls >= settings.llm_max_tool_calls:
                    if "loop:max_tool_calls" not in out.notes:
                        out.notes.append("loop:max_tool_calls")
                    results.append(self._result_block(b, ToolResult.fail(BUDGET_NOTE).model_dump()))
                    continue
                calls += 1
                bad = tools.validate_args(str(name), args)
                res = ToolResult.fail(f"{name}: {bad}") if bad else tools.run_tool(ctx, str(name), args)
                payload = res.model_dump()
                seen[key] = payload
                safe_args = args if isinstance(args, dict) else {}
                out.turns.append({"step": out.steps, "tool": str(name), "args": safe_args,
                                  "sources": list(res.sources), "ok": res.ok})
                out.tool_data.append({"tool": str(name), "args": safe_args, **payload})
                for s in res.sources:
                    if s not in out.sources:
                        out.sources.append(s)
                results.append(self._result_block(b, payload))
            messages.append({"role": "user", "content": results})

    @staticmethod
    def _result_block(block: Any, payload: dict) -> dict:
        r = {"type": "tool_result", "tool_use_id": _get(block, "id"),
             "content": json.dumps(payload, ensure_ascii=False, default=str)}
        if payload.get("error") is not None:
            r["is_error"] = True
        return r


class LocalProvider:
    """Slot for a small model running on board, with no network. Same interface as AnthropicProvider.

    What it would need (not built in this plan): a small instruction-tuned model served by llama.cpp or Ollama
    with JSON-schema-constrained output (grammar from `default_schema(task)`) and tool calling, driven by the same
    loop and guards as AnthropicProvider."""
    name = "local"
    configured = False

    def complete(self, req: ProviderRequest) -> ProviderResult:
        return ProviderResult(ok=False, error="LocalProvider is a slot: not implemented yet")


_PROVIDERS = {"none": NullProvider, "anthropic": AnthropicProvider, "local": LocalProvider}


def get_provider() -> LLMProvider:
    return _PROVIDERS.get(settings.llm_provider, NullProvider)()


def status() -> dict:
    p = get_provider()
    return {"provider": p.name, "configured": p.configured, "available": list(_PROVIDERS),
            "model": settings.llm_model if p.name == "anthropic" else None,
            "entries": list(contracts.AI_ENTRIES),
            "limits": {"max_steps": settings.llm_max_steps, "max_tool_calls": settings.llm_max_tool_calls,
                       "timeout_s": settings.llm_timeout_s},
            "rules": ["Answers only from this person's data, the system cards and the protocols",
                      "Every claim cites a source; claims without one are dropped",
                      "No diagnosis, no medication doses: those go to the medical officer",
                      "Emergencies use Guided Response, never the assistant",
                      "Every question and answer is logged"]}
