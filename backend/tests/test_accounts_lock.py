"""Accounts, roles, server-side authorization on every write, the operating mode and the locked mission.

- Every person signs in with their own account: crew with their crew id, the medical console with the crew medical officer or
  a flight surgeon, Canary Control with an MCC account (or the bootstrap PIN while none exists).
- The sender of a message is the token's, never the body's.
- A registered mission is locked: no second registration, no clearing, no plan change, no import that defines the mission.
- Flight mode has no demo endpoints.
- Wrong PINs pause an account and an address, in SQLite, with growing waits.
"""
import importlib
import os
import tempfile

os.environ["CANARY_DB"] = os.path.join(tempfile.mkdtemp(), "accounts.db")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from canary import auth, config, db  # noqa: E402
from canary.config import settings  # noqa: E402
from canary.domain import data, plan, registry  # noqa: E402
from canary.main import app  # noqa: E402
from tests import golden_capture as gc  # noqa: E402
from tests.support import GROUND, client_from, control_headers, crew_headers, empty, medical_headers, reset_demo  # noqa: E402

client = TestClient(app)
KEY = "test-ingest-key-not-a-secret"
MARS = data.package_dir("odyssey1-mars")


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    monkeypatch.setattr(settings, "live_space_weather", False)
    monkeypatch.setattr(settings, "ingest_key", KEY)
    assert reset_demo(client).status_code == 200
    yield
    monkeypatch.undo()
    reset_demo(client)


def demo_form():
    return client.get("/api/control/demo", headers=control_headers(client)).json()


def register_on_empty(**mission):
    """Empty the system and register the demo crew and ground accounts (the Mars plan needs the waiver by default)."""
    form = demo_form()
    empty(client)
    return client.post("/api/control/register", headers=control_headers(client),
                       json={"crew": form["crew"], "ground": form["ground"], "mission": {**form["mission"], **mission}})


# ---------------------------------------------------------------- every write needs a role
WRITES = [
    ("put", "/api/mission", {"day": 10}),
    ("put", "/api/plan", {"name": "x", "legs": [{"location": "earth", "start": 0, "end": 5}]}),
    ("post", "/api/plan/preset", {"preset": "iss"}),
    ("post", "/api/setup", {"name": "x", "legs": [{"location": "earth", "start": 0, "end": 5}]}),
    ("post", "/api/demo/reset", None),
    ("post", "/api/emergencies", {}),
    ("post", "/api/emergencies/1", {"text": "x"}),
    ("post", "/api/messages", {"recipient": "medical", "text": "hi"}),
    ("post", "/api/protocols/match", {"text": "he is shaking"}),
    ("put", "/api/medical/thresholds", {"watch": 1.0, "act": 2.0}),
    ("post", "/api/medical/goals", {"who": "all", "area": "physical", "title": "Walk", "days": 3}),
    ("delete", "/api/medical/goals/1", None),
    ("put", "/api/control/clock", {"real": True}),
    ("post", "/api/control/register", {}),
    ("post", "/api/control/demo-data", None),
    ("post", "/api/control/space-events", {}),
]
READS = ["/api/emergencies", "/api/messages", "/api/control/overview", "/api/medical/overview", "/api/control/demo", "/api/control/register-options"]


@pytest.mark.parametrize("method,path,body", WRITES)
def test_a_write_without_a_token_is_refused(method, path, body):
    r = client.request(method.upper(), path, json=body) if body is not None else client.request(method.upper(), path)
    assert r.status_code in (401, 403), (path, r.status_code)


@pytest.mark.parametrize("path", READS)
def test_a_read_without_a_token_is_refused(path):
    assert client.get(path).status_code in (401, 403)


def test_the_wrong_kind_of_token_is_refused():
    crew, med, ctl = crew_headers(client, "h"), medical_headers(client), control_headers(client)
    for h in (crew, med):  # control writes need a control token
        assert client.post("/api/demo/reset", headers=h).status_code == 401
        assert client.put("/api/mission", json={"day": 5}, headers=h).status_code == 401
    assert client.put("/api/medical/thresholds", json={"watch": 1.0, "act": 2.0}, headers=ctl).status_code == 401  # a medical write needs a medical token
    assert client.put("/api/medical/thresholds", json={"watch": 1.0, "act": 2.0}, headers=crew).status_code == 401
    # a token in another kind's header does not count either
    tok = crew["X-Canary-Viewer"]
    assert client.get("/api/control/overview", headers={"X-Canary-Control": tok}).status_code == 401
    assert client.get("/api/medical/overview", headers={"Authorization": f"Bearer {tok}"}).status_code == 401


def test_emergencies_are_for_the_people_on_board():
    assert client.post("/api/emergencies", json={}, headers=crew_headers(client, "h")).status_code == 200
    assert client.post("/api/emergencies", json={}, headers=medical_headers(client)).status_code == 200  # the crew medical officer
    surgeon = medical_headers(client, "g-fs1")
    assert client.post("/api/emergencies", json={}, headers=surgeon).status_code == 403  # on the ground
    assert client.post("/api/emergencies", json={}, headers=control_headers(client)).status_code == 403
    e = client.post("/api/emergencies", json={}, headers=crew_headers(client, "a")).json()
    assert e["responder"] == "a"  # recorded from the token
    sent = [m for m in client.get("/api/messages", headers=medical_headers(client)).json() if m["kind"] == "emergency"]
    assert sent and sent[0]["sender"] == "a"
    for h in (crew_headers(client, "t"), medical_headers(client, "g-fs1"), control_headers(client)):
        assert client.get("/api/emergencies", headers=h).status_code == 200  # any signed-in person reads them


# ---------------------------------------------------------------- the sender is the token's
def test_a_message_cannot_be_sent_in_someone_elses_name():
    for h in (crew_headers(client, "h"), control_headers(client)):
        r = client.post("/api/messages", json={"sender": "g-mcc1", "recipient": "medical", "text": "spoof"}, headers=h)
        assert r.status_code == 422 and "sender" in str(r.json()["detail"])  # a body sender is refused, not ignored
    cases = {"h": crew_headers(client, "h"), "k": medical_headers(client), "g-fs1": medical_headers(client, "g-fs1"),
             "g-mcc1": control_headers(client)}
    for who, h in cases.items():
        r = client.post("/api/messages", json={"recipient": "medical", "text": f"from {who}"}, headers=h)
        assert r.status_code == 200, r.text
        assert [m for m in r.json() if m["text"] == f"from {who}"][0]["sender"] == who
    # the bootstrap sign-in is nobody until an MCC account exists
    empty(client)
    assert client.post("/api/messages", json={"recipient": "medical", "text": "x"}, headers=control_headers(client)).status_code == 403


def test_emergency_report_and_security_messages_stay_with_their_people():
    e = client.post("/api/emergencies", json={}, headers=crew_headers(client, "h")).json()
    client.post(f"/api/emergencies/{e['id']}", json={"close": True, "outcome": "stable"}, headers=crew_headers(client, "h"))
    kinds = lambda h: {m["kind"] for m in client.get("/api/messages", headers=h).json()}  # noqa: E731
    assert {"emergency", "report"} <= kinds(crew_headers(client, "h"))  # the sender
    assert {"emergency", "report"} <= kinds(medical_headers(client, "g-fs1"))
    assert not {"emergency", "report"} & kinds(crew_headers(client, "t"))
    assert not {"emergency", "report"} & kinds(control_headers(client))


def test_the_mission_overview_hides_personal_fields_from_nobody_signed_in():
    anon = client.get("/api/mission/overview").json()["crew"][0]
    assert not {"nationality", "agency", "flights", "days_in_space"} & set(anon)
    assert {"nationality", "agency", "flights", "days_in_space"} <= set(client.get("/api/mission/overview", headers=crew_headers(client, "h")).json()["crew"][0])


# ---------------------------------------------------------------- accounts and sessions
def test_the_public_account_list_has_names_and_roles_and_never_a_pin():
    r = client.get("/api/accounts/public")
    assert r.status_code == 200
    j = r.json()
    assert [c["id"] for c in j["crew"]] == ["h", "k", "a", "t"] and {"id", "name", "role", "initials"} <= set(j["crew"][0])
    assert {g["id"]: g["role"] for g in j["ground"]} == {"g-fs1": "flight_surgeon", "g-mcc1": "mcc"}
    assert "pin" not in r.text.lower() and "1961" not in r.text and "1001" not in r.text and "hash" not in r.text


def test_the_medical_console_takes_the_crew_medical_officer_and_flight_surgeons_only():
    assert client.post("/api/medical/session", json={"account_id": "k", "pin": "1002"}).status_code == 200
    assert client.post("/api/medical/session", json={"account_id": "g-fs1", "pin": "1961"}).status_code == 200
    # Helena is crew without the cmo role: her own PIN does not open the medical console
    assert client.post("/api/medical/session", json={"account_id": "h", "pin": "1001"}).status_code == 401
    assert client.post("/api/medical/session", json={"account_id": "g-mcc1", "pin": "4242"}).status_code == 401  # an MCC account is not a medical one
    assert client.post("/api/medical/session", json={"account_id": "nobody", "pin": "1002"}).status_code == 401
    assert client.post("/api/medical/session", json={"pin": "1002"}).status_code == 422  # an account is required
    assert client.post("/api/medical/session", json={"account_id": "k", "pin": "1961"}).status_code == 401  # the PIN is the account's own
    assert "cmo" in client.post("/api/medical/session", json={"account_id": "k", "pin": "1002"}).json()["roles"]
    assert "crew" in client.post("/api/crew/k/session", json={"pin": "1002"}).json()["roles"]


def test_a_token_is_one_signed_format_and_a_forged_one_is_nobody():
    tok = crew_headers(client, "h")["X-Canary-Viewer"]
    kind, who, roles, exp, jti, sig = tok.split(".")
    assert (kind, who, roles) == ("crew", "h", "crew") and exp.isdigit() and jti
    assert client.get("/api/goals/h", headers={"X-Canary-Viewer": tok}).status_code == 200
    for forged in (tok.replace(".crew.", ".crew+cmo.", 1), tok[:-1] + ("0" if tok[-1] != "0" else "1"), "h", f"control.g-mcc1.mcc.{exp}.{jti}.{sig}"):
        assert client.get("/api/goals/h", headers={"X-Canary-Viewer": forged}).status_code == 403
    assert client.get("/api/control/overview", headers={"X-Canary-Control": f"control.g-mcc1.mcc+x.{exp}.{jti}.{sig}"}).status_code == 401


def test_logout_revokes_the_token():
    ctl, crew = control_headers(client), crew_headers(client, "h")
    assert client.get("/api/control/overview", headers=ctl).status_code == 200
    assert client.post("/api/session/logout").status_code == 401  # nothing to end
    r = client.post("/api/session/logout", headers={**ctl, **crew})
    assert r.status_code == 200 and r.json()["revoked"] == 2
    assert client.get("/api/control/overview", headers=ctl).status_code == 401
    assert client.get("/api/goals/h", headers=crew).status_code == 403
    assert db.q("SELECT COUNT(*) n FROM revoked_tokens")[0]["n"] == 2
    other = crew_headers(client, "h")  # a new sign-in works
    assert client.get("/api/goals/h", headers=other).status_code == 200
    db.x("UPDATE revoked_tokens SET exp=0")
    auth.revoke(other["X-Canary-Viewer"])  # an expired entry is pruned when the next one is added
    assert db.q("SELECT COUNT(*) n FROM revoked_tokens")[0]["n"] == 1


def test_the_bootstrap_pin_opens_control_only_while_no_mcc_account_exists():
    empty(client)
    r = client.post("/api/control/session", json={"pin": "4242"})
    assert r.status_code == 200 and r.json()["roles"] == ["bootstrap"]
    assert client.post("/api/control/session", json={"pin": "1111"}).status_code == 401
    ctl = {"X-Canary-Control": r.json()["token"]}
    assert client.get("/api/control/overview", headers=ctl).status_code == 200
    form = demo_form_after_empty = None  # noqa: F841
    reg = register_on_empty()
    assert reg.status_code == 200, reg.text
    assert client.post("/api/control/session", json={"pin": "4242"}).status_code == 401  # closed: an MCC account exists
    assert client.get("/api/control/overview", headers=ctl).status_code == 401  # and so is a bootstrap token from before
    assert client.post("/api/control/session", json={"account_id": "g-mcc1", "pin": "4242"}).status_code == 200
    assert client.post("/api/control/session", json={"account_id": "g-fs1", "pin": "1961"}).status_code == 401  # a flight surgeon is not an MCC account


# ---------------------------------------------------------------- lockout
def test_wrong_pins_pause_the_account_and_the_address_and_the_wait_grows():
    auth.clear_failures()
    for _ in range(5):
        assert client.post("/api/crew/h/session", json={"pin": "0000"}).status_code == 401
    r = client.post("/api/crew/h/session", json={"pin": "1001"})
    assert r.status_code == 429 and "1 min" in r.json()["detail"]  # even the right PIN waits
    row = db.q("SELECT * FROM auth_failures WHERE key='acct:h'")[0]
    assert row["count"] == 5 and 50 < row["until"] - row["last"] <= 60
    # a pause already served: five more wrong PINs and the wait is five minutes, then fifteen, then an hour
    for n, minutes in ((10, 5), (15, 15), (20, 60), (25, 60)):
        db.x("UPDATE auth_failures SET until=0")  # the wait is over
        for _ in range(5):
            client.post("/api/crew/h/session", json={"pin": "0000"})
        row = db.q("SELECT * FROM auth_failures WHERE key='acct:h'")[0]
        assert row["count"] == n and round((row["until"] - row["last"]) / 60) == minutes, n
    auth.clear_failures()


def test_the_lockout_survives_a_restart_and_a_right_pin_forgives_the_account():
    auth.clear_failures()
    for _ in range(5):
        client.post("/api/crew/a/session", json={"pin": "0000"})
    importlib.reload(auth)  # the process starts over: nothing is kept in memory
    assert auth.locked("acct:a") and auth.remaining("acct:a") > 0
    assert client.post("/api/crew/a/session", json={"pin": "1003"}).status_code == 429
    elsewhere = client_from("10.1.1.1")
    assert elsewhere.post("/api/crew/a/session", json={"pin": "1003"}).status_code == 429  # the account is paused from every address
    auth.clear_failures()
    for _ in range(3):
        client.post("/api/crew/a/session", json={"pin": "0000"})
    assert client.post("/api/crew/a/session", json={"pin": "1003"}).status_code == 200
    assert not db.q("SELECT 1 FROM auth_failures WHERE key='acct:a'")  # the account's count starts over


def test_a_paused_account_tells_the_crew_medical_officer_without_the_pin():
    auth.clear_failures()
    for _ in range(5):
        client.post("/api/crew/t/session", json={"pin": "0000"})
    msgs = [m for m in client.get("/api/messages", headers=crew_headers_after_clear("k")).json() if m["kind"] == "security"]
    assert len(msgs) == 1 and msgs[0]["recipient"] == "k" and msgs[0]["sender"] == "canary"
    assert "Tomás Rivera" in msgs[0]["text"] and "paused for 1 min" in msgs[0]["text"] and "0000" not in msgs[0]["text"] and "1004" not in msgs[0]["text"]
    assert not [m for m in client.get("/api/messages", headers=crew_headers_after_clear("a")).json() if m["kind"] == "security"]  # private to the officer


def crew_headers_after_clear(cid):
    auth.clear_failures()
    return crew_headers(client, cid)


def test_a_demo_start_over_forgives_wrong_pins_but_a_flight_system_never_does(monkeypatch):
    from canary.main import _start_over
    auth.clear_failures()
    auth.fail("acct:h")
    _start_over(None)
    assert not db.q("SELECT 1 FROM auth_failures")  # demo mode: forgiven
    auth.fail("acct:h")
    monkeypatch.setattr(settings, "mode", "flight")
    _start_over(None)
    assert db.q("SELECT 1 FROM auth_failures")  # flight mode: kept
    auth.clear_failures()


# ---------------------------------------------------------------- the mission is locked once registered
def test_a_registered_mission_cannot_be_registered_again():
    form = demo_form()
    body = {"crew": form["crew"], "ground": form["ground"], "mission": form["mission"]}
    r = client.post("/api/control/register", headers=control_headers(client), json=body)
    assert r.status_code == 409 and r.json() == {"detail": "The mission is registered and locked."}
    locked = "The mission is registered and locked."
    ctl = control_headers(client)
    assert client.post("/api/control/demo-data", headers=ctl).json()["detail"] == locked
    assert client.post("/api/setup", json={"name": "x", "legs": [{"location": "earth", "start": 0, "end": 5}]}, headers=ctl).json()["detail"] == locked
    assert client.put("/api/plan", json={"name": "x", "legs": [{"location": "earth", "start": 0, "end": 5}]}, headers=ctl).json()["detail"] == locked
    assert client.post("/api/plan/preset", json={"preset": "iss"}, headers=ctl).json()["detail"] == locked
    assert client.get("/api/plan").json()["preset"] == "mars"  # nothing changed
    assert client.get("/api/catalog").json()["crew"][0]["name"] == "Helena Duarte"
    # the only way to start over is the demo reset
    assert client.post("/api/demo/reset", headers=ctl).status_code == 200


def test_there_is_no_clear_route_any_more():
    for method in ("post", "get", "put", "delete"):
        assert getattr(client, method)("/api/control/clear", headers=control_headers(client)).status_code in (404, 405)
    assert client.get("/api/catalog").json()["crew"] != []


def test_importing_a_file_that_defines_the_mission_is_refused_and_nothing_is_written():
    snap = (data.count_observations(), db.q("SELECT COUNT(*) n FROM goal_log")[0]["n"], db.q("SELECT COUNT(*) n FROM scenes")[0]["n"],
            data.version(), db.get_setting("registry"), db.get_setting("plan"))
    shut = ("crew.csv", "mission.csv", "legs.csv", "scenes.csv", "ground.csv")
    for name in shut:
        r = client.post("/api/control/import", headers=control_headers(client), files=[("file", (name, (MARS / name).read_bytes(), "text/csv"))])
        assert r.status_code == 422, name
        assert r.json()["errors"] == [{"field": "file", "message": f"{name} cannot change a registered mission"}] and r.json()["accepted"] == {}
    # one error per file, and the readings sent with them are not written either
    parts = [("file", (n, (MARS / n).read_bytes(), "text/csv")) for n in ("crew.csv", "ground.csv", "observations.csv")]
    r = client.post("/api/control/import", headers=control_headers(client), files=parts)
    assert r.status_code == 422 and [e["message"] for e in r.json()["errors"]] == ["crew.csv cannot change a registered mission", "ground.csv cannot change a registered mission"]
    assert snap == (data.count_observations(), db.q("SELECT COUNT(*) n FROM goal_log")[0]["n"], db.q("SELECT COUNT(*) n FROM scenes")[0]["n"],
                    data.version(), db.get_setting("registry"), db.get_setting("plan"))


def test_readings_goal_history_and_space_events_can_still_be_imported():
    extra = b"crew_id,day,indicator,value,unit,measured_at\nh,5,sleep,7.1,h,2035-06-06T09:00:00Z\n"
    n = data.count_observations()
    r = client.post("/api/control/import", headers=control_headers(client), files=[("file", ("observations.csv", extra, "text/csv"))])
    assert r.status_code == 200, r.text
    assert r.json()["accepted"]["observations"] == 1 and data.count_observations() == n + 1
    assert data.loaded_package()["name"] == "odyssey1-mars"  # the readings did not rename the loaded package
    for name in ("goal_log.csv", "space_events.csv"):
        r = client.post("/api/control/import", headers=control_headers(client), files=[("file", (name, (MARS / name).read_bytes(), "text/csv"))])
        assert r.status_code == 200, (name, r.text)


def test_a_bundled_package_by_name_is_refused_once_registered():
    r = client.post("/api/control/import", headers=control_headers(client), json={"package": "odyssey1-moon"})
    assert r.status_code == 409 and r.json()["detail"] == "The mission is registered and locked."
    assert client.get("/api/plan").json()["preset"] == "mars"


# ---------------------------------------------------------------- the dose waiver
def test_the_mars_plan_needs_the_waiver_and_the_waiver_is_recorded():
    form = demo_form()
    empty(client)
    ctl = control_headers(client)
    body = {"crew": form["crew"], "ground": form["ground"], "mission": {**form["mission"], "dose_waiver": False}}
    r = client.post("/api/control/register", headers=ctl, json=body)
    assert r.status_code == 422
    assert r.json()["detail"] == [{"field": "mission.dose_waiver", "message": "Projected career dose exceeds the NASA limit (NASA-STD-3001 Vol 1, 4.2.10); a risk-acceptance waiver is required."}]
    assert not registry.registered()  # nothing was saved
    r = client.post("/api/control/register", headers=ctl, json={**body, "mission": {**body["mission"], "dose_waiver": True}})
    assert r.status_code == 200, r.text
    w = r.json()["waiver"]
    assert w["accepted"] is True and w["by"] == "bootstrap" and w["at"].endswith("Z")
    career = r.json()["career"]
    assert career["limit_msv"] == 600 and career["projected_max_msv"] > 600 and career["mission_msv"] > 600
    assert registry.mission_info()["waiver"] == w


def test_a_short_plan_does_not_need_the_waiver_and_records_none():
    form = demo_form()
    empty(client)
    r = client.post("/api/control/register", headers=control_headers(client),
                    json={"crew": form["crew"], "ground": form["ground"], "mission": {**form["mission"], "preset": "moon", "dose_waiver": False}})
    assert r.status_code == 200, r.text
    assert r.json()["waiver"] is None and r.json()["career"]["projected_max_msv"] < 600


def test_a_large_earlier_dose_alone_can_need_the_waiver():
    form = demo_form()
    crew = [dict(p) for p in form["crew"]]
    crew[0]["prior_dose_msv"] = 580  # 580 + the 46.9 mSv of the lunar plan
    empty(client)
    r = client.post("/api/control/register", headers=control_headers(client),
                    json={"crew": crew, "ground": form["ground"], "mission": {**form["mission"], "preset": "moon", "dose_waiver": False}})
    assert r.status_code == 422 and r.json()["detail"][0]["field"] == "mission.dose_waiver"


def test_the_demo_package_carries_the_waiver_accepted_by_the_demo_mcc_account():
    w = registry.mission_info()["waiver"]
    assert w["accepted"] is True and w["by"] == "g-mcc1"
    assert client.get("/api/control/overview", headers=control_headers(client)).json()["waiver"] == w
    assert client.get("/api/control/overview", headers=control_headers(client)).json()["career"]["projected_max_msv"] > 600


def test_the_register_options_do_not_depend_on_the_demo():
    j = client.get("/api/control/register-options", headers=control_headers(client)).json()
    assert j["career_limit_msv"] == 600 and j["mission_dose_msv"]["mars"]["rover"] > 600 and j["mission_dose_msv"]["moon"]["plain"] < 100


# ---------------------------------------------------------------- roles and ids at registration
def test_one_crew_medical_officer_and_ground_accounts_are_checked():
    form = demo_form()
    empty(client)
    ctl = control_headers(client)
    mission = {**form["mission"]}
    crew = [dict(p) for p in form["crew"]]
    crew[2]["cmo"] = True  # Kenji already is one
    r = client.post("/api/control/register", headers=ctl, json={"crew": crew, "ground": form["ground"], "mission": mission})
    assert r.status_code == 422 and r.json()["detail"][0]["field"] == "crew.2.cmo"
    crew = [dict(p) for p in form["crew"]]
    crew[1]["cmo"] = False  # nobody is the officer: allowed
    r = client.post("/api/control/register", headers=ctl, json={"crew": crew, "ground": form["ground"], "mission": mission})
    assert r.status_code == 200 and registry.cmo_id() is None
    assert client.post("/api/medical/session", json={"account_id": "k", "pin": "1002"}).status_code == 401  # no cmo: that console has no crew user
    assert client.post("/api/medical/session", json={"account_id": "g-fs1", "pin": "1961"}).status_code == 200


def test_registered_ids_are_generated_prefixed_and_never_collide():
    form = demo_form()
    crew = [{k: v for k, v in p.items() if k != "seat"} for p in form["crew"]]
    ground = [{k: v for k, v in g.items() if k != "id"} for g in form["ground"]]
    empty(client)
    r = client.post("/api/control/register", headers=control_headers(client), json={"crew": crew, "ground": ground, "mission": form["mission"]})
    assert r.status_code == 200, r.text
    pub = client.get("/api/accounts/public").json()
    ids = [c["id"] for c in pub["crew"]] + [g["id"] for g in pub["ground"]]
    assert all(i.startswith("c-") for i in ids[:4]) and all(i.startswith("g-") for i in ids[4:]) and len(set(ids)) == 6
    assert registry.cmo_id() == pub["crew"][1]["id"]  # Kenji, from the role text of the form
    # a crew id may not look like a ground id
    empty(client)
    r = client.post("/api/control/register", headers=control_headers(client),
                    json={"crew": [{**form["crew"][0], "seat": "g-sneaky"}], "ground": form["ground"], "mission": form["mission"]})
    assert r.status_code == 422 and r.json()["detail"][0]["field"] == "crew.0.seat"


# ---------------------------------------------------------------- flight mode
def test_flight_mode_has_no_demo_endpoints(monkeypatch):
    ctl = control_headers(client)
    monkeypatch.setattr(settings, "mode", "flight")
    for method, path, body in (("post", "/api/demo/reset", None), ("put", "/api/mission", {"day": 3}), ("put", "/api/control/clock", {"real": True}),
                               ("post", "/api/control/demo-data", None), ("get", "/api/control/demo", None), ("post", "/api/setup", {"name": "x", "legs": []}),
                               ("put", "/api/plan", {"name": "x", "legs": []}), ("post", "/api/plan/preset", {"preset": "iss"})):
        for h in (ctl, {}):  # the route does not exist, with or without a token
            r = client.request(method.upper(), path, json=body, headers=h) if body is not None else client.request(method.upper(), path, headers=h)
            assert r.status_code == 404, (path, r.status_code)
    assert client.get("/api/scenes").json() == []
    assert client.get("/api/health").json()["mode"] == "flight" and client.get("/api/catalog").json()["mode"] == "flight"
    assert client.get("/api/catalog").json()["crew"]  # the registered mission is still there
    assert client.get("/api/control/register-options", headers=ctl).status_code == 200  # what a real registration needs stays


def test_demo_mode_is_reported_and_the_demo_routes_work():
    assert client.get("/api/health").json()["mode"] == "demo" and client.get("/api/catalog").json()["mode"] == "demo"
    assert len(client.get("/api/scenes").json()) == 6


def test_flight_mode_refuses_to_start_without_its_secrets(monkeypatch):
    monkeypatch.setattr(settings, "mode", "flight")
    monkeypatch.delenv("CANARY_TOKEN_SECRET", raising=False)
    with pytest.raises(RuntimeError, match="CANARY_TOKEN_SECRET"):
        config.check_mode()
    monkeypatch.setenv("CANARY_TOKEN_SECRET", "x" * 32)
    monkeypatch.setattr(settings, "control_bootstrap_pin", "")
    with pytest.raises(RuntimeError, match="CANARY_CONTROL_BOOTSTRAP_PIN"):
        config.check_mode()
    monkeypatch.setattr(settings, "control_bootstrap_pin", "7391")
    config.check_mode()  # both set: fine
    monkeypatch.setattr(settings, "mode", "demo")
    config.check_mode()


def test_an_unknown_mode_is_refused():
    with pytest.raises(ValueError, match="CANARY_MODE"):
        config._mode("test")
    assert config._mode("flight") == "flight" and config._mode("demo") == "demo"


def test_flight_mode_loads_nothing_on_its_own(monkeypatch):
    monkeypatch.setattr(settings, "mode", "flight")
    empty_db = os.path.join(tempfile.mkdtemp(), "flight.db")
    old = db._conn
    try:
        db.connect(empty_db)
        assert data.bootstrap() is None and data.count_observations() == 0 and registry.stored() is None
        monkeypatch.setattr(settings, "mode", "demo")
        assert data.bootstrap() is not None  # the same empty database in demo mode loads the package
    finally:
        db._conn = old
        db._forget()
        db._bump_epoch()


def test_flight_mode_has_no_default_crew_pins_and_no_demo_form_pins(monkeypatch):
    monkeypatch.setattr(settings, "crew_pins", {"zz": "1111"})  # the fallback of an id with no stored PIN (a demo convenience)
    assert auth.check_pin("zz", "1111") is True
    assert auth.check_pin("g-zz", "1111") is False  # a ground id has no fallback at all
    monkeypatch.setattr(settings, "mode", "flight")
    form = data.demo_form()
    assert all("pin" not in p for p in form["crew"]) and all("pin" not in g for g in form["ground"])


# ---------------------------------------------------------------- a preset reload never touches other readings
def test_reloading_a_preset_keeps_readings_that_did_not_come_from_the_package(monkeypatch):
    mine = {"crew_id": "h", "indicator": "sleep", "value": 7.7, "unit": "h", "measured_at": "2035-06-03T09:00:00Z", "source": "device:band"}
    assert client.post("/api/observations", headers={"X-Canary-Key": KEY}, json={"rows": [mine]}).json()["accepted"] == 1
    n_mine = db.q("SELECT COUNT(*) n FROM observations WHERE package IS NULL")[0]["n"]
    n_package = db.q("SELECT COUNT(*) n FROM observations WHERE package='odyssey1-mars'")[0]["n"]
    assert n_mine == 1 and n_package > 50000
    assert data.reload_for_preset("moon") is True
    assert db.q("SELECT COUNT(*) n FROM observations WHERE package IS NULL")[0]["n"] == 1  # still there
    assert db.q("SELECT value FROM observations WHERE package IS NULL")[0]["value"] == 7.7
    assert db.q("SELECT COUNT(*) n FROM observations WHERE package='odyssey1-mars'")[0]["n"] == 0
    assert db.q("SELECT COUNT(*) n FROM observations WHERE package='odyssey1-moon'")[0]["n"] > 0
    assert data.loaded_package()["preset"] == "moon" and plan.get()["preset"] == "mars"  # (the plan itself is the route's business)


def test_package_readings_are_tagged_with_the_package_name():
    assert db.q("SELECT DISTINCT package FROM observations") == [{"package": "odyssey1-mars"}]


def test_a_database_made_before_the_package_column_is_migrated(tmp_path):
    import sqlite3
    path = str(tmp_path / "old.db")
    raw = sqlite3.connect(path)
    raw.execute("CREATE TABLE observations (id INTEGER PRIMARY KEY AUTOINCREMENT, crew_id TEXT NOT NULL, day INTEGER NOT NULL, indicator TEXT NOT NULL, "
                "value REAL NOT NULL, unit TEXT NOT NULL, origin TEXT NOT NULL, method TEXT NOT NULL, source TEXT NOT NULL, note TEXT NOT NULL, "
                "measured_at TEXT NOT NULL, received_at TEXT NOT NULL, UNIQUE (crew_id, indicator, measured_at, source))")
    raw.commit()
    raw.close()
    old = db._conn
    try:
        db.connect(path)
        assert "package" in [r["name"] for r in db.q("PRAGMA table_info(observations)")]
        assert db.q("SELECT name FROM sqlite_master WHERE name IN ('revoked_tokens','auth_failures') ORDER BY name") == [{"name": "auth_failures"}, {"name": "revoked_tokens"}]
    finally:
        db._conn = old
        db._forget()
        db._bump_epoch()
