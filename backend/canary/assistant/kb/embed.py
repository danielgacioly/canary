"""Embedders for the knowledge base.

`LocalEmbedder` runs BAAI/bge-small-en-v1.5 on the CPU through fastembed (ONNX, 384 dimensions), with its
model files cached in backend/.cache/ so the ship never needs a network once `make index` has run.
`NullEmbedder` embeds nothing: search is then BM25 only. It is used when CANARY_EMBEDDER=none or when
the local model cannot be loaded.
"""
import logging
import os
import threading
from typing import List, Optional, Protocol, Sequence

from ...config import ROOT, settings

log = logging.getLogger("canary.kb")

MODEL = "BAAI/bge-small-en-v1.5"
DIMS = 384
CACHE_DIR = str(ROOT / "backend" / ".cache")
# bge models expect this prefix on queries (not on passages).
QUERY_PREFIX = "Represent this sentence for searching relevant passages: "


class Embedder(Protocol):
    name: str   # recorded in kb_meta; vectors are only compared when the names match
    dims: int   # 0 means "no vectors"

    def embed_passages(self, texts: Sequence[str]) -> List[List[float]]: ...

    def embed_query(self, text: str) -> Optional[List[float]]: ...


class NullEmbedder:
    """No vectors at all: the knowledge base falls back to BM25."""
    name = "none"
    dims = 0

    def embed_passages(self, texts: Sequence[str]) -> List[List[float]]:
        return []

    def embed_query(self, text: str) -> Optional[List[float]]:
        return None


class LocalEmbedder:
    """fastembed with bge-small-en-v1.5. Raises on construction if the model cannot be loaded."""
    name = f"fastembed:{MODEL}"
    dims = DIMS

    def __init__(self, local_files_only: bool = False, cache_dir: str = CACHE_DIR):
        os.environ.setdefault("FASTEMBED_CACHE_PATH", cache_dir)
        from fastembed import TextEmbedding  # imported here: heavy, and optional at runtime
        self._model = TextEmbedding(model_name=MODEL, cache_dir=cache_dir, local_files_only=local_files_only)

    def embed_passages(self, texts: Sequence[str]) -> List[List[float]]:
        return [[float(x) for x in v] for v in self._model.passage_embed(list(texts))]

    def embed_query(self, text: str) -> Optional[List[float]]:
        return [float(x) for x in next(iter(self._model.embed([QUERY_PREFIX + text])))]


_lock = threading.Lock()
_cached: dict = {}


def get_embedder(offline: bool = True, kind: Optional[str] = None) -> Embedder:
    """The embedder chosen by CANARY_EMBEDDER ("local" or "none").

    `offline=True` (runtime) never downloads: it only uses model files already in the cache. The builder
    passes `offline=False` so `make index` can fetch the model once. Any failure gives a NullEmbedder.
    """
    kind = kind or settings.embedder
    if kind != "local":
        return NullEmbedder()
    with _lock:
        key = (kind, offline)
        if key not in _cached:
            try:
                _cached[key] = LocalEmbedder(local_files_only=offline)
            except Exception as e:  # missing model files, no network, broken onnxruntime
                log.warning("knowledge base: local embedder unavailable (%s); using BM25 only", e)
                _cached[key] = NullEmbedder()
        return _cached[key]
