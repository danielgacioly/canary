"""Phase 5: the crew is whoever is registered, one to six people, and nothing about them is borrowed from a demo character.

- Registering 1, 3 and 6 people through Mission Control: every GET answers 200 for every role, every registered id signs in
  with its own PIN, the demo PINs open nothing, and no response carries a `base`.
- The rules of the form: 1 to 6 people, ids and PINs unique, errors on `crew.N.field`.
- The crew's weekly exercise target grows with the crew (6 sessions each: 24 for four).
- A person who starts with no pre-flight data is learning their normal; they are never compared with a seed.
"""
import datetime as dt
import os
import re
import tempfile

os.environ["CANARY_DB"] = os.path.join(tempfile.mkdtemp(), "size.db")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from canary import auth, db  # noqa: E402
from canary.config import settings  # noqa: E402
from canary.domain import catalog, data, goals, health, privacy, registry  # noqa: E402
from canary.main import app  # noqa: E402
from tests.golden_capture import reset_demo  # noqa: E402
from tests.support import GROUND, control_headers, crew_headers, empty, fresh as fresh_demo, medical_headers  # noqa: E402,F401
from tests import golden_capture as gc  # noqa: E402

client = TestClient(app)
KEY = "test-ingest-key-not-a-secret"
LAUNCH = "2036-03-01"
NAMES = ["Ines Almeida", "Jonas Berg", "Kofi Mensah", "Lena Vogel", "Mateo Ruiz", "Noor Haddad"]
ROLES = ["Commander", "Crew medical officer", "Pilot", "Engineer", "Geologist", "Biologist"]


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    monkeypatch.setattr(settings, "ingest_key", KEY)
    import canary.main as _main, datetime as _dt0
    monkeypatch.setattr(_main, "_ingest_now", lambda: _dt0.datetime(2100, 1, 1))  # these readings are in the past; the future check has its own tests
    monkeypatch.setattr(settings, "mission_package", "")
    monkeypatch.setattr(settings, "live_space_weather", False)
    assert reset_demo(client).status_code == 200
    yield
    monkeypatch.setattr(settings, "mission_package", "odyssey1-mars")
    reset_demo(client)


def ctl():
    return control_headers(client)


def medical():
    return {"Authorization": "Bearer " + gc.medical_token(client, "g-fs1")}


def person(i, **over):
    p = {"seat": f"s{i + 1}", "name": NAMES[i], "role": ROLES[i], "home": "Somewhere", "pin": f"{3001 + i}", "dob": f"{1985 + i}-04-1{i + 1}",
         "sex": "Female" if i % 2 == 0 else "Male", "nationality": "Portuguese", "languages": ["Portuguese"], "agency": "Test agency",
         "flights": 0, "days_in_space": 0, "height_cm": 170, "weight_kg": 68, "blood_type": "A+", "skin_type": "III",
         "handedness": "Right", "eva": "surface"}
    p.update(over)
    return p


MISSION = {"callsign": "Test 1", "name": "Test mission", "launch_date": LAUNCH, "preset": "mars", "dose_waiver": True}


def register(n, **over):
    return client.post("/api/control/register", headers=ctl(), json={"crew": [person(i) for i in range(n)], "mission": MISSION, "ground": GROUND, **over})


def ids():
    return [c["id"] for c in catalog.CREW]


def post_obs(rows):
    r = client.post("/api/observations", headers={"X-Canary-Key": KEY}, json={"rows": rows})
    assert r.status_code == 200, r.text
    return r.json()


def reading(cid, ind, d, v):
    when = dt.datetime(2036, 3, 1, 9, 30) + dt.timedelta(days=d)
    return {"crew_id": cid, "indicator": ind, "value": v, "unit": catalog.ACCEPT[ind]["units"][0],
            "measured_at": when.strftime("%Y-%m-%dT%H:%M:%SZ"), "source": "test:band", "origin": "device"}


def go(day):
    assert client.put("/api/mission", json={"day": day}, headers=control_headers(client)).status_code == 200


def every_get(crew):
    """Every GET of the golden capture for this crew, as every role. Each must answer 200."""
    out = {}
    tok = {c: {"Authorization": "Bearer " + gc._token(client, f"/api/crew/{c}/session", PINS[c])} for c in crew}
    med = medical()
    for p in gc.PUBLIC_PATHS:
        out[p] = gc._get(client, p, tok[crew[0]] if p in gc.SIGNED_IN_PATHS else None)
    for c in crew:
        for t in gc.CREW_PATHS:
            p = t.format(c=c)
            out[f"{p} [as {c}]"] = gc._get(client, p, tok[c])
        for t in gc.MEDICAL_CREW_PATHS:
            p = t.format(c=c)
            out[f"{p} [as medical]"] = gc._get(client, p, med)
    for p in gc.MEDICAL_PATHS:
        out[f"{p} [as medical]"] = gc._get(client, p, med)
    for p in gc.CONTROL_PATHS:
        out[f"{p} [as control]"] = gc._get(client, p, ctl())
    return out


PINS = {f"s{i + 1}": f"{3001 + i}" for i in range(6)}


def keys_of(x, found=None):
    found = set() if found is None else found
    if isinstance(x, dict):
        for k, v in x.items():
            found.add(k)
            keys_of(v, found)
    elif isinstance(x, list):
        for v in x:
            keys_of(v, found)
    return found


@pytest.mark.parametrize("n", [1, 3, 6])
def test_every_endpoint_answers_for_a_crew_of_n(n):
    r = register(n)
    assert r.status_code == 200, r.text
    assert ids() == [f"s{i + 1}" for i in range(n)] and len(catalog.CREW) == n
    rows = []
    for c in ids()[:2]:  # a few readings for some of them; the others have none
        rows += [reading(c, "sleep", d, 7.0 + 0.1 * (d % 3)) for d in range(-12, 3)] + [reading(c, "hr", d, 60 + d % 3) for d in range(-12, 3)]
    post_obs(rows)
    go(5)
    out = every_get(ids())
    assert len(out["/api/crew/overview"]["people"]) == n and len(out["/api/leaderboard"]["rows"]) == n
    assert len(out["/api/mission/overview"]["crew"]) == n and len(out["/api/control/overview [as control]"]["people"]) == n
    assert "base" not in keys_of(out)
    # nothing seeded by a demo character: ages come from the record and the launch date
    assert [c["age"] for c in client.get("/api/catalog", headers=ctl()).json()["crew"]] == [int(LAUNCH[:4]) - (1985 + i) - 1 for i in range(n)]  # the age is for signed-in people (SEC-06)


@pytest.mark.parametrize("n", [1, 3, 6])
def test_every_registered_id_signs_in_with_its_own_pin_and_the_demo_pins_open_nothing(n):
    assert register(n).status_code == 200
    for c in ids():
        auth.clear_failures()  # these wrong PINs come from one address: do not let them pause the next sign-in
        assert client.post(f"/api/crew/{c}/session", json={"pin": PINS[c]}).status_code == 200
        assert client.post(f"/api/crew/{c}/session", json={"pin": "9999"}).status_code == 401
    auth.clear_failures()
    for demo_id, demo_pin in (("h", "1001"), ("k", "1002"), ("a", "1003"), ("t", "1004"), ("s1", "1001")):
        assert client.post(f"/api/crew/{demo_id}/session", json={"pin": demo_pin}).status_code in (401, 404), (demo_id, demo_pin)
    # every PIN is stored hashed
    stored = db.get_setting("pins")
    assert sorted(stored) == sorted(ids() + ["g-fs1", "g-mcc1"]) and all(set(v) == {"salt", "hash"} for v in stored.values())


def test_a_crew_that_reuses_the_demo_ids_does_not_inherit_the_demo_pins():
    form = [person(i, seat=s, pin=f"{4001 + i}") for i, s in enumerate(["h", "k"])]
    r = client.post("/api/control/register", headers=ctl(), json={"crew": form, "mission": MISSION, "ground": GROUND})
    assert r.status_code == 200 and ids() == ["h", "k"]
    assert client.post("/api/crew/h/session", json={"pin": "1001"}).status_code == 401
    assert client.post("/api/crew/h/session", json={"pin": "4001"}).status_code == 200


def test_ids_are_stable_when_the_same_people_are_registered_again():
    assert register(3).status_code == 200
    first = ids()
    empty(client)
    assert register(3).status_code == 200
    assert ids() == first == ["s1", "s2", "s3"]
    empty(client)
    form = [person(0, seat="s2", pin="5001"), person(1, seat=None, pin="5002"), person(2, seat=None, pin="5003")]  # an explicit s2 is kept; the others get a generated id
    r = client.post("/api/control/register", headers=ctl(), json={"crew": form, "mission": MISSION, "ground": GROUND})
    assert r.status_code == 200
    assert ids()[0] == "s2" and all(re.fullmatch(r"c-[0-9a-f]{6}", i) for i in ids()[1:]) and len(set(ids())) == 3  # generated ids are never s1..s6 and never repeat


def test_registering_replaces_the_crew_and_the_pins_of_the_one_before():
    assert register(4).status_code == 200
    empty(client)
    assert register(2).status_code == 200
    assert ids() == ["s1", "s2"] and sorted(db.get_setting("pins")) == ["g-fs1", "g-mcc1", "s1", "s2"]
    assert client.post("/api/crew/s3/session", json={"pin": PINS["s3"]}).status_code == 404


def test_duplicate_pin_and_duplicate_id_are_refused_on_the_field():
    form = [person(0, pin="7001"), person(1, pin="7001"), person(2, pin="7003")]
    r = client.post("/api/control/register", headers=ctl(), json={"crew": form, "mission": MISSION, "ground": GROUND})
    assert r.status_code == 422
    assert [(e["field"], "already used by person 1" in e["message"]) for e in r.json()["detail"]] == [("crew.1.pin", True)]
    form = [person(0, seat="x1", pin="7001"), person(1, seat="x1", pin="7002")]
    r = client.post("/api/control/register", headers=ctl(), json={"crew": form, "mission": MISSION, "ground": GROUND})
    assert r.status_code == 422 and [e["field"] for e in r.json()["detail"]] == ["crew.1.seat"] and "used by person 1" in r.json()["detail"][0]["message"]
    form = [person(0, seat="cabin")]
    r = client.post("/api/control/register", headers=ctl(), json={"crew": form, "mission": MISSION, "ground": GROUND})
    assert r.status_code == 422 and r.json()["detail"][0]["field"] == "crew.0.seat"
    assert catalog.CREW == []  # a refused registration writes nothing


def test_nobody_and_seven_people_are_refused_on_the_crew_field():
    for n in (0, 7):
        form = [person(i % 6, pin=f"{6001 + i}", seat=f"p{i}") for i in range(n)]
        r = client.post("/api/control/register", headers=ctl(), json={"crew": form, "mission": MISSION, "ground": GROUND})
        assert r.status_code == 422, n
        assert r.json()["detail"][0]["field"] == "crew" and "between 1 and 6" in r.json()["detail"][0]["message"]
    assert catalog.CREW == []
    r = client.post("/api/control/register", headers=ctl(), json={"crew": [{**person(0), "name": ""}], "mission": MISSION, "ground": GROUND})
    assert r.status_code == 422 and r.json()["detail"][0]["field"] == "crew.0.name"
    assert registry.normalize([person(0)])[0][0]["seat"] == "s1"
    assert re.fullmatch(r"c-[0-9a-f]{6}", registry.normalize([person(0, seat=None)])[0][0]["seat"])
    with pytest.raises(ValueError):
        registry.normalize([person(i % 6, pin=f"{6001 + i}", seat=f"p{i}") for i in range(7)])
    with pytest.raises(ValueError):
        registry.normalize([person(0, pin="1234"), person(1, pin="1234")])


@pytest.mark.parametrize("n,target", [(1, 6), (2, 12), (3, 18), (4, 24), (6, 36)])
def test_the_crew_exercise_target_grows_with_the_crew(n, target):
    assert register(n).status_code == 200
    go(5)
    team = client.get("/api/leaderboard", headers=ctl()).json()["team"]
    ex = next(t for t in team if t["id"] == "team_exercise")
    assert ex["target"] == target and ex["title"] == f"Crew exercise: {target} sessions this week" and ex["pct"] == 0
    mind = next(t for t in team if t["id"] == "team_mind")
    assert mind["target"] == 5 * n and "per_person" not in mind
    assert goals.crew_quorum(n) == {1: 1, 2: 2, 3: 3, 4: 3, 6: 5}.get(n, 3)
    assert client.get("/api/crew/overview", headers=ctl()).json()["crew_streak"] == 0


def test_the_demo_crew_keeps_its_old_targets_and_quorum():
    assert goals.team_target(next(t for t in catalog.TEAM_GOALS if t["id"] == "team_exercise"), 4) == 24
    assert goals.crew_quorum(4) == 3


def test_a_person_without_preflight_data_is_learning_and_never_compared_with_a_seed():
    assert register(3).status_code == 200
    post_obs([reading("s2", "sleep", d, 5.0) for d in range(1, 4)] + [reading("s2", "hr", d, 90) for d in range(1, 4)])
    go(4)
    b = health.baselines("s2")
    assert all(v["mean"] is None and v["from"] in ("learning", "early_flight") for v in b.values()) or all(v["mean"] is None for v in b.values())
    snap = client.get("/api/crew/s2", headers={"Authorization": "Bearer " + gc._token(client, "/api/crew/s2/session", PINS["s2"])}).json()
    sleep = snap["indicators"]["sleep"]
    assert sleep["baseline"] is None and sleep["z"] is None and sleep["learning"] is True
    assert snap["indicators"]["gluc"]["value"] is None and snap["indicators"]["gluc"]["status"] == "no_data"
    assert "base" not in keys_of(snap)
    assert client.get("/api/crew/s3", headers={"Authorization": "Bearer " + gc._token(client, "/api/crew/s3/session", PINS["s3"])}).json()["no_data"] is True


def test_a_crew_without_a_medical_officer_still_works():
    form = [person(0, role="Commander"), person(1, role="Pilot", pin="3002")]
    assert client.post("/api/control/register", headers=ctl(), json={"crew": form, "mission": MISSION, "ground": GROUND}).status_code == 200
    assert privacy.medical_officer() is None
    assert privacy.alerts_to("s2") == "s1" and privacy.alerts_to("s1") == "s2"  # the commander, else the other person
    out = every_get(ids())
    assert "no medical officer" in out["/api/crew/s1 [as s1]"]["care_by"]
    empty(client)
    solo = [person(0, role="Astronaut")]
    assert client.post("/api/control/register", headers=ctl(), json={"crew": solo, "mission": MISSION, "ground": GROUND}).status_code == 200
    assert privacy.alerts_to("s1") == "s1" and privacy.substitute() == "s1"
    every_get(ids())


def test_the_demo_form_is_the_bundled_packages_crew():
    r = client.get("/api/control/demo", headers=ctl())
    assert r.status_code == 200
    j = r.json()
    assert [p["seat"] for p in j["crew"]] == ["h", "k", "a", "t"] and [p["pin"] for p in j["crew"]] == ["1001", "1002", "1003", "1004"]
    assert j["mission"]["callsign"] == "Odyssey 1" and all(p["prior_dose_msv"] is None for p in j["crew"])
    assert "base" not in keys_of(j) and "cbc_subject" not in keys_of(j)
    r = client.post("/api/control/register", headers=ctl(), json={"crew": j["crew"], "mission": j["mission"], "ground": j["ground"]})
    assert r.status_code == 200 and ids() == ["h", "k", "a", "t"]


def test_a_registered_person_has_blood_only_from_their_own_observations():
    assert register(2).status_code == 200
    go(5)
    b = client.get("/api/crew/s1", headers={"Authorization": "Bearer " + gc._token(client, "/api/crew/s1/session", PINS["s1"])}).json()["blood"]
    assert b["analytes"] == {} and b["timepoints"] == [] and b["subject"] is None and b["origin"] is None
    post_obs([{**reading("s1", "lym", -20, 2100), "origin": "lab", "method": "blood", "source": "lab:test", "note": "L-20 draw"}])
    b = client.get("/api/crew/s1", headers={"Authorization": "Bearer " + gc._token(client, "/api/crew/s1/session", PINS["s1"])}).json()["blood"]
    assert b["timepoints"] == ["L-20"] and b["lymphocytes"] == [2100.0] and b["analytes"]["lym"]["status"] == ["in"]


def test_a_person_registered_without_a_sex_has_no_sex_specific_range_and_nothing_breaks():
    form = [person(0, sex=""), person(1, sex="Other", pin="3002")]
    r = client.post("/api/control/register", headers=ctl(), json={"crew": form, "mission": MISSION, "ground": GROUND})
    assert r.status_code == 200 and [c["sex"] for c in catalog.CREW] == [None, None]
    post_obs([reading("s1", "grip", d, 20.0) for d in range(-12, 3)])
    go(5)
    out = every_get(ids())
    assert out["/api/crew/s1 [as s1]"]["indicators"]["grip"]["population"]["low"] == 16  # DATA-08: no sex takes the widest range of the two (F 16, M 27)
