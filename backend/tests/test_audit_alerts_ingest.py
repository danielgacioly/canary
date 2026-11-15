"""Audit trail, stored alert events with acknowledgement and escalation, and realistic ingestion (devices, origins, times,
corrections, idempotency, size limit). Everything here goes through the API, except `notify.escalate`, which takes a clock."""
import json
import os
import tempfile
import time
from datetime import datetime, timedelta, timezone

os.environ["CANARY_DB"] = os.path.join(tempfile.mkdtemp(), "audit_alerts_ingest.db")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from canary import db  # noqa: E402
from canary.config import settings  # noqa: E402
from canary.domain import audit, data, devices, mission, notify  # noqa: E402
from canary.main import app  # noqa: E402
from tests.support import control_headers, crew_headers, medical_headers, reset_demo  # noqa: E402

client = TestClient(app)
KEY = "legacy-key-for-the-tests"
DAY = "2035-06-11"  # mission day 10 of the demo (launch 2035-06-01)
CRITICAL = {"crew_id": "t", "indicator": "spo2", "value": 85, "unit": "%", "measured_at": DAY + "T20:00:00Z", "source": "test:oximeter", "origin": "device"}
GOOD = {"crew_id": "h", "indicator": "sleep", "value": 6.6, "unit": "h", "measured_at": DAY + "T20:00:00Z", "source": "test:band", "origin": "device"}


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    monkeypatch.setattr(settings, "ingest_key", KEY)
    monkeypatch.setattr(settings, "mission_package", "odyssey1-mars")
    monkeypatch.setattr(settings, "live_space_weather", False)
    assert reset_demo(client).status_code == 200
    assert client.put("/api/control/clock", json={"date": DAY, "time": "23:00"}, headers=ctl()).status_code == 200
    yield
    monkeypatch.undo()
    reset_demo(client)


def ctl():
    return control_headers(client)


def med(account="k"):
    return medical_headers(client, account)


def key(k=KEY, **extra):
    return {"X-Canary-Key": k, **extra}


def post(rows, headers=None, **kw):
    return client.post("/api/observations", headers=headers or key(), json={"rows": rows}, **kw)


def actions():
    return [r["action"] for r in db.q("SELECT action FROM audit_log ORDER BY id")]


def open_events(key_=None):
    rows = db.q("SELECT * FROM alert_events WHERE closed_at IS NULL" + (" AND key=?" if key_ else ""), (key_,) if key_ else ())
    return rows


# ---------------------------------------------------------------- audit trail
def test_the_demo_reset_is_the_first_entry_and_the_chain_verifies():
    first = db.q("SELECT * FROM audit_log ORDER BY id LIMIT 1")[0]
    assert first["id"] == 1 and first["action"] == "demo.reset" and first["actor_id"] in ("g-mcc1", "bootstrap") and first["prev_hash"] == "0" * 64
    assert audit.verify() is None
    r = client.get("/api/audit/verify", headers=med("g-fs1"))
    assert r.status_code == 200 and r.json() == {"ok": True, "broken_at": None}


def test_tampering_with_a_row_is_found():
    client.post("/api/messages", json={"recipient": "h", "text": "hello"}, headers=crew_headers(client, "k"))
    client.post("/api/messages", json={"recipient": "k", "text": "hi"}, headers=crew_headers(client, "h"))
    ids = [r["id"] for r in db.q("SELECT id FROM audit_log ORDER BY id")]
    assert len(ids) >= 4 and audit.verify() is None
    db.connect().execute("UPDATE audit_log SET action='nothing happened' WHERE id=?", (ids[2],))
    db.connect().commit()
    assert audit.verify() == ids[2]
    assert client.get("/api/audit/verify", headers=med("g-fs1")).json() == {"ok": False, "broken_at": ids[2]}


def test_deleting_a_row_breaks_the_chain_at_the_next_one():
    for i in range(3):
        client.post("/api/messages", json={"recipient": "h", "text": f"m{i}"}, headers=crew_headers(client, "k"))
    ids = [r["id"] for r in db.q("SELECT id FROM audit_log ORDER BY id")]
    db.connect().execute("DELETE FROM audit_log WHERE id=?", (ids[1],))
    db.connect().commit()
    assert audit.verify() == ids[2]


def test_the_module_offers_no_update_or_delete():
    assert not [n for n in dir(audit) if n.startswith(("update", "delete", "remove", "purge"))]


def test_every_write_site_records_an_entry():
    start = len(actions())
    h = crew_headers(client, "k")
    e = client.post("/api/emergencies", json={"responder": "k"}, headers=h).json()
    client.post(f"/api/emergencies/{e['id']}", json={"protocol": "seizure", "patient": "t", "text": "log line with 120 bpm"}, headers=h)
    client.post("/api/messages", json={"recipient": "h", "text": "the private text"}, headers=h)
    assert client.put("/api/medical/thresholds", json={"watch": 1.2, "act": 2.4}, headers=med()).status_code == 200
    assert client.put("/api/medical/care-sensitivity", json={"factor": 0.8}, headers=med()).status_code == 200
    assert client.put("/api/medical/exercise-adjust", json={"max_pct": 10, "level1": 5, "level2": 10}, headers=med()).status_code == 200
    assert client.post("/api/medical/goals", json={"who": "h", "area": "physical", "title": "Walk 20 minutes"}, headers=med()).status_code == 200
    assert client.put("/api/control/clock", json={"date": "2035-06-12"}, headers=ctl()).status_code == 200
    assert client.post("/api/control/space-events", json={"id": "ev_test", "kind": "sep", "start_day": 3, "end_day": 4, "locations": ["transit"],
                                                          "extra_dose_msv": 1, "origin": "simulated", "source": "test", "note": ""}, headers=ctl()).status_code == 200
    new = actions()[start:]
    for a in ("emergency.open", "emergency.update", "message.send", "medical.thresholds", "medical.care_sensitivity", "medical.exercise_adjust",
              "medical.goal_add", "mission.clock", "space_event.add"):
        assert a in new, (a, new)
    # the entry says who did it, and a private message text never lands in the log
    row = db.q("SELECT * FROM audit_log WHERE action='message.send'")[0]
    assert row["actor_id"] == "k" and "private text" not in json.dumps(row)
    assert "120 bpm" not in json.dumps(db.q("SELECT * FROM audit_log WHERE action='emergency.update'"))
    assert audit.verify() is None


def test_registration_is_audited():
    from tests.support import empty
    empty(client)
    person = lambda i: {"seat": f"s{i + 1}", "name": f"Person {i}", "role": "Commander" if i == 0 else "Crew medical officer", "home": "Somewhere",  # noqa: E731
                        "pin": f"{3001 + i}", "dob": f"{1985 + i}-04-1{i + 1}", "sex": "Female", "nationality": "Portuguese", "languages": ["Portuguese"],
                        "agency": "Test agency", "flights": 0, "days_in_space": 0, "height_cm": 170, "weight_kg": 68, "blood_type": "A+",
                        "skin_type": "III", "handedness": "Right", "eva": "surface"}
    MISSION = {"callsign": "Test 1", "name": "Test mission", "launch_date": "2036-03-01", "preset": "mars", "dose_waiver": True}
    c = client.post("/api/control/session", json={"pin": "4242"}).json()["token"]
    body = {"crew": [person(0), person(1)], "mission": MISSION, "ground": [{"id": "g-mcc1", "name": "Test Controller", "role": "mcc", "pin": "4242"}]}
    r = client.post("/api/control/register", headers={"Authorization": "Bearer " + c}, json=body)
    assert r.status_code == 200, r.text
    row = db.q("SELECT * FROM audit_log WHERE action='mission.register'")[0]
    assert "4242" not in json.dumps(row) and row["actor_id"] == "bootstrap"
    assert audit.verify() is None


def test_sign_in_failure_lockout_success_and_logout_are_recorded_without_pins():
    from canary import auth
    auth.clear_failures()
    for _ in range(5):
        assert client.post("/api/crew/a/session", json={"pin": "9999"}).status_code in (401, 429)
    assert client.post("/api/crew/a/session", json={"pin": "1003"}).status_code == 429  # locked, even for the right PIN
    auth.clear_failures()
    tok = client.post("/api/crew/a/session", json={"pin": "1003"}).json()["token"]
    assert client.post("/api/session/logout", headers={"Authorization": "Bearer " + tok}).status_code == 200
    new = actions()
    for a in ("auth.signin_failed", "auth.lockout", "auth.signin", "auth.logout"):
        assert a in new, a
    log = json.dumps(db.q("SELECT * FROM audit_log"))
    assert "9999" not in log and "1003" not in log and tok not in log


def test_the_audit_log_pages_and_redacts_health_values_for_control():
    audit.record({"id": "k", "role": "cmo"}, "test.write", "x", before={"value": 1, "note": "n"}, after={"vitals": {"hr": 60}, "values": [1], "ok": True})
    fs = client.get("/api/audit?limit=2", headers=med("g-fs1")).json()  # (the sign-in of the reader is newer than the test entry)
    assert len(fs["entries"]) == 2 and fs["next"] is not None
    assert next(e for e in audit.entries(10)["entries"] if e["action"] == "test.write")["after"] == {"ok": True, "values": [1], "vitals": {"hr": 60}}
    older = client.get(f"/api/audit?limit=2&before_id={fs['next']}", headers=med("g-fs1")).json()
    assert older["entries"][0]["id"] < fs["next"]
    mcc = next(e for e in client.get("/api/audit?limit=10", headers=ctl()).json()["entries"] if e["action"] == "test.write")
    assert mcc["action"] == "test.write" and mcc["before"] == {"value": "[redacted]", "note": "n"}
    assert mcc["after"] == {"vitals": "[redacted]", "values": "[redacted]", "ok": True}
    assert client.get("/api/audit").status_code == 401
    assert client.get("/api/audit", headers=crew_headers(client, "h")).status_code == 401  # a crew token is not a reader
    assert client.get("/api/audit", headers=med("k")).status_code == 403  # the officer is not a flight surgeon


def test_a_goal_is_voided_not_deleted_and_needs_a_reason():
    h = med()
    gid = client.post("/api/medical/goals", json={"who": "h", "area": "physical", "title": "Walk 20 minutes"}, headers=h).json()[0]["id"]
    assert client.request("DELETE", f"/api/medical/goals/{gid}", headers=h).status_code == 422
    assert client.request("DELETE", f"/api/medical/goals/{gid}", json={"reason": ""}, headers=h).status_code == 422
    assert client.request("DELETE", f"/api/medical/goals/{gid}", json={}, headers=h).status_code == 422
    assert db.q("SELECT voided_at FROM medical_goals WHERE id=?", (gid,))[0]["voided_at"] is None
    r = client.request("DELETE", f"/api/medical/goals/{gid}", json={"reason": "Patient recovered"}, headers=h)
    assert r.status_code == 200 and gid not in [g["id"] for g in r.json()]
    row = db.q("SELECT * FROM medical_goals WHERE id=?", (gid,))[0]  # still there
    assert row["voided_by"] == "k" and row["void_reason"] == "Patient recovered" and row["voided_at"]
    assert gid in [g["id"] for g in client.get("/api/medical/goals?include_voided=true", headers=h).json()]
    assert "medical.goal_void" in actions()


def test_thresholds_keep_their_history():
    h = med()
    client.put("/api/medical/thresholds", json={"watch": 1.2, "act": 2.4}, headers=h)
    client.put("/api/medical/thresholds", json={"watch": 1.4, "act": 2.6}, headers=h)
    client.put("/api/medical/care-sensitivity", json={"factor": 0.7}, headers=h)
    hist = client.get("/api/medical/settings-history?key=thresholds", headers=h).json()
    assert [(v["version"], v["value"]["watch"]) for v in hist] == [(1, 1.2), (2, 1.4)]
    assert hist[0]["by"] == "k" and client.get("/api/medical/thresholds", headers=h).status_code in (200, 404, 405)
    assert [v["value"]["factor"] for v in client.get("/api/medical/settings-history?key=care_sensitivity", headers=h).json()] == [0.7]
    assert client.get("/api/medical/care-sensitivity", headers=h).json()["factor"] == 0.7


# ---------------------------------------------------------------- alert events
def test_a_critical_reading_opens_an_event_and_reaches_the_officer_in_the_same_request():
    before = len(db.q("SELECT id FROM messages WHERE recipient='k' AND kind='alert'"))
    r = post([CRITICAL])
    assert r.status_code == 200 and r.json()["accepted"] == 1 and r.json()["alerts_opened"] >= 1, r.text
    ev = db.q("SELECT * FROM alert_events WHERE crew_id='t' AND key='ind_spo2'")
    assert len(ev) == 1 and ev[0]["level"] == 2 and ev[0]["closed_at"] is None and ev[0]["rules_version"] == notify.RULES_VERSION
    inputs = json.loads(ev[0]["inputs"])
    assert inputs["reading"] == 85 and inputs["unit"] == "%" and "baseline" in inputs and "z" in inputs
    assert json.loads(ev[0]["thresholds"])["watch_act"] == {"watch": 1.5, "act": 2.5} or "watch_act" in json.loads(ev[0]["thresholds"])
    msgs = db.q("SELECT * FROM messages WHERE recipient='k' AND kind='alert'")
    assert len(msgs) == before + 1 and "Tom" in msgs[-1]["text"]
    assert db.q("SELECT 1 FROM messages WHERE recipient='earth' AND kind='alert_earth'")  # and Earth, with the delay
    assert "alert.open" in actions() and "observations.ingest" in actions()
    # the same reading again opens nothing new and tells nobody twice
    again = post([CRITICAL]).json()
    assert again["duplicates"] == 1 and again["alerts_opened"] == 0
    assert len(db.q("SELECT id FROM messages WHERE recipient='k' AND kind='alert'")) == before + 1


def test_changing_the_thresholds_afterwards_does_not_change_a_stored_event():
    post([CRITICAL])
    stored = db.q("SELECT inputs, thresholds, rule, level FROM alert_events WHERE crew_id='t' AND key='ind_spo2'")[0]
    client.put("/api/medical/thresholds", json={"watch": 3.5, "act": 4.5}, headers=med())
    client.put("/api/medical/care-sensitivity", json={"factor": 0.5}, headers=med())
    assert db.q("SELECT inputs, thresholds, rule, level FROM alert_events WHERE crew_id='t' AND key='ind_spo2'")[0] == stored


def test_the_event_closes_when_the_alert_ends():
    post([CRITICAL])
    assert open_events("ind_spo2")
    assert client.put("/api/control/clock", json={"date": "2035-06-25"}, headers=ctl()).status_code == 200  # two weeks on, with no new reading
    ev = db.q("SELECT * FROM alert_events WHERE key='ind_spo2' AND crew_id='t'")[0]
    assert ev["closed_at"] is not None and ev["closed_day"] is not None and "alert.close" in actions()


def test_acknowledgement_by_the_officer_and_by_a_flight_surgeon():
    post([CRITICAL])
    eid = db.q("SELECT id FROM alert_events WHERE key='ind_spo2' AND crew_id='t'")[0]["id"]
    assert client.post(f"/api/alerts/events/{eid}/ack").status_code == 401
    assert client.post(f"/api/alerts/events/{eid}/ack", headers=crew_headers(client, "h")).status_code == 403  # a crew member is not the officer
    assert client.post(f"/api/alerts/events/{eid}/ack", headers=ctl()).status_code == 401  # nor is Control
    r = client.post(f"/api/alerts/events/{eid}/ack", headers=med("k"))
    assert r.status_code == 200 and r.json()["acknowledged"] and r.json()["acks"][0]["by"] == "k" and r.json()["acks"][0]["role"] == "cmo"
    r = client.post(f"/api/alerts/events/{eid}/ack", headers=med("g-fs1"))
    assert [a["role"] for a in r.json()["acks"]] == ["cmo", "flight_surgeon"]
    assert client.post(f"/api/alerts/events/{eid}/ack", headers=med("k")).json()["acks"].__len__() == 2  # once per person
    assert client.post("/api/alerts/events/9999/ack", headers=med("k")).status_code == 404
    assert "alert.ack" in actions()


def test_who_sees_which_events_and_control_never_sees_values():
    post([CRITICAL])
    all_ = client.get("/api/alerts/events", headers=med("k")).json()["events"]
    assert any(e["key"] == "ind_spo2" and e["inputs"]["reading"] == 85 for e in all_)
    own = client.get("/api/alerts/events", headers=crew_headers(client, "h")).json()["events"]
    assert all(e["crew_id"] == "h" for e in own)
    t_own = client.get("/api/alerts/events", headers=crew_headers(client, "t")).json()["events"]
    assert any(e["key"] == "ind_spo2" for e in t_own)
    mcc = client.get("/api/alerts/events", headers=ctl()).json()["events"]
    e = next(x for x in mcc if x["key"] == "ind_spo2")
    assert e["crew_id"] == "t" and e["level"] == 2 and e["opened_at"] and e["acknowledged"] is False
    assert "inputs" not in e and "thresholds" not in e and "title" not in e and "85" not in json.dumps(e)
    assert client.get("/api/alerts/events").status_code == 401


def test_unacknowledged_critical_events_climb_to_the_commander_then_the_flight_surgeon():
    post([CRITICAL])
    ev = db.q("SELECT * FROM alert_events WHERE key='ind_spo2' AND crew_id='t'")[0]
    wait = notify.escalate_after_s()
    t0 = time.time()
    assert notify.escalate(t0 + wait - 1) == 0  # not yet
    assert notify.escalate(t0 + wait + 1) >= 1
    assert notify.get(ev["id"])["escalation_stage"] == 1
    cmd = db.q("SELECT * FROM messages WHERE recipient='h' AND kind='alert' ORDER BY id DESC LIMIT 1")[0]  # Helena is the commander
    assert "not acknowledged" in cmd["text"]
    assert notify.escalate(t0 + wait + 2) == 0  # one step at a time
    assert notify.escalate(t0 + 2 * wait + 5) >= 1
    assert notify.get(ev["id"])["escalation_stage"] == 2
    fs = db.q("SELECT * FROM messages WHERE recipient='g-fs1' AND kind='alert_earth' ORDER BY id DESC LIMIT 1")[0]
    assert fs["deliver_at"] > fs["sent_at"]  # Earth hears it after the signal delay
    assert [r["reason"] for r in notify.get(ev["id"])["recipients"] if r["reason"].startswith("escalation")] == ["escalation_1", "escalation_2"]
    assert notify.escalate(t0 + 10 * wait) == 0  # the top of the ladder
    assert actions().count("alert.escalate") >= 2


def test_an_acknowledged_event_does_not_climb():
    post([CRITICAL])
    eid = db.q("SELECT id FROM alert_events WHERE key='ind_spo2' AND crew_id='t'")[0]["id"]
    client.post(f"/api/alerts/events/{eid}/ack", headers=med("k"))
    assert notify.escalate(time.time() + 10 * notify.escalate_after_s()) == 0
    assert notify.get(eid)["escalation_stage"] == 0


def test_the_escalation_wait_is_set_by_the_environment_and_scaled_in_the_demo(monkeypatch):
    monkeypatch.setattr(settings, "escalate_minutes", 10)
    monkeypatch.setattr(settings, "delay_speedup", 20)
    assert notify.escalate_after_s() == 30
    monkeypatch.setattr(settings, "delay_speedup", 1)
    assert notify.escalate_after_s() == 600


def test_a_storm_reaches_the_officer_and_earth_once_for_the_crew():
    storm = next(s["index"] for s in data.scenes() if s["storm"] == "sep")
    assert client.put("/api/mission", json={"step": storm}, headers=ctl()).status_code == 200
    evs = open_events("storm")
    assert len(evs) == 4  # one event per person ...
    cmo = db.q("SELECT * FROM messages WHERE recipient='k' AND kind='alert' AND text LIKE 'Environment alert%'")
    assert len(cmo) == 1 and cmo[0]["deliver_at"] == cmo[0]["sent_at"]  # ... one message for the officer, at once
    fs = db.q("SELECT * FROM messages WHERE recipient='g-fs1' AND kind='alert_earth' AND text LIKE 'Environment alert%'")
    mcc = db.q("SELECT * FROM messages WHERE recipient='g-mcc1' AND kind='alert_env'")
    assert len(fs) == 1 and len(mcc) == 1 and fs[0]["deliver_at"] > fs[0]["sent_at"] and mcc[0]["deliver_at"] > mcc[0]["sent_at"]
    assert {r["role"] for r in json.loads(evs[0]["recipients"])} == {"cmo", "flight_surgeon", "mcc"}
    # one acknowledgement answers the storm for everyone
    eid = evs[0]["id"]
    client.post(f"/api/alerts/events/{eid}/ack", headers=med("k"))
    assert all(json.loads(e["acks"]) for e in open_events("storm"))


def test_a_watch_alert_that_lasts_a_week_tells_the_officer_once(monkeypatch):
    from canary.domain import health
    h = {"id": "ind_sleep", "level": 1, "title": "Sleep is outside your normal.", "why": "", "sources": [], "days_active": 1, "since_day": 10}
    real = health.snapshot

    def snap(cid, ms):
        s = real(cid, ms)
        return {**s, "alerts": [dict(h, since_day=ms["day"])] if cid == "h" else []}
    monkeypatch.setattr(health, "snapshot", snap)
    ms = mission.state()
    notify.run(ms, ["h"])
    assert not db.q("SELECT 1 FROM messages WHERE recipient='k' AND text LIKE 'Watch alert%'")
    later = {**ms, "day": ms["day"] + 7}
    notify.run(later, ["h"])
    notify.run({**later, "day": later["day"] + 1}, ["h"])
    assert len(db.q("SELECT 1 FROM messages WHERE recipient='k' AND text LIKE 'Watch alert%'")) == 1


# ---------------------------------------------------------------- devices
def new_device(**body):
    r = client.post("/api/control/devices", headers=ctl(), json={"name": "Wrist band", "kind": "wearable", **body})
    assert r.status_code == 200, r.text
    return r.json()


def test_a_device_key_ingests_and_the_server_stamps_the_device_and_the_time():
    d = new_device()
    assert d["key"].startswith("ck_") and d["id"].startswith("dev-")
    r = post([GOOD], headers=key(d["key"]))
    assert r.status_code == 200 and r.json()["accepted"] == 1
    row = db.q("SELECT device_id, received_at FROM observations WHERE source='test:band' AND crew_id='h'")[0]
    assert row["device_id"] == d["id"] and row["received_at"]
    listing = client.get("/api/control/devices", headers=ctl()).json()["devices"]
    assert d["key"] not in json.dumps(listing) and "key_hash" not in json.dumps(listing)
    assert next(x for x in listing if x["id"] == d["id"])["last_received_at"] == row["received_at"]
    assert db.q("SELECT key_hash FROM devices WHERE id=?", (d["id"],))[0]["key_hash"] != d["key"]
    e = db.q("SELECT * FROM audit_log WHERE action='observations.ingest'")[0]
    assert e["actor_id"] == d["id"] and "6.6" not in json.dumps(e) and d["key"] not in json.dumps(db.q("SELECT * FROM audit_log"))


def test_only_control_registers_devices():
    assert client.post("/api/control/devices", json={"name": "x", "kind": "wearable"}).status_code == 401
    assert client.post("/api/control/devices", json={"name": "x", "kind": "wearable"}, headers=med("k")).status_code == 401
    assert client.post("/api/control/devices", headers=ctl(), json={"name": "x", "kind": "toaster"}).status_code == 422
    assert client.post("/api/control/devices", headers=ctl(), json={"name": "x", "kind": "wearable", "crew_id": "zz"}).status_code == 422
    assert client.get("/api/control/devices").status_code == 401


def test_a_revoked_key_is_refused():
    d = new_device()
    assert post([GOOD], headers=key(d["key"])).status_code == 200
    assert client.post(f"/api/control/devices/{d['id']}/revoke", headers=ctl()).json()["revoked_at"]
    r = post([{**GOOD, "source": "test:later"}], headers=key(d["key"]))
    assert r.status_code == 401 and d["key"] not in r.text
    assert client.post("/api/control/devices/dev-nope/revoke", headers=ctl()).status_code == 404
    assert "device.revoke" in actions()


def test_a_device_bound_to_a_person_can_send_only_their_readings():
    d = new_device(crew_id="h")
    assert post([GOOD], headers=key(d["key"])).status_code == 200
    r = post([{**GOOD, "crew_id": "k", "source": "test:other"}], headers=key(d["key"]))
    assert r.status_code == 422 and r.json()["detail"][0]["field"] == "rows.0.crew_id"
    assert post([{**GOOD, "crew_id": "cabin", "indicator": "dose_rate", "value": 0.5, "unit": "mSv/day"}], headers=key(d["key"])).status_code == 422


def test_in_flight_mode_only_device_keys_count(monkeypatch):
    d = new_device()
    monkeypatch.setattr(settings, "mode", "flight")
    monkeypatch.setattr(mission, "_now", lambda: datetime(2035, 6, 11, 23, 0, tzinfo=timezone.utc))
    assert post([GOOD], headers=key(KEY)).status_code == 401  # the shared key is a demo convenience
    assert post([GOOD], headers=key(d["key"])).status_code == 200


# ---------------------------------------------------------------- origins, times, corrections
def test_origin_is_required_and_checked():
    r = post([{k: v for k, v in GOOD.items() if k != "origin"}])
    assert r.status_code == 422 and r.json()["detail"][0]["field"] == "rows.0.origin"
    assert post([{**GOOD, "origin": "real"}]).status_code == 422  # `real` is only what an old package says
    for i, origin in enumerate(("device", "manual", "lab", "simulated", "sample")):
        assert post([{**GOOD, "origin": origin, "source": f"test:{origin}"}]).status_code == 200, origin


def test_sample_readings_are_refused_in_flight_and_never_used_by_alerts_in_demo(monkeypatch):
    r = post([{**CRITICAL, "origin": "sample"}])
    assert r.status_code == 200 and r.json()["accepted"] == 1 and r.json()["alerts_opened"] == 0  # stored, but never an alert
    assert not db.q("SELECT 1 FROM alert_events WHERE key='ind_spo2'")
    assert db.q("SELECT 1 FROM observations WHERE origin='sample'")
    assert data.last("t", "spo2", 10)["value"] != 85  # and never a baseline or a value
    monkeypatch.setattr(settings, "mode", "flight")
    monkeypatch.setattr(mission, "_now", lambda: datetime(2035, 6, 11, 23, 0, tzinfo=timezone.utc))
    d = new_device()
    r = post([{**GOOD, "origin": "sample", "source": "test:s2"}], headers=key(d["key"]))
    assert r.status_code == 422 and r.json()["detail"][0]["field"] == "rows.0.origin"


def test_a_time_more_than_five_minutes_ahead_is_refused():
    now = datetime(2035, 6, 11, 23, 0)
    ok = post([{**GOOD, "measured_at": (now + timedelta(minutes=4)).strftime("%Y-%m-%dT%H:%M:%SZ")}])
    assert ok.status_code == 200
    r = post([{**GOOD, "source": "test:x", "measured_at": (now + timedelta(minutes=6)).strftime("%Y-%m-%dT%H:%M:%SZ")}])
    assert r.status_code == 422 and r.json()["detail"][0]["field"] == "rows.0.measured_at"
    r = post([{**GOOD, "source": "test:y", "measured_at": "2036-01-01T00:00:00Z"}])
    assert r.status_code == 422


def test_in_flight_the_future_is_judged_against_the_server_clock(monkeypatch):
    d = new_device()
    monkeypatch.setattr(settings, "mode", "flight")
    monkeypatch.setattr(mission, "_now", lambda: datetime(2035, 6, 11, 12, 0, tzinfo=timezone.utc))
    assert post([{**GOOD, "measured_at": "2035-06-11T12:04:00Z"}], headers=key(d["key"])).status_code == 200
    assert post([{**GOOD, "measured_at": "2035-06-11T12:06:00Z", "source": "test:z"}], headers=key(d["key"])).status_code == 422


def test_a_row_with_only_a_day_keeps_no_time_and_still_counts():
    assert post([{**GOOD, "measured_at": None, "day": 9, "value": 3.1, "source": "test:daily"}]).status_code == 200
    row = db.q("SELECT measured_at, day FROM observations WHERE source='test:daily'")[0]
    assert row["measured_at"] is None and row["day"] == 9
    assert data.last("h", "sleep", 9)["value"] == 3.1
    assert post([{**GOOD, "measured_at": None, "day": 9, "value": 3.1, "source": "test:daily"}]).json()["duplicates"] == 1
    assert post([{**GOOD, "measured_at": None, "day": 9, "value": 3.9, "source": "test:daily"}]).status_code == 409


def test_the_day_of_a_reading_follows_the_launch_date_at_read_time():
    post([{**GOOD, "measured_at": "2035-06-03T20:00:00Z", "value": 2.2, "source": "test:moves"}])
    assert data.last("h", "sleep", 2)["day"] == 2 and data.last("h", "sleep", 2)["value"] == 2.2
    r = db.get_setting("registry")
    r["mission"]["launch_date"] = "2035-05-31"
    db.set_setting("registry", r)
    assert data.last("h", "sleep", 3)["value"] == 2.2 and data.last("h", "sleep", 3)["day"] == 3  # one day later on the new calendar
    r["mission"]["launch_date"] = "2035-06-01"
    db.set_setting("registry", r)


def test_a_correction_replaces_the_old_reading_and_keeps_it():
    assert post([GOOD]).status_code == 200
    old = db.q("SELECT id FROM observations WHERE source='test:band' AND crew_id='h'")[0]["id"]
    assert data.last("h", "sleep", 10)["value"] == 6.6
    r = post([{**GOOD, "value": 5.1, "supersedes": old, "reason": "Band was on the wrong wrist"}])
    assert r.status_code == 200 and r.json()["corrected"] == 1 and r.json()["accepted"] == 0
    assert data.last("h", "sleep", 10)["value"] == 5.1
    rows = db.q("SELECT * FROM observations WHERE source='test:band' AND crew_id='h' ORDER BY id")
    assert len(rows) == 2 and rows[0]["superseded_by"] == rows[1]["id"] and rows[1]["supersedes"] == old and rows[1]["reason"].startswith("Band")
    assert post([{**GOOD, "value": 4.0, "supersedes": old, "reason": "again"}]).status_code == 409  # already corrected
    assert post([{**GOOD, "value": 4.0, "source": "test:n", "supersedes": old}]).status_code == 422  # no reason
    assert post([{**GOOD, "value": 4.0, "source": "test:n", "supersedes": 999999999, "reason": "x"}]).status_code == 422
    other = db.q("SELECT id FROM observations WHERE crew_id='k' AND indicator='hr' LIMIT 1")[0]["id"]
    assert post([{**GOOD, "supersedes": other, "reason": "x", "source": "test:n"}]).status_code == 422  # not the same person and indicator


def test_a_conflicting_duplicate_is_a_409_and_stores_nothing():
    assert post([GOOD]).status_code == 200
    n = db.q("SELECT COUNT(*) n FROM observations")[0]["n"]
    r = post([{**GOOD, "source": "test:fine"}, {**GOOD, "value": 7.7}])
    assert r.status_code == 409 and "supersedes" in r.json()["detail"][0]["message"] and r.json()["detail"][0]["field"] == "rows.1"
    assert db.q("SELECT COUNT(*) n FROM observations")[0]["n"] == n
    assert post([GOOD]).json()["duplicates"] == 1  # the same value is idempotent


def test_an_idempotency_key_returns_the_first_answer():
    h = key(**{"Idempotency-Key": "batch-1"})
    first = post([GOOD], headers=h)
    assert first.status_code == 200 and first.json()["accepted"] == 1
    again = post([GOOD], headers=h)
    assert again.status_code == 200 and again.json() == first.json()  # not {"accepted": 0, "duplicates": 1}
    assert post([{**GOOD, "source": "test:diff"}], headers=h).status_code == 409  # same key, another body
    assert post([{**GOOD, "source": "test:diff"}], headers=key(**{"Idempotency-Key": "batch-2"})).json()["accepted"] == 1


def test_a_body_over_two_megabytes_is_refused_before_it_is_parsed():
    big = b'{"rows": [], "pad": "' + b"x" * 2_100_000 + b'"}'
    r = client.post("/api/observations", headers={**key(), "Content-Type": "application/json"}, content=big)
    assert r.status_code == 413
    # a body that does not declare its length is stopped while it streams
    def chunks():
        for _ in range(21):
            yield b"x" * 100_000
    r = client.post("/api/observations", headers={**key(), "Content-Type": "application/json"}, content=chunks())
    assert r.status_code == 413
    assert client.post("/api/observations", headers=key(), content=b"not json").status_code == 422
    assert client.post("/api/observations", headers={"X-Canary-Key": "nope"}, content=big).status_code == 401  # the key is checked first


def test_a_package_that_says_real_is_mapped_to_lab_or_device_at_import():
    """The demo package is all `simulated` (the blood is modelled on Inspiration4); a package that still says `real` is mapped
    at import: a laboratory method becomes `lab`, anything else `device`; the engine reads both as measured."""
    csv_ = ("crew_id,day,indicator,value,unit,origin,method,source,note,measured_at\n"
            "h,-40,hgb,13.9,g/dL,real,blood,lab:test,,2035-04-22T08:00:00Z\n"
            "h,-40,hr,60,bpm,real,wearable,test:band,,2035-04-22T08:00:00Z\n")
    r = client.post("/api/control/import", headers=ctl(), files=[("file", ("observations.csv", csv_.encode(), "text/csv"))])
    assert r.status_code == 200, r.text
    origins = {r["origin"] for r in db.q("SELECT DISTINCT origin FROM observations")}
    assert origins <= {"device", "manual", "lab", "simulated"} and "real" not in origins
    assert db.q("SELECT 1 FROM observations WHERE origin='lab' AND method='blood' AND source='lab:test'")
    assert db.q("SELECT 1 FROM observations WHERE origin='device' AND method='wearable' AND source='test:band'")
    from canary.domain import data as _data
    assert {o["origin"] for o in _data.table().rows_on("h", "hgb", -40)} == {"real"}  # the engine's word for measured
