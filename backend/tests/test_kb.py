"""Knowledge base (docs/ai/plan.md Phase 3, schema.md §3): build, ids, retrieval, gravity/place filter,
abstention and reproducibility. No model and no network: BM25 only, or a tiny deterministic fake embedder."""
import hashlib
import json
import logging
import math
import re
import sqlite3

import pytest

from canary.assistant import contracts as C
from canary.assistant import kb
from canary.assistant.kb import build as B
from canary.assistant.kb import corpus, hybrid
from canary.assistant.kb.embed import DIMS, NullEmbedder
from canary.config import settings
from canary.domain import protocols, selftests
from canary.domain.catalog import LOCATIONS, SYSTEMS


class FakeEmbedder:
    """Bag of hashed words, normalised: deterministic, instant, good enough to exercise the vector path."""
    name = "fake:hash-bow"
    dims = DIMS

    def __init__(self):
        self.passages = 0

    def _vec(self, text):
        v = [0.0] * DIMS
        for w in re.findall(r"[a-z0-9]+", text.lower()):
            v[int(hashlib.md5(w.encode()).hexdigest(), 16) % DIMS] += 1.0
        n = math.sqrt(sum(x * x for x in v)) or 1.0
        return [x / n for x in v]

    def embed_passages(self, texts):
        self.passages += len(texts)
        return [self._vec(t) for t in texts]

    def embed_query(self, text):
        return self._vec(text)


@pytest.fixture(scope="module")
def kb_path(tmp_path_factory):
    path = str(tmp_path_factory.mktemp("kb") / "kb.db")
    B.build(path, NullEmbedder())
    return path


@pytest.fixture
def use_kb(kb_path, monkeypatch):
    """Point the public kb.search at the BM25-only test index."""
    monkeypatch.setattr(settings, "kb_path", kb_path)
    monkeypatch.setattr(settings, "embedder", "none")
    return kb_path


def rows(path, sql, args=()):
    conn = sqlite3.connect(path)
    B.load_vec(conn)
    try:
        return conn.execute(sql, args).fetchall()
    finally:
        conn.close()


# ---------------------------------------------------------------- build and ids
def test_build_writes_every_table_and_kind(kb_path):
    tables = {r[0] for r in rows(kb_path, "SELECT name FROM sqlite_master")}
    assert {"kb_documents", "kb_chunks", "kb_chunks_fts", "kb_vec", "kb_meta"} <= tables
    meta = dict(rows(kb_path, "SELECT key, value FROM kb_meta"))
    assert meta["embedder"] == "none" and meta["dims"] == "0" and len(meta["corpus_hash"]) == 64
    kinds = dict(rows(kb_path, "SELECT kind, COUNT(*) FROM kb_documents GROUP BY kind"))
    assert kinds == {"protocol": len(protocols.order()), "system_card": len(SYSTEMS), "location": 6,
                     "nasa_source": 4, "hazard": 5, "privacy": 1, "self_test": len(selftests.TESTS)}
    docs = {r[0] for r in rows(kb_path, "SELECT doc_id FROM kb_documents")}
    assert {f"HAZARD-{h}" for h in "RIDGE"} <= docs
    assert {f"LOC-{p.upper()}" for p in LOCATIONS} <= docs
    assert {"PRIVACY-CONTRACT", "TEST-KSS", "TEST-TLX", "TEST-WELLBEING", "PROTO-NEURO-001", "CARD-EYES"} <= docs


def test_chunk_ids_are_versioned_kb_sources(kb_path):
    ids = [r[0] for r in rows(kb_path, "SELECT chunk_id FROM kb_chunks")]
    assert len(ids) == len(set(ids)) > 100
    assert all(C.KB_SOURCE_RE.match(i) and C.is_knowledge_source(i) for i in ids)
    assert "kb:PROTO-NEURO-001@1#s2-g0" in ids and "kb:TEST-KSS@1#summary" in ids
    assert "kb:HAZARD-G@1#mars" in ids and "kb:PRIVACY-CONTRACT@1#r3" in ids


def test_chunks_follow_the_protocol_bank(kb_path):
    bank = json.loads((corpus.DATA / "protocols.json").read_text())
    for pid, p in bank["protocols"].items():
        assert isinstance(p["version"], int) and p["reviewed"] == "illustrative"
        doc = corpus.load_map()["protocols"][pid]
        sections = [r[0] for r in rows(kb_path, "SELECT section FROM kb_chunks WHERE doc_id = ?", (doc,))]
        assert sections.count("summary") == 1 and sections.count("step") == len(p["steps"])
        assert sections.count("variant") == sum(len(st.get("v") or {}) for st in p["steps"])


def test_kb_map_covers_every_legacy_id(kb_path):
    legacy = kb.legacy_map()
    docs = {r[0] for r in rows(kb_path, "SELECT doc_id FROM kb_documents")}
    assert set(legacy.values()) <= docs
    assert {f"protocol:{pid}" for pid in protocols.order()} <= set(legacy)
    assert {f"card:{sid}" for sid in SYSTEMS} <= set(legacy)
    m = corpus.load_map()
    assert set(m["keywords"]) <= docs and set(m["notes"]) <= docs


def test_same_corpus_same_hash(tmp_path):
    a, b = str(tmp_path / "a.db"), str(tmp_path / "b.db")
    ra, rb = B.build(a, NullEmbedder()), B.build(b, NullEmbedder())
    assert ra["corpus_hash"] == rb["corpus_hash"] == corpus.corpus_hash(corpus.documents())
    q = "SELECT chunk_id, gravity, location, not_in, title, text FROM kb_chunks ORDER BY rowid"
    assert rows(a, q) == rows(b, q)
    assert rows(a, "SELECT * FROM kb_documents ORDER BY doc_id") == rows(b, "SELECT * FROM kb_documents ORDER BY doc_id")


def test_changed_document_changes_the_hash():
    docs = corpus.documents()
    before = corpus.corpus_hash(docs)
    docs[0].chunks[0].text += " Changed."
    assert corpus.corpus_hash(docs) != before


def test_reembeds_only_changed_documents(tmp_path, monkeypatch):
    if not _has_vec():
        pytest.skip("sqlite-vec not available")
    path = str(tmp_path / "kb.db")
    e1 = FakeEmbedder()
    r1 = B.build(path, e1)
    assert r1["embedder"] == FakeEmbedder.name and r1["embedded"] == r1["chunks"] == e1.passages
    assert rows(path, "SELECT COUNT(*) FROM kb_vec")[0][0] == r1["chunks"]

    e2 = FakeEmbedder()
    r2 = B.build(path, e2)
    assert e2.passages == 0 and r2["embedded"] == 0 and r2["corpus_hash"] == r1["corpus_hash"]

    real = corpus.documents

    def edited():
        docs = real()
        d = next(d for d in docs if d.doc_id == "CARD-EYES")
        d.chunks[0].text += " Edited by the flight surgeon."
        return docs

    monkeypatch.setattr(corpus, "documents", edited)
    e3 = FakeEmbedder()
    r3 = B.build(path, e3)
    assert e3.passages == 1 and r3["corpus_hash"] != r1["corpus_hash"]


def _has_vec():
    conn = sqlite3.connect(":memory:")
    try:
        return B.load_vec(conn)
    finally:
        conn.close()


def test_runtime_connection_is_read_only(kb_path):
    conn, _ = hybrid.connect(kb_path)
    try:
        with pytest.raises(sqlite3.OperationalError):
            conn.execute("DELETE FROM kb_chunks")
    finally:
        conn.close()


# ---------------------------------------------------------------- retrieval (BM25 only)
def top(query, k=3, **kw):
    return [c.chunk_id for c in kb.search(query, k=k, **kw)]


@pytest.mark.parametrize("query,expected", [
    ("someone is shaking and not responding", "kb:PROTO-NEURO-001@1#"),
    ("why are my eyes blurry", "kb:CARD-EYES@1#summary"),
    ("what does a sleepiness score of 8 mean", "kb:TEST-KSS@1#summary"),
    ("who can see my status", "kb:PRIVACY-CONTRACT@1#"),
    ("my friend is choking", "kb:PROTO-AIRWAY-001@1#"),
    ("radiation storm what do I do", "kb:PROTO-RAD-001@1#"),
    ("what is DONKI", "kb:NASA-DONKI@1#summary"),
    ("I feel hopeless", "kb:PROTO-PSYCH-001@1#"),
])
def test_fixed_questions(use_kb, query, expected):
    got = top(query, place="transit")
    assert any(c.startswith(expected) for c in got), got


def test_results_are_chunks_best_first(use_kb):
    res = kb.search("seizure", kind="protocol", k=4, gravity="g0", place="transit")
    assert 0 < len(res) <= 4 and all(isinstance(c, kb.Chunk) for c in res)
    assert [c.score for c in res] == sorted((c.score for c in res), reverse=True)
    assert all(c.doc_id.startswith("PROTO-") for c in res)
    assert set(res[0].as_tool_data()) == {"chunk_id", "title", "text", "score"}


def test_kind_filter(use_kb):
    assert all(c.doc_id.startswith("TEST-") for c in kb.search("sleep", kind="self_test", k=10))
    assert all(c.doc_id.startswith("HAZARD-") for c in kb.search("radiation", kind="hazard", k=10))
    assert kb.search("sleep", kind="nonsense") == []


def test_abstains_without_evidence(use_kb):
    assert kb.search("what is the capital of France") == []
    assert kb.search("tell me a joke") == []
    assert kb.search("") == [] and kb.search("   ") == []


# ---------------------------------------------------------------- gravity and place filter
@pytest.mark.parametrize("place", list(LOCATIONS))
def test_place_filter_matches_protocol_resolve(kb_path, place):
    """Visible variant chunks at a place are exactly the variants protocols.resolve(place) shows there."""
    where, args = hybrid._where("protocol", LOCATIONS[place]["gravity_key"], place)
    visible = sorted(r[0] for r in rows(kb_path, f"SELECT c.text {hybrid.FROM} WHERE c.section = 'variant'{where}", args))
    expected = sorted(st["variant"] for p in protocols.resolve(place)["protocols"].values()
                      for st in p["steps"] if st["variant"])
    assert visible == expected and expected


@pytest.mark.parametrize("place", list(LOCATIONS))
def test_search_never_returns_other_gravity_or_place(use_kb, place):
    g = LOCATIONS[place]["gravity_key"]
    for q in ("compressions chest", "seizure tether floor", "radiation shelter", "bleeding pressure", "gravity",
              "hazard level here", "choking back blows", "vomit suction"):
        for c in kb.search(q, k=50, place=place):
            assert c.gravity in ("any", g), (place, c.chunk_id)
            assert c.location in ("any", place), (place, c.chunk_id)


def test_zero_g_variant_never_on_mars(use_kb):
    on_mars = top("restraint board compressions handstand", k=50, place="mars")
    assert on_mars and not any(c.endswith("-g0") for c in on_mars)
    in_transit = top("restraint board compressions handstand", k=50, place="transit")
    assert any(c.endswith("-g0") for c in in_transit)
    # gravity alone filters too
    assert not any(c.endswith("-g0") for c in top("restraint board", k=50, gravity="gp"))


def test_unknown_place_returns_nothing(use_kb):
    assert kb.search("seizure", place="venus") == []


# ---------------------------------------------------------------- vectors (fake embedder) and startup
def test_hybrid_with_fake_embedder(tmp_path):
    if not _has_vec():
        pytest.skip("sqlite-vec not available")
    path = str(tmp_path / "kb.db")
    emb = FakeEmbedder()
    B.build(path, emb)
    res = hybrid.search(path, "stiff or jerking body", k=3, place="transit", embedder=emb)
    assert res and res[0]["doc_id"] == "PROTO-NEURO-001"
    # a different embedder than the one in the file: vectors are skipped, BM25 still answers
    res = hybrid.search(path, "seizure", k=3, place="transit", embedder=NullEmbedder())
    assert res and res[0]["doc_id"] == "PROTO-NEURO-001"


def test_missing_index_is_built_with_a_warning(tmp_path, monkeypatch, caplog):
    path = str(tmp_path / "sub" / "kb.db")
    monkeypatch.setattr(settings, "kb_path", path)
    monkeypatch.setattr(settings, "embedder", "none")
    with caplog.at_level(logging.WARNING, logger="canary.kb"):
        res = kb.search("seizure", k=2, place="mars")
    assert res and "missing" in caplog.text
    assert dict(rows(path, "SELECT key, value FROM kb_meta"))["embedder"] == "none"


def test_broken_index_never_raises(tmp_path, monkeypatch):
    path = tmp_path / "kb.db"
    path.write_text("not a database")
    monkeypatch.setattr(settings, "kb_path", str(path))
    monkeypatch.setattr(settings, "embedder", "none")
    assert kb.search("seizure") == []
