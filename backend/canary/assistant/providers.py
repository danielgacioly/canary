"""LLM provider interface. Pick one with CANARY_LLM_PROVIDER (auto | none | gemini | anthropic | local).

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
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol, Tuple

from ..config import settings
from . import contracts, tools
from .contracts import ToolContext, ToolResult

log = logging.getLogger("canary.assistant")


@dataclass
class ProviderRequest:
    task: str                      # "chat" | "briefing" | "suggestions" (contracts.AI_ENTRIES)
    system: str                    # stable rules for the model (prompts/*.md), sent as systemInstruction
    question: str                  # the user message: question plus who asks, or the briefing/suggestions input
    context: List[dict] = field(default_factory=list)  # chat: unused (tools fetch data); others: computed facts
    knowledge: List[dict] = field(default_factory=list)  # legacy: cards pasted in the prompt (not sent any more)
    ctx: Optional[ToolContext] = None        # chat: the bound person and viewer every tool call runs in
    deadline: Optional[float] = None         # time.monotonic() value; default now + settings.llm_timeout_s
    output_schema: Optional[Dict[str, Any]] = None  # JSON Schema for responseJsonSchema (default per task)


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


# ---------------------------------------------------------------- shared tool loop and provider adapters

MAX_TOKENS = 2000
# HTTP statuses that mean "try again shortly": 503 unavailable (both APIs), 529 overloaded (Anthropic).
RETRY_STATUS = (503, 529)
REPEAT_NOTE = "Repeated call: this is the same result as before. Use it instead of calling again."
BUDGET_NOTE = "Tool budget used up for this question: answer from the results you already have."


def _parse_json(text: str) -> Any:
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        return None


class ToolCallingProvider:
    """Shared execution budgets, tool validation, audit and failure handling.

    Subclasses translate native messages without altering their signed model content.
    """
    name: str
    key_env: str
    model_setting: str

    def __init__(self, client: Any = None):
        self._client = client

    @property
    def configured(self) -> bool:
        return self._client is not None or bool(os.environ.get(self.key_env, "").strip())

    @property
    def model(self) -> str:
        # The global override applies only to an explicitly selected provider: under "auto" the key decides the
        # provider, so a CANARY_LLM_MODEL meant for one provider must never be sent to the other.
        if settings.llm_model and settings.llm_provider == self.name:
            return settings.llm_model
        return getattr(settings, self.model_setting)

    def _post(self, url: str, body: dict, headers: dict, timeout: float) -> dict:
        import httpx
        deadline = time.monotonic() + timeout

        def send(client):
            for attempt in range(3):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise httpx.TimeoutException("AI request deadline exhausted")
                response = client.post(url, json=body, headers=headers, timeout=remaining)
                if response.status_code not in RETRY_STATUS or attempt == 2:
                    return response
                # Retry only an explicit unavailable/overloaded response, never an ambiguous timeout.
                delay = 2 ** attempt
                retry_after = response.headers.get("retry-after", "")
                if retry_after.isdigit():
                    delay = max(delay, int(retry_after))
                if deadline - time.monotonic() <= delay:
                    return response
                response.close()
                time.sleep(delay)
            raise AssertionError("unreachable")

        if self._client is not None:
            response = send(self._client)
        else:
            with httpx.Client() as client:
                response = send(client)
        response.raise_for_status()
        try:
            result = response.json()
        except ValueError:
            return {}
        return result if isinstance(result, dict) else {}

    @staticmethod
    def _api_error(e: BaseException) -> Optional[Tuple[str, str]]:
        import httpx
        if isinstance(e, httpx.TimeoutException):
            return "api:timeout", "AI service timed out"
        if isinstance(e, httpx.HTTPStatusError):
            code = e.response.status_code
            if code == 429:
                return "api:rate_limit", "AI service rate limit"
            if code in RETRY_STATUS:
                return "api:status", f"AI service temporarily unavailable ({code})"
            if code in (408, 504):
                return "api:timeout", "AI service timed out"
            return "api:status", f"AI service error {code}"
        if isinstance(e, httpx.RequestError):
            return "api:connection", "no connection to the AI service"
        return None

    def complete(self, req: ProviderRequest) -> ProviderResult:
        deadline = req.deadline if req.deadline is not None else time.monotonic() + settings.llm_timeout_s
        out = ProviderResult(ok=False, model=self.model)
        if not self.configured:  # no key and no injected client: never attempt a request
            out.error, out.guard_exit = GUARD_EXITS["api:error"], "api:error"
            return out
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

    def _finish(self, out: ProviderResult, msg: Any, task: str) -> ProviderResult:
        text = self._text(msg)
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

    def _single(self, req: ProviderRequest, deadline: float, out: ProviderResult) -> ProviderResult:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return self._fail(out, "loop:timeout")
        user = req.question
        if req.context:
            user += "\n\nComputed facts (JSON):\n" + json.dumps(req.context, ensure_ascii=False, default=str)
        out.steps = 1
        try:
            msg = self._call(req, [self._user_message(user)], with_tools=False, timeout=remaining)
        except Exception as e:  # noqa: BLE001 - only transport errors are swallowed, see _api_error
            err = self._api_error(e)
            if err is None:
                raise
            return self._fail(out, *err)
        self._usage(out, msg)
        if time.monotonic() >= deadline:
            return self._fail(out, "loop:timeout")
        stopped = self._stop(out, msg)
        if stopped:
            return stopped
        return self._finish(out, msg, req.task)

    def _loop(self, req: ProviderRequest, deadline: float, out: ProviderResult) -> ProviderResult:
        ctx = req.ctx
        messages: List[dict] = [self._user_message(req.question)]
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
            except Exception as e:  # noqa: BLE001 - only transport errors are swallowed, see _api_error
                err = self._api_error(e)
                if err is None:
                    raise
                return self._fail(out, *err)
            self._usage(out, msg)
            if time.monotonic() >= deadline:
                return self._fail(out, "loop:timeout")
            stopped = self._stop(out, msg)
            if stopped:
                return stopped
            content = self._model_message(msg)
            uses = self._tool_calls(msg)
            if not uses:
                return self._finish(out, msg, req.task)

            # Echo native model content unchanged, including thinking signatures.
            messages.append(content)
            results = []
            for b in uses:
                name, args = b.get("name"), b.get("args", {})
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
            messages.append(self._user_message(results))


def gemini_thinking(model: str, effort: str) -> Optional[Dict[str, str]]:
    """thinkingConfig for Gemini 3 models only (older ids reject thinkingLevel). Gemini accepts LOW or HIGH:
    "high" maps to HIGH, any other effort to LOW."""
    if not model.lower().startswith("gemini-3"):
        return None
    return {"thinkingLevel": "HIGH" if effort.strip().lower() == "high" else "LOW"}


class GeminiProvider(ToolCallingProvider):
    """Gemini Developer API, with credentials only in the request header."""
    name = "gemini"
    key_env = "GEMINI_API_KEY"
    model_setting = "gemini_model"

    def _call(self, req: ProviderRequest, messages: List[dict], with_tools: bool, timeout: float) -> Any:
        from urllib.parse import quote

        config: Dict[str, Any] = {"maxOutputTokens": MAX_TOKENS}
        thinking = gemini_thinking(self.model, settings.llm_effort)
        if thinking:
            config["thinkingConfig"] = thinking
        schema = req.output_schema or default_schema(req.task)
        if schema:
            config.update(responseMimeType="application/json", responseJsonSchema=schema)
        body = {"systemInstruction": {"parts": [{"text": req.system}]},
                "contents": messages, "generationConfig": config}
        if with_tools:
            body["tools"] = [{"functionDeclarations": tools.gemini_tools()}]
            body["toolConfig"] = {"functionCallingConfig": {"mode": "AUTO"}}
        url = "https://generativelanguage.googleapis.com/v1beta/models/" + quote(self.model, safe="") + ":generateContent"
        return self._post(url, body, {"x-goog-api-key": os.environ.get(self.key_env, "").strip()}, timeout)

    @staticmethod
    def _usage(out: ProviderResult, msg: Any) -> None:
        u = msg.get("usageMetadata") or {}
        out.input_tokens += int(u.get("promptTokenCount") or 0)
        out.output_tokens += int(u.get("candidatesTokenCount") or 0) + int(u.get("thoughtsTokenCount") or 0)
        out.model = msg.get("modelVersion") or out.model

    @staticmethod
    def _candidate(msg: dict) -> dict:
        candidates = msg.get("candidates") or []
        return candidates[0] if candidates else {}

    def _stop(self, out: ProviderResult, msg: Any) -> Optional[ProviderResult]:
        """Handle the stop reasons that end a call before content is read."""
        reason = self._candidate(msg).get("finishReason")
        if (msg.get("promptFeedback") or {}).get("blockReason") or reason in {
            "SAFETY", "RECITATION", "BLOCKLIST", "PROHIBITED_CONTENT", "SPII", "IMAGE_SAFETY"}:
            return self._fail(out, "model:refusal")
        if reason == "MAX_TOKENS":
            return self._fail(out, "model:max_tokens")
        if reason != "STOP":
            return self._fail(out, "model:bad_output")
        return None

    @staticmethod
    def _result_block(block: Any, payload: dict) -> dict:
        response = {"name": block["name"], "response": payload}
        if block.get("id"):
            response["id"] = block["id"]
        return {"functionResponse": response}

    def _text(self, msg: dict) -> str:
        parts = (self._candidate(msg).get("content") or {}).get("parts", [])
        return "".join(p.get("text", "") for p in parts if not p.get("thought")).strip()

    @staticmethod
    def _user_message(content: Any) -> dict:
        return {"role": "user", "parts": [{"text": content}] if isinstance(content, str) else content}

    def _model_message(self, msg: dict) -> dict:
        return self._candidate(msg).get("content") or {}

    def _tool_calls(self, msg: dict) -> list:
        return [p["functionCall"] for p in self._model_message(msg).get("parts", []) if "functionCall" in p]


class AnthropicProvider(ToolCallingProvider):
    """Anthropic Messages API through the same HTTP transport and guarded executor."""
    name = "anthropic"
    key_env = "ANTHROPIC_API_KEY"
    model_setting = "anthropic_model"

    def _call(self, req: ProviderRequest, messages: List[dict], with_tools: bool, timeout: float) -> dict:
        output_config = {"effort": settings.llm_effort}
        schema = req.output_schema or default_schema(req.task)
        if schema:
            output_config["format"] = {"type": "json_schema", "schema": schema}
        body = {"model": self.model, "max_tokens": MAX_TOKENS,
                "thinking": {"type": "adaptive"}, "output_config": output_config,
                "system": [{"type": "text", "text": req.system, "cache_control": {"type": "ephemeral"}}],
                "messages": messages, "fallbacks": "default"}
        if with_tools:
            body["tools"] = tools.anthropic_tools()
            body["tool_choice"] = {"type": "auto"}
        headers = {"Authorization": "Bearer " + os.environ.get(self.key_env, "").strip(),
                   "anthropic-version": "2026-10-21",
                   "anthropic-beta": "server-side-fallback-2026-07-01"}
        return self._post("https://api.anthropic.com/v1/messages", body, headers, timeout)

    @staticmethod
    def _usage(out: ProviderResult, msg: dict) -> None:
        usage = msg.get("usage") or {}
        out.input_tokens += sum(int(usage.get(k) or 0) for k in
                                ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"))
        out.output_tokens += int(usage.get("output_tokens") or 0)
        out.model = msg.get("model") or out.model

    def _stop(self, out: ProviderResult, msg: dict) -> Optional[ProviderResult]:
        reason = msg.get("stop_reason")
        if reason == "refusal":
            return self._fail(out, "model:refusal")
        if reason == "max_tokens":
            return self._fail(out, "model:max_tokens")
        if reason not in {"end_turn", "tool_use"}:
            return self._fail(out, "model:bad_output")
        return None

    @staticmethod
    def _text(msg: dict) -> str:
        return "".join(p.get("text", "") for p in msg.get("content", []) if p.get("type") == "text").strip()

    @staticmethod
    def _user_message(content: Any) -> dict:
        return {"role": "user", "content": content}

    @staticmethod
    def _model_message(msg: dict) -> dict:
        return {"role": "assistant", "content": msg.get("content", [])}

    @staticmethod
    def _tool_calls(msg: dict) -> list:
        return [{"id": p.get("id"), "name": p.get("name"), "args": p.get("input", {})}
                for p in msg.get("content", []) if p.get("type") == "tool_use"]

    @staticmethod
    def _result_block(block: dict, payload: dict) -> dict:
        result = {"type": "tool_result", "tool_use_id": block["id"],
                  "content": json.dumps(payload, ensure_ascii=False, default=str)}
        if payload.get("error") is not None:
            result["is_error"] = True
        return result


class LocalProvider:
    """Slot for a small model running on board, with no network. Same interface as GeminiProvider.

    What it would need (not built in this plan): a small instruction-tuned model served by llama.cpp or Ollama
    with JSON-schema-constrained output (grammar from `default_schema(task)`) and tool calling, driven by the same
    loop and guards as GeminiProvider."""
    name = "local"
    configured = False

    def complete(self, req: ProviderRequest) -> ProviderResult:
        return ProviderResult(ok=False, error="LocalProvider is a slot: not implemented yet")


_PROVIDERS = {"none": NullProvider, "gemini": GeminiProvider, "anthropic": AnthropicProvider, "local": LocalProvider}


_warned: set = set()


def selection_warning() -> Optional[str]:
    """A message when CANARY_LLM_PROVIDER holds an unknown value (the assistant then runs offline)."""
    if settings.llm_provider == "auto" or settings.llm_provider in _PROVIDERS:
        return None
    return (f"Unknown CANARY_LLM_PROVIDER {settings.llm_provider!r}: using offline rules. "
            f"Expected one of: auto, {', '.join(_PROVIDERS)}.")


def get_provider() -> LLMProvider:
    warning = selection_warning()
    if warning:
        if settings.llm_provider not in _warned:
            _warned.add(settings.llm_provider)
            log.warning(warning)
        return NullProvider()
    if settings.llm_provider == "auto":
        # Deterministic priority if both keys are set. Never switch providers after an API failure.
        for name in ("gemini", "anthropic"):
            provider = _PROVIDERS[name]()
            if provider.configured:
                return provider
        return NullProvider()
    return _PROVIDERS[settings.llm_provider]()


def status() -> dict:
    p = get_provider()
    return {"provider": p.name, "configured": p.configured, "available": list(_PROVIDERS),
            "model": getattr(p, "model", None),
            "selection": settings.llm_provider,
            "warning": selection_warning(),
            "entries": list(contracts.AI_ENTRIES),
            "limits": {"max_steps": settings.llm_max_steps, "max_tool_calls": settings.llm_max_tool_calls,
                       "timeout_s": settings.llm_timeout_s},
            "rules": ["Answers only from this person's data, the system cards and the protocols",
                      "Every claim cites a source; claims without one are dropped",
                      "No diagnosis, no medication doses: those go to the medical officer",
                      "Emergencies use Guided Response, never the assistant",
                      "Every question and answer is logged"]}
