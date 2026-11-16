"""Mission clock and place.

The mission day is the mission date minus the launch date in the registry. The mission date is the simulated date kept in
the settings (it starts from `simulated_today` of the mission package, and the control console or a scene can change it),
or, when there is no simulated date, today's date in UTC (the "real date"). The mission time of day follows the same rule:
the simulated time (`simulated_time` of the package, 12:00 by default) or the current UTC time.

Scenes are bookmarks in the `scenes` table (see data.py): jumping to one sets the simulated date and forgets any place
the crew had overridden. The place comes from the mission plan for that day, unless the crew overrides it ("Where are
you?"). A radiation storm is an event of the `space_events` table active on the day at the place.
"""
import logging
import re
from datetime import date, datetime, timedelta, timezone
from typing import List, Optional

from .. import db
from . import data, dose, plan, registry, spacetime
from .catalog import LOCATIONS, day_label, reply_text
from .validation import FieldError

log = logging.getLogger("canary.clock")

DEFAULT = {"scene": None, "location": None, "custom": False}
_TIME = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def _now() -> datetime:
    """The wall clock, UTC. Tests replace it."""
    return datetime.now(timezone.utc)


def _get() -> dict:
    return {**DEFAULT, **(db.get_setting("mission") or {})}


# ---------------------------------------------------------------- the clock
def launch_date() -> date:
    return date.fromisoformat(registry.launch_date())


def simulated_date() -> Optional[date]:
    d = db.get_setting("sim_date")
    return date.fromisoformat(d) if d else None


def mission_date() -> date:
    return simulated_date() or _now().date()


def mission_time() -> str:
    """Time of day of the mission clock, "HH:MM": the simulated time, or the current UTC time on the real date."""
    return data.mission_time() if simulated_date() else _now().strftime("%H:%M")


def clock() -> dict:
    return {"mode": "simulated" if simulated_date() else "real", "date": mission_date().isoformat(), "time": mission_time()}


def mission_day() -> int:
    return (mission_date() - launch_date()).days


def _set_date(d: Optional[date]) -> None:
    db.set_setting("sim_date", d.isoformat() if d else None)


def set_clock(date_text: Optional[str] = None, time_text: Optional[str] = None, real: bool = False) -> dict:
    """Move the mission clock: a simulated date (and time of day), or back to the real date. Raises validation.FieldError (422) on bad input."""
    if real:
        _set_date(None)
    else:
        if date_text is None:
            raise FieldError("date", "date is required (YYYY-MM-DD), or send real: true")
        try:
            d = date.fromisoformat(date_text) if isinstance(date_text, str) else None
        except ValueError:
            d = None
        if d is None:
            raise FieldError("date", "date must look like 2035-10-31")
        if not 1990 <= d.year <= 2200:
            raise FieldError("date", "date must be between 1990 and 2200")
        if time_text is not None:
            if not isinstance(time_text, str) or not _TIME.match(time_text):
                raise FieldError("time", "time must look like 12:00")
            db.set_setting("mission_time", time_text)
        _set_date(d)
    db.set_setting("mission", {**_get(), "scene": None, "location": None, "custom": not real})
    return state()


# ---------------------------------------------------------------- state
def _scene_step(scenes: List[dict], s: dict, day: int) -> int:
    """Which scene the story bar shows: the remembered one, else the one on this day, else the first."""
    if s["scene"] is not None and 0 <= s["scene"] < len(scenes):
        return s["scene"]
    return next((i for i, sc in enumerate(scenes) if sc["day"] == day), 0)


def mission_datetime() -> datetime:
    """The mission clock as a UTC instant: the mission date and the time of day (GMT)."""
    h, m = (int(x) for x in mission_time().split(":"))
    d = mission_date()
    return datetime(d.year, d.month, d.day, h, m, tzinfo=timezone.utc)


def launch_datetime() -> datetime:
    """Launch as a UTC instant: 00:00 GMT of the launch date (the registry holds a date, not a time)."""
    d = launch_date()
    return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)


def site_longitude() -> float:
    """Longitude of the Mars site in degrees east (setting `site_longitude_east_deg`; Jezero crater by default)."""
    v = db.get_setting("site_longitude_east_deg")
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else spacetime.A.value("mars.site_longitude_east_deg")


def timing(day: int, loc: str, leg: dict) -> dict:
    """MET, GMT, Mars time (on Mars), and the light time to Earth for the place and the instant of the mission clock."""
    now, launch = mission_datetime(), launch_datetime()
    light, down = spacetime.one_way_light_s(loc, now, leg, launch)
    out = {"met": spacetime.met(launch, now), "gmt": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "one_way_light_s": round(light, 2), "blackout": down,
           "mars_time": None, "sol": None}
    if LOCATIONS[loc].get("body") == "mars":
        landing_day = plan.landing_day(day, "mars") if loc == leg["location"] else 0
        landing = launch + timedelta(days=landing_day)
        lon = site_longitude()
        out["sol"] = spacetime.sol_since(landing, now)
        out["mars_time"] = {"msd": round(spacetime.msd(now), 4), "mtc": spacetime.hms(spacetime.mtc_hours(now)),
                            "lmst": spacetime.hms(spacetime.lmst_hours(now, lon)), "site_longitude_east_deg": lon,
                            "sol_s": spacetime.A.value("mars.sol_s"), "landing": landing.strftime("%Y-%m-%dT%H:%M:%SZ")}
    return out


def state() -> dict:
    s = _get()
    day = mission_day()
    scenes = data.scenes()
    step = _scene_step(scenes, s, day) if scenes else 0
    sc = scenes[step] if scenes else None
    leg = plan.leg_at(day)
    loc = s["location"] or plan.location_at(day)
    t = timing(day, loc, leg)
    place = {"id": loc, **LOCATIONS[loc], "delay_s": t["one_way_light_s"], "reply": reply_text(t["one_way_light_s"]),
             "one_way_light_s": t["one_way_light_s"], "blackout": t["blackout"]}
    if loc == "transit" and leg.get("direction") == "back":
        place.update(name="Transit to Earth", sub="Deep space, homeward")
    label = f"Sol {t['sol']}" if t["sol"] is not None else day_label(day, loc, 0)
    return {
        "step": step,
        "steps": len(scenes),
        "story": {"day": sc["day"], "loc": sc["location"], "me": sc["person"], "storm": sc["storm"], "text": sc["text"], "when": sc["when"]} if sc else None,
        "day": day,
        "day_label": label if day >= 0 else day_label(day, loc, 0),
        "met": t["met"], "gmt": t["gmt"], "sol": t["sol"], "mars_time": t["mars_time"],
        "one_way_light_s": t["one_way_light_s"], "blackout": t["blackout"],
        "location": loc,
        "place": place,
        "storm": dose.active_storm(day, loc),
        "suggested_user": (sc["person"] or None) if sc else None,
        "learning": loc == "earth" and day < 0,
        "leg": leg,
        "custom_day": bool(s["custom"]),
        "location_override": s["location"] is not None,
        "plan_name": plan.get()["name"],
        "setup_done": bool(db.get_setting("setup_done", True)),
        "callsign": (registry.mission_info() or {}).get("callsign"),
        "registered": registry.registered(),  # the mission admin (future flow) ships it configured
        "clock": clock(),
    }


def set_step(step: int) -> dict:
    """Go to scene `step` (the index in the scenes table order): the simulated date becomes launch + the scene's day and the
    place the plan's. With no scenes loaded nothing changes."""
    scenes = data.scenes()
    if scenes:
        i = max(0, min(len(scenes) - 1, step))
        _set_date(launch_date() + timedelta(days=scenes[i]["day"]))
        db.set_setting("mission", {**DEFAULT, "scene": i})
    return state()


def set_day(day: Optional[int]) -> dict:
    """Set the simulated date to launch + `day` and forget the scene. None goes back to the real date."""
    if day is None:
        return set_clock(real=True)
    _set_date(launch_date() + timedelta(days=day))
    db.set_setting("mission", {**DEFAULT, "custom": True})
    return state()


def story() -> List[dict]:
    """The scenes as the story the web app has always read: day, loc, me, storm, when, text."""
    return [{"loc": s["location"], "day": s["day"], "me": s["person"], "storm": s["storm"], "when": s["when"], "text": s["text"]}
            for s in data.scenes()]


def set_location(location: Optional[str]) -> dict:
    if location is not None and location not in LOCATIONS:
        raise ValueError(f"unknown location {location}")
    db.set_setting("mission", {**_get(), "location": location})
    return state()


def set_setup_done(done: bool = True) -> None:
    db.set_setting("setup_done", done)


# ---------------------------------------------------------------- day change
def sync_day(force: bool = False) -> bool:
    """When the mission day is not the one last synced (or `force`): run what a new day triggers, the advice review that
    may call for a message to the medical officer and the notice of a new critical alert. Returns True when it ran.
    Called by the background thread every ten minutes and right after any change of the clock."""
    from . import advice, notify
    ms = state()
    if not force and db.get_setting("last_synced_day") == ms["day"]:
        return False
    advice.sync_all(ms["day"])
    notify.sync(ms)
    db.set_setting("last_synced_day", ms["day"])
    return True


def safe_sync_day(force: bool = False) -> bool:
    """`sync_day` that never raises: the background thread must not take the API down."""
    try:
        return sync_day(force)
    except Exception:  # noqa: BLE001
        log.exception("day sync failed")
        return False
