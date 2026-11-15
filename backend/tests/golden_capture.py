"""Helpers that freeze what the API returns for the demo (the "golden" snapshots).

Used by test_golden.py. Later phases move the demo story, storms, goal history and dose out of the engine into
CSV mission packages; the golden files prove the demo did not change number by number.

Only two helpers know HOW the demo is loaded and HOW a scene is reached: `load_demo` and `go_to_scene`.
"""
import json
import os
import tempfile
from typing import Any, Dict, List, Optional

PLACEHOLDER = "<volatile>"
CREW_IDS = ("h", "k", "a", "t")
PINS = {"h": "1001", "k": "1002", "a": "1003", "t": "1004"}
MEDICAL_PIN = "1961"
CONTROL_PIN = "4242"
SCENES = 6

# Keys whose values change on every run (wall clock, random per start). Found by capturing twice and diffing.
VOLATILE_KEYS = {"created_at", "sent_at", "deliver_at", "fetched_at", "at", "updated_at", "expires_at", "token",
                 "eta_s", "ts", "time"}

# Fields that later phases may ADD to a dict without failing the comparison. Changed values of keys that already
# exist in the golden file always fail.
NEW_FIELDS = {"stale", "age_days", "origin", "clock", "event", "measured_days", "estimated_days",
              "no_data", "learning", "max_age", "baseline_need",
              "personal_ids", "patches", "what",
              "protocol", "rejected_rules"}  # the crew warnings name the Protocols page they belong to; the suggestion rule ids a rewrite broke  # phase 4: a system or a person with no data yet; an indicator still learning its normal


def new_client(db_path: Optional[str] = None):
    """A TestClient on a fresh temporary database. Must run before canary is imported in this process, or the
    caller must have set CANARY_DB already (test_canary.py does that at import time)."""
    from fastapi.testclient import TestClient
    from canary.main import app
    return TestClient(app)


def load_demo(client) -> None:
    """Put the app in the demo state: reset the database, which loads the mock mission package named by
    CANARY_MISSION_PACKAGE (odyssey1-mars by default) through the same import the control endpoint and
    scripts/load_mission.py use. Then check the package really is what the engine runs on."""
    from canary import db
    from canary.config import settings
    r = client.post("/api/demo/reset")
    assert r.status_code == 200, r.text
    assert settings.mission_package == "odyssey1-mars" and db.get_setting("package")["name"] == "odyssey1-mars"


def go_to_scene(client, i: int) -> dict:
    """Move the demo to story scene i (0..5).

    TODAY a scene is a step of the built-in story: PUT /api/mission {"step": i}.
    PHASE 3 WILL CHANGE THIS: scenes will come from a loaded mission package and a simulated mission date, so this
    helper (and only this one) will set the simulated date of scene i instead. Everything else in this module and in
    test_golden.py must keep working unchanged."""
    r = client.put("/api/mission", json={"step": i})
    assert r.status_code == 200, r.text
    return r.json()


def _token(client, path: str, pin: str) -> str:
    r = client.post(path, json={"pin": pin})
    assert r.status_code == 200, (path, r.text)
    return r.json()["token"]


def _get(client, path: str, headers: Optional[dict] = None) -> Any:
    r = client.get(path, headers=headers or {})
    assert r.status_code == 200, (path, r.status_code, r.text[:300])
    return r.json()


# The GETs the frontend makes, by who asks. test_empty_and_stale.py reads these lists too, so a new endpoint added here is
# also checked on an empty system.
PUBLIC_PATHS = ("/api/catalog", "/api/mission", "/api/mission/overview", "/api/crew/overview", "/api/leaderboard",
                "/api/space-weather", "/api/nasa/rad", "/api/nasa/sources", "/api/plan", "/api/plan/conditions",
                "/api/protocols", "/api/emergencies")
CREW_PATHS = ("/api/crew/{c}", "/api/crew/{c}/record", "/api/goals/{c}", "/api/advice/{c}", "/api/checkins/{c}",
              "/api/suggestions/{c}", "/api/messages?crew_id={c}")  # each with the person's own token
MEDICAL_PATHS = ("/api/crew", "/api/medical/overview", "/api/medical/goals", "/api/medical/care-sensitivity",
                 "/api/medical/exercise-adjust", "/api/messages")
MEDICAL_CREW_PATHS = ("/api/crew/{c}", "/api/crew/{c}/record", "/api/goals/{c}")  # the medical officer reads every private page too
CONTROL_PATHS = ("/api/control/overview", "/api/control/demo")


def capture_scene(client) -> Dict[str, Any]:
    """Every GET the frontend makes for the crew (My space, Crew, Mission plan, Ranking), the medical console and
    Canary Control, for the scene the app is in now. Assistant/LLM endpoints and photos are skipped."""
    out = {}  # type: Dict[str, Any]
    crew_h = {c: {"X-Canary-Viewer": _token(client, f"/api/crew/{c}/session", PINS[c])} for c in CREW_IDS}
    med = {"Authorization": "Bearer " + _token(client, "/api/medical/session", MEDICAL_PIN)}
    ctl = {"X-Canary-Control": _token(client, "/api/control/session", CONTROL_PIN)}

    for p in PUBLIC_PATHS:
        out[p] = _get(client, p)
    for c in CREW_IDS:
        for t in CREW_PATHS:
            p = t.format(c=c)
            out[f"{p} [as {c}]"] = _get(client, p, crew_h[c])
    for p in MEDICAL_PATHS:
        out[f"{p} [as medical]"] = _get(client, p, med)
    for c in CREW_IDS:
        for t in MEDICAL_CREW_PATHS:
            p = t.format(c=c)
            out[f"{p} [as medical]"] = _get(client, p, med)
    for p in CONTROL_PATHS:
        out[f"{p} [as control]"] = _get(client, p, ctl)
    return out


def capture_all(client=None, scenes: int = SCENES) -> List[Dict[str, Any]]:
    """One fresh demo per scene, so a scene never depends on the order the scenes are visited in."""
    from canary import db
    from canary.config import settings
    client = client or new_client()
    live = settings.live_space_weather
    old_conn = db._conn
    settings.live_space_weather = False  # never read the network: the snapshot must not depend on NASA being up
    try:
        res = []
        for i in range(scenes):
            # A brand-new database file per scene: row ids (AUTOINCREMENT) survive a demo reset, so ids would
            # otherwise depend on what ran before in the same process.
            db.connect(os.path.join(tempfile.mkdtemp(), "golden.db"))
            load_demo(client)
            go_to_scene(client, i)
            res.append(normalise(capture_scene(client)))
        return res
    finally:
        settings.live_space_weather = live
        if old_conn is not None:
            db._conn = old_conn
            db._forget()


def normalise(v: Any) -> Any:
    """Replace volatile values with a placeholder; round-trip through JSON so the result is exactly what is stored."""
    def walk(x, key=None):
        if isinstance(x, dict):
            return {k: walk(val, k) for k, val in x.items()}
        if isinstance(x, list):
            return [walk(i) for i in x]
        if key in VOLATILE_KEYS and x is not None:
            return PLACEHOLDER
        return x
    return json.loads(json.dumps(walk(v)))


def dump(v: Any) -> str:
    return json.dumps(v, sort_keys=True, indent=1, ensure_ascii=False) + "\n"


def diff(golden: Any, now: Any, path: str = "$", limit: int = 20, allow=NEW_FIELDS) -> List[str]:
    """Deep compare, exact. Returns up to `limit` readable differences. Extra keys in `now` named in `allow`
    are ignored; any other extra key, missing key or changed value is a difference."""
    out = []  # type: List[str]

    def rec(g, n, p):
        if len(out) >= limit:
            return
        if isinstance(g, dict) and isinstance(n, dict):
            for k in g:
                if k not in n:
                    out.append(f"{p}.{k}: missing now (golden {_short(g[k])})")
                else:
                    rec(g[k], n[k], f"{p}.{k}")
            for k in n:
                if k not in g and k not in allow:
                    out.append(f"{p}.{k}: new key not in golden ({_short(n[k])})")
        elif isinstance(g, list) and isinstance(n, list):
            if len(g) != len(n):
                out.append(f"{p}: list length {len(g)} in golden, {len(n)} now")
            for i, (a, b) in enumerate(zip(g, n)):
                rec(a, b, f"{p}[{i}]")
        elif type(g) is not type(n) or g != n:
            out.append(f"{p}: golden {_short(g)} != now {_short(n)}")

    rec(golden, now, path)
    return out


def _short(x: Any, n: int = 80) -> str:
    s = json.dumps(x, ensure_ascii=False)
    return s if len(s) <= n else s[:n] + "..."
