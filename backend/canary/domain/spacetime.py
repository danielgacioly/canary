"""Time and distance beyond Earth: Mars time, mission elapsed time and the Earth-Mars light time.

Pure functions of a date and time (no database, no clock). Every constant is in domain/assumptions.py with its source.

- Mars Sol Date: MSD = (JD_TT - 2405522.0028779) / 1.0274912517; Mars Coordinated Time MTC = (24 x MSD) mod 24 hours
  (Allison and McEwen 2000, NASA GISS Mars24). JD_TT is the Julian date of the UTC instant plus 69.184 s.
- Local mean solar time at a site: LMST = MTC + longitude / 15 h, longitude east-positive.
- A Mars solar day is 88,775.244 s. The sol of a mission counts from the landing instant in sols of that length.
- Earth and Mars are taken on circular, coplanar orbits (1.000 and 1.524 AU, synodic period 779.94 days, opposition on
  2035-09-15T19:33Z): distance d = sqrt(aE^2 + aM^2 - 2 aE aM cos(theta)) with theta = 2 pi (t - t_opposition) / synodic
  period; one-way light time = d x 499.005 s. That gives about 4.4 minutes at opposition and 21 minutes at conjunction
  (the real orbits are eccentric: the range is about 3 to 22 minutes).
- Solar conjunction: the Sun-Earth-Mars angle (elongation) below 3 degrees is treated as a communications blackout, an
  approximation of the roughly two-week conjunction blackout.
"""
import math
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple

from . import assumptions as A

_JD_UNIX_EPOCH = 2440587.5  # Julian date of 1970-01-01T00:00:00Z


def _utc(t: datetime) -> datetime:
    return t.replace(tzinfo=timezone.utc) if t.tzinfo is None else t.astimezone(timezone.utc)


def julian_date_utc(t: datetime) -> float:
    return _JD_UNIX_EPOCH + _utc(t).timestamp() / 86400.0


def julian_date_tt(t: datetime) -> float:
    return julian_date_utc(t) + A.value("time.tt_minus_utc_s") / 86400.0


def msd(t: datetime) -> float:
    """Mars Sol Date at a UTC instant."""
    return (julian_date_tt(t) - A.value("mars.msd_epoch_jd")) / A.value("mars.sol_in_days")


def mtc_hours(t: datetime) -> float:
    """Mars Coordinated Time, in hours of 24 (the mean solar time at the Mars prime meridian)."""
    return (24.0 * msd(t)) % 24.0


def lmst_hours(t: datetime, longitude_east_deg: Optional[float] = None) -> float:
    """Local mean solar time at a site, in hours of 24: MTC + longitude / 15, east-positive."""
    lon = A.value("mars.site_longitude_east_deg") if longitude_east_deg is None else longitude_east_deg
    return (mtc_hours(t) + lon / 15.0) % 24.0


def hms(hours: float) -> str:
    """Hours of a Mars day as HH:MM (a Mars hour is 1/24 of a sol)."""
    m = int(round(hours * 60)) % (24 * 60)
    return f"{m // 60:02d}:{m % 60:02d}"


def sol_after(earth_days: float) -> int:
    """Whole sols elapsed after `earth_days` Earth days (86,400 s each) from the landing instant, with the real sol length."""
    return int(math.floor(earth_days * 86400.0 / A.value("mars.sol_s")))


def sol_since(landing: datetime, now: datetime) -> int:
    return int(math.floor((_utc(now) - _utc(landing)).total_seconds() / A.value("mars.sol_s")))


def met(launch: datetime, now: datetime) -> str:
    """Mission elapsed time d/hh:mm since launch (a minus sign before launch)."""
    s = int((_utc(now) - _utc(launch)).total_seconds())
    sign = "-" if s < 0 else ""
    s = abs(s) // 60
    return f"{sign}{s // 1440}/{(s % 1440) // 60:02d}:{s % 60:02d}"


# ---------------------------------------------------------------- Earth-Mars geometry
def _theta(t: datetime) -> float:
    opp = datetime.fromisoformat(A.value("orbit.opposition_utc"))
    return 2 * math.pi * ((_utc(t) - opp).total_seconds() / 86400.0) / A.value("orbit.synodic_days")


def earth_mars_au(t: datetime) -> float:
    aE, aM = A.value("orbit.a_earth_au"), A.value("orbit.a_mars_au")
    return math.sqrt(aE * aE + aM * aM - 2 * aE * aM * math.cos(_theta(t)))


def elongation_deg(t: datetime) -> float:
    """Sun-Earth-Mars angle seen from Earth, in degrees (0 at conjunction, 180 at opposition)."""
    aE, aM, th = A.value("orbit.a_earth_au"), A.value("orbit.a_mars_au"), _theta(t)
    # Earth at (aE, 0); Mars at aM (cos th, sin th), seen from Earth; the Sun is in the direction (-aE, 0).
    mx, my = aM * math.cos(th) - aE, aM * math.sin(th)
    sx = -aE
    dot = mx * sx
    return math.degrees(math.acos(max(-1.0, min(1.0, dot / (math.hypot(mx, my) * abs(sx))))))


def light_time_s(t: datetime) -> float:
    """One-way light time between Earth and Mars at a UTC instant."""
    return earth_mars_au(t) * A.value("orbit.light_s_per_au")


def blackout(t: datetime) -> bool:
    """Solar conjunction: no link while the elongation is below the limit (an approximation of the real blackout)."""
    return elongation_deg(t) < A.value("orbit.blackout_elongation_deg")


def one_way_light_s(location: str, t: datetime, leg: Optional[dict] = None, launch: Optional[datetime] = None) -> Tuple[float, bool]:
    """(one-way light time in seconds, blackout) for the place the crew is at, at a UTC instant.

    Earth and the station: 0. The Moon: 1.28 s. Mars surface and rover: the Earth-Mars light time at that instant. In transit
    the distance from Earth grows (or shrinks, on the way back) linearly over the leg between 0 and the Earth-Mars distance at
    the end (or start) of the leg: `leg` carries `start` and `end` (mission days) and `direction` ("out" or "back"); `launch`
    is the launch instant that day numbers count from. Blackout only counts where Mars is at the other end of the link.
    """
    if location in ("earth", "rocket", "iss"):
        return 0.0, False
    if location in ("moon", "moon_rover"):
        return A.value("comms.moon_one_way_s"), False
    if location in ("mars", "mars_rover"):
        return light_time_s(t), blackout(t)
    if location == "transit":
        if not leg or launch is None:
            return light_time_s(t), blackout(t)
        start = _utc(launch) + timedelta(days=leg["start"])
        end = _utc(launch) + timedelta(days=leg["end"] + 1)
        span = (end - start).total_seconds() or 1.0
        f = min(1.0, max(0.0, (_utc(t) - start).total_seconds() / span))
        if leg.get("direction") == "back":
            d = (1.0 - f) * earth_mars_au(start)
        else:
            d = f * earth_mars_au(end)
        near_mars = f >= 0.9 if leg.get("direction") != "back" else f <= 0.1  # the craft is close to Mars, so the Sun passes near the line of sight
        return d * A.value("orbit.light_s_per_au"), blackout(t) and near_mars
    return 0.0, False
