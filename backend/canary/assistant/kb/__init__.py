"""Knowledge base: approved protocols, system cards, places and NASA sources, searched by the assistant.

Contract (docs/ai/plan.md Phase 3, docs/ai/schema.md §3). Wave 0 fixes only the signature; the
knowledge-base agent implements it behind this exact interface:

- The index lives in `settings.kb_path` (backend/kb.db), built offline by `make index`
  (`python -m canary.assistant.kb.build`), opened read-only at runtime.
- `search` is hybrid: BM25 over `kb_chunks_fts` plus vector similarity over `kb_vec` when
  `settings.embedder == "local"` (fastembed); BM25 only when it is "none" or the embedder is unavailable.
- `kind` filters by document kind: "protocol", "system_card", "location", "nasa_source" or "any".
- `gravity` ("g0" | "gp" | "g1") and `place` ("earth" | "transit" | "mars") keep chunks that match the
  current mission or are tagged "any", so the model never sees a variant for the wrong gravity.
- Returns at most `k` chunks, best first. Every `chunk_id` is a versioned source id
  (`kb:{doc_id}@{version}#{chunk}`) that tools may return and the guard may accept.
- Never raises for a missing or unbuilt index: returns [] so the caller falls back to the in-memory cards.
"""
from dataclasses import dataclass
from typing import List, Optional

KINDS = ("protocol", "system_card", "location", "nasa_source", "any")


@dataclass(frozen=True)
class Chunk:
    chunk_id: str          # kb:PROTO-NEURO-001@1#s2
    doc_id: str            # PROTO-NEURO-001
    version: int           # 1
    title: str
    text: str
    score: float           # higher is better; only comparable within one search
    section: str           # summary | step | variant | after
    gravity: str = "any"   # g0 | gp | g1 | any
    location: str = "any"  # earth | transit | mars | any

    def as_tool_data(self) -> dict:
        """The fields a tool hands to the model (schema.md §5: chunk_id, title, text, score)."""
        return {"chunk_id": self.chunk_id, "title": self.title, "text": self.text, "score": round(self.score, 4)}


def search(query: str, kind: str = "any", k: int = 4, gravity: Optional[str] = None,
           place: Optional[str] = None) -> List[Chunk]:
    """Search the knowledge base. Stub: returns [] until the knowledge-base agent implements it."""
    return []
