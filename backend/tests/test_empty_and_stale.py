"""Phase 4: nothing breaks without data, and an old reading never passes as a current one.

- An empty system (no package, or a package whose observations were removed) answers every GET with 200, every person
  has no data, and no alert or notice comes out of it.
- A person who is still learning their normal is compared with nothing of their own: no z, no alert; a safety limit of
  the population range still speaks.
- A reading older than the indicator's `max_age` is stale: it is not today's value.
"""
import os
import tempfile

os.environ["CANARY_DB"] = os.path.join(tempfile.mkdtemp(), "empty.db")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from canary import db  # noqa: E402
from canary.config import settings  # noqa: E402
from canary.domain import catalog, data, health, mission, plan, registry, risk, telemetry  # noqa: E402
from canary.main import app  # noqa: E402
from tests.golden_capture import reset_demo  # noqa: E402
from tests.support import GROUND, add_ground, control_headers, crew_headers, empty, fresh as fresh_demo, medical_headers  # noqa: E402,F401
from tests import golden_capture as gc  # noqa: E402

client = TestClient(app)


def reset(monkeypatch, package):
    monkeypatch.setattr(settings, "mission_package", package)
    monkeypatch.setattr(settings, "live_space_weather", False)
    assert reset_demo(client).status_code == 200
    if not package:
        add_ground()  # nothing registered, but the ground accounts exist so the consoles have someone to sign in


def reset_crew(monkeypatch):
    """No data at all, but the demo crew registered through Mission Control (an empty package registers nobody)."""
    reset(monkeypatch, "")
    assert catalog.CREW == []
    form = data.demo_form()
    r = client.post("/api/control/register", headers=tokens()[2], json={"crew": form["crew"], "mission": form["mission"], "ground": form["ground"]})
    assert r.status_code == 200, r.text
    assert [c["id"] for c in catalog.CREW] == list(gc.CREW_IDS)


@pytest.fixture(autouse=True)
def restore(monkeypatch):
    monkeypatch.setattr(settings, "live_space_weather", False)
    yield
    monkeypatch.setattr(settings, "mission_package", "odyssey1-mars")
    reset_demo(client)


def day(d):
    return client.put("/api/mission", json={"day": d}, headers=control_headers(client)).json()


def add(crew_id, ind, d, value):
    """One reading on mission day d (the entry point wants a timestamp: the launch is 2035-06-01 in the demo)."""
    import datetime as dt
    unit = catalog.INDICATORS[ind]["unit"]
    when = dt.datetime(2035, 6, 1, 9, 30) + dt.timedelta(days=d)
    data.add_observations([{"crew_id": crew_id, "indicator": ind, "value": value, "unit": unit, "measured_at": when.strftime("%Y-%m-%dT%H:%M:%SZ"),
                            "source": "test:band"}])


def remove_all_observations():
    with data._transaction() as c:
        c.execute("DELETE FROM observations")


def tokens():
    crew = {c: {"Authorization": "Bearer " + gc._token(client, f"/api/crew/{c}/session", gc.PINS[c])} for c in [x["id"] for x in catalog.CREW]}
    med = {"Authorization": "Bearer " + gc.medical_token(client, "g-fs1")}
    ctl = control_headers(client)
    return crew, med, ctl


def every_get(crew=gc.CREW_IDS):
    """Every GET of the golden capture, as every role, on whatever the system holds now. Each must answer 200."""
    ch, med, ctl = tokens()
    out = {}
    for p in gc.PUBLIC_PATHS:
        out[p] = gc._get(client, p, med if p in gc.SIGNED_IN_PATHS else None)
    for c in crew:
        for t in gc.CREW_PATHS:
            p = t.format(c=c)
            out[f"{p} [as {c}]"] = gc._get(client, p, ch[c])
        for t in gc.MEDICAL_CREW_PATHS:
            p = t.format(c=c)
            out[f"{p} [as medical]"] = gc._get(client, p, med)
    for p in gc.MEDICAL_PATHS:
        out[f"{p} [as medical]"] = gc._get(client, p, med)
    for p in gc.CONTROL_PATHS:
        out[f"{p} [as control]"] = gc._get(client, p, ctl)
    return out


def check_empty(out, crew=gc.CREW_IDS):
    for c in crew:
        s = out[f"/api/crew/{c} [as {c}]"]
        assert s["no_data"] is True
        assert all(i["value"] is None and i["status"] == "no_data" and i["level"] == 0 and i["z"] is None and i["bad"] is None
                   for i in s["indicators"].values())
        assert not [a for a in s["alerts"] if not a.get("data")]  # missing data is never a health alert
        assert s["level"] == 0
        assert all(x["no_data"] for x in s["systems"].values() if x["indicators"])
        assert all(not any(v for _d, v in t if v is not None) for t in s["trends"].values())  # no line to draw
    assert db.q("SELECT COUNT(*) n FROM notices")[0]["n"] == 0


@pytest.mark.parametrize("d", [-30, 100])
def test_an_empty_system_answers_every_endpoint_for_every_role(monkeypatch, d):
    reset_crew(monkeypatch)
    assert data.count_observations() == 0 and data.events() == []
    day(d)
    check_empty(every_get())


@pytest.mark.parametrize("d", [-30, 100, 200])
def test_a_package_without_observations_is_just_as_empty(monkeypatch, d):
    reset(monkeypatch, "odyssey1-mars")
    assert data.count_observations() > 0
    remove_all_observations()
    day(d)
    out = every_get()
    check_empty(out)
    # nothing the rest of the package carries (crew, plan, goals, scenes) is lost
    assert len(out["/api/crew/overview"]["people"]) == 4 and out["/api/plan"]["legs"]


def test_no_data_does_not_hide_a_non_data_alert(monkeypatch):
    reset(monkeypatch, "odyssey1-mars")
    remove_all_observations()
    client.put("/api/mission", json={"step": 3}, headers=control_headers(client))  # the particle storm of the replay: not a thing the data says
    out = every_get()
    assert any(a["id"] == "storm" for a in out["/api/crew/h [as h]"]["alerts"])
    assert out["/api/crew/h [as h]"]["no_data"] is True


def test_a_registered_crew_with_no_measurements_is_empty_too(monkeypatch):
    """Canary Control registers the crew and loads the preset's package;
    with every reading removed the system is empty again."""
    reset(monkeypatch, "")
    ctl = tokens()[2]
    form = [{**p, "pin": str(2001 + i)} for i, p in enumerate(data.demo_form()["crew"])]
    r = client.post("/api/control/register", headers=ctl, json={"crew": form, "mission": {**data.demo_form()["mission"], "launch_date": "2036-03-01"}, "ground": data.demo_form()["ground"]})
    assert r.status_code == 200, r.text
    remove_all_observations()
    day(60)
    ch = {c["id"]: {"Authorization": "Bearer " + gc._token(client, f"/api/crew/{c['id']}/session", str(2001 + i))} for i, c in enumerate(catalog.CREW)}
    for c in catalog.CREW:
        s = gc._get(client, f"/api/crew/{c['id']}", ch[c["id"]])
        assert s["no_data"] is True and not [a for a in s["alerts"] if not a.get("data")]
    for p in gc.PUBLIC_PATHS:
        gc._get(client, p, next(iter(ch.values())) if p in gc.SIGNED_IN_PATHS else None)


def test_a_system_with_no_crew_at_all_answers_too(monkeypatch):
    reset(monkeypatch, "")
    registry.clear()
    add_ground()
    assert catalog.CREW == []
    day(10)
    _, med, ctl = tokens()
    for p in gc.PUBLIC_PATHS:
        gc._get(client, p, med if p in gc.SIGNED_IN_PATHS else None)
    for p in gc.MEDICAL_PATHS:
        gc._get(client, p, med)
    for p in gc.CONTROL_PATHS:
        gc._get(client, p, ctl)
    assert client.get("/api/crew/overview").json()["people"] == []
    assert client.get("/api/leaderboard").status_code == 200


# ---------------------------------------------------------------- learning the normal
def test_a_person_with_two_observations_is_learning_and_never_alerted(monkeypatch):
    reset_crew(monkeypatch)
    add("h", "sleep", 99, 7.6)
    add("h", "sleep", 100, 7.4)
    b = health.baselines("h")["sleep"]
    assert b == {"mean": None, "sd": None, "from": "learning", "n": 2, "need": health.MIN_PREFLIGHT, "confidence": "low"}
    ms = day(100)
    d = health.indicator("h", "sleep", ms)
    assert d["learning"] is True and d["z"] is None and d["baseline"] is None and d["bad"] is None and d["value"] == pytest.approx(7.45, abs=0.2)
    assert d["level"] == 0 and d["baseline_from"] == "learning"
    snap = client.get("/api/crew/h", headers=tokens()[0]["h"]).json()
    assert not [a for a in snap["alerts"] if a["id"] == "ind_sleep"]
    assert db.q("SELECT COUNT(*) n FROM notices")[0]["n"] == 0
    assert not any(v["from"] == "catalog" for v in health.baselines("h").values())  # never a seed


def test_after_enough_preflight_readings_the_baseline_is_the_persons_own(monkeypatch):
    reset_crew(monkeypatch)
    for i, v in enumerate([6.8, 7.0, 7.2, 6.9, 7.1]):
        add("h", "sleep", -20 + i, v)
    b = health.baselines("h")["sleep"]
    assert b["from"] == "preflight" and b["n"] == 5 and b["mean"] == 7.0 and b["sd"] >= catalog.INDICATORS["sleep"]["sd"]
    ms = {**day(100), "day": 50, "location": plan.location_at(50), "learning": False}
    add("h", "sleep", 49, 3.0)  # far below their own normal, two days in a row
    add("h", "sleep", 50, 3.0)
    d = health.indicator("h", "sleep", ms)
    assert d["learning"] is False and d["baseline"] == 7.0 and d["z"] < -2.5 and d["level"] == 2


def test_a_person_who_starts_in_flight_learns_from_their_first_two_weeks(monkeypatch):
    reset_crew(monkeypatch)
    for i in range(5):
        add("k", "sleep", 3 + i, 7.0)
    b = health.baselines("k")["sleep"]
    assert b["from"] == "early_flight" and b["mean"] == 7.0 and b["n"] == 5
    add("t", "sleep", 3, 7.0)
    add("t", "sleep", 30, 7.0)  # a reading a month later is not one of their first 14 days
    assert health.baselines("t")["sleep"]["from"] == "learning"


def test_a_population_critical_single_reading_still_raises_level_two_while_learning(monkeypatch):
    reset_crew(monkeypatch)
    add("h", "hr", 40, 180)  # no normal of their own yet (one reading), but 180 bpm at rest is past the safety limit
    ms = {**day(100), "day": 40, "location": plan.location_at(40), "learning": False}
    d = health.indicator("h", "hr", ms)
    assert d["learning"] is True and d["z"] is None and d["population"]["status"] == "critical" and d["level"] == 2
    assert "outside the safe range" in next(e for e in risk.evaluate("h", ms) if e["id"] == "cardio")["evidence"][0]["text"]
    assert any(a["id"] == "ind_hr" and a["level"] == 2 for a in health.snapshot("h", ms)["alerts"])


# ---------------------------------------------------------------- stale readings
def test_every_indicator_has_a_max_age_from_how_often_it_is_measured():
    ages = {k: v["max_age"] for k, v in catalog.INDICATORS.items()}
    assert ages["sleep"] == 3 and ages["gluc"] == 10 and ages["dsst"] == 10 and ages["vo2"] == 21 and ages["tlx"] == 21
    assert catalog.max_age_for(1) == 3 and catalog.max_age_for(3) == 10 and catalog.max_age_for(30) == 45
    assert catalog.max_age_for(15) == 23 and catalog.max_age_for(60) == 90  # any other interval: 1.5 x, rounded up
    import json
    recipes = json.load(open(os.path.join(os.path.dirname(__file__), "..", "..", "data", "recipes.json")))["indicators"]
    assert all(catalog.MEASURED_EVERY[k] == recipes[k]["frequency"]["every"] for k in catalog.INDICATORS)  # the table follows the recipes


def test_a_reading_older_than_max_age_is_stale_and_a_recent_one_is_current(monkeypatch):
    reset_crew(monkeypatch)
    add("h", "sleep", 10, 3.0)  # sleep: max_age 3 days
    o = telemetry.observation("h", "sleep", 13)
    assert o["value"] == 3.0 and o["age_days"] == 3 and o["stale"] is False  # carried forward, within max_age: still current
    assert telemetry.current("h", "sleep", 13) is None  # display smoothing counts only days with a reading of their own
    o = telemetry.observation("h", "sleep", 14)
    assert o["value"] == 3.0 and o["age_days"] == 4 and o["stale"] is True  # kept to show "last measured", never counted
    assert telemetry.current("h", "sleep", 16) is None  # all three days are stale
    none = telemetry.observation("h", "sleep", 5)
    assert none["value"] is None and none["origin"] == "none" and none["day"] is None and none["age_days"] is None and none["stale"] is False
    ser = dict(telemetry.series("h", "sleep", 16, 7))  # days 10..16: current, then a gap, never a repeated old value
    assert ser[10] == 3.0 and ser[13] == 3.0 and ser[14] is None and ser[15] is None and ser[16] is None
    assert [v for _d, v in telemetry.series("k", "sleep", 16, 7)] == [None] * 7  # nobody measured: no line


def test_current_averages_only_the_days_that_are_not_stale_and_renormalises_the_weights(monkeypatch):
    reset_crew(monkeypatch)
    add("h", "react", 5, 330)  # old: from day 9 on it is stale (react: max_age 3)
    day(100)
    h = {"Authorization": "Bearer " + gc._token(client, "/api/crew/h/session", gc.PINS["h"])}
    day(14)
    assert client.post("/api/checkins", json={"crew_id": "h", "kind": "pvt", "payload": {"ms": 300}}, headers=h).status_code == 200
    assert telemetry.observation("h", "react", 13)["stale"] and telemetry.observation("h", "react", 14)["origin"] == "user"
    assert telemetry.current("h", "react", 14) == pytest.approx(300)  # only today counts: weights 0.6 / 0.6, not 0.6 of 1.0
    add("h", "react", 13, 330)
    assert telemetry.current("h", "react", 14) == pytest.approx((0.6 * 300 + 0.25 * 330) / 0.85)  # day 12 still reads the old row: stale


def test_a_stale_reading_raises_no_alert_and_the_system_says_no_data(monkeypatch):
    reset(monkeypatch, "odyssey1-mars")
    ms = day(100)
    base = health.indicator("h", "sleep", ms)
    assert base["value"] is not None and base["stale"] is False
    # the sleep of h stops being reported: ten days later nothing current is left
    with data._transaction() as c:
        c.execute("DELETE FROM observations WHERE crew_id='h' AND indicator='sleep' AND day>=95")
    ms = day(100)
    d = health.indicator("h", "sleep", ms)
    assert d["value"] is None and d["stale"] is True and d["status"] == "no_data" and d["level"] == 0 and d["population"]["status"] == "no_data"
    assert d["last_measured_day"] is not None and d["last_measured_day"] < 95
    snap = health.snapshot("h", ms)
    assert not [a for a in snap["alerts"] if a["id"] == "ind_sleep"] and snap["no_data"] is False
    assert snap["indicators"]["hr"]["value"] is not None


# ---------------------------------------------------------------- partial data
@pytest.mark.parametrize("inds", [
    ("sleep", "mood", "react", "stress", "social"),                  # the whole fatigue picture
    ("bone", "grip", "exer", "vo2", "water", "gluc"),               # bones, muscles, kidneys, gut
    ("hr", "sbp", "dbp", "spo2", "temp", "dsst", "span", "kss", "tlx"),     # the rest
])
@pytest.mark.parametrize("d", [0, 152, 222])
def test_missing_some_indicators_breaks_nothing_and_alerts_nothing_for_them(monkeypatch, inds, d):
    reset(monkeypatch, "odyssey1-mars")
    marks = ",".join("?" * len(inds))
    with data._transaction() as c:
        c.execute(f"DELETE FROM observations WHERE indicator IN ({marks})", inds)
    day(d)
    out = every_get()
    for c in gc.CREW_IDS:
        s = out[f"/api/crew/{c} [as {c}]"]
        assert s["no_data"] is False
        for i in inds:
            x = s["indicators"][i]
            assert x["value"] is None and x["status"] == "no_data" and x["level"] == 0
        assert not [a for a in s["alerts"] if a["id"] in {f"ind_{i}" for i in inds}]
    assert db.q("SELECT COUNT(*) n FROM notices WHERE alert_id IN ({})".format(",".join("?" * len(inds))), tuple(f"ind_{i}" for i in inds))[0]["n"] == 0


def test_the_writing_routes_work_on_an_empty_system_too(monkeypatch):
    """Ask the assistant, draft a briefing, tick a goal, save a check-in, accept a suggestion: none may fail on no data, and
    none may turn missing data into a notice."""
    reset_crew(monkeypatch)
    day(100)
    h = tokens()[0]["h"]
    for q in ("how am i", "how is my sleep", "what about my pulse and radiation risk", "goals for today", "bone and kidney"):
        r = client.post("/api/assistant/ask", json={"crew_id": "h", "question": q}, headers=h)
        assert r.status_code == 200, (q, r.text)
    assert client.post("/api/briefings", json={"crew_id": "h"}, headers=h).status_code == 200
    items = client.get("/api/suggestions/h", headers=h).json()["items"]
    assert items
    for it in items:
        if it["goal"]:
            assert client.post(f"/api/suggestions/h/{it['id']}/accept", headers=h).status_code == 200
    assert client.post("/api/checkins", json={"crew_id": "h", "kind": "mood", "payload": {"mood": 4, "stress": 2}}, headers=h).status_code == 200
    assert client.post("/api/goals/h/mood", json={"done": True}, headers=h).status_code in (200, 204)
    assert db.q("SELECT COUNT(*) n FROM notices")[0]["n"] == 0
