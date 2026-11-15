"""The knowledge base is checked against the live corpus at startup (item 16): the comparison is tested, not the thread."""
import re
import sqlite3

from canary.assistant.kb import corpus, freshness


def test_compare_says_fresh_stale_or_missing():
    assert freshness.compare("abc", "abc") == freshness.FRESH
    assert freshness.compare("abc", "def") == freshness.STALE
    assert freshness.compare(None, "def") == freshness.MISSING


def test_the_live_hash_is_the_corpus_hash():
    live = freshness.live_hash()
    assert re.fullmatch(r"[0-9a-f]{64}", live)
    assert live == corpus.corpus_hash(corpus.documents())


def _built(path, corpus_hash):
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE kb_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    if corpus_hash is not None:
        conn.execute("INSERT INTO kb_meta VALUES ('corpus_hash', ?)", (corpus_hash,))
    conn.commit()
    conn.close()
    return str(path)


def test_status_of_a_built_file_follows_its_corpus_hash(tmp_path):
    fresh = _built(tmp_path / "fresh.db", freshness.live_hash())
    old = _built(tmp_path / "old.db", "0" * 64)
    no_hash = _built(tmp_path / "no_hash.db", None)
    assert freshness.status(fresh) == freshness.FRESH
    assert freshness.status(old) == freshness.STALE
    assert freshness.status(no_hash) == freshness.MISSING
    assert freshness.status(str(tmp_path / "absent.db")) == freshness.MISSING


def test_a_file_that_is_not_a_database_is_missing_not_an_error(tmp_path):
    bad = tmp_path / "bad.db"
    bad.write_bytes(b"not sqlite at all")
    assert freshness.stored_hash(str(bad)) is None
    assert freshness.status(str(bad)) == freshness.MISSING
