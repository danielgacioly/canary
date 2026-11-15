"""Sign-in helpers for the tests: one token per kind of person, and a way to put the app in a known state.

    crew_token(client, "h")            Helena's crew token (header X-Canary-Viewer)
    medical_token(client)              Kenji as the crew medical officer (Authorization: Bearer); "g-fs1" for the flight surgeon
    control_token(client)              the demo MCC account g-mcc1 (header X-Canary-Control)
    fresh(client, package=...)         reset through the demo reset (needs the MCC account) and load the package
    empty(client)                      nothing registered at all (what a flight system starts as): Control signs in with the bootstrap PIN
"""
from typing import List

from tests import golden_capture as gc

from tests.golden_capture import PINS, control_headers, medical_headers, medical_token, reset_demo  # noqa: F401

# The ground accounts a hand registration needs: the MCC account Control signs in with, and a flight surgeon for the medical console.
GROUND = [{"id": "g-mcc1", "name": "Test Controller", "role": "mcc", "pin": "4242"},
          {"id": "g-fs1", "name": "Test Surgeon", "role": "flight_surgeon", "pin": "1961"}]


def crew_token(client, crew_id: str) -> str:
    return gc._token(client, f"/api/crew/{crew_id}/session", PINS[crew_id])


def crew_headers(client, crew_id: str) -> dict:
    return {"X-Canary-Viewer": crew_token(client, crew_id)}


def control_token(client) -> str:
    return control_headers(client)["X-Canary-Control"]


def fresh(client, package: str = "odyssey1-mars"):
    """Reset to the bundled demo package through POST /api/demo/reset (an MCC token). Returns the response."""
    from canary.config import settings
    old = settings.mission_package
    settings.mission_package = package
    try:
        return reset_demo(client)
    finally:
        settings.mission_package = old


def empty(client) -> None:
    """Wipe everything and load nothing: no crew, no mission, no ground accounts (the state before a registration)."""
    from canary import auth
    from canary.main import _start_over
    _start_over(None)
    auth.clear_failures()


# ---------------------------------------------------------------- plan changes without the (locked) API
class _Reply:
    """What the old plan routes answered, for tests that change the plan of the loaded demo directly: a registered mission
    is locked against PUT /api/plan, POST /api/plan/preset and POST /api/setup (see test_accounts_lock.py)."""

    def __init__(self, status_code: int, body=None):
        self.status_code, self._body = status_code, body

    def json(self):
        return self._body


def plan_preset(preset: str) -> _Reply:
    from canary.domain import data, mission, plan
    try:
        plan.use_preset(preset)
    except ValueError as e:
        return _Reply(400, {"detail": str(e)})
    data.reload_for_preset(preset)
    mission.set_setup_done()
    return _Reply(200, plan.get())


def plan_put(body: dict) -> _Reply:
    from canary.domain import mission, plan
    from canary.main import _reload_for_legs
    try:
        plan.save(plan.validate(body["name"], body["legs"]))
    except ValueError as e:
        return _Reply(400, {"detail": str(e)})
    mission.set_setup_done()
    _reload_for_legs(plan.get()["legs"])
    return _Reply(200, plan.get())


def plan_setup(body: dict) -> _Reply:
    from canary.domain import mission
    r = plan_put(body)
    return r if r.status_code != 200 else _Reply(200, mission.set_step(0))


def add_ground() -> None:
    """Ground accounts (an MCC and a flight surgeon) on a system with no crew: the state tests of an empty system need so the
    medical console and Canary Control have someone to sign in. (Through the API the ground accounts come with the crew.)"""
    from canary import auth, db
    from canary.domain import registry
    rows, pins = registry.normalize_ground(GROUND)
    r = registry.stored() or {"crew": [], "mission": None}
    db.set_setting("registry", {**r, "ground": rows})
    db.set_setting("pins", auth.hashed_pins(pins, keep=True))
    registry.load()


def client_from(host: str):
    """A TestClient whose requests come from another client address (the lockout is also kept per address)."""
    from fastapi.testclient import TestClient
    from canary.main import app

    async def asgi(scope, receive, send):
        if scope["type"] in ("http", "websocket"):
            scope = {**scope, "client": (host, 4000)}
        await app(scope, receive, send)
    return TestClient(asgi)
