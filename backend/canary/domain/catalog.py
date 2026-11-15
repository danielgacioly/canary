"""Static mission data: places, indicators, body systems, goals and badges (and the views of the registered crew).

Everything numeric that comes from literature is marked `source` so it can be
checked before the pitch.
"""
from typing import Dict, List, Optional

from . import assumptions as A

# ---------------------------------------------------------------- places
LOCATIONS: Dict[str, dict] = {
    "earth": {"name": "Earth", "sub": "Pre-flight training", "gravity_key": "g1", "gravity": "1 g",
              "delay_s": 0, "hospital": "Minutes",
              "what": "Canary is learning what your normal looks like. No alerts yet."},
    "rocket": {"name": "Launch", "sub": "First 72 hours", "gravity_key": "g0", "gravity": "0 g",
               "delay_s": 0, "hospital": "Hours",
               "what": "Your body is adjusting to weightlessness. Short goals, patient alerts."},
    "iss": {"name": "Space station", "sub": "Low Earth orbit", "gravity_key": "g0", "gravity": "0 g",
            "delay_s": 0, "hospital": "About 1 day",
            "what": "Two hours of exercise a day protect bone and muscle."},
    "moon": {"name": "Moon", "sub": "Lunar surface", "gravity_key": "gp", "gravity": "1/6 g",
             "delay_s": 1.3, "hospital": "About 3 days",
             "what": "No magnetic shield. Every walk outside depends on space weather."},
    "transit": {"name": "Transit to Mars", "sub": "Deep space", "gravity_key": "g0", "gravity": "0 g",
                "delay_s": 300, "hospital": "No way back",
                "what": "Earth is too far to help in time. Canary guides the crew first, then reports."},
    "mars": {"name": "Mars", "sub": "Gale crater", "gravity_key": "gp", "gravity": "3/8 g",
             "delay_s": 840, "hospital": "About 500 days",
             "what": "Your body is relearning weight after months in 0 g. Stand up slowly."},
    "moon_rover": {"name": "Lunar rover", "sub": "Pressurized rover traverse", "gravity_key": "gp", "gravity": "1/6 g",
                   "delay_s": 1.3, "hospital": "About 3 days",
                   "what": "Days away from the base in a small cabin. Every walk outside is a surface EVA."},
    "mars_rover": {"name": "Mars rover", "sub": "Pressurized rover traverse", "gravity_key": "gp", "gravity": "3/8 g",
                   "delay_s": 840, "hospital": "About 500 days",
                   "what": "Far from the habitat's gym and medical bay. Canary guides first; the base is hours away."},
}
# `delay_s` is the nominal one-way delay of the place (the middle of the real range), kept for places that have no date to
# compute from. The delay of the mission clock is computed from the Earth-Mars geometry (domain/spacetime.py) and replaces
# it in `mission.state()`. `reply` is the round trip, derived from the delay.


def reply_text(one_way_s: float) -> str:
    rt = 2 * one_way_s
    return "Live" if rt < 1 else f"{round(rt)} seconds" if rt < 60 else f"{round(rt / 60)} minutes"


# The body a place belongs to (a rover counts sols and uses the protocols of its planet) and the kind of EVA done there,
# which sets the aerobic-capacity limit of NASA-STD-3001 (V1 4001 microgravity, V1 4002 surface).
for _k, _body, _eva in (("earth", "earth", "none"), ("rocket", "space", "none"), ("iss", "space", "microgravity"),
                        ("transit", "space", "microgravity"), ("moon", "moon", "surface"), ("mars", "mars", "surface"),
                        ("moon_rover", "moon", "surface"), ("mars_rover", "mars", "surface")):
    LOCATIONS[_k].update(body=_body, eva=_eva, dose_rate=A.value("dose.quiet_rate_msv_day")[_k])
    LOCATIONS[_k]["reply"] = reply_text(LOCATIONS[_k]["delay_s"])
LOCATIONS["moon"]["delay_s"] = LOCATIONS["moon_rover"]["delay_s"] = A.value("comms.moon_one_way_s")
LOCATIONS["moon"]["reply"] = LOCATIONS["moon_rover"]["reply"] = reply_text(A.value("comms.moon_one_way_s"))
DOSE_SOURCE = A.ASSUMPTIONS["dose.quiet_rate_msv_day"]["source"]
# NASA-STD-3001 Volume 1 Rev. C (2023), checked against the document on 2026-11-14:
# [V1 4030] career effective dose below 600 mSv, the same for all ages and sexes; [V1 4031] the design solar particle
# event below 250 mSv effective dose. https://www.nasa.gov/wp-content/uploads/2023/11/nasa-std-3001-vol-1-rev-c-with-signature.pdf
CAREER_LIMIT_MSV = A.value("nasa.career_effective_dose_msv")  # [V1 4030], 4.2.10
SPE_LIMIT_MSV = A.value("nasa.spe_design_effective_dose_msv")  # [V1 4031], design reference for a solar particle event


def day_label(day: int, location: str, leg_start: int = 0) -> str:
    """L-30 before launch, Sol N on Mars (counted from landing with the real 88,775.244 s sol, rover traverses included; the day is read at noon UTC), Day N otherwise."""
    if day < 0:
        return f"L{day}"
    if LOCATIONS.get(location, {}).get("body") == "mars":
        from . import spacetime
        return f"Sol {spacetime.sol_after((day - leg_start) + 0.5)}"  # noon UTC of the mission day, real sol length
    return f"Day {day}"


# ---------------------------------------------------------------- the registered crew
# Filled in place by registry.load() from what Mission Control registered (or a mission package imported): from one to
# six people, with nothing but what was registered. The engine has no crew of its own; the demo crew lives with the
# sheet generator (data/demo_crew.json) and reaches the engine only as the odyssey1 packages' crew.csv.
CREW: List[dict] = []
CREW_BY_ID: Dict[str, dict] = {}
RECORDS: Dict[str, dict] = {}  # each person's registered record, by id (private: the person and the medical team)
MAX_CREW = 6

# ---------------------------------------------------------------- indicators
# dir: which way is bad. sd: floor of the personal day-to-day spread used for the z-score (value in domain/assumptions.py).
# adapts_in_flight: the indicator moves with the first days of microgravity (fluid shift), so it raises no level-1 alert in
# the adaptation window and is re-baselined on flight days 8 to 14. scan: measured only before and after the flight (not on board).
# context: what a reading may say about how it was taken (heart rate: rest or exercise; pressure: seated, supine or standing).
INDICATORS: Dict[str, dict] = {
    "sleep": {"name": "Sleep", "unit": "h", "area": "mental", "facet": "Rest", "dir": "low", "sd": 0.5, "dp": 1},
    "react": {"name": "Reaction time", "unit": "ms", "area": "mental", "facet": "Focus", "dir": "high", "sd": 18, "dp": 0},
    "mood": {"name": "Mood", "unit": "/5", "area": "mental", "facet": "Mood", "dir": "low", "sd": 0.35, "dp": 1},
    "stress": {"name": "Stress", "unit": "/5", "area": "mental", "facet": "Stress", "dir": "high", "sd": 0.4, "dp": 1},
    "social": {"name": "Time with crew", "unit": "min", "area": "mental", "facet": "Connection", "dir": "low", "sd": 15, "dp": 0},
    "dsst": {"name": "Processing speed", "unit": "correct", "area": "mental", "facet": "Speed", "dir": "low", "sd": 4, "dp": 0},
    "span": {"name": "Working memory", "unit": "digits", "area": "mental", "facet": "Memory", "dir": "low", "sd": 0.5, "dp": 1},
    "kss": {"name": "Sleepiness", "unit": "/9", "area": "mental", "facet": "Alertness", "dir": "high", "sd": 0.5, "dp": 1},
    "tlx": {"name": "Workload", "unit": "/100", "area": "mental", "facet": "Workload", "dir": "high", "sd": 6, "dp": 0},
    "hr": {"name": "Resting pulse", "unit": "bpm", "area": "physical", "dir": "both", "sd": 3, "dp": 0, "adapts_in_flight": True,
           "context": {"field": "activity", "options": ["rest", "exercise"], "counts": ["rest"]}},
    "sbp": {"name": "Systolic pressure", "unit": "mmHg", "area": "physical", "dir": "both", "sd": 5, "dp": 0, "adapts_in_flight": True,
            "context": {"field": "position", "options": ["seated", "supine", "standing"], "counts": ["seated"]}},
    "dbp": {"name": "Diastolic pressure", "unit": "mmHg", "area": "physical", "dir": "both", "sd": 4, "dp": 0, "adapts_in_flight": True,
            "context": {"field": "position", "options": ["seated", "supine", "standing"], "counts": ["seated"]}},
    "spo2": {"name": "Blood oxygen", "unit": "%", "area": "physical", "dir": "low", "sd": 0.7, "dp": 0},
    "temp": {"name": "Temperature", "unit": "°C", "area": "physical", "dir": "high", "sd": 0.15, "dp": 1},
    "gluc": {"name": "Fasting glucose", "unit": "mg/dL", "area": "physical", "dir": "both", "sd": 6, "dp": 0},
    "water": {"name": "Water", "unit": "L", "area": "physical", "dir": "low", "sd": 0.25, "dp": 1},
    "exer": {"name": "Exercise", "unit": "min", "area": "physical", "dir": "low", "sd": 12, "dp": 0},
    "grip": {"name": "Grip strength", "unit": "kg", "area": "physical", "dir": "low", "sd": 1.5, "dp": 1},
    "bone": {"name": "Bone density (DXA)", "unit": "g/cm²", "area": "physical", "dir": "low", "sd": 0.03, "dp": 2, "scan": True, "min_baseline": 1},
    "vo2": {"name": "Aerobic capacity (VO2max)", "unit": "mL/kg/min", "area": "physical", "dir": "low", "sd": 3.0, "dp": 1},
}

for _ind, _I in INDICATORS.items():
    _I["sd"] = A.value("indicator.sd")[_ind]

# How long a reading stays current, in days (`max_age`). Derived from how often the indicator is measured (the
# `frequency.every` of its recipe in data/recipes.json): measured every day -> 3 days; every 2 to 7 days -> 10 days; a
# monthly blood panel -> 45 days; any other interval -> 1.5 times the interval, rounded up. Exception to the 10 days: a
# weekly measurement gets 21 (three intervals), because the simulated data skips weekly tests for up to 20 days on purpose
# (a VO2max series of the demo, days -28 to -7) and a carried-forward test inside that window is still current.
# A reading older than that is stale: it is shown as the last measurement, but never counted as today's value.
MEASURED_EVERY = {"sleep": 1, "react": 1, "mood": 1, "stress": 1, "social": 1, "hr": 1, "sbp": 1, "dbp": 1, "spo2": 1, "temp": 1, "gluc": 3,
                  "water": 1, "exer": 1, "grip": 1, "vo2": 7, "bone": 365, "dsst": 3, "span": 3, "kss": 1, "tlx": 7}


def max_age_for(every: int) -> int:
    """Days a reading of an indicator measured every `every` days stays current (rule above)."""
    if every <= 1:
        return 3
    if every <= 7:
        return max(10, 3 * every)  # 10 days; a weekly test 21: three intervals
    if every == 30:
        return 45
    return -(-3 * every // 2)  # ceil(1.5 * every)


for _ind, _every in MEASURED_EVERY.items():
    INDICATORS[_ind]["max_age"] = max_age_for(_every)
INDICATORS["bone"]["max_age"] = 900  # a DXA scan is read until the next one (before launch, then after landing): longer than any plan
OTHER_MEASURED_EVERY = {"weight": 3, "hrv": 1}  # measured and stored, but not in INDICATORS


def max_age(ind: str) -> Optional[int]:
    """Days a reading of `ind` stays current, or None for what has no rule here (lab panels have their own, in risk.PANELS)."""
    if ind in INDICATORS:
        return INDICATORS[ind]["max_age"]
    return max_age_for(OTHER_MEASURED_EVERY[ind]) if ind in OTHER_MEASURED_EVERY else None


# Where each cognitive or self-report indicator comes from. None of the numbers is a published value.
INDICATOR_NOTES: Dict[str, dict] = {
    "dsst": {"source": "prototype assumption", "verified": False,
             "note": "Correct answers in 60 s of a digit-symbol task. Baseline and spread are fictional, same as data/recipes.json."},
    "span": {"source": "prototype assumption", "verified": False,
             "note": "Longest forward digit span. Baseline and spread are fictional, same as data/recipes.json."},
    "kss": {"source": "prototype assumption", "verified": False,
            "note": "Karolinska Sleepiness Scale, 1 to 9. The scale is published; the personal baseline and spread are fictional."},
    "tlx": {"source": "prototype assumption", "verified": False,
            "note": "NASA-TLX raw score, 0 to 100. The scale is published; the personal baseline and spread are fictional."},
}

# ---------------------------------------------------------------- body systems (what the 3D body shows)
SYSTEMS: Dict[str, dict] = {
    "brain": {"name": "Brain & mind", "area": "mental", "indicators": ["sleep", "react", "mood", "stress", "social", "dsst", "span", "kss", "tlx"],
              "space": "Isolation, confinement, noise and shifted light cycles erode sleep, mood and focus. NASA lists behavioural health among the top risks of long missions.",
              "hazard": "Isolation & confinement"},
    "eyes": {"name": "Eyes & vision", "area": "physical", "indicators": [],
             "space": "Fluids shift toward the head in 0 g. After months, some astronauts develop swelling at the back of the eye (SANS). A weekly Amsler grid is a quick screen.",
             "hazard": "Altered gravity"},
    "heart": {"name": "Heart & circulation", "area": "physical", "indicators": ["hr", "sbp", "dbp", "vo2"],
              "space": "Without gravity the heart works less and blood volume drops. Back under gravity, standing up can make you faint.",
              "hazard": "Altered gravity"},
    "lungs": {"name": "Lungs & breathing", "area": "physical", "indicators": ["spo2"],
              "space": "Cabin air is recycled. Carbon dioxide builds up faster than on Earth and dust on the Moon and Mars is fine and sharp.",
              "hazard": "Hostile, closed environment"},
    "skeleton": {"name": "Bones", "area": "physical", "indicators": ["bone"],
                 "space": "Weight-bearing bones lose mineral in 0 g, on the order of 1% a month without countermeasures. Resistive exercise slows it.",
                 "hazard": "Altered gravity"},
    "muscles": {"name": "Muscles", "area": "physical", "indicators": ["exer", "grip"],
                "space": "Leg and back muscles shrink fast without load. Daily resistive exercise is the main defence.",
                "hazard": "Altered gravity"},
    "gut": {"name": "Gut & nutrition", "area": "physical", "indicators": ["gluc"],
            "space": "Appetite falls, food is packaged and the gut microbiome shifts. Weight loss is common on long missions.",
            "hazard": "Distance from Earth"},
    "kidneys": {"name": "Kidneys & hydration", "area": "physical", "indicators": ["water"],
                "space": "Bone mineral ends up in urine and thirst fades, which raises the risk of kidney stones.",
                "hazard": "Altered gravity"},
    "immune": {"name": "Blood & immunity", "area": "physical", "indicators": ["temp"],
               "space": "Stress, radiation and confinement change immune cells. Latent viruses can wake up. Lymphocytes are among the first cells to drop after radiation.",
               "hazard": "Radiation"},
    "skin": {"name": "Radiation exposure", "area": "physical", "indicators": [],
             "space": "Outside Earth's magnetic field, galactic cosmic rays and solar storms add dose every day. The total is tracked against a career limit.",
             "hazard": "Radiation"},
}
REGION_SYSTEM = {"head": "brain", "torso": "skin", "arm": "muscles", "hand": "muscles", "leg": "muscles", "foot": "muscles"}

# ---------------------------------------------------------------- goals
EXERCISE_BY_PLACE = {
    "earth": ("1 h of strength and running", 60),
    "rocket": ("Stretch hands, feet and neck every hour", 20),
    "iss": ("2 h of exercise: resistance and treadmill", 120),
    "transit": ("2 h of exercise: resistance and bike", 120),
    "moon": ("1 h of resistance exercise", 60),
    "mars": ("1 h of resistance and a suited walk", 60),
    "moon_rover": ("30 min of resistance bands in the rover cabin", 30),
    "mars_rover": ("30 min of resistance bands in the rover cabin", 30),
}
WINDOW_BY_PLACE = {
    "earth": "Walk outside for 15 min",
    "rocket": "Watch Earth from the window for 5 min",
    "iss": "5 min in the cupola, watching Earth",
    "transit": "5 min at the porthole: find the blue dot",
    "moon": "Watch Earth in the lunar sky for 5 min",
    "mars": "Watch the blue Martian sunset",
    "moon_rover": "5 min at the rover window, watching Earth over the horizon",
    "mars_rover": "5 min at the rover window, watching the horizon",
}

# sys links the goal to a body system.
PERSONAL_GOALS: List[dict] = [
    {"id": "exercise", "area": "physical", "sys": "muscles", "why": "Without weight, bone and muscle waste away. Daily exercise is the main defence."},
    {"id": "water", "area": "physical", "sys": "kidneys", "title": "Drink 2.5 L of water", "why": "Thirst fades in space but your kidneys still need it."},
    {"id": "vitals", "area": "physical", "sys": "heart", "title": "Measure pressure, pulse and temperature", "why": "Canary spots change early by comparing you with your own normal.", "action": "vitals"},
    {"id": "mobility", "area": "physical", "sys": "muscles", "title": "10 min of mobility and stretching", "why": "Spine and hips stiffen without load."},
    {"id": "calcium", "area": "physical", "sys": "skeleton", "title": "Calcium and vitamin D with breakfast", "why": "No sunlight on board: bones depend on what you eat."},
    {"id": "amsler", "area": "physical", "sys": "eyes", "title": "Vision check (Amsler grid, 1 min)", "why": "A quick screen for eye changes caused by fluid shift.", "action": "amsler", "space_only": True},
    {"id": "sleep", "area": "mental", "sys": "brain", "title": "Sleep at least 7 h", "why": "Short sleep slows your reactions before you feel it."},
    {"id": "pvt", "area": "mental", "sys": "brain", "title": "Reaction test (1 min)", "why": "It measures the tiredness you do not feel.", "action": "pvt"},
    {"id": "mood", "area": "mental", "sys": "brain", "title": "Mood check-in (30 s)", "why": "Only you and the medical team see it. A hard day counts the same as a good one.", "action": "mood"},
    {"id": "meditate", "area": "mental", "sys": "brain", "title": "10 min of meditation, prayer or slow breathing", "why": "A moment that is yours. Fill it with what gives you meaning."},
    {"id": "read", "area": "mental", "sys": "brain", "title": "Read for 20 min, not work", "why": "Deep attention on something that is not the mission."},
    {"id": "social", "area": "mental", "sys": "brain", "title": "30 min with the crew, off duty", "why": "Time together off the clock is what keeps a crew a team."},
    {"id": "leisure", "area": "mental", "sys": "brain", "title": "A film, series or album you enjoy", "why": "Rest the part of you that is always on watch."},
    {"id": "home", "area": "mental", "sys": "brain", "why": "Staying close to people at home protects you most on long missions."},
    {"id": "window", "area": "mental", "sys": "brain", "why": "Looking far away reminds you why you are here."},
    {"id": "journal", "area": "mental", "sys": "brain", "title": "Write three lines in your journal", "why": "Naming the day makes it lighter."},
]
PERSONAL_BY_ID = {g["id"]: g for g in PERSONAL_GOALS}

# Weekly crew missions. `metric` says how progress is counted from the last 7 days. A count goal has `per_person`: its target
# is that times the number of people (6 exercise sessions each, so 24 for a crew of four). A `all_done` goal needs most of the
# crew (goals.crew_quorum) on each of its days.
TEAM_GOALS: List[dict] = [
    # Counts the routine exercise goal ticked, never the measured exercise minutes: those are health data.
    {"id": "team_exercise", "area": "physical", "title": "Crew exercise: {target} sessions this week", "per_person": 6, "what": "Every exercise session anyone on the crew completes adds one to the total.", "unit": "sessions", "metric": "count:exercise"},
    {"id": "team_meals", "area": "mental", "title": "Share a meal as a crew 5 times", "target": 5, "what": "A day counts when most of the crew spends their off-duty time together.", "unit": "meals", "metric": "all_done:social"},
    {"id": "team_checkins", "area": "mental", "title": "Crew mood check-ins on 6 of 7 days", "target": 6, "what": "A day counts when most of the crew has done their mood check-in.", "unit": "days", "metric": "all_done:mood"},
    {"id": "team_movie", "area": "mental", "title": "Movie night together, twice", "target": 2, "what": "A night counts when most of the crew takes time for something they enjoy.", "unit": "nights", "metric": "all_done:leisure"},
    {"id": "team_mind", "area": "mental", "title": "Crew mind: {target} meditation sessions", "per_person": 5, "what": "Every meditation, prayer or slow-breathing session adds one to the total.", "unit": "sessions", "metric": "count:meditate"},
    {"id": "team_books", "area": "mental", "title": "Book club: {hours} hours of reading", "per_person": 150, "what": "Every reading session adds twenty minutes to the crew's total.", "unit": "min", "metric": "count20:read"},
    {"id": "team_water", "area": "physical", "title": "Crew hydrated: 2.5 L on 6 days of 7", "target": 6, "what": "A day counts when most of the crew reaches their water goal.", "unit": "days", "metric": "all_done:water"},
]

BADGES: List[dict] = [
    {"id": "iron_bones", "name": "Iron Bones", "desc": "Exercise goal done 30 times", "goal": "exercise", "count": 30, "area": "physical"},
    {"id": "hydro", "name": "Steady Flow", "desc": "Water goal done 40 times", "goal": "water", "count": 40, "area": "physical"},
    {"id": "still_water", "name": "Still Water", "desc": "20 meditation sessions", "goal": "meditate", "count": 20, "area": "mental"},
    {"id": "deep_reader", "name": "Deep Reader", "desc": "25 reading sessions", "goal": "read", "count": 25, "area": "mental"},
    {"id": "crew_glue", "name": "Crew Glue", "desc": "30 off-duty sessions with the crew", "goal": "social", "count": 30, "area": "mental"},
    {"id": "honest_signal", "name": "Honest Signal", "desc": "60 mood check-ins. Rewards reporting, not feeling good", "goal": "mood", "count": 60, "area": "mental"},
    {"id": "blue_dot", "name": "Pale Blue Dot", "desc": "Looked homeward 20 times", "goal": "window", "count": 20, "area": "mental"},
    {"id": "fortnight", "name": "Fortnight", "desc": "14-day streak", "streak": 14, "area": "both"},
    {"id": "first_responder", "name": "First Responder", "desc": "Took part in a guided response", "emergency": True, "area": "both"},
]

# ---------------------------------------------------------------- hazard matrix (hazard x indicator)
# The team's matrix "matriz-perigos-indicadores". Hazards: R radiation, I isolation & confinement, D distance from
# Earth, G altered gravity, E hostile closed environment. Keys are indicator ids, check-in kinds or evidence names
# ("dose", "amsler", "symptoms"). Every link carries its `source` as the team wrote it and `verified: False`: the
# "HRP" and "Patel 2020" sources are still to be checked against the HRP risk pages and the article. These are
# possible factors for a signal, never a cause.
_P, _H = "Patel 2020", "HRP"
HAZARDS_BY_INDICATOR: Dict[str, List[dict]] = {}


def _link(keys, hazard: str, why: str, source: str, verified: bool = False) -> None:
    for k in ([keys] if isinstance(keys, str) else keys):
        HAZARDS_BY_INDICATOR.setdefault(k, []).append({"hazard": hazard, "why": why, "source": source, "verified": verified})


_link("sleep", "I", "routine and monotony", f"{_P} (BMed); {_H}")
_link("sleep", "E", "noise, light, CO2", f"{_P} (BMed); {_H}")
_link("react", "R", "effect on the nervous system", _P)
_link("react", "I", "fatigue, stress", _P)
_link("react", "E", "high CO2", _P)
_link("mood", "I", "isolation, conflicts", f"{_P} (BMed)")
_link("mood", "D", "no real-time contact", f"{_P} (BMed)")
_link("mood", "E", "confinement", f"{_P} (BMed)")
_link(["stress", "cortisol"], "I", "confinement", f"{_P} (BMed)")
_link(["stress", "cortisol"], "D", "distance from home", f"{_P} (BMed)")
_link(["stress", "cortisol"], "E", "noise, confinement", f"{_P} (BMed)")
_link("social", "I", "isolation", f"{_P} (BMed)")
_link(["hr", "sbp", "dbp"], "R", "long-term cardiovascular disease", f"{_P}; {_H}")
_link("hr", "G", "deconditioning, readaptation", f"{_P}; {_H}")
_link(["sbp", "dbp"], "G", "fluid shift, dizziness back under gravity", f"{_P}; {_H}")
_link("spo2", "E", "recirculated air, CO2, dust", _H)
_link("temp", "E", "microbes in a closed environment", _H)
_link("gluc", "D", "limited diet", f"{_P} (nutrition); {_H}")
_link("gluc", "G", "inactivity", f"{_P} (nutrition); {_H}")
_link("weight", "I", "appetite drops", f"{_P} (nutrition)")
_link("weight", "D", "limited food, no resupply", f"{_P} (nutrition)")
_link("weight", "G", "muscle loss", f"{_P} (nutrition)")
_link("water", "D", "recycled water", _H)
_link("water", "G", "thirst fades", _H)
_link("exer", "I", "motivation", _H)
_link("exer", "G", "a countermeasure is needed", _H)
_link("exer", "E", "little space, equipment", _H)
_link("grip", "G", "no load", _H)
_link("bone", "D", "nutrition (vitamin D)", _H)
_link("bone", "G", "no load", _H)
_link("urine_calcium", "G", "calcium leaves the bone", f"{_H} (kidney stones)")
_link("creatinine", "G", "hydration, muscle", _H)
_link("vo2", "G", "deconditioning without load", f"{_H}; NASA-STD-3001 V1 4001-4004")
_link("calcium", "G", "calcium leaves the bone", f"{_H} (kidney stones); real data OSD-575")
_link("potassium", "D", "limited diet, hydration", f"{_P} (nutrition); real data OSD-575")
_link("crp", "I", "stress", f"{_P}; {_H}; real data OSD-575")
_link("crp", "E", "microbes", f"{_P}; {_H}; real data OSD-575")
_link("vitamin_d", "E", "no sunlight", _H)
_link(["wbc", "lym", "neu", "hgb", "hct", "plt", "rbc"], "R", "drops first after a dose", f"{_P}; {_H}; real data OSD-569")
_link(["wbc", "lym", "neu", "hgb", "hct", "plt", "rbc"], "I", "stress", f"{_P}; {_H}; real data OSD-569")
_link(["wbc", "lym", "neu", "hgb", "hct", "plt", "rbc"], "E", "microbes", f"{_P}; {_H}; real data OSD-569")
_link("amsler", "G", "fluid shift towards the head", f"{_P} (SANS)")
_link("amsler", "E", "CO2 as a cofactor", f"{_P} (SANS)")
_link("dose", "R", "direct", "real data RadLab, DONKI")
_link("co2", "E", "direct", f"{_P} (SANS cofactor)")
# Links the matrix does not have and the code suggests (the hazard each body system already declares in SYSTEMS).
# Not silent: marked as prototype assumptions, to confirm with the team.
_ASSUME = "prototype assumption (hazard of the body system in SYSTEMS)"
_link(["dsst", "span", "kss", "tlx"], "I", "the brain system's hazard in SYSTEMS", _ASSUME)
_link("urine_volume", "G", "the kidney system's hazard in SYSTEMS", _ASSUME)
# Rows of the matrix with no indicator in the catalog yet: cytokines (OSD-575/656).
HAZARD_ROWS_WITHOUT_INDICATOR = ["cytokines"]


# ---------------------------------------------------------------- what an incoming measurement may look like
# One entry per measurement the system accepts (POST /api/observations and mission packages): the units it may be sent
# in and a plausibility range [lo, hi]. The range catches typos, unit slips and broken sensors; it is NOT a clinical
# range and says nothing about what is healthy (prototype assumption, `verified: False`). Vitals reuse the limits of
# the self check-in forms (selftests.VITALS_LIMITS). The lab panel and the cabin sensors are listed here too, because
# the observation table carries them although they are not in INDICATORS. Adding a key to INDICATORS itself would
# change every health snapshot, so the plausibility ranges live apart.
ACCEPT: Dict[str, dict] = {
    "sleep": {"units": ("h",), "range": (0, 24)},
    "react": {"units": ("ms",), "range": (50, 10000)},
    "mood": {"units": ("/5",), "range": (0, 5)},
    "stress": {"units": ("/5",), "range": (0, 5)},
    "social": {"units": ("min",), "range": (0, 1440)},
    "dsst": {"units": ("correct", "correct/60s"), "range": (0, 500)},
    "span": {"units": ("digits",), "range": (0, 30)},
    "kss": {"units": ("/9",), "range": (0, 9)},
    "tlx": {"units": ("/100",), "range": (0, 100)},
    "hr": {"units": ("bpm",), "range": (25, 250)},
    "sbp": {"units": ("mmHg",), "range": (60, 260)},
    "dbp": {"units": ("mmHg",), "range": (30, 180)},
    "spo2": {"units": ("%",), "range": (50, 100)},
    "temp": {"units": ("°C",), "range": (30, 45)},
    "gluc": {"units": ("mg/dL",), "range": (20, 800)},
    "water": {"units": ("L",), "range": (0, 20)},
    "exer": {"units": ("min",), "range": (0, 1440)},
    "grip": {"units": ("kg",), "range": (0, 120)},
    "bone": {"units": ("g/cm²", "g/cm2"), "range": (0.2, 2.5)},
    "vo2": {"units": ("mL/kg/min",), "range": (5, 100)},
    "hrv": {"units": ("ms",), "range": (0, 400)},
    "weight": {"units": ("kg",), "range": (20, 300)},
    # blood and urine panels
    "wbc": {"units": ("10^3/uL",), "range": (0.2, 100)},
    "lym": {"units": ("cells/uL",), "range": (0, 20000)},
    "neu": {"units": ("cells/uL",), "range": (0, 40000)},
    "hgb": {"units": ("g/dL",), "range": (3, 25)},
    "hct": {"units": ("percent", "%"), "range": (10, 70)},
    "plt": {"units": ("10^3/uL",), "range": (5, 2000)},
    "rbc": {"units": ("10^6/uL",), "range": (1, 10)},
    "creatinine": {"units": ("mg/dL",), "range": (0.1, 15)},
    "potassium": {"units": ("mmol/L",), "range": (1, 10)},
    "calcium": {"units": ("mg/dL",), "range": (4, 20)},
    "crp": {"units": ("mg/L",), "range": (0, 1000)},
    "urine_calcium": {"units": ("mg/24h",), "range": (0, 3000)},
    "urine_volume": {"units": ("mL/24h",), "range": (0, 10000)},
    "cortisol": {"units": ("ug/dL",), "range": (0, 100)},
    "tsh": {"units": ("mIU/L",), "range": (0, 100)},
    "vitamin_d": {"units": ("ng/mL",), "range": (0, 200)},
    # cabin air
    "co2": {"units": ("ppm",), "range": (200, 100000)},
    # the dosimeter: accepted as a measurement (crew badge or cabin), but NOT an INDICATOR (no baseline, no alert of its
    # own): the dose model reads it. `dose_rate`: absorbed dose in mGy per day; `dose_eq_rate`: dose equivalent in mSv per day.
    "dose_rate": {"units": ("mGy/day", "mSv/day"), "range": (0, 100)},  # absorbed dose rate; mSv/day is read as the dose equivalent (legacy)
    "dose_eq_rate": {"units": ("mSv/day",), "range": (0, 100)},         # dose-equivalent rate
}
ACCEPT_SOURCE = {"source": "prototype assumption: typing limits, not clinical ranges", "verified": False}
CABIN_ID = "cabin"  # the crew id of cabin sensors (air, dosimeter)
