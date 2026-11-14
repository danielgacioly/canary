"""Build the knowledge base file (`settings.kb_path`, backend/kb.db): `python -m canary.assistant.kb.build`.

Tables (docs/ai/schema.md §3): kb_documents, kb_chunks, kb_chunks_fts (FTS5, porter), kb_vec (sqlite-vec,
float[384], cosine) and kb_meta. The new file is written next to the old one and swapped in atomically, so
a reader never sees a half-built index. Vectors are re-embedded only for documents whose content_hash
changed (or when the embedder changed); the rest are copied from the previous file.
"""
import argparse
import datetime as dt
import logging
import os
import sqlite3
import struct
import tempfile
from typing import Dict, List, Optional

from ...config import settings
from . import corpus
from .embed import DIMS, Embedder, NullEmbedder, get_embedder

log = logging.getLogger("canary.kb")

SCHEMA = """
CREATE TABLE kb_documents (
  doc_id TEXT NOT NULL, version INTEGER NOT NULL, kind TEXT NOT NULL, title TEXT NOT NULL,
  legacy_id TEXT NOT NULL, reviewed TEXT NOT NULL, source_ref TEXT NOT NULL, content_hash TEXT NOT NULL,
  PRIMARY KEY (doc_id, version));
CREATE TABLE kb_chunks (
  rowid INTEGER PRIMARY KEY, chunk_id TEXT NOT NULL UNIQUE, doc_id TEXT NOT NULL, version INTEGER NOT NULL,
  section TEXT NOT NULL, gravity TEXT NOT NULL, location TEXT NOT NULL,
  not_in TEXT NOT NULL,      -- ",mars," places where a more specific variant of the same step replaces this one
  title TEXT NOT NULL, text TEXT NOT NULL,
  keywords TEXT NOT NULL,    -- plain-language words for lexical search only; never shown
  tokens INTEGER NOT NULL,
  FOREIGN KEY (doc_id, version) REFERENCES kb_documents (doc_id, version));
CREATE INDEX kb_chunks_doc ON kb_chunks (doc_id, version);
CREATE VIRTUAL TABLE kb_chunks_fts USING fts5(title, text, keywords, tokenize = 'porter unicode61');
CREATE TABLE kb_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


def load_vec(conn: sqlite3.Connection) -> bool:
    """Load sqlite-vec into a connection. False when the extension is not available."""
    try:
        import sqlite_vec
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
        return True
    except Exception as e:  # no extension support in this sqlite3 build, or package missing
        log.warning("knowledge base: sqlite-vec unavailable (%s); vector search disabled", e)
        return False


def pack(vec: List[float]) -> bytes:
    return struct.pack(f"{len(vec)}f", *vec)


def _previous(path: str, embedder_name: str) -> Dict[str, bytes]:
    """chunk_id → embedding from the old file, for documents whose content_hash we can trust."""
    if not os.path.exists(path):
        return {}
    try:
        old = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            meta = dict(old.execute("SELECT key, value FROM kb_meta"))
            if meta.get("embedder") != embedder_name or not load_vec(old):
                return {}
            hashes = {f"{d}@{v}": h for d, v, h in old.execute("SELECT doc_id, version, content_hash FROM kb_documents")}
            rows = old.execute("SELECT c.chunk_id, c.doc_id, c.version, v.embedding FROM kb_chunks c "
                               "JOIN kb_vec v ON v.rowid = c.rowid").fetchall()
            return {f"{cid}|{hashes.get(f'{d}@{ver}')}": bytes(e) for cid, d, ver, e in rows}
        finally:
            old.close()
    except sqlite3.Error as e:
        log.warning("knowledge base: cannot reuse vectors from %s (%s)", path, e)
        return {}


def embed_text(title: str, text: str, keywords: str = "") -> str:
    """What the embedder sees: title, text and the plain-language keywords (summary chunks only have them)."""
    return " ".join(x for x in (f"{title}.", text, keywords) if x)


def build(path: Optional[str] = None, embedder: Optional[Embedder] = None) -> dict:
    """Write the knowledge base to `path` and return a summary (counts, corpus_hash, embedder, re-embedded)."""
    path = path or settings.kb_path
    embedder = embedder or NullEmbedder()
    docs = corpus.documents()
    chash = corpus.corpus_hash(docs)
    reuse = _previous(path, embedder.name) if embedder.dims else {}

    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".kb-", suffix=".db", dir=os.path.dirname(os.path.abspath(path)))
    os.close(fd)
    conn = sqlite3.connect(tmp)
    try:
        conn.executescript(SCHEMA)
        has_vec = load_vec(conn)
        if has_vec:
            conn.execute(f"CREATE VIRTUAL TABLE kb_vec USING vec0(embedding float[{DIMS}] distance_metric=cosine)")
        rows, todo = [], []
        rowid = 0
        for d in docs:
            conn.execute("INSERT INTO kb_documents VALUES (?,?,?,?,?,?,?,?)",
                         (d.doc_id, d.version, d.kind, d.title, d.legacy_id, d.reviewed, d.source_ref, d.content_hash))
            for c in d.chunks:
                rowid += 1
                cid = d.chunk_id(c)
                not_in = "," + ",".join(c.not_in) + "," if c.not_in else ""
                conn.execute("INSERT INTO kb_chunks VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                             (rowid, cid, d.doc_id, d.version, c.section, c.gravity, c.location, not_in,
                              c.title, c.text, c.keywords, len(c.text.split())))
                conn.execute("INSERT INTO kb_chunks_fts (rowid, title, text, keywords) VALUES (?,?,?,?)",
                             (rowid, c.title, c.text, c.keywords))
                old = reuse.get(f"{cid}|{d.content_hash}")
                if old is not None:
                    rows.append((rowid, old))
                else:
                    todo.append((rowid, embed_text(c.title, c.text, c.keywords)))
        embedded = 0
        if has_vec and embedder.dims:
            if todo:
                vecs = embedder.embed_passages([t for _, t in todo])
                rows += [(rid, pack(v)) for (rid, _), v in zip(todo, vecs)]
                embedded = len(todo)
            conn.executemany("INSERT INTO kb_vec (rowid, embedding) VALUES (?, ?)", sorted(rows))
        vectors = embedder.dims > 0 and has_vec
        meta = {"embedder": embedder.name if vectors else "none", "dims": str(DIMS if vectors else 0),
                "built_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
                "corpus_hash": chash, "chunker": str(corpus.CHUNKER_VERSION)}
        conn.executemany("INSERT INTO kb_meta VALUES (?, ?)", sorted(meta.items()))
        conn.commit()
        kinds = dict(conn.execute("SELECT d.kind, COUNT(*) FROM kb_chunks c JOIN kb_documents d "
                                  "USING (doc_id, version) GROUP BY d.kind ORDER BY d.kind"))
        conn.close()
        os.chmod(tmp, 0o644)  # mkstemp makes it 0600; the index is not secret
        os.replace(tmp, path)
    except BaseException:
        conn.close()
        if os.path.exists(tmp):
            os.remove(tmp)
        raise
    return {"path": path, "documents": len(docs), "chunks": rowid, "by_kind": kinds, "corpus_hash": chash,
            "embedder": meta["embedder"], "embedded": embedded, "reused": len(rows) - embedded if vectors else 0}


def main(argv: Optional[List[str]] = None) -> None:
    ap = argparse.ArgumentParser(description="Build the Canary knowledge base (kb.db).")
    ap.add_argument("--path", default=settings.kb_path, help="output file (default: CANARY_KB)")
    ap.add_argument("--embedder", choices=("local", "none"), default=settings.embedder,
                    help="local = fastembed bge-small (downloads once into backend/.cache), none = BM25 only")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    for noisy in ("httpx", "httpcore", "huggingface_hub"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    r = build(a.path, get_embedder(offline=False, kind=a.embedder))
    size = os.path.getsize(r["path"])
    print(f"kb: {r['documents']} documents, {r['chunks']} chunks -> {r['path']} ({size / 1024:.0f} KiB)")
    print("    by kind: " + ", ".join(f"{k} {n}" for k, n in r["by_kind"].items()))
    print(f"    embedder: {r['embedder']} (embedded {r['embedded']}, reused {r['reused']})")
    print(f"    corpus_hash: {r['corpus_hash']}")


if __name__ == "__main__":
    main()
