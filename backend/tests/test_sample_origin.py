"""Check-ins filled with sample values are stored with origin 'sample' and never feed the engine."""
import pytest
from fastapi.testclient import TestClient

from canary.config import settings
from canary.main import app
from tests.support import crew_headers, reset_demo

client = TestClient(app)
VITALS = {"hr": 110, "sbp": 150, "temp": 37.0, "spo2": 94}


@pytest.fixture(autouse=True)
def fresh():
    assert reset_demo(client).status_code == 200
    yield
    reset_demo(client)


def _post(origin=None, **kw):
    body = {"crew_id": "h", "kind": "vitals", "payload": VITALS, **({"origin": origin} if origin else {}), **kw}
    return client.post("/api/checkins", json=body, headers=crew_headers(client, "h"))


def test_a_sample_checkin_is_stored_but_does_not_change_the_readings():
    from canary.domain import telemetry
    day = client.get("/api/mission").json()["day"]
    before = telemetry.user_values("h", day, day)
    assert _post("sample").status_code == 200
    assert telemetry.user_values("h", day, day) == before
    hist = client.get("/api/checkins/h", headers=crew_headers(client, "h")).json()
    assert hist  # still in the person's history
    assert _post().status_code == 200  # a real one counts
    assert telemetry.user_values("h", day, day) != before


def test_the_origin_is_one_of_two_values_and_samples_exist_only_in_the_demo(monkeypatch):
    assert _post("invented").status_code == 422
    monkeypatch.setattr(settings, "mode", "flight")
    assert _post("sample").status_code == 404
