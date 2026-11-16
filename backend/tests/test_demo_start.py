"""The intro's two demo-only endpoints: start empty for the guided tour, quickstart for the skipped intro."""
import pytest
from fastapi.testclient import TestClient

from canary.config import settings
from canary.domain import registry
from canary.main import app
from tests.support import empty, reset_demo

client = TestClient(app)


@pytest.fixture(autouse=True)
def fresh():
    yield
    reset_demo(client)


def test_start_empty_wipes_to_nothing_registered():
    assert reset_demo(client).status_code == 200 and registry.registered()
    assert client.post("/api/demo/start-empty").json() == {"registered": False}
    assert not registry.registered()


def test_quickstart_loads_the_demo_once_and_never_replaces_a_mission():
    empty(client)
    assert client.post("/api/demo/quickstart").json() == {"registered": True}
    assert client.post("/api/demo/quickstart").status_code == 409


def test_demo_counts_are_offered_to_the_demo_form():
    from tests.support import control_headers
    reset_demo(client)
    r = client.get("/api/control/demo", headers=control_headers(client)).json()
    assert r["counts"]["readings"] > 1000 and r["counts"]["goal_entries"] > 1000 and r["counts"]["events"] >= 1 and r["ground"]


@pytest.mark.parametrize("path", ["/api/demo/start-empty", "/api/demo/quickstart"])
def test_not_in_flight_mode(monkeypatch, path):
    monkeypatch.setattr(settings, "mode", "flight")
    assert client.post(path).status_code == 404
