"""Population reference ranges: the safety limit that sits beside the personal baseline.

Two references, two jobs. The personal baseline (health.baseline) is the early warning: it says "different from
your own normal". The population range here is the safety limit: it says "outside what is usual for an adult",
and, past a critical limit, it raises the level to 2 on its own, whatever the personal numbers say.

Every entry has a `source`. None is `verified`: the ranges are well-known clinical references quoted from
memory of the guideline, to be checked by the team before the pitch. Critical limits are marked as prototype
assumptions unless a guideline gives them. These are not diagnostic thresholds.
"""
from typing import Dict, Optional, Union

from .catalog import INDICATORS

Num = Optional[float]
Sexed = Union[Num, Dict[str, Num]]
ASSUMPTION = "prototype assumption"

# low / high / critical_*: a number, a {"F": x, "M": y} pair, or None (no limit on that side).
POPULATION: Dict[str, dict] = {
    "hr": {"low": 40, "high": 100, "critical_low": 30, "critical_high": 150,
           "source": "AHA: resting heart rate 60 to 100 bpm in adults, 40 to 60 is common in trained people. Critical limits: prototype assumption",
           "verified": False},
    "bp": {"low": 90, "high": 139, "critical_low": 70, "critical_high": 180,
           "source": "Systolic pressure. Below 90 is low blood pressure; 140 or more is hypertension (ESC/ESH 2018); above 180 is the AHA hypertensive-crisis line. Critical low: prototype assumption",
           "verified": False},
    "spo2": {"low": 95, "high": 100, "critical_low": 90, "critical_high": None,
             "source": "Usual pulse-oximetry range 95 to 100%; below 90% is hypoxaemia (WHO pulse oximetry training manual)",
             "verified": False},
    "temp": {"low": 36.1, "high": 37.2, "critical_low": 35.0, "critical_high": 40.0,
             "source": "MedlinePlus: normal body temperature about 36.1 to 37.2 °C; below 35 °C is hypothermia; above 40 °C is hyperpyrexia",
             "verified": False},
    "gluc": {"low": 70, "high": 99, "critical_low": 54, "critical_high": None,
             "source": "ADA Standards of Care: fasting normal below 100 mg/dL; level 2 hypoglycaemia below 54 mg/dL. Low edge 70: ADA level 1",
             "verified": False},
    "sleep": {"low": 6, "high": 10, "critical_low": None, "critical_high": None,
              "source": "National Sleep Foundation 2015: 7 to 9 h recommended for adults, 6 to 10 h may be appropriate",
              "verified": False},
    "water": {"low": {"F": 1.6, "M": 2.0}, "high": None, "critical_low": None, "critical_high": None,
              "source": "EFSA 2010: adequate intake from drinks about 1.6 L (women) and 2.0 L (men)", "verified": False},
    "exer": {"low": 21, "high": None, "critical_low": None, "critical_high": None,
             "source": "WHO 2020 physical activity guidelines: 150 min a week of moderate activity, about 21 min a day", "verified": False},
    "grip": {"low": {"F": 16, "M": 27}, "high": None, "critical_low": None, "critical_high": None,
             "source": "EWGSOP2 2019 sarcopenia cut-offs: grip below 16 kg (women) or 27 kg (men) is low strength", "verified": False},
    "kss": {"low": None, "high": 6, "critical_low": None, "critical_high": None,
            "source": "Karolinska Sleepiness Scale (Åkerstedt and Gillberg 1990): 7 or more means sleepy", "verified": False},
    "react": {"low": 150, "high": 500, "critical_low": None, "critical_high": None,
              "source": ASSUMPTION + ": wide on purpose, the result depends on the device and screen lag", "verified": False},
    "dsst": {"low": 20, "high": 100, "critical_low": None, "critical_high": None,
             "source": ASSUMPTION + ": wide on purpose, depends on the task version and device", "verified": False},
    "span": {"low": 4, "high": 10, "critical_low": None, "critical_high": None,
             "source": ASSUMPTION + ": wide on purpose; forward digit span of adults is usually 5 to 9", "verified": False},
}
NO_RANGE_SOURCE = "No population range: the scale is personal or relative to your own pre-flight."


def _pick(v: Sexed, sex: str) -> Num:
    return v.get(sex) if isinstance(v, dict) else v


def check(ind: str, sex: str, value: float) -> dict:
    """{"low","high","status","source","verified"}. status: "in", "out" or "critical". No entry: always "in"."""
    P = POPULATION.get(ind)
    if P is None:
        return {"low": None, "high": None, "status": "in", "source": NO_RANGE_SOURCE, "verified": False}
    v = round(value, INDICATORS[ind]["dp"])
    low, high = _pick(P["low"], sex), _pick(P["high"], sex)
    cl, ch = _pick(P["critical_low"], sex), _pick(P["critical_high"], sex)
    if (cl is not None and v < cl) or (ch is not None and v > ch):
        status = "critical"
    elif (low is not None and v < low) or (high is not None and v > high):
        status = "out"
    else:
        status = "in"
    return {"low": low, "high": high, "status": status, "source": P["source"], "verified": P["verified"]}


def _fmt(v: Sexed, unit: str) -> str:
    if isinstance(v, dict):
        return " / ".join(f"{k} {x:g}" for k, x in v.items())
    return "-" if v is None else f"{v:g}"


def table_md() -> str:
    """The README table, generated from POPULATION."""
    L = ["| Indicator | Unit | Low | High | Critical (below / above) | Source | Verified |", "| --- | --- | --- | --- | --- | --- | :---: |"]
    for ind, P in POPULATION.items():
        crit = f"{_fmt(P['critical_low'], '')} / {_fmt(P['critical_high'], '')}"
        L.append(f"| `{ind}` {INDICATORS[ind]['name']} | {INDICATORS[ind]['unit']} | {_fmt(P['low'], '')} | {_fmt(P['high'], '')} | "
                 f"{'-' if crit == '- / -' else crit} | {P['source']} | {'yes' if P['verified'] else 'no'} |")
    L.append(f"\nNo population range (personal or relative scales): {', '.join(f'`{i}`' for i in INDICATORS if i not in POPULATION)}.")
    return "\n".join(L)
