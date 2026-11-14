"""Hybrid search over kb.db: BM25 (FTS5) + vectors (sqlite-vec), fused with Reciprocal Rank Fusion.

Steps: filter by kind, gravity and place, take the BM25 top 20 and the vector top 20, fuse them with RRF,
keep only chunks with real evidence (a BM25 or cosine score above a floor), return the best `k`.
When nothing clears the floor the result is [] so the model hears "no evidence" instead of a weak match.
The file is opened read-only; a missing file is built once (BM25 only if no embedder) with a warning.
"""
import logging
import os
import re
import sqlite3
import threading
from typing import Dict, List, Optional, Tuple

from ...domain.catalog import LOCATIONS
from .build import build, load_vec, pack
from .embed import Embedder, get_embedder

log = logging.getLogger("canary.kb")

TOP_N = 20          # candidates from each retriever
RRF_K = 60          # standard RRF constant
MIN_BM25 = 2.0      # -bm25() floor for a lexical match to count as evidence
MIN_COSINE = 0.66   # cosine floor for a vector match to count as evidence (bge-small: off-topic queries reach ~0.60)

STOPWORDS = frozenset("""
a about above after again all am an and any are as at be been before being below between both but by can
could did do does doing down during each few for from further had has have having he her here hers him his
how i if in into is it its itself just me more most my myself no nor now of off on once only or other our
ours out over own same she should so some such than that the their theirs them then there these they this
those through to too under until up very was we were what when where which while who whom why will with
would you your yours yourself someone something anyone thing things mean means please tell know get got
""".split())

# Words too common to be evidence on their own (plan.md W1-3): "best football team" must not retrieve the privacy
# contract on "team". They still search and still rank; they only never make a lexical match count alone.
GENERIC = frozenset("""
team teams crew best better good great bad nice fine day days today tonight tomorrow yesterday week time times
people person thing way ways lot lots kind sort like want need make made use used work works new old big small
long little many much well really right left first last next one two three year years life world
look looks say said think go going come give find help ok okay yes sure maybe also even still feel feeling
friend friends guy guys stuff recommend favourite favorite worse worst happen happens happened space earth
""".split())
# Words that are only specific next to a qualifier: the corpus knows "space weather", not the weather on Earth.
QUALIFIED = {"weather": frozenset({"space", "solar"})}
MIN_TERMS = 2       # a lexical match needs this many matched query terms (fewer only if the query has fewer)

_build_lock = threading.Lock()


def connect(path: str) -> Tuple[sqlite3.Connection, bool]:
    """Read-only connection plus whether sqlite-vec is loaded."""
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, check_same_thread=False)
    return conn, load_vec(conn)


def ensure_index(path: str, embedder: Optional[Embedder] = None) -> bool:
    """Build the index if the file is missing. True when the file exists afterwards."""
    if os.path.exists(path):
        return True
    with _build_lock:
        if os.path.exists(path):
            return True
        embedder = embedder or get_embedder(offline=True)
        log.warning("knowledge base %s is missing; building it now (embedder: %s). Run `make index` to build it ahead.",
                    path, embedder.name)
        try:
            build(path, embedder)
        except Exception as e:
            log.warning("knowledge base build failed (%s)", e)
            return False
    return True


def query_terms(query: str) -> List[str]:
    """Meaningful query words: lower-case, no stopwords, no repeats, single letters dropped."""
    words: List[str] = []
    for w in re.findall(r"[a-z0-9]+", query.lower()):
        if w not in STOPWORDS and w not in words and (len(w) > 1 or w.isdigit()):
            words.append(w)
    return words


def fts_query(query: str) -> str:
    return " OR ".join(f'"{w}"' for w in query_terms(query))


def _matched_terms(conn: sqlite3.Connection, terms: List[str], rowids: List[int]) -> Dict[int, set]:
    """rowid -> the query terms that chunk matches (same tokenizer and stemming as the index)."""
    out: Dict[int, set] = {rid: set() for rid in rowids}
    if not rowids:
        return out
    marks = ",".join("?" * len(rowids))
    for t in terms:
        for (rid,) in conn.execute(f"SELECT rowid FROM kb_chunks_fts WHERE kb_chunks_fts MATCH ? AND rowid IN ({marks})",
                                   [f'"{t}"'] + rowids):
            out[rid].add(t)
    return out


def lexical_evidence(terms: List[str], matched: set) -> bool:
    """A BM25 hit counts as evidence only when it matches at least MIN_TERMS specific (non-generic) query terms,
    or every specific term when the query has fewer; generic words never count. So "seizure" or "I feel
    hopeless" (one specific term) match on that term, "recommend a movie" needs two of its words in one chunk,
    and "best football team" (specific: football) never matches on "team"."""
    specific = {t for t in terms if t not in GENERIC and (t not in QUALIFIED or QUALIFIED[t] & set(terms))}
    hit = matched & specific
    return bool(hit) and len(hit) >= min(MIN_TERMS, len(specific))


def resolve_filters(gravity: Optional[str], place: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    if place is not None and place not in LOCATIONS:
        raise ValueError(f"unknown place {place!r}")
    if gravity is None and place is not None:
        gravity = LOCATIONS[place]["gravity_key"]
    if gravity is not None and gravity not in ("g0", "gp", "g1"):
        raise ValueError(f"unknown gravity {gravity!r}")
    return gravity, place


def _where(kind: str, gravity: Optional[str], place: Optional[str]) -> Tuple[str, list]:
    sql, args = [], []
    if kind != "any":
        sql.append("d.kind = ?")
        args.append(kind)
    if gravity:
        sql.append("c.gravity IN ('any', ?)")
        args.append(gravity)
    if place:
        sql.append("c.location IN ('any', ?) AND instr(c.not_in, ?) = 0")
        args += [place, f",{place},"]
    return (" AND " + " AND ".join(sql)) if sql else "", args


COLS = "c.rowid, c.chunk_id, c.doc_id, c.version, c.title, c.text, c.section, c.gravity, c.location"
FROM = "FROM kb_chunks c JOIN kb_documents d ON d.doc_id = c.doc_id AND d.version = c.version"


def run(conn: sqlite3.Connection, has_vec: bool, embedder: Embedder, query: str, kind: str, k: int,
        gravity: Optional[str], place: Optional[str]) -> List[dict]:
    """The search itself on an open connection. Returns dicts with the Chunk fields."""
    where, args = _where(kind, gravity, place)
    rows: Dict[int, tuple] = {}
    bm25: Dict[int, Tuple[int, float]] = {}     # rowid -> (rank, relevance)
    vec: Dict[int, Tuple[int, float]] = {}

    terms = query_terms(query)
    q = " OR ".join(f'"{w}"' for w in terms)
    if q:
        sql = (f"SELECT {COLS}, -bm25(kb_chunks_fts, 2.0, 1.0, 1.5) AS s {FROM} "
               f"JOIN kb_chunks_fts f ON f.rowid = c.rowid WHERE kb_chunks_fts MATCH ?{where} "
               f"ORDER BY s DESC LIMIT {TOP_N}")
        for rank, r in enumerate(conn.execute(sql, [q] + args), 1):
            rows[r[0]] = r[:-1]
            bm25[r[0]] = (rank, r[-1])
        matched = _matched_terms(conn, terms, list(bm25))
        for rid in list(bm25):
            if not lexical_evidence(terms, matched[rid]):
                bm25[rid] = (bm25[rid][0], 0.0)  # still ranks for RRF, never counts as evidence

    meta = dict(conn.execute("SELECT key, value FROM kb_meta"))
    if has_vec and embedder.dims and meta.get("embedder") == embedder.name:
        qv = embedder.embed_query(query)
        if qv:
            total = conn.execute("SELECT COUNT(*) FROM kb_chunks").fetchone()[0]
            near = conn.execute("SELECT rowid, distance FROM kb_vec WHERE embedding MATCH ? AND k = ?",
                                (pack(qv), total)).fetchall()
            allowed = {r[0]: r for r in conn.execute(f"SELECT {COLS} {FROM} WHERE 1 = 1{where}", args)}
            rank = 0
            for rid, dist in near:  # already sorted by distance
                if rid in allowed:
                    rank += 1
                    rows[rid] = allowed[rid]
                    vec[rid] = (rank, 1.0 - dist)
                    if rank >= TOP_N:
                        break

    fused = []
    for rid in rows:
        evidence = (rid in bm25 and bm25[rid][1] >= MIN_BM25) or (rid in vec and vec[rid][1] >= MIN_COSINE)
        if not evidence:
            continue
        score = sum(1.0 / (RRF_K + lst[rid][0]) for lst in (bm25, vec) if rid in lst)
        fused.append((score, rows[rid][1], rid))
    fused.sort(key=lambda t: (-t[0], t[1]))
    out = []
    for score, _, rid in fused[:k]:
        _, chunk_id, doc_id, version, title, text, section, g, loc = rows[rid]
        out.append({"chunk_id": chunk_id, "doc_id": doc_id, "version": version, "title": title, "text": text,
                    "score": score, "section": section, "gravity": g, "location": loc})
    return out


def search(path: str, query: str, kind: str = "any", k: int = 4, gravity: Optional[str] = None,
           place: Optional[str] = None, embedder: Optional[Embedder] = None, build_missing: bool = True) -> List[dict]:
    if not query or not query.strip() or k <= 0:
        return []
    gravity, place = resolve_filters(gravity, place)
    if build_missing and not ensure_index(path, embedder):
        return []
    if not os.path.exists(path):
        return []
    embedder = embedder or get_embedder(offline=True)
    conn, has_vec = connect(path)
    try:
        return run(conn, has_vec, embedder, query, kind, k, gravity, place)
    finally:
        conn.close()
