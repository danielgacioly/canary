"""Security and operations, offline: who may read the crew's data, what the public banner shows, the security headers, the
404s of the built app, and the health and metrics routes. One focused test per item."""
import os
import pathlib
import tempfile

os.environ["CANARY_DB"] = os.path.join(tempfile.mkdtemp(), "wave_ops.db")

import pytest  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from canary.main import app  # noqa: E402
from canary.web import mount_spa  # noqa: E402
from tests.golden_capture import PINS, _token, control_headers, reset_demo  # noqa: E402

client = TestClient(app)


@pytest.fixture(autouse=True)
def fresh():
    reset_demo(client)
    yield
    reset_demo(client)


def crew(cid):
    return {"Authorization": "Bearer " + _token(client, f"/api/crew/{cid}/session", PINS[cid])}


# ---------------------------------------------------------------- SEC-06: crew data needs a sign-in on board
def test_crew_overview_needs_someone_on_board():
    assert client.get("/api/crew/overview").status_code == 401  # no sign-in: the crew's hazards, participation and goals stay private
    assert client.get("/api/crew/overview", headers=crew("h")).status_code == 200


# ---------------------------------------------------------------- SEC-06: catalog personal data (home, age) for people on board
def test_catalog_shows_the_crews_home_and_age_only_to_people_on_board():
    anonymous = client.get("/api/catalog").json()["crew"][0]
    assert set(anonymous) == {"id", "name", "role", "initials"}
    signed_in = client.get("/api/catalog", headers=crew("h")).json()["crew"][0]
    assert "home" in signed_in and "age" in signed_in


# ---------------------------------------------------------------- SEC-06: the public emergency banner is name + protocol only
def test_the_public_emergency_banner_shows_only_name_and_protocol():
    assert client.post("/api/emergencies", json={"patient": "h"}, headers=crew("k")).status_code == 200
    banner = client.get("/api/emergencies/open").json()  # no sign-in: everyone on board sees it
    assert banner and set(banner[0]) == {"id", "patient", "protocol"}


# ---------------------------------------------------------------- SEC-09: security headers and no-store on the API
def test_every_response_has_security_headers_and_api_answers_are_not_stored():
    r = client.get("/api/health")
    assert r.headers["X-Frame-Options"] == "DENY"
    assert r.headers["Referrer-Policy"] == "no-referrer"
    assert "frame-ancestors 'none'" in r.headers["Content-Security-Policy"] and "script-src 'self'" in r.headers["Content-Security-Policy"]
    assert r.headers["Cache-Control"] == "no-store"


# ---------------------------------------------------------------- OPS-04: unknown API paths and missing assets are 404, never the app's HTML
def test_unknown_api_paths_are_json_404_and_missing_assets_are_404(tmp_path: pathlib.Path):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html>app</html>")
    (dist / "favicon.svg").write_text("<svg/>")
    built = FastAPI()
    mount_spa(built, dist)
    c = TestClient(built)
    unknown = c.get("/api/does-not-exist")
    assert unknown.status_code == 404 and unknown.headers["content-type"].startswith("application/json") and "<html" not in unknown.text
    assert c.get("/assets/missing.js").status_code == 404
    assert c.get("/favicon-missing.svg").status_code == 404
    assert c.get("/favicon.svg").text == "<svg/>"  # a file that exists is served
    assert c.get("/crew/h").text == "<html>app</html>"  # a route of the app is the app


# ---------------------------------------------------------------- OPS-06: liveness, readiness and metrics
def test_health_live_ready_and_metrics_report_what_they_check():
    assert client.get("/api/health/live").json() == {"ok": True}
    ready = client.get("/api/health/ready")
    assert ready.json()["checks"]["database"] == "ok" and "knowledge_base" in ready.json()["checks"]
    assert client.get("/api/metrics").status_code == 401  # Mission Control only
    client.get("/api/health/live")
    routes = client.get("/api/metrics", headers=control_headers(client)).json()["routes"]
    row = next(r for r in routes if r["route"] == "GET /api/health/live")
    assert row["requests"] >= 1 and row["p50_ms"] is not None and row["p95_ms"] is not None
