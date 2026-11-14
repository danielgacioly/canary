"""Self-tests and logs an astronaut can run any time from the Tests page.

Cognition comes from the kind of tasks in NASA's Cognition battery (reaction time, processing
speed, working memory). Feelings use short validated scales that are free to use: the Karolinska
Sleepiness Scale, NASA-TLX for workload (NASA Ames) and PHQ-2 / GAD-2 (public domain). Logs record
habits that help read the numbers. Results are private: the astronaut and the medical team.
"""
from typing import Optional

TESTS = [
    # cognition
    {"id": "pvt", "group": "Cognition", "name": "Reaction time", "measures": "Alertness you cannot feel", "minutes": 1,
     "source": "Psychomotor vigilance, as in NASA's Cognition battery"},
    {"id": "dsst", "group": "Cognition", "name": "Processing speed", "measures": "How fast you match symbols to digits", "minutes": 1,
     "source": "Digit Symbol Substitution, as in NASA's Cognition battery"},
    {"id": "span", "group": "Cognition", "name": "Working memory", "measures": "How many digits you can hold in mind", "minutes": 2,
     "source": "Forward digit span"},
    # how you feel
    {"id": "mood", "group": "How you feel", "name": "Mood and stress", "measures": "Two quick 1 to 5 ratings", "minutes": 0.5,
     "source": "Canary check-in"},
    {"id": "kss", "group": "How you feel", "name": "Sleepiness", "measures": "How sleepy you are right now", "minutes": 0.2,
     "source": "Karolinska Sleepiness Scale"},
    {"id": "tlx", "group": "How you feel", "name": "Workload", "measures": "How demanding today's work was", "minutes": 2,
     "source": "NASA Task Load Index (NASA-TLX), NASA Ames"},
    {"id": "wellbeing", "group": "How you feel", "name": "Wellbeing", "measures": "Low mood and worry over the last two weeks", "minutes": 1,
     "source": "PHQ-2 and GAD-2 (public domain)"},
    # body
    {"id": "vitals", "group": "Body", "name": "Vital signs", "measures": "Pulse, pressure, temperature, oxygen", "minutes": 2,
     "source": "On-board device or typed in"},
    {"id": "amsler", "group": "Body", "name": "Vision", "measures": "Changes at the back of the eye", "minutes": 1,
     "source": "Amsler grid"},
    {"id": "symptoms", "group": "Body", "name": "Symptoms", "measures": "Anything that hurts or feels off", "minutes": 1,
     "source": "Canary symptom log"},
    # logs
    {"id": "sleep", "group": "Logs", "name": "Sleep diary", "measures": "When you slept and how well", "minutes": 0.5,
     "source": "Sleep diary"},
    {"id": "reading", "group": "Logs", "name": "Reading", "measures": "What you are reading and for how long", "minutes": 0.5,
     "source": "Canary reading log"},
    {"id": "journal", "group": "Logs", "name": "Journal", "measures": "Three lines about your day", "minutes": 2,
     "source": "Your words stay on the screen; only the fact that you wrote is saved"},
]
TEST_IDS = {t["id"] for t in TESTS}
KSS = ["Extremely alert", "Very alert", "Alert", "Rather alert", "Neither alert nor sleepy", "Some signs of sleepiness",
       "Sleepy, no effort to stay awake", "Sleepy, some effort to stay awake", "Very sleepy, fighting sleep"]


# Typing limits for the vital signs: wide on purpose, only to catch typos and impossible numbers.
# They are NOT clinical ranges and say nothing about what is healthy.
VITALS_LIMITS = {"hr": (20, 250), "bp": (50, 260), "temp": (30, 45), "spo2": (50, 100)}
VITALS_LIMITS_SOURCE = {"source": "prototype assumption: typing limits, not clinical ranges", "verified": False}


def validate(kind: str, payload: dict) -> Optional[str]:
    """An error message when the payload cannot be a real measurement, else None. Only vitals are checked."""
    if kind != "vitals":
        return None
    for k, (lo, hi) in VITALS_LIMITS.items():
        v = payload.get(k)
        if v is None:
            continue
        if isinstance(v, bool) or not isinstance(v, (int, float)) or v != v:
            return f"{k} must be a number"
        if not lo <= v <= hi:
            return f"{k} {v} is outside what can be typed ({lo} to {hi}). Check the number and try again."
    return None


def _hours(bed: str, wake: str) -> float:
    bh, bm = (int(x) for x in bed.split(":"))
    wh, wm = (int(x) for x in wake.split(":"))
    mins = (wh * 60 + wm) - (bh * 60 + bm)
    return round((mins + 24 * 60) % (24 * 60) / 60, 1)


def normalise(kind: str, payload: dict) -> dict:
    """Derived numbers saved with the raw answers; the journal text is never kept."""
    p = dict(payload)
    if kind == "sleep" and p.get("bed") and p.get("wake"):
        p["hours"] = _hours(p["bed"], p["wake"])
    if kind == "tlx" and p.get("scores"):
        p["raw"] = round(sum(p["scores"].values()) / len(p["scores"]))
    if kind == "wellbeing" and p.get("answers"):
        a = p["answers"]
        p["phq2"], p["gad2"] = a[0] + a[1], a[2] + a[3]
    if kind == "journal":
        p = {"lines": int(p.get("lines", 0))}
    return p


# kind -> [(payload field, indicator)] for the tests that get a conclusion.
CONCLUDES = {"pvt": [("ms", "react")], "dsst": [("correct", "dsst")], "span": [("span", "span")], "kss": [("level", "kss")],
             "tlx": [("raw", "tlx")], "mood": [("mood", "mood")], "sleep": [("hours", "sleep")],
             "vitals": [("hr", "hr"), ("bp", "bp"), ("temp", "temp"), ("spo2", "spo2")]}
_POP_TEXT = {"in": "Within the normal human range", "out": "Outside the usual adult range", "critical": "Past the safety limit"}
_DIRECTION = {"react": ("slower", "faster")}  # words for above / below your own average
_RANK = {"critical": 2, "out": 1, "in": 0}


def conclusion(kind: str, payload: dict, crew_id: str) -> Optional[dict]:
    """What a result means against the two references: the population range (safety) and the person's own
    pre-flight average (early warning). Risk words only, never a diagnosis. None for tests with no number to compare."""
    from . import health, reference
    from .catalog import CREW_BY_ID, INDICATORS
    base = health.baselines(crew_id)
    picks = []
    for field, ind in CONCLUDES.get(kind, []):
        if payload.get(field) is None:
            continue
        v = float(payload[field])
        pop = reference.check(ind, CREW_BY_ID[crew_id]["sex"], v)
        z = (v - base[ind]["mean"]) / base[ind]["sd"]
        picks.append((_RANK[pop["status"]], abs(z), ind, v, pop, z))
    if not picks:
        return None
    _, _, ind, v, pop, z = max(picks, key=lambda t: (t[0], t[1]))
    has_range = pop["low"] is not None or pop["high"] is not None
    population = _POP_TEXT[pop["status"]] if has_range else "No population range for this scale"
    mean = base[ind]["mean"]
    pct = round(abs(100 * (v - mean) / mean)) if mean else 0
    if pct < 3:
        personal = "in line with your own average"
    else:
        if ind in _DIRECTION:
            personal = f"{pct}% {_DIRECTION[ind][0] if v > mean else _DIRECTION[ind][1]} than your own average"
        else:
            personal = f"{pct}% {'above' if v > mean else 'below'} your own average"
    subject = f"{INDICATORS[ind]['name']}: " if kind == "vitals" else ""
    return {"population": population, "personal": personal, "text": f"{subject}{population}, {personal}."}


def goal_for(kind: str, p: dict) -> Optional[str]:
    """The daily goal a test or log completes, if any."""
    if kind in ("mood", "pvt", "amsler", "vitals", "journal"):
        return kind
    if kind == "reading" and float(p.get("minutes") or 0) >= 20:
        return "read"
    if kind == "sleep" and float(p.get("hours") or 0) >= 7:
        return "sleep"
    return None


def summary(kind: str, p: dict) -> str:
    try:
        return {
            "pvt": lambda: f"{p['ms']} ms",
            "dsst": lambda: f"{p['correct']} correct in 60 s",
            "span": lambda: f"{p['span']} digits",
            "mood": lambda: f"mood {p['mood']}/5, stress {p['stress']}/5",
            "kss": lambda: f"{p['level']}/9, {KSS[int(p['level']) - 1].lower()}",
            "tlx": lambda: f"workload {p['raw']}/100",
            "wellbeing": lambda: "worth talking about" if max(p["phq2"], p["gad2"]) >= 3 else "no flags",
            "vitals": lambda: ", ".join(f"{k} {v}" for k, v in p.items() if v is not None) or "sensor values",
            "amsler": lambda: "lines distorted" if p.get("distortion") else "all straight",
            "symptoms": lambda: ", ".join(p.get("items", [])) or "none",
            "sleep": lambda: f"{p['hours']} h, quality {p['quality']}/5",
            "reading": lambda: f"{p.get('title') or 'a book'}, {p.get('minutes')} min",
            "journal": lambda: "written",
        }[kind]()
    except (KeyError, TypeError, ValueError, IndexError):
        return "saved"
