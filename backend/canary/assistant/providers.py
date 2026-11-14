"""LLM provider interface. Pick one with CANARY_LLM_PROVIDER (none | anthropic | local).

To plug a model in, implement `complete` in AnthropicProvider (ground support,
needs a network link) or LocalProvider (on board, no network), and return
structured output that guard.py can check:

    {"answer": str, "claims": [{"text": str, "source_ids": [str, ...]}]}

Every claim must cite only source ids that tools returned in the same turn.
"""
from dataclasses import dataclass, field
from typing import List, Optional, Protocol

from ..config import settings


@dataclass
class ProviderRequest:
    task: str                      # "chat" or "briefing"
    system: str                    # rules for the model (see chat.SYSTEM_PROMPT)
    question: str                  # user text, or the briefing instruction
    context: List[dict] = field(default_factory=list)  # tool results with their sources
    knowledge: List[dict] = field(default_factory=list)  # system cards and protocols


@dataclass
class ProviderResult:
    ok: bool
    answer: str = ""
    claims: List[dict] = field(default_factory=list)
    error: Optional[str] = None


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


class AnthropicProvider:
    """Slot for Claude through the Anthropic API (ground segment or a demo with internet).

    TODO(team): read ANTHROPIC_API_KEY from the environment (never commit it),
    send req.system + req.knowledge as a cached system prompt, req.context as
    tool results, ask for the JSON shape in the module docstring and parse it.
    """
    name = "anthropic"
    configured = False

    def complete(self, req: ProviderRequest) -> ProviderResult:
        return ProviderResult(ok=False, error="AnthropicProvider is a slot: not implemented yet")


class LocalProvider:
    """Slot for a small model running on board, with no network (e.g. through llama.cpp or Ollama)."""
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
            "entries": ["chat", "briefing"],
            "rules": ["Answers only from this person's data, the system cards and the protocols",
                      "Every claim cites a source; claims without one are dropped",
                      "No diagnosis, no medication doses: those go to the medical officer",
                      "Emergencies use Guided Response, never the assistant",
                      "Every question and answer is logged"]}
