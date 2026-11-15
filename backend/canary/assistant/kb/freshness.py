"""Is the knowledge base built from the corpus this code ships? (item 16)

At startup the API compares `kb_meta.corpus_hash` in settings.kb_path with the hash of the live corpus (corpus.py). A file
that is missing or built from an older corpus is rebuilt in a background thread: the API starts at once, the assistant
uses the file as it is meanwhile, and the embedder falls back to BM25 when it cannot load (embed.get_embedder). `make index`
rebuilds it ahead of time. `compare` is a pure function, so the rule is tested without a thread or a server.
"""
import logging
import os
import sqlite3
from typing import Optional

from . import build as _build
from . import corpus, embed

log = logging.getLogger("canary.kb")
FRESH, STALE, MISSING = "fresh", "stale", "missing"


def compare(stored: Optional[str], live: str) -> str:
    """FRESH when the stored corpus hash is the live one, STALE when it differs, MISSING when there is none."""
    if stored is None:
        return MISSING
    return FRESH if stored == live else STALE


def stored_hash(path: str) -> Optional[str]:
    """kb_meta.corpus_hash of a built file (read-only), or None when the file or the value is not there."""
    if not os.path.exists(path):
        return None
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    except sqlite3.Error:
        return None
    try:
        row = conn.execute("SELECT value FROM kb_meta WHERE key='corpus_hash'").fetchone()
        return row[0] if row else None
    except sqlite3.Error:
        return None
    finally:
        conn.close()


def live_hash() -> str:
    """The hash of the corpus this code ships (protocols, cards, places, NASA sources, hazards, privacy, self-tests, risks, care)."""
    return corpus.corpus_hash(corpus.documents())


def status(path: str) -> str:
    if not os.path.exists(path):
        return MISSING
    return compare(stored_hash(path), live_hash())


def rebuild(path: str) -> bool:
    """Build `path` again with the configured embedder (BM25 only when it cannot load). True when the build worked."""
    try:
        _build.build(path, embed.get_embedder(offline=True))
        return True
    except Exception as e:  # noqa: BLE001 - the API keeps running on the old file, or without one
        log.warning("knowledge base rebuild failed (%s); run `make index`", e)
        return False


def check_at_startup(path: str) -> str:
    """Runs in a background thread from the lifespan: log what is wrong and rebuild it. Returns the status it found."""
    st = status(path)
    if st != FRESH:
        log.warning("knowledge base %s is %s (built from another corpus); rebuilding it in the background. "
                    "`make index` rebuilds it now.", path, st)
        rebuild(path)
    return st
