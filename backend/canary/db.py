"""SQLite storage. One file, no server: it has to run on board without a network.

Everything lives here: what people do (check-ins, goals, messages, emergencies, briefings, settings) and what the
mission measured. Measurements (`observations`), space-weather events (`space_events`) and the guided-demo bookmarks
(`scenes`) arrive only through the entry points in domain/data.py (the API routes, a mission package import, or
scripts/load_mission.py); the engine reads them back through that module and nothing else.
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
CREATE TABLE IF NOT EXISTS checkin_photos (
  checkin_id INTEGER PRIMARY KEY, crew_id TEXT NOT NULL, data_url TEXT NOT NULL, created_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS goal_log (
  crew_id TEXT NOT NULL, day INTEGER NOT NULL, goal_id TEXT NOT NULL, done INTEGER NOT NULL,
  updated_at REAL NOT NULL, done_at_time TEXT, PRIMARY KEY (crew_id, day, goal_id));
CREATE TABLE IF NOT EXISTS observations (
  id INTEGER PRIMARY KEY AUTOINCREMENT, crew_id TEXT NOT NULL, day INTEGER NOT NULL, indicator TEXT NOT NULL,
  value REAL NOT NULL, unit TEXT NOT NULL, origin TEXT NOT NULL, method TEXT NOT NULL, source TEXT NOT NULL,
  note TEXT NOT NULL, measured_at TEXT NOT NULL, received_at TEXT NOT NULL, package TEXT,
  UNIQUE (crew_id, indicator, measured_at, source));
CREATE TABLE IF NOT EXISTS space_events (
  id TEXT PRIMARY KEY, kind TEXT NOT NULL, start_day INTEGER NOT NULL, end_day INTEGER NOT NULL, locations TEXT NOT NULL,
  extra_dose_msv REAL NOT NULL, origin TEXT NOT NULL, source TEXT NOT NULL, note TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS scenes (
  idx INTEGER PRIMARY KEY, day INTEGER NOT NULL, location TEXT NOT NULL, person TEXT NOT NULL, storm TEXT NOT NULL,
  when_label TEXT NOT NULL, text TEXT NOT NULL);
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
CREATE TABLE IF NOT EXISTS suggestion_feedback (
  id INTEGER PRIMARY KEY AUTOINCREMENT, crew_id TEXT NOT NULL, sid TEXT NOT NULL, action TEXT NOT NULL,
  day INTEGER NOT NULL, created_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS revoked_tokens (jti TEXT PRIMARY KEY, exp REAL NOT NULL);
CREATE TABLE IF NOT EXISTS auth_failures (key TEXT PRIMARY KEY, count INTEGER NOT NULL, until REAL NOT NULL, last REAL NOT NULL);
CREATE TABLE IF NOT EXISTS assistant_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT, crew_id TEXT NOT NULL, question TEXT NOT NULL,
  response TEXT NOT NULL, created_at REAL NOT NULL);
"""

_lock = threading.RLock()
_conn: Optional[sqlite3.Connection] = None
# Read cache. A health snapshot asks the same few questions (settings, the person's check-ins) tens of thousands of
# times while it walks back through the days of a risk; the answers only change when something is written. Every
# write goes through x(), reset() or a new connection, and each of them empties the cache, so a read never returns
# data older than the last write. Rows are copied out, so a caller that edits a row cannot change the cache.
_cache: dict = {}
# Bumped when the connection changes or the demo is reset: anything built from a table (domain/data.py) is stale then.
epoch = 0
# Counts every write (any table): a cache of something read from the database stays valid while it is unchanged.
writes = 0
_CACHE_MAX = 50_000


def _forget() -> None:
    global writes
    writes += 1
    _cache.clear()


def _bump_epoch() -> None:
    global epoch
    epoch += 1


def connect(path: Optional[str] = None) -> sqlite3.Connection:
    global _conn
    with _lock:
        if _conn is None or path is not None:
            _conn = sqlite3.connect(path or settings.db_path, check_same_thread=False)
            _conn.row_factory = sqlite3.Row
            _conn.executescript(SCHEMA)
            cols = [r[1] for r in _conn.execute("PRAGMA table_info(goal_log)").fetchall()]
            if "done_at_time" not in cols:  # a database made before the goal log carried the time of day
                _conn.execute("ALTER TABLE goal_log ADD COLUMN done_at_time TEXT")
            ocols = [r[1] for r in _conn.execute("PRAGMA table_info(observations)").fetchall()]
            if "package" not in ocols:  # a database made before readings recorded which package they came from
                _conn.execute("ALTER TABLE observations ADD COLUMN package TEXT")
            _conn.commit()
            _forget()
            _bump_epoch()
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
        for t in ("settings", "checkins", "checkin_photos", "goal_log", "medical_goals", "messages", "emergencies", "briefings", "assistant_log", "suggestion_feedback", "advice", "care_events", "notices", "observations", "space_events", "scenes"):
            c.execute(f"DELETE FROM {t}")
        c.commit()
        _forget()
    _bump_epoch()
