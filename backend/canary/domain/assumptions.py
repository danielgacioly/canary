"""Every tunable number of the engine, in one table.

Each entry has a `value`, a `unit` and a `source`: either a citation (a standard, a paper, a physical constant) or the
words "Canary prototype assumption" (a design choice that no published rule backs: it is there to be reviewed and
changed, never to be quoted as fact). Modules import from here with `value(key)`; nothing else in the engine should
carry a bare tuning constant.

`table()` lists the entries for a review page or the README.
"""
from typing import Any, Dict, List

PROTOTYPE = "Canary prototype assumption"
NASA_STD = "NASA-STD-3001 Vol 1 Rev C (2023)"

ASSUMPTIONS: Dict[str, dict] = {}


def _a(key: str, value: Any, unit: str, source: str = PROTOTYPE) -> None:
    ASSUMPTIONS[key] = {"value": value, "unit": unit, "source": source}


def value(key: str) -> Any:
    return ASSUMPTIONS[key]["value"]


def table() -> List[dict]:
    return [{"key": k, **v} for k, v in sorted(ASSUMPTIONS.items())]


# ---------------------------------------------------------------- alert levels (statistics)
_a("z.watch", 1.5, "personal standard deviations", PROTOTYPE + ": level 1 (watch) enters at this distance from the personal normal")
_a("z.act", 2.5, "personal standard deviations", PROTOTYPE + ": level 2 (act) enters at this distance from the personal normal")
_a("z.hysteresis", 0.5, "personal standard deviations", PROTOTYPE + ": a level already reached is kept until the distance drops this far below its entry threshold")
_a("z.persistence_readings", 2, "consecutive measured days", PROTOTYPE + ": level 1 needs the condition on this many consecutive readings, unless a critical population bound or a NASA limit is crossed")
_a("baseline.min_points", 5, "readings", PROTOTYPE + ": readings needed before a person's own normal is used")
_a("baseline.confidence_moderate", 10, "readings", PROTOTYPE + ": below this many baseline readings the confidence is low")
_a("baseline.confidence_high", 20, "readings", PROTOTYPE + ": from this many baseline readings the confidence is high")
_a("baseline.early_flight_days", 14, "days", PROTOTYPE + ": a person who starts in flight learns their normal from their first days of measurements")
_a("adaptation.first_day", 1, "flight day", PROTOTYPE + ": first flight day of the microgravity adaptation window")
_a("adaptation.last_day", 14, "flight day", PROTOTYPE + ": last flight day of the adaptation window; indicators flagged adapts_in_flight raise no level-1 alert inside it")
_a("adaptation.rebaseline_first", 8, "flight day", PROTOTYPE + ": first flight day of the in-flight re-baseline window")
_a("adaptation.rebaseline_last", 14, "flight day", PROTOTYPE + ": last flight day of the in-flight re-baseline window")
_a("adaptation.min_points", 4, "readings", PROTOTYPE + ": readings the in-flight re-baseline needs")
_a("history.window_points", 30, "days", PROTOTYPE + ": how far back the level history (hysteresis, persistence) looks, at least")

# personal day-to-day spread floor per indicator (the baseline spread never goes below it)
_a("indicator.sd", {"sleep": 0.5, "react": 18, "mood": 0.35, "stress": 0.4, "social": 15, "dsst": 4, "span": 0.5, "kss": 0.5, "tlx": 6,
                    "hr": 3, "sbp": 5, "dbp": 4, "spo2": 0.7, "temp": 0.15, "gluc": 6, "water": 0.25, "exer": 12, "grip": 1.5,
                    "bone": 0.03, "vo2": 3.0},
   "indicator units", PROTOTYPE + ": floor of the personal spread used for the z-score; not a published value")

# ---------------------------------------------------------------- scores and risks
_a("readiness.free_spread", 0.6, "personal standard deviations", PROTOTYPE + ": an indicator loses no points inside this distance")
_a("readiness.points_per_spread", 18, "points per spread", PROTOTYPE + ": readiness points lost for every spread beyond the free one")
_a("readiness.system_penalty", 6, "points per level", PROTOTYPE + ": physical readiness lost per level of eyes, skin and immune (no indicators of their own)")
_a("advice.margin", 0.5, "personal standard deviations", PROTOTYPE + ": the average deviation must move this much to count as improved or worse")
_a("care.sensitivity_factor", 0.8, "factor", PROTOTYPE + ": thresholds are scaled by this inside the care window of a closed emergency")
_a("fatigue.weights", {"sleep": 1.0, "react": 1.0, "mood": 1.0, "dsst": 0.75, "stress": 0.5, "social": 0.5, "span": 0.5, "kss": 0.5, "tlx": 0.5},
   "points per level", PROTOTYPE + ": no published model sums these signals")
_a("fatigue.checkins", {"wellbeing": 1.0, "missing_mood": 0.5}, "points", PROTOTYPE)
_a("fatigue.drift", {"weight": 0.5, "cap": 1.0}, "points", PROTOTYPE + ": a slow slide still inside the normal range")
_a("fatigue.cuts", {1: 2.0, 2: 4.0}, "points", PROTOTYPE + ": score needed for level 1 and level 2")
_a("fatigue.min_signals_level_2", 3, "signals", PROTOTYPE)
_a("fatigue.sustained_days", 2, "days", PROTOTYPE + ": level 2 also needs level 1 or more this many days earlier")
_a("fatigue.trend", {"days": 3, "delta": 0.5}, "days, points", PROTOTYPE)
_a("fatigue.lookback_days", 60, "days", PROTOTYPE)
_a("drift", {"window": 14, "horizon": 10, "min_slope": 0.08}, "days, days, spreads per day", PROTOTYPE)
_a("risk.specs", {
    "radiation": {"cuts": {1: 1.0, 2: 99.0}, "min2": 99, "clock_days": 1},
    "sans": {"cuts": {1: 1.0, 2: 2.0}, "min2": 1, "clock_days": 7},
    "nutrition": {"cuts": {1: 1.0, 2: 3.0}, "min2": 2, "clock_days": 7},
    "renal": {"cuts": {1: 1.0, 2: 3.0}, "min2": 2, "clock_days": 15},
    "immune": {"cuts": {1: 1.0, 2: 3.0}, "min2": 2, "clock_days": 30},
    "cardio": {"cuts": {1: 1.0, 2: 4.0}, "min2": 3, "clock_days": 1},
    "bone_muscle": {"cuts": {1: 1.0, 2: 4.0}, "min2": 3, "clock_days": 30}}, "points, signals, days", PROTOTYPE + ": no published model sums these signals")
_a("risk.rules", {
    "radiation": {"watch_pct_of_limit": 50, "lym_points": 1.0},
    "nutrition": {"loss_pct": {1: 5.0, 2: 10.0}},
    "renal": {"bone_loss_pct_30d": 1.0, "points": 1.0},
    "immune": {"blood_point": 0.5, "blood_cap": 1.5, "storm_follow_days": 13, "follow_kinds": ["sep"], "storm_points": 1.0,
               "crp_rise_pct": 50.0, "crp_points": 0.5},
    "cardio": {"regravity_points": 0.5},
    "bone_muscle": {"estimate_points": 1.0, "estimate_loss_pct": 3.0},
    "sans": {"amsler_points": 2.0, "vision_symptom_points": 1.0, "window_days": 7}}, "mixed", PROTOTYPE + ": thresholds of the evidence functions")
_a("ridge.cuts", {"R": {"moderate_msv_day": 0.1, "high_msv_day": 1.0}, "I": {"moderate_until_day": 90, "large_crew": 6},
                  "D": {"high_delay_s": 60, "moderate_hospital_days": 2}, "G": {"readapt_days": 30},
                  "hospital_days": {"earth": 0, "rocket": 0, "iss": 1, "moon": 3, "transit": 9999, "mars": 500, "moon_rover": 3, "mars_rover": 500}},
   "mSv/day, days, s", PROTOTYPE + ": no published rule maps these numbers to a level")
_a("ridge.environment_level", {"earth": 0, "rocket": 1, "iss": 1, "moon": 2, "transit": 1, "mars": 2, "moon_rover": 2, "mars_rover": 2},
   "level 0 to 2", PROTOTYPE + ": recycled air, noise and shared surfaces are not in the plan")

# ---------------------------------------------------------------- NASA limits and early-warning steps
_a("nasa.career_effective_dose_msv", 600, "mSv", NASA_STD + ", 4.2.10 [V1 4030]: career effective dose limit, same for all ages and sexes")
_a("nasa.spe_design_effective_dose_msv", 250, "mSv", NASA_STD + " [V1 4031]: design reference for a solar particle event (a vehicle and shielding design requirement, not a personal limit)")
_a("nasa.grip_limit_pct", 80, "% of pre-flight baseline", NASA_STD + " [V1 4024]: in-mission skeletal muscle strength at or above 80% of baseline")
_a("nasa.bone_limit_pct", 95, "% of pre-flight baseline", NASA_STD + " [V1 4027]: hip and spine bone mineral density at or above 95% of pre-mission values")
_a("nasa.vo2_microgravity", 32.9, "mL/kg/min", NASA_STD + " [V1 4001]")
_a("nasa.vo2_surface", 36.5, "mL/kg/min", NASA_STD + " [V1 4002]")
_a("early.grip_pct", 90, "% of pre-flight baseline", PROTOTYPE + ": early warning before the NASA strength limit")
_a("early.bone_loss_pct", 3.0, "% loss", PROTOTYPE + ": early warning before the NASA bone limit")

# ---------------------------------------------------------------- radiation
_a("dose.quiet_rate_msv_day", {"earth": 0.01, "rocket": 0.5, "iss": 0.5, "moon": 1.37, "transit": 1.8, "mars": 0.67, "moon_rover": 1.37, "mars_rover": 0.67},
   "mSv/day dose equivalent", "Typical daily dose by place from published ISS, Apollo, MSL cruise and Curiosity RAD figures; to be verified. "
   "A pressurized rover takes the dose of its planet's surface (prototype assumption: no rover shielding figure)")
_a("dose.shelter_ratio", 3.0, "x the quiet rate of the place", PROTOTYPE + ": a cabin or personal dosimeter above this multiple of the place's quiet rate orders the shelter")
_a("dose.earth_orbit_shelter_msv_day", 2.0, "mSv/day", PROTOTYPE + ": in low Earth orbit the magnetosphere attenuates solar particles; the shelter is ordered only when the cabin dosimeter exceeds this")
_a("dose.quality_factor", 2.0, "mSv per mGy", PROTOTYPE + ": mean quality factor used only when a dosimeter reports the absorbed dose (mGy/day) and no dose equivalent")
_a("dose.model_note", "effective dose approximated by the dosimeter's dose equivalent; organ-weighted model not applied", "text", PROTOTYPE)

# ---------------------------------------------------------------- bone model (inferred in flight: bone density is not measurable on board)
_a("bone.model", {"max_pct_per_month": 1.0, "exercise_gain": 0.65, "exercise_full_min": 110, "gravity_rate": {"g0": 1.0, "gp": 0.4, "g1": -0.25}},
   "% per month", "NASA HRP order of magnitude (about 1% a month without countermeasures); exercise effect and partial-gravity rates are " + PROTOTYPE)

# ---------------------------------------------------------------- Mars time and the Earth-Mars geometry
_a("mars.sol_s", 88775.244, "s", "Allison and McEwen 2000; NASA GISS Mars24: one Mars solar day, 24 h 39 min 35.244 s")
_a("mars.msd_epoch_jd", 2405522.0028779, "JD", "Allison and McEwen 2000: MSD = (JD_TT - 2405522.0028779) / 1.0274912517")
_a("mars.sol_in_days", 1.0274912517, "days", "Allison and McEwen 2000")
_a("time.tt_minus_utc_s", 69.184, "s", "TT - UTC = 32.184 s + 37 leap seconds (since 2017); close enough for a clock")
_a("mars.site_longitude_east_deg", 77.45, "degrees east", "Jezero crater; override with the setting site_longitude_east_deg")
_a("orbit.a_earth_au", 1.000, "AU", "Circular coplanar approximation")
_a("orbit.a_mars_au", 1.524, "AU", "Circular coplanar approximation")
_a("orbit.synodic_days", 779.94, "days", "Earth-Mars synodic period")
_a("orbit.opposition_utc", "2035-09-15T19:33:00+00:00", "UTC", "Reference opposition of 2035 (phase angle 0)")
_a("orbit.light_s_per_au", 499.005, "s/AU", "Light travel time over one astronomical unit")
_a("orbit.blackout_elongation_deg", 3.0, "degrees", "Approximation of the roughly two-week solar conjunction blackout: no link while the Sun-Earth-Mars angle is below this")
_a("comms.moon_one_way_s", 1.28, "s", "Earth-Moon distance 384,400 km")
