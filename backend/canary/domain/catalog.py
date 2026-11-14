"""Static mission data: places, crew, indicators, body systems, goals, badges and the demo story.

Everything numeric that comes from literature is marked `source` so it can be
checked before the pitch. Crew members and their baselines are fictional.
"""
from typing import Dict, List

# ---------------------------------------------------------------- places
LOCATIONS: Dict[str, dict] = {
    "earth": {"name": "Earth", "sub": "Pre-flight training", "gravity_key": "g1", "gravity": "1 g",
              "delay_s": 0, "reply": "Live", "hospital": "Minutes", "dose_rate": 0.01,
              "what": "Canary is learning what your normal looks like. No alerts yet."},
    "rocket": {"name": "Launch", "sub": "First 72 hours", "gravity_key": "g0", "gravity": "0 g",
               "delay_s": 0, "reply": "Live", "hospital": "Hours", "dose_rate": 0.5,
               "what": "Your body is adjusting to weightlessness. Short goals, patient alerts."},
    "iss": {"name": "Space station", "sub": "Low Earth orbit", "gravity_key": "g0", "gravity": "0 g",
            "delay_s": 0, "reply": "Live", "hospital": "About 1 day", "dose_rate": 0.5,
            "what": "Two hours of exercise a day protect bone and muscle."},
    "moon": {"name": "Moon", "sub": "Lunar surface", "gravity_key": "gp", "gravity": "1/6 g",
             "delay_s": 1.3, "reply": "3 seconds", "hospital": "About 3 days", "dose_rate": 1.37,
             "what": "No magnetic shield. Every walk outside depends on space weather."},
    "transit": {"name": "Transit to Mars", "sub": "Deep space", "gravity_key": "g0", "gravity": "0 g",
                "delay_s": 300, "reply": "10 minutes", "hospital": "No way back", "dose_rate": 1.8,
                "what": "Earth is too far to help in time. Canary guides the crew first, then reports."},
    "mars": {"name": "Mars", "sub": "Gale crater", "gravity_key": "gp", "gravity": "3/8 g",
             "delay_s": 840, "reply": "28 minutes", "hospital": "About 500 days", "dose_rate": 0.67,
             "what": "Your body is relearning weight after months in 0 g. Stand up slowly."},
}
DOSE_SOURCE = "Typical daily dose by place from published ISS, Apollo, MSL cruise and Curiosity RAD figures; to be verified."
CAREER_LIMIT_MSV = 600  # NASA career limit, NASA-STD-3001 (2022). To be verified before quoting.


def day_label(day: int, location: str, leg_start: int = 0) -> str:
    """L-30 before launch, Sol N on Mars (counted from landing), Day N otherwise."""
    if day < 0:
        return f"L{day}"
    if location == "mars":
        return f"Sol {day - leg_start}"
    return f"Day {day}"


# ---------------------------------------------------------------- crew (fictional)
CREW: List[dict] = [
    {"id": "h", "name": "Helena Duarte", "role": "Commander", "initials": "HD", "home": "São Paulo, Brazil",
     "cbc_subject": "C001", "age": 46,
     "base": {"sleep": 7.4, "react": 265, "mood": 4.1, "stress": 2.0, "social": 70, "hr": 58, "bp": 116,
              "temp": 36.5, "spo2": 98, "gluc": 88, "exer": 95, "water": 2.6, "grip": 34, "bone": 0}},
    {"id": "k", "name": "Kenji Mori", "role": "Crew medical officer", "initials": "KM", "home": "Sapporo, Japan",
     "cbc_subject": "C002", "age": 41,
     "base": {"sleep": 7.0, "react": 280, "mood": 3.9, "stress": 2.2, "social": 60, "hr": 62, "bp": 121,
              "temp": 36.6, "spo2": 97.5, "gluc": 92, "exer": 90, "water": 2.4, "grip": 40, "bone": 0}},
    {"id": "a", "name": "Amara Okafor", "role": "Flight engineer", "initials": "AO", "home": "Lagos, Nigeria",
     "cbc_subject": "C003", "age": 38,
     "base": {"sleep": 7.8, "react": 250, "mood": 4.3, "stress": 1.8, "social": 90, "hr": 55, "bp": 110,
              "temp": 36.4, "spo2": 98.5, "gluc": 85, "exer": 110, "water": 2.8, "grip": 31, "bone": 0}},
    {"id": "t", "name": "Tomás Rivera", "role": "Geologist", "initials": "TR", "home": "Valparaíso, Chile",
     "cbc_subject": "C004", "age": 44,
     "base": {"sleep": 6.9, "react": 290, "mood": 3.8, "stress": 2.4, "social": 55, "hr": 66, "bp": 124,
              "temp": 36.7, "spo2": 97.8, "gluc": 95, "exer": 85, "water": 2.3, "grip": 44, "bone": 0}},
]
CREW_BY_ID = {c["id"]: c for c in CREW}

# ---------------------------------------------------------------- indicators
# dir: which way is bad. sd: personal day-to-day spread used for the z-score.
INDICATORS: Dict[str, dict] = {
    "sleep": {"name": "Sleep", "unit": "h", "area": "mental", "facet": "Rest", "dir": "low", "sd": 0.5, "dp": 1},
    "react": {"name": "Reaction time", "unit": "ms", "area": "mental", "facet": "Focus", "dir": "high", "sd": 18, "dp": 0},
    "mood": {"name": "Mood", "unit": "/5", "area": "mental", "facet": "Mood", "dir": "low", "sd": 0.35, "dp": 1},
    "stress": {"name": "Stress", "unit": "/5", "area": "mental", "facet": "Stress", "dir": "high", "sd": 0.4, "dp": 1},
    "social": {"name": "Time with crew", "unit": "min", "area": "mental", "facet": "Connection", "dir": "low", "sd": 15, "dp": 0},
    "hr": {"name": "Resting pulse", "unit": "bpm", "area": "physical", "dir": "both", "sd": 3, "dp": 0},
    "bp": {"name": "Blood pressure", "unit": "mmHg", "area": "physical", "dir": "both", "sd": 5, "dp": 0},
    "spo2": {"name": "Blood oxygen", "unit": "%", "area": "physical", "dir": "low", "sd": 0.7, "dp": 0},
    "temp": {"name": "Temperature", "unit": "°C", "area": "physical", "dir": "high", "sd": 0.15, "dp": 1},
    "gluc": {"name": "Fasting glucose", "unit": "mg/dL", "area": "physical", "dir": "both", "sd": 6, "dp": 0},
    "water": {"name": "Water", "unit": "L", "area": "physical", "dir": "low", "sd": 0.25, "dp": 1},
    "exer": {"name": "Exercise", "unit": "min", "area": "physical", "dir": "low", "sd": 12, "dp": 0},
    "grip": {"name": "Grip strength", "unit": "kg", "area": "physical", "dir": "low", "sd": 1.5, "dp": 1},
    "bone": {"name": "Bone density (est.)", "unit": "%", "area": "physical", "dir": "low", "sd": 1.5, "dp": 1},
}

# ---------------------------------------------------------------- body systems (what the 3D body shows)
SYSTEMS: Dict[str, dict] = {
    "brain": {"name": "Brain & mind", "area": "mental", "indicators": ["sleep", "react", "mood", "stress", "social"],
              "space": "Isolation, confinement, noise and shifted light cycles erode sleep, mood and focus. NASA lists behavioural health among the top risks of long missions.",
              "hazard": "Isolation & confinement"},
    "eyes": {"name": "Eyes & vision", "area": "physical", "indicators": [],
             "space": "Fluids shift toward the head in 0 g. After months, some astronauts develop swelling at the back of the eye (SANS). A weekly Amsler grid is a quick screen.",
             "hazard": "Altered gravity"},
    "heart": {"name": "Heart & circulation", "area": "physical", "indicators": ["hr", "bp"],
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
}
WINDOW_BY_PLACE = {
    "earth": "Walk outside for 15 min",
    "rocket": "Watch Earth from the window for 5 min",
    "iss": "5 min in the cupola, watching Earth",
    "transit": "5 min at the porthole: find the blue dot",
    "moon": "Watch Earth in the lunar sky for 5 min",
    "mars": "Watch the blue Martian sunset",
}

# xp is the reward for doing it. sys links the goal to a body system.
PERSONAL_GOALS: List[dict] = [
    {"id": "exercise", "area": "physical", "xp": 30, "sys": "muscles", "why": "Without weight, bone and muscle waste away. Daily exercise is the main defence."},
    {"id": "water", "area": "physical", "xp": 10, "sys": "kidneys", "title": "Drink 2.5 L of water", "why": "Thirst fades in space but your kidneys still need it."},
    {"id": "vitals", "area": "physical", "xp": 10, "sys": "heart", "title": "Measure pressure, pulse and temperature", "why": "Canary spots change early by comparing you with your own normal.", "action": "vitals"},
    {"id": "mobility", "area": "physical", "xp": 10, "sys": "muscles", "title": "10 min of mobility and stretching", "why": "Spine and hips stiffen without load."},
    {"id": "calcium", "area": "physical", "xp": 10, "sys": "skeleton", "title": "Calcium and vitamin D with breakfast", "why": "No sunlight on board: bones depend on what you eat."},
    {"id": "amsler", "area": "physical", "xp": 15, "sys": "eyes", "title": "Vision check (Amsler grid, 1 min)", "why": "A quick screen for eye changes caused by fluid shift.", "action": "amsler", "space_only": True},
    {"id": "sleep", "area": "mental", "xp": 20, "sys": "brain", "title": "Sleep at least 7 h", "why": "Short sleep slows your reactions before you feel it."},
    {"id": "pvt", "area": "mental", "xp": 10, "sys": "brain", "title": "Reaction test (1 min)", "why": "It measures the tiredness you do not feel.", "action": "pvt"},
    {"id": "mood", "area": "mental", "xp": 10, "sys": "brain", "title": "Mood check-in (30 s)", "why": "Only you and the medical team see it. Honest answers earn the same XP as good ones.", "action": "mood"},
    {"id": "meditate", "area": "mental", "xp": 15, "sys": "brain", "title": "10 min of meditation, prayer or slow breathing", "why": "A moment that is yours. Fill it with what gives you meaning."},
    {"id": "read", "area": "mental", "xp": 15, "sys": "brain", "title": "Read for 20 min, not work", "why": "Deep attention on something that is not the mission."},
    {"id": "social", "area": "mental", "xp": 15, "sys": "brain", "title": "30 min with the crew, off duty", "why": "Time together off the clock is what keeps a crew a team."},
    {"id": "leisure", "area": "mental", "xp": 10, "sys": "brain", "title": "A film, series or album you enjoy", "why": "Rest the part of you that is always on watch."},
    {"id": "home", "area": "mental", "xp": 15, "sys": "brain", "why": "Staying close to people at home protects you most on long missions."},
    {"id": "window", "area": "mental", "xp": 10, "sys": "brain", "why": "Looking far away reminds you why you are here."},
    {"id": "journal", "area": "mental", "xp": 10, "sys": "brain", "title": "Write three lines in your journal", "why": "Naming the day makes it lighter."},
]
PERSONAL_BY_ID = {g["id"]: g for g in PERSONAL_GOALS}

# Weekly crew missions. `metric` says how progress is counted from the last 7 days.
TEAM_GOALS: List[dict] = [
    {"id": "team_exercise", "area": "physical", "title": "Crew exercise: 2,400 minutes this week", "target": 2400, "unit": "min", "metric": "sum_exer", "xp": 120},
    {"id": "team_meals", "area": "mental", "title": "Share a meal as a crew 5 times", "target": 5, "unit": "meals", "metric": "all_done:social", "xp": 100},
    {"id": "team_checkins", "area": "mental", "title": "Crew mood check-ins on 6 of 7 days", "target": 6, "unit": "days", "metric": "all_done:mood", "xp": 100},
    {"id": "team_movie", "area": "mental", "title": "Movie night together, twice", "target": 2, "unit": "nights", "metric": "all_done:leisure", "xp": 60},
    {"id": "team_mind", "area": "mental", "title": "Crew mind: 20 meditation sessions", "target": 20, "unit": "sessions", "metric": "count:meditate", "xp": 100},
    {"id": "team_books", "area": "mental", "title": "Book club: 10 hours of reading", "target": 600, "unit": "min", "metric": "count20:read", "xp": 80},
    {"id": "team_water", "area": "physical", "title": "Crew hydrated: 2.5 L on 6 days of 7", "target": 6, "unit": "days", "metric": "all_done:water", "xp": 80},
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

LEVEL_STEP = 400  # xp per level, grows linearly


def level_for(xp: int) -> dict:
    lvl, need, acc = 1, LEVEL_STEP, 0
    while xp >= acc + need:
        acc += need
        lvl += 1
        need = LEVEL_STEP + 50 * (lvl - 1)
    return {"level": lvl, "into": xp - acc, "need": need}


# ---------------------------------------------------------------- demo story
STORY: List[dict] = [
    {"loc": "earth", "day": -30, "me": "h", "storm": None, "when": "30 days before launch",
     "text": "The crew measures everything it will measure in space. From here on, Canary compares each person with themselves, never with an average."},
    {"loc": "rocket", "day": 2, "me": "t", "storm": None, "when": "Day 2, in orbit",
     "text": "Tomás has a fast pulse and has barely had any water. Space sickness. The alert already comes with what to do."},
    {"loc": "transit", "day": 147, "me": "h", "storm": None, "when": "Day 147, on the way to Mars",
     "text": "Helena's sleep, mood, focus and time with the crew have been slipping together for two weeks. None would matter alone. Together they do."},
    {"loc": "transit", "day": 152, "me": "h", "storm": "sep", "when": "Day 152, replaying 10 May 2024",
     "text": "This storm really happened: the strongest in 20 years. The readings are NASA's records from that day. What if a crew had been in its path?"},
    {"loc": "transit", "day": 153, "me": "k", "storm": None, "when": "Day 153, dinner",
     "text": "Tomás has a seizure. Earth will not know for 5 minutes. Hold EMERGENCY, pick Seizure and follow the steps."},
    {"loc": "mars", "day": 222, "me": "a", "storm": "mars", "when": "Sol 12 on Mars, replaying 20 May 2024",
     "text": "That day the Curiosity rover measured radiation 51 times above normal. The chart is that record. The crew stays inside."},
]
