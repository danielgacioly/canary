"""The on-board AI assistant (docs/ai/plan.md, data shapes in docs/ai/schema.md).

A model explains; deterministic code decides alerts, emergencies and thresholds. Every answer is checked
before anyone sees it.

- providers.py   NullProvider (default), AnthropicProvider (manual tool loop: CANARY_LLM_MAX_STEPS rounds,
                 CANARY_LLM_MAX_TOOL_CALLS calls, one CANARY_LLM_TIMEOUT_S deadline), LocalProvider (slot)
- chat.py        entry 1: ask(crew_id, question, viewer) -> precheck, provider loop, postcheck, log
- briefing.py    entry 2: weekly briefing; the model rewrites computed facts as a BriefingDraft
- suggestions.py entry 3: rule-written suggestions; a model may only rephrase each reason
- tools.py       8 strict tools bound to the signed-in viewer (ToolContext); route() picks them by rule
- guard.py       precheck (emergency, diagnosis, dose, injection) and postcheck (sources, numbers, wording,
                 action allow-list, other people's health), rule bank in data/guard_rules.json
- kb/            knowledge base in kb.db (`make index`): hybrid BM25 + vectors, BM25 only offline
- contracts.py   ToolContext, ToolResult, AssistantResponse, BriefingDraft, source-id and action formats
- prompts/       versioned system prompts; the version is logged with every answer
- knowledge.py   legacy card list from before the knowledge base (no longer used by chat)

Modes of a chat answer: "ai" (model answer that passed the guard), "grounded" (no provider set: rule answer
from route()), "fallback" (a set provider failed or the guard rejected its answer: rule answer), "unknown",
"refused", "emergency". Emergencies never go through the model: Guided Response is deterministic.
"""
