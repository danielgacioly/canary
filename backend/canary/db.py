"""SQLite storage. One file, no server: it has to run on board without a network.

Only what people do is stored here (check-ins, goals, messages, emergencies,
briefings, settings). Sensor telemetry comes from a TelemetrySource
(see domain/telemetry.py), which today reads the observation table (see domain/simdata.py).
"""
import json
import sqlite3
import threading
from typing import Any, Optional

from .config import settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS checkins (
  id INTEGER PRIMARY KEY AUTOINCREMENT, crew_id TEXT NOT NULL, day INTEGER NOT NULL,
  kind TEXT NOT NULL, payload TEXT NOT NULL, created_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS goal_log (
  crew_id TEXT NOT NULL, day INTEGER NOT NULL, goal_id TEXT NOT NULL, done INTEGER NOT NULL,
  updated_at REAL NOT NULL, PRIMARY KEY (crew_id, day, goal_id));
CREATE TABLE IF NOT EXISTS medical_goals (
  id INTEGER PRIMARY KEY AUTOINCREMENT, who TEXT NOT NULL, area TEXT NOT NULL, title TEXT NOT NULL,
  why TEXT NOT NULL, xp INTEGER NOT NULL, from_day INTEGER NOT NULL, to_day INTEGER NOT NULL,
  created_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT, sender TEXT NOT NULL, recipient TEXT NOT NULL, kind TEXT NOT NULL,
  text TEXT NOT NULL, sent_at REAL NOT NULL, deliver_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS emergencies (
  id INTEGER PRIMARY KEY AUTOINCREMENT, protocol TEXT, patient TEXT, responder TEXT, location TEXT NOT NULL,
  day INTEGER NOT NULL, started_at REAL NOT NULL, ended_at REAL, outcome TEXT, log TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS briefings (
  id INTEGER PRIMARY KEY AUTOINCREMENT, crew_id TEXT NOT NULL, day INTEGER NOT NULL, status TEXT NOT NULL,
  facts TEXT NOT NULL, text TEXT NOT NULL, mode TEXT NOT NULL, created_at REAL NOT NULL,
  sent_at REAL, deliver_at REAL);
CREATE TABLE IF NOT EXISTS advice (
  id INTEGER PRIMARY KEY AUTOINCREMENT, crew_id TEXT NOT NULL, goal_id TEXT NOT NULL, origin TEXT NOT NULL,
  indicator TEXT NOT NULL, risk TEXT, start_day INTEGER NOT NULL, check_day INTEGER NOT NULL,
  start_bad REAL NOT NULL, created_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS care_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT, emergency_id INTEGER NOT NULL UNIQUE, crew_id TEXT NOT NULL, protocol TEXT NOT NULL,
  outcome TEXT NOT NULL, from_day INTEGER NOT NULL, until_day INTEGER NOT NULL, ops TEXT NOT NULL, created_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS notices (
  crew_id TEXT NOT NULL, alert_id TEXT NOT NULL, since_day INTEGER NOT NULL, day INTEGER NOT NULL, level INTEGER NOT NULL,
  title TEXT NOT NULL, to_id TEXT NOT NULL, created_at REAL NOT NULL, PRIMARY KEY (crew_id, alert_id, since_day));
CREATE TABLE IF NOT EXISTS assistant_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT, crew_id TEXT NOT NULL, question TEXT NOT NULL,
  response TEXT NOT NULL, created_at REAL NOT NULL,
  provider TEXT, model TEXT, kb_version TEXT, outcome TEXT, guard_flags TEXT,
  latency_ms INTEGER, input_tokens INTEGER, output_tokens INTEGER);
CREATE TABLE IF NOT EXISTS assistant_turns (
  id INTEGER PRIMARY KEY AUTOINCREMENT, log_id INTEGER NOT NULL REFERENCES assistant_log(id) ON DELETE CASCADE,
  step INTEGER NOT NULL, tool TEXT NOT NULL, args TEXT NOT NULL, sources TEXT NOT NULL, ok INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS assistant_turns_log ON assistant_turns(log_id);
"""

# Columns added to existing tables after their first release. CREATE TABLE IF NOT EXISTS does not add
# columns to a table that already exists, so migrate() adds any that are missing (see docs/ai/schema.md §4).
ADDED_COLUMNS = {
    "assistant_log": [
        ("provider", "TEXT"), ("model", "TEXT"), ("kb_version", "TEXT"), ("outcome", "TEXT"),
        ("guard_flags", "TEXT"), ("latency_ms", "INTEGER"), ("input_tokens", "INTEGER"), ("output_tokens", "INTEGER"),
    ],
}


def migrate(conn: sqlite3.Connection) -> None:
    """Idempotent: add every column in ADDED_COLUMNS that the table does not have yet (all nullable)."""
    for table, cols in ADDED_COLUMNS.items():
        have = {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        for name, typ in cols:
            if name not in have:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {typ}")

_lock = threading.RLock()
_conn: Optional[sqlite3.Connection] = None
# Read cache. A health snapshot asks the same few questions (settings, the person's check-ins) tens of thousands of
# times while it walks back through the days of a risk; the answers only change when something is written. Every
# write goes through x(), reset() or a new connection, and each of them empties the cache, so a read never returns
# data older than the last write. Rows are copied out, so a caller that edits a row cannot change the cache.
_cache: dict = {}
_CACHE_MAX = 50_000


def _forget() -> None:
    _cache.clear()


def connect(path: Optional[str] = None) -> sqlite3.Connection:
    global _conn
    with _lock:
        if _conn is None or path is not None:
            _conn = sqlite3.connect(path or settings.db_path, check_same_thread=False)
            _conn.row_factory = sqlite3.Row
            _conn.executescript(SCHEMA)
            migrate(_conn)
            _conn.commit()
            _forget()
        return _conn


def q(sql: str, args: tuple = ()) -> list:
    with _lock:
        try:
            key = (sql, tuple(args))
            hit = _cache.get(key)
        except TypeError:  # an argument that cannot be a key: read without the cache
            key, hit = None, None
        if hit is None:
            hit = [dict(r) for r in connect().execute(sql, args).fetchall()]
            if key is not None:
                if len(_cache) >= _CACHE_MAX:
                    _forget()
                _cache[key] = hit
        return [dict(r) for r in hit]


def x(sql: str, args: tuple = ()) -> int:
    with _lock:
        c = connect()
        cur = c.execute(sql, args)
        c.commit()
        _forget()
        return cur.lastrowid


def get_setting(key: str, default: Any = None) -> Any:
    rows = q("SELECT value FROM settings WHERE key=?", (key,))
    return json.loads(rows[0]["value"]) if rows else default


def set_setting(key: str, value: Any) -> None:
    x("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, json.dumps(value)))


def reset() -> None:
    with _lock:
        c = connect()
        for t in ("settings", "checkins", "goal_log", "medical_goals", "messages", "emergencies", "briefings", "assistant_turns", "assistant_log", "advice", "care_events", "notices"):
            c.execute(f"DELETE FROM {t}")
        c.commit()
        _forget()
