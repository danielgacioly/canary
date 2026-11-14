"""Test doubles for the AI layer. No network, no API key.

`ScriptedProvider` has the shape of `canary.assistant.providers.LLMProvider` (name, configured,
complete(req)) and replays canned turns in order, recording every request it was given. Each turn is
either a `ProviderResult` to return or an exception instance to raise (to test timeouts and API errors).

The provider-loop agent will extend this for tool-use turns (e.g. a turn that asks for a tool call,
then a turn with the final AssistantResponse JSON). Keep it data-driven: turns in, requests recorded.
"""
from typing import List, Optional, Sequence, Union

from canary.assistant.providers import ProviderRequest, ProviderResult

Turn = Union[ProviderResult, BaseException]


class ScriptedProvider:
    name = "scripted"

    def __init__(self, turns: Sequence[Turn] = (), configured: bool = True, name: Optional[str] = None):
        self.turns: List[Turn] = list(turns)
        self.configured = configured
        if name:
            self.name = name
        self.requests: List[ProviderRequest] = []

    @property
    def calls(self) -> int:
        return len(self.requests)

    @property
    def exhausted(self) -> bool:
        return self.calls >= len(self.turns)

    def complete(self, req: ProviderRequest) -> ProviderResult:
        self.requests.append(req)
        if len(self.requests) > len(self.turns):
            raise AssertionError(f"ScriptedProvider ran out of turns after {len(self.turns)} call(s)")
        turn = self.turns[len(self.requests) - 1]
        if isinstance(turn, BaseException):
            raise turn
        return turn


def answer(text: str, claims: Optional[list] = None) -> ProviderResult:
    """Shortcut for a successful final turn in the current ProviderResult shape."""
    return ProviderResult(ok=True, answer=text, claims=claims or [])
