"""Who may do what, offline: the built app never serves a file outside dist, a briefing stays with its astronaut until
they approve it, and wiping the demo needs the Canary Control sign-in."""
import os
import pathlib
import tempfile

os.environ["CANARY_DB"] = os.path.join(tempfile.mkdtemp(), "security.db")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from canary.main import app, spa_file  # noqa: E402
from tests.golden_capture import PINS, _token, control_headers, medical_headers, reset_demo  # noqa: E402

client = TestClient(app)


@pytest.fixture(autouse=True)
def fresh():
    reset_demo(client)
    yield
    reset_demo(client)


def crew(cid):
    return {"Authorization": "Bearer " + _token(client, f"/api/crew/{cid}/session", PINS[cid])}


def medical():
    return medical_headers(client)


# ---------------------------------------------------------------- the built app
def test_spa_never_serves_a_file_outside_dist(tmp_path: pathlib.Path):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html>app</html>")
    (dist / "favicon.svg").write_text("<svg/>")
    (tmp_path / "canary.db").write_text("secret")
    index = (dist / "index.html").resolve()
    assert spa_file(dist, "favicon.svg") == (dist / "favicon.svg").resolve()
    assert spa_file(dist, "") == index
    assert spa_file(dist, "missions/today") == index  # a route of the app, not a file
    for path in ("../canary.db", "assets/../../canary.db", str(tmp_path / "canary.db"), "../../../../etc/hosts"):
        assert spa_file(dist, path) == index, path


# ---------------------------------------------------------------- briefings
def _briefing(cid="h") -> dict:
    return client.post("/api/briefings", json={"crew_id": cid}, headers=crew(cid)).json()


def test_only_the_medical_team_approves_a_briefing():
    b = _briefing("h")
    url = f"/api/briefings/{b['id']}/approve"
    assert client.post(url).status_code == 401
    assert client.post(url, headers=crew("h")).status_code == 401  # not even the astronaut it is about
    assert client.post(url, headers=crew("k")).status_code == 401
    assert client.get(f"/api/briefings/h", headers=crew("h")).json()[0]["status"] == "draft"  # nothing was queued
    r = client.post(url, headers=medical())
    assert r.status_code == 200 and r.json()["status"] == "queued"


def test_a_missing_briefing_is_404_for_the_medical_team_and_401_for_everyone_else():
    assert client.post("/api/briefings/999999/approve", headers=medical()).status_code == 404
    assert client.post("/api/briefings/999999/approve").status_code == 401  # a caller without sign-in learns nothing about ids
    assert client.post("/api/briefings/999999/approve", headers=crew("h")).status_code == 401


def test_approving_twice_sends_one_briefing():
    b = _briefing("h")
    for _ in range(2):
        assert client.post(f"/api/briefings/{b['id']}/approve", headers=medical()).status_code == 200
    sent = [m for m in client.get("/api/messages", headers=crew("h")).json() if m["kind"] == "briefing"]
    assert len(sent) == 1


def test_a_briefing_message_is_private():
    b = _briefing("h")
    # approval is medical-only (crew approving their own briefing is refused), so the medical team approves here
    assert client.post(f"/api/briefings/{b['id']}/approve", headers=crew("h")).status_code == 401
    client.post(f"/api/briefings/{b['id']}/approve", headers=medical())
    kinds = lambda headers=None: [m["kind"] for m in client.get("/api/messages", headers=headers or {}).json()]  # noqa: E731
    assert client.get("/api/messages").status_code == 401  # no token, no messages
    assert "briefing" not in kinds(crew("k"))
    assert "briefing" not in kinds(control_headers(client))
    assert "briefing" in kinds(crew("h"))
    assert "briefing" in kinds(medical())


# ---------------------------------------------------------------- reset
def test_reset_needs_the_control_sign_in():
    assert client.post("/api/demo/reset").status_code == 401
    assert client.post("/api/demo/reset", headers=crew("h")).status_code == 401
    assert client.post("/api/demo/reset", headers={"Authorization": "Bearer " + medical()["Authorization"][7:]}).status_code == 401
    assert client.post("/api/demo/reset", headers=control_headers(client)).status_code == 200


# ---------------------------------------------------------------- CORS
def test_another_origin_is_not_allowed():
    r = client.options("/api/demo/reset", headers={"Origin": "http://evil.example", "Access-Control-Request-Method": "POST"})
    assert r.headers.get("access-control-allow-origin") != "http://evil.example"
    r = client.options("/api/mission", headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "PUT"})
    assert r.headers.get("access-control-allow-origin") == "http://localhost:5173"
