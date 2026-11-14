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
CREATE TABLE IF NOT EXISTS assistant_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT, crew_id TEXT NOT NULL, question TEXT NOT NULL,
  response TEXT NOT NULL, created_at REAL NOT NULL);
"""

_lock = threading.RLock()
_conn: Optional[sqlite3.Connection] = None


def connect(path: Optional[str] = None) -> sqlite3.Connection:
    global _conn
    with _lock:
        if _conn is None or path is not None:
            _conn = sqlite3.connect(path or settings.db_path, check_same_thread=False)
            _conn.row_factory = sqlite3.Row
            _conn.executescript(SCHEMA)
            _conn.commit()
        return _conn


def q(sql: str, args: tuple = ()) -> list:
    with _lock:
        return [dict(r) for r in connect().execute(sql, args).fetchall()]


def x(sql: str, args: tuple = ()) -> int:
    with _lock:
        c = connect()
        cur = c.execute(sql, args)
        c.commit()
        return cur.lastrowid


def get_setting(key: str, default: Any = None) -> Any:
    rows = q("SELECT value FROM settings WHERE key=?", (key,))
    return json.loads(rows[0]["value"]) if rows else default


def set_setting(key: str, value: Any) -> None:
    x("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, json.dumps(value)))


def reset() -> None:
    with _lock:
        c = connect()
        for t in ("settings", "checkins", "goal_log", "medical_goals", "messages", "emergencies", "briefings", "assistant_log", "advice"):
            c.execute(f"DELETE FROM {t}")
        c.commit()
