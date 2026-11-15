"""Test speed. Two things made the suite slow: every test that wants the demo resets the database and loads the ~93,000-row
mission package again (parsing, validating and indexing it), and every registered PIN is hashed with PBKDF2.

- The package is loaded for real once per session; the freshly loaded database is kept as an in-memory SQLite copy, and
  every later reset-then-load of the same package restores that copy (the SQLite backup API) and reuses the observation
  table built from it. What a test sees is the same database a real load would leave; a load into a database that is not
  empty (an import on top of other data) always runs for real.
- PBKDF2 rounds are lowered with CANARY_PBKDF2_ITERATIONS, set here before the app is imported. Production keeps its default
  of 100,000 (canary/config.py).
"""
import os
import sqlite3

os.environ.setdefault("CANARY_PBKDF2_ITERATIONS", "1000")

import pytest  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def reuse_the_loaded_package():
    from canary import db  # imported now: the test modules have set CANARY_DB by the time the first test runs
    from canary.config import settings
    from canary.domain import data, plan, registry

    real = data.import_named
    kept = {}

    def pristine() -> bool:
        return data.count_observations() == 0 and db.q("SELECT COUNT(*) n FROM settings")[0]["n"] == 0

    def import_named(name):
        key = (name, settings.missions_dir)
        if not pristine():
            return real(name)
        if key not in kept:
            res = real(name)
            copy = sqlite3.connect(":memory:", check_same_thread=False)
            db.connect().backup(copy)
            kept[key] = (copy, res, data._state["table"])
            return res
        copy, res, table = kept[key]
        with db._lock:
            copy.backup(db.connect())
            db._forget()
            db._bump_epoch()
        data.version()  # starts the in-memory state afresh for the new epoch
        if table is not None:
            data._state.update(key=data.token(), table=table)
        plan.reset_cache()
        registry.load()
        return dict(res)

    data.import_named = import_named
    yield
    data.import_named = real
