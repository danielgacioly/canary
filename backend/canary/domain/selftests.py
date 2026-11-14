"""Self-tests and logs an astronaut can run any time from the Tests page.

Cognition comes from the kind of tasks in NASA's Cognition battery (reaction time, processing
speed, working memory). Feelings use short validated scales that are free to use: the Karolinska
Sleepiness Scale, NASA-TLX for workload (NASA Ames) and PHQ-2 / GAD-2 (public domain). Logs record
habits that help read the numbers. Results are private: the astronaut and the medical team.
"""
from typing import Optional

from . import validation as V
from .validation import FieldError

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
VITALS_LIMITS = {"hr": (25, 250), "bp": (60, 260), "temp": (30, 45), "spo2": (50, 100)}
VITALS_LIMITS_SOURCE = {"source": "prototype assumption: typing limits, not clinical ranges", "verified": False}
_VITALS_LABEL = {"hr": ("Pulse", "bpm", False, None), "bp": ("Systolic pressure", "mmHg", False, None),
                 "temp": ("Temperature", "°C", False, 1), "spo2": ("Oxygen", "%", True, None)}
SYMPTOM_NAMES = ["Headache", "Congestion", "Back pain", "Nausea", "Eye discomfort", "Blurred vision", "Skin irritation",
                 "Trouble sleeping", "Muscle or joint pain", "Dizziness"]
TLX_KEYS = ["mental", "physical", "temporal", "performance", "effort", "frustration"]


def validate(kind: str, payload: dict) -> None:
    """Refuse a payload that cannot be a real answer: raises FieldError({field, message}). The web form checks the same
    rules first; this is the barrier that counts. Absent optional fields are fine, wrong types and out-of-range numbers are not."""
    if not isinstance(payload, dict):
        raise FieldError("payload", "The answers must be an object")
    n = lambda key, label, lo, hi, unit="", **kw: V.number(payload, key, label, lo, hi, unit, **kw)  # noqa: E731
    if kind == "vitals":
        got = [n(k, lab, *VITALS_LIMITS[k], unit, integer=integer, decimals=dec)
               for k, (lab, unit, integer, dec) in _VITALS_LABEL.items()]
        if all(v is None for v in got):
            raise FieldError("form", "Type at least one value")
    elif kind == "pvt":
        n("ms", "Reaction time", 50, 10000, "ms", required=True)
    elif kind == "mood":
        n("mood", "Mood", 1, 5, integer=True, required=True)
        n("stress", "Stress", 1, 5, integer=True, required=True)
    elif kind == "kss":
        n("level", "Sleepiness", 1, 9, integer=True, required=True)
    elif kind == "tlx":
        scores = payload.get("scores")
        if scores is None:
            n("raw", "Workload", 0, 100, required=True)
        else:
            if not isinstance(scores, dict) or not 1 <= len(scores) <= len(TLX_KEYS):
                raise FieldError("scores", "Answer the workload questions")
            for k in scores:
                V.number(scores, k, str(k).capitalize(), 0, 100, field=f"scores.{k}", required=True)
    elif kind == "wellbeing":
        a = payload.get("answers")
        if a is None:
            n("phq2", "PHQ-2", 0, 6, integer=True, required=True)
            n("gad2", "GAD-2", 0, 6, integer=True, required=True)
        else:
            if not isinstance(a, list) or len(a) != 4:
                raise FieldError("answers", "Answer all four questions")
            for i, x in enumerate(a):
                if isinstance(x, bool) or not isinstance(x, int) or not 0 <= x <= 3:
                    raise FieldError(f"answers.{i}", f"Question {i + 1} needs an answer")
    elif kind == "amsler":
        if not isinstance(payload.get("distortion"), bool):
            raise FieldError("distortion", "Say whether the lines look distorted")
    elif kind == "dsst":
        n("correct", "Correct answers", 0, 500, integer=True, required=True)
        n("errors", "Errors", 0, 500, integer=True)
    elif kind == "span":
        n("span", "Digits held", 0, 30, integer=True, required=True)
    elif kind == "symptoms":
        items = payload.get("items")
        if not isinstance(items, list) or any(i not in SYMPTOM_NAMES for i in items) or len(set(items)) != len(items):
            raise FieldError("items", "Pick symptoms from the list")
        n("severity", "Strength", 0, 3, integer=True)
        if items and payload.get("severity") in (None, 0):
            raise FieldError("severity", "Say how strong it is")
        V.text(payload, "note", "Note", max_len=200)
    elif kind == "sleep":
        if payload.get("bed") is not None or payload.get("wake") is not None or payload.get("hours") is None:
            V.clock(payload, "bed", "Lights out")
            V.clock(payload, "wake", "Woke up")
            h = _hours(payload["bed"], payload["wake"])
            if not 1 <= h <= 16:
                raise FieldError("wake", f"Sleep must last between 1 and 16 h (these times give {h} h)")
        else:
            n("hours", "Sleep", 1, 16, "h", required=True)
        n("quality", "Sleep quality", 1, 5, integer=True)
    elif kind == "reading":
        V.text(payload, "title", "Title", required=True, max_len=120)
        n("minutes", "Minutes", 1, 600, "min", integer=True, required=True)
        n("pages", "Pages", 0, 2000, integer=True)
        n("absorbing", "How absorbing", 1, 5, integer=True)
    elif kind == "journal":
        n("lines", "Lines written", 1, 3, integer=True, required=True)


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
