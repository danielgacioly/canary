"""Live space weather: NASA DONKI solar particle events turned into space events.

Only when `settings.live_space_weather` is on and the mission clock runs on the real date (no simulated date). The
background thread in main.py calls `import_donki()` every ten minutes. Each SEP event of the last 30 days becomes a
space event with origin "donki" and id "donki:<activityID>", on the mission day it happened, but only when the plan puts
the crew away from Earth that day. An event already stored is left alone. Offline, a rate limit or an answer in an
unexpected shape: nothing happens, never an error.
"""
import datetime as dt
import logging
from typing import Callable, List, Optional

from ..config import settings
from . import data, mission, plan

log = logging.getLogger("canary.live")
WINDOW_DAYS = 30
BASE = "https://api.nasa.gov/DONKI/SEP"

Fetch = Callable[[dt.date, dt.date], List[dict]]


def fetch_sep(start: dt.date, end: dt.date) -> List[dict]:
    """The SEP events DONKI logged between two dates (raises when the network or the API fails)."""
    import httpx
    with httpx.Client(timeout=8) as c:
        r = c.get(BASE, params={"startDate": start.isoformat(), "endDate": end.isoformat(), "api_key": settings.nasa_api_key})
        r.raise_for_status()
        return r.json() or []


def _activity_id(e: dict) -> Optional[str]:
    return e.get("activityID") or e.get("sepID")


def import_donki(fetch: Optional[Fetch] = None) -> int:
    """Store the SEP events of the last 30 days that the plan puts the crew away from Earth for. Returns how many are new."""
    if not settings.live_space_weather or mission.simulated_date() is not None:
        return 0
    try:
        today = mission._now().date()
        rows = (fetch or fetch_sep)(today - dt.timedelta(days=WINDOW_DAYS), today)
        launch = mission.launch_date()
        stored = {e["id"] for e in data.events()}
        new = 0
        for e in rows if isinstance(rows, list) else []:
            try:
                aid, when = _activity_id(e), str(e.get("eventTime") or e.get("startTime") or "")[:10]
                if not aid or not when:
                    continue
                eid = f"donki:{aid}"
                if eid in stored:
                    continue
                day = (dt.date.fromisoformat(when) - launch).days
                loc = plan.location_at(day)
                if loc == "earth":  # on the ground the particles do not reach the crew
                    continue
                data.add_space_event({"id": eid, "kind": "sep", "start_day": day, "end_day": day, "locations": [loc],
                                      "extra_dose_msv": 0, "origin": "donki", "source": "nasa:donki",
                                      "note": f"NASA DONKI solar particle event of {when}"})
                stored.add(eid)
                new += 1
            except Exception:  # noqa: BLE001  one odd event must not stop the others
                log.warning("DONKI event skipped", exc_info=True)
        return new
    except Exception:  # noqa: BLE001  offline on board, rate limited or an API change: nothing happens
        return 0
