"""Space for the on-board AI assistant.

The AI itself is not implemented. What is here is everything around it, so a
model can be plugged in without touching the rest of the system:

- providers.py  LLMProvider interface; NullProvider is the default
- knowledge.py  the only facts the assistant may use, each with a source id
- tools.py      read-only tools the model can call; every result carries sources
- guard.py      refuses diagnosis and dosing, checks citations and numbers
- chat.py       entry 1: an astronaut asks a question
- briefing.py   entry 2: a one-page weekly summary for the flight surgeon

Without a provider, both entries still answer with grounded, rule-based text.
Emergencies never go through the assistant: Guided Response is deterministic.
"""
