"""Knowledge base: approved protocols, system cards, places and NASA sources, searched by the assistant.

Contract (docs/ai/plan.md Phase 3, docs/ai/schema.md §3). Implementation: `corpus.py` (documents and
chunks), `embed.py` (LocalEmbedder / NullEmbedder), `build.py` (writes kb.db), `hybrid.py`
(the search itself; not `search.py`, which would shadow this function).

- The index lives in `settings.kb_path` (backend/kb.db), built offline by `make index`
  (`python -m canary.assistant.kb.build`), opened read-only at runtime.
- `search` is hybrid: BM25 over `kb_chunks_fts` plus vector similarity over `kb_vec` when
  `settings.embedder == "local"` (fastembed); BM25 only when it is "none" or the embedder is unavailable.
- `kind` filters by document kind: "protocol", "system_card", "location", "nasa_source", "hazard",
  "privacy", "self_test" or "any".
- `gravity` ("g0" | "gp" | "g1") and `place` ("earth" | "rocket" | "iss" | "moon" | "transit" | "mars") keep
  chunks that match the current mission or are tagged "any", so the model never sees a variant for the wrong
  gravity or place. When only `place` is given, its gravity comes from `catalog.LOCATIONS[place]["gravity_key"]`.
  A gravity variant is also hidden where a place-specific variant of the same step replaces it.
- Below a minimum evidence score (BM25 or cosine) a chunk is dropped; no evidence at all returns [].
- Returns at most `k` chunks, best first. Every `chunk_id` is a versioned source id
  (`kb:{doc_id}@{version}#{chunk}`) that tools may return and the guard may accept.
- Never raises for a missing or unbuilt index: returns [] so the caller falls back to the in-memory cards.
"""
import logging
from dataclasses import dataclass
from typing import List, Optional

log = logging.getLogger("canary.kb")

KINDS = ("protocol", "system_card", "location", "nasa_source", "hazard", "privacy", "self_test", "any")


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
    location: str = "any"  # earth | rocket | iss | moon | transit | mars | any

    def as_tool_data(self) -> dict:
        """The fields a tool hands to the model (schema.md §5: chunk_id, title, text, score)."""
        return {"chunk_id": self.chunk_id, "title": self.title, "text": self.text, "score": round(self.score, 4)}


def search(query: str, kind: str = "any", k: int = 4, gravity: Optional[str] = None,
           place: Optional[str] = None) -> List[Chunk]:
    """Search the knowledge base (`settings.kb_path`). Never raises: any failure returns []."""
    from ...config import settings
    from . import hybrid as _search
    if kind not in KINDS:
        return []
    try:
        rows = _search.search(settings.kb_path, query, kind=kind, k=k, gravity=gravity, place=place)
    except Exception as e:  # unknown place, corrupt file, extension trouble: the caller falls back
        log.warning("knowledge search failed (%s)", e)
        return []
    return [Chunk(**r) for r in rows]


def ensure_index() -> bool:
    """For startup: build `settings.kb_path` if it is missing (logs a warning). True when it exists."""
    from ...config import settings
    from . import hybrid as _search
    try:
        return _search.ensure_index(settings.kb_path)
    except Exception as e:
        log.warning("knowledge base unavailable (%s)", e)
        return False


def legacy_map() -> dict:
    """Legacy source id (`protocol:seizure`, `card:brain`, `nasa:rad`) -> kb document id (data/kb_map.json)."""
    from . import corpus
    return corpus.legacy_map()
