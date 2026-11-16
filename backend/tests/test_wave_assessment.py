"""Assessment states (RULE-03, DATA-03) and the limits read route (RULE-12).

- A clean database in flight shows insufficient_data for every indicator, system, area and person, never an assessed
  (normal-looking) state. The only exception is a scan that cannot be taken on board (bone), which is not_applicable.
- GET /api/catalog serves the NASA limits, units and sources the screens read; the frontend no longer keeps its own copy.
"""
from tests.test_empty_and_stale import client, day, reset_crew, remove_all_observations, tokens  # noqa: F401
from tests import golden_capture as gc  # noqa: F401
from canary.domain import standards  # noqa: F401


def test_clean_database_in_flight_is_insufficient_everywhere(monkeypatch):
    reset_crew(monkeypatch)
    remove_all_observations()
    day(30)
    ch, _med, _ctl = tokens()
    for c in gc.CREW_IDS:
        d = client.get(f"/api/crew/{c}", headers=ch[c]).json()
        assert d["mission"]["location"] != "earth"
        assert d["no_data"] is True
        for k, i in d["indicators"].items():
            assert i["assessment"] in ("insufficient_data", "not_applicable"), k
            assert i["assessment"] == "insufficient_data" or i.get("scan"), k
            assert i["level"] == 0 and i["value"] is None
        assert all(s["assessment"] != "assessed" for s in d["systems"].values())
        assert all(a["assessment"] != "assessed" for a in d["areas"].values())
        assert d["assessment"] == "insufficient_data"


def test_limits_route_serves_the_nasa_numbers(monkeypatch):
    limits = client.get("/api/catalog").json()["limits"]
    assert limits["grip"]["limit_pct"] == standards.LIMITS["grip"]["limit_pct"] == 80
    assert limits["bone"]["limit_pct"] == standards.LIMITS["bone"]["limit_pct"] == 95
    assert limits["vo2"]["surface"] == standards.LIMITS["vo2"]["surface"] and limits["vo2"]["microgravity"] == standards.LIMITS["vo2"]["microgravity"]
    assert limits["radiation"]["career_msv"] == 600 and limits["radiation"]["spe_msv"] == 250
    assert limits["document"]["url"].startswith("https://www.nasa.gov/")
    assert limits["units"]["vo2"]["unit"] == "mL/kg/min"
