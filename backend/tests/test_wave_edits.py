"""Edits and transactions: a failed multi-step write leaves nothing behind (EDIT-02), corrections are made by role with an audit
entry (EDIT-01), TLX takes only its six scales (EDIT-04), the plan rejects gaps and needs launch and landing (EDIT-05), photos are
decoded and limited (EDIT-06), and a repeated Idempotency-Key returns the first answer (EDIT-08). One focused test per fix."""
import base64
import io
import os
import tempfile

os.environ["CANARY_DB"] = os.path.join(tempfile.mkdtemp(), "wave_edits.db")

import pytest  # noqa: E402
from fastapi import HTTPException  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from PIL import Image  # noqa: E402

from canary import db, main  # noqa: E402
from canary.config import settings  # noqa: E402
from canary.domain import data, images, plan, registry  # noqa: E402
from canary.domain.validation import FieldError  # noqa: E402
from canary.main import app  # noqa: E402
from tests.support import crew_headers, medical_headers, reset_demo  # noqa: E402

client = TestClient(app)


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    monkeypatch.setattr(settings, "mission_package", "odyssey1-mars")
    monkeypatch.setattr(settings, "live_space_weather", False)
    assert reset_demo(client).status_code == 200
    yield
    monkeypatch.undo()
    reset_demo(client)


def first_crew() -> str:
    return registry.stored()["crew"][0]["seat"]


def test_a_failed_start_over_puts_the_database_back_as_it_was():  # EDIT-02
    crew_before = [p["seat"] for p in registry.stored()["crew"]]
    readings_before = data.count_observations()
    with pytest.raises(HTTPException):
        main._start_over("odyssey1-no-such-package")  # wipes first, then the load fails: all of it is undone
    assert [p["seat"] for p in registry.stored()["crew"]] == crew_before
    assert data.count_observations() == readings_before


def test_medical_team_corrects_a_height_and_the_audit_keeps_old_new_and_why():  # EDIT-01
    cid = first_crew()
    old = registry.stored()["crew"][0]["height_cm"]
    new = 181.5 if old != 181.5 else 179.0
    r = client.put(f"/api/corrections/crew/{cid}/height", json={"value": new, "reason": "Re-measured on board"}, headers=medical_headers(client))
    assert r.status_code == 200 and registry.stored()["crew"][0]["height_cm"] == new
    row = db.q("SELECT before, after FROM audit_log WHERE action='crew.height_correct' ORDER BY id DESC LIMIT 1")[0]
    assert str(old) in row["before"] and str(new) in row["after"] and "Re-measured on board" in row["after"]
    assert client.put(f"/api/corrections/crew/{cid}/height", json={"value": 170, "reason": "nope"}, headers=crew_headers(client, cid)).status_code == 401


def test_tlx_takes_only_its_six_scales_and_derives_the_overall_score():  # EDIT-04
    cid = first_crew()
    bad = client.post("/api/checkins", json={"crew_id": cid, "kind": "tlx", "payload": {"scores": {"mental": 40, "made_up": 99}}},
                      headers=crew_headers(client, cid))
    assert bad.status_code == 422
    good = client.post("/api/checkins", json={"crew_id": cid, "kind": "tlx", "payload": {"scores": {"mental": 40, "physical": 20}, "raw": 99}},
                       headers=crew_headers(client, cid))
    assert good.status_code == 200
    stored = db.q("SELECT payload FROM checkins WHERE crew_id=? AND kind='tlx' ORDER BY id DESC LIMIT 1", (cid,))[0]["payload"]
    assert '"raw": 30' in stored or '"raw": 30.0' in stored  # the average of the two answers, not the client's 99


def test_the_plan_refuses_a_gap_and_needs_launch_and_landing():  # EDIT-05
    with pytest.raises(ValueError, match="missing"):
        plan.validate("x", [{"location": "earth", "start": -5, "end": -1}, {"location": "rocket", "start": 0, "end": 3},
                            {"location": "transit", "start": 5, "end": 9}, {"location": "earth", "start": 10, "end": 20}])
    with pytest.raises(ValueError, match="launch day 0"):
        plan.validate("x", [{"location": "earth", "start": -5, "end": -1}])
    assert plan.validate("x", [{"location": "earth", "start": -2, "end": -1}, {"location": "rocket", "start": 0, "end": 3},
                               {"location": "earth", "start": 4, "end": 20}])["legs"][0]["start"] == -2


def test_a_truncated_or_oversized_photo_is_refused_and_a_good_one_kept():  # EDIT-06
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), (200, 10, 10)).save(buf, "PNG")
    good = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
    assert images.check(good) == good
    broken = "data:image/png;base64," + base64.b64encode(buf.getvalue()[:-30]).decode()
    with pytest.raises(FieldError):
        images.check(broken)
    old_limit = images.MAX_PIXELS
    images.MAX_PIXELS = 10
    try:
        with pytest.raises(FieldError, match="too large in pixels"):
            images.check(good)
    finally:
        images.MAX_PIXELS = old_limit


def test_a_repeated_idempotency_key_with_the_same_body_writes_once():  # EDIT-08
    cid = first_crew()
    body = {"crew_id": cid, "kind": "mood", "payload": {"mood": 4, "stress": 2}}
    headers = {**crew_headers(client, cid), "Idempotency-Key": "wave-edits-1"}
    before = db.q("SELECT COUNT(*) n FROM checkins WHERE crew_id=?", (cid,))[0]["n"]
    first = client.post("/api/checkins", json=body, headers=headers)
    again = client.post("/api/checkins", json=body, headers=headers)
    assert first.status_code == 200 and again.status_code == 200 and again.headers.get("idempotent-replay") == "true"
    assert again.json() == first.json()
    assert db.q("SELECT COUNT(*) n FROM checkins WHERE crew_id=?", (cid,))[0]["n"] == before + 1
    other = client.post("/api/checkins", json={**body, "payload": {"mood": 1, "stress": 5}}, headers=headers)
    assert other.status_code == 409
