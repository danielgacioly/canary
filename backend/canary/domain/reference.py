"""Population reference ranges: the safety limit that sits beside the personal baseline.

Two references, two jobs. The personal baseline (health.baseline) is the early warning: it says "different from
your own normal". The population range here is the safety limit: it says "outside what is usual for an adult",
and, past a critical limit, it raises the level to 2 on its own, whatever the personal numbers say.

Every entry has a `source`. `checked` lists the numbers that were read on the guideline's own page (with the link,
on 2026-11-14, the pulse, hypothermia, glucose 54 and sleep pages on 2026-11-15); `verified` stays False while any number of the entry is still a prototype assumption or quoted
from memory. Critical limits are marked as prototype assumptions unless a guideline gives them. These are not
diagnostic thresholds. Limits NASA sets for flight live in standards.py (NASA-STD-3001).
"""
from typing import Dict, Optional, Union

from .catalog import INDICATORS

Num = Optional[float]
Sexed = Union[Num, Dict[str, Num]]
ASSUMPTION = "prototype assumption"

# low / high / critical_*: a number, a {"F": x, "M": y} pair, or None (no limit on that side).
MEDLINE_VITALS = "https://medlineplus.gov/ency/article/002341.htm"
AHA_BP = "https://www.heart.org/en/health-topics/high-blood-pressure/understanding-blood-pressure-readings"
MEDLINE_OXIMETRY = "https://medlineplus.gov/lab-tests/pulse-oximetry/"
MEDLINE_FEVER = "https://medlineplus.gov/ency/article/003090.htm"
ADA_LOW = "https://diabetes.org/living-with-diabetes/hypoglycemia-low-blood-glucose"
CDC_SLEEP = "https://www.cdc.gov/sleep/about/index.html"
OSD575 = "https://osdr.nasa.gov/bio/repo/data/studies/OSD-575"
MEDLINE_PULSE = "https://medlineplus.gov/ency/article/003399.htm"
MEDLINE_HYPOTHERMIA = "https://medlineplus.gov/ency/article/000038.htm"
# ADA and EASD joint position statement (International Hypoglycaemia Study Group), Diabetologia 2017, doi 10.1007/s00125-016-4146-6
ADA_EASD_54 = "https://europepmc.org/article/PMC/PMC6518070"
# National Sleep Foundation 2015 recommendations (Hirshkowitz et al., Sleep Health 2015), the table of the release
NSF_SLEEP = "https://www.eurekalert.org/news-releases/554948"

POPULATION: Dict[str, dict] = {
    "hr": {"low": 40, "high": 100, "critical_low": 30, "critical_high": 150,
           "source": "MedlinePlus: resting pulse 60 to 100 bpm for adults, 40 to 60 for well-trained athletes (the low edge 40). Critical limits: prototype assumption",
           "checked": [f"high 100 bpm: {MEDLINE_VITALS}", f"athletes 40 to 60 bpm: {MEDLINE_PULSE}"], "verified": False},
    "sbp": {"low": 90, "high": 129, "critical_low": 70, "critical_high": 180,
            "source": "Systolic pressure. AHA: normal below 120, elevated 120 to 129, hypertension stage 1 from 130, stage 2 from 140, severe above 180. "
                      "MedlinePlus: 90/60 to 120/80 for a healthy adult. Critical low: prototype assumption",
            "checked": [f"130 = stage 1 hypertension, above 180 = severe: {AHA_BP}", f"low 90: {MEDLINE_VITALS}"], "verified": False},
    "dbp": {"low": 60, "high": 79, "critical_low": 40, "critical_high": 120,
            "source": "Diastolic pressure. AHA: normal below 80, stage 1 hypertension 80 to 89, stage 2 from 90, hypertensive crisis above 120. "
                      "MedlinePlus: 60 as the lower edge of 90/60 for a healthy adult. Critical low 40: prototype assumption",
            "checked": [f"80 = stage 1 hypertension, above 120 = crisis: {AHA_BP}", f"low 60: {MEDLINE_VITALS}"], "verified": False},
    "spo2": {"low": 95, "high": 100, "critical_low": 89, "critical_high": None,
             "source": "MedlinePlus: normal 95 to 100%; contact your provider at 92% or lower; 88% or lower needs immediate medical attention (critical below 89)",
             "checked": [f"95 to 100, 92 and 88: {MEDLINE_OXIMETRY}"], "verified": True},
    "temp": {"low": 36.1, "high": 37.2, "critical_low": 35.0, "critical_high": 39.3,
             "source": "MedlinePlus: an adult probably has a fever above 37.2 to 37.5 °C by mouth (the app flags from 37.2, the lower edge); contact a provider right away for a fever that stays at "
                       "39.4 °C or above (critical above 39.3). MedlinePlus lists 36.5 to 37.3 as the usual range; the low edge 36.1 is kept so a "
                       "cool personal normal (36.4) is not flagged every day (a prototype choice). MedlinePlus: hypothermia is a body temperature below 35 °C (critical low 35)",
             "checked": [f"fever above 37.2 to 37.5, act at 39.4: {MEDLINE_FEVER}", f"usual 36.5 to 37.3: {MEDLINE_VITALS}",
                         f"hypothermia below 35: {MEDLINE_HYPOTHERMIA}"], "verified": False},
    "gluc": {"low": 70, "high": 99, "critical_low": 54, "critical_high": None,
             "source": "ADA: below 70 mg/dL is low blood glucose and needs treatment (the 15-15 rule). High 99: the fasting reference range of the "
                       "Inspiration4 laboratory (65 to 99, OSD-575). Critical 54: the ADA and EASD joint statement (2017) says below 54 mg/dL is serious, clinically important hypoglycaemia",
             "checked": [f"low 70: {ADA_LOW}", f"high 99: {OSD575}", f"below 54 serious: {ADA_EASD_54}"], "verified": True},
    "sleep": {"low": 6, "high": 10, "critical_low": None, "critical_high": None,
              "source": "CDC: adults need 7 hours or more (the app's sleep goal is 7 h, and NASA-STD-3001 V1 6001 plans an 8.5 h sleep period). "
                        "The range 6 to 10 h is the National Sleep Foundation's 2015 'may be appropriate' band for adults 26 to 64 (7 to 9 h recommended)",
              "checked": [f"7 h or more for adults: {CDC_SLEEP}", f"6 and 10 h may be appropriate (26 to 64): {NSF_SLEEP}"], "verified": True},
    "water": {"low": {"F": 1.6, "M": 2.0}, "high": None, "critical_low": None, "critical_high": None,
              "source": "EFSA 2010: adequate intake from drinks about 1.6 L (women) and 2.0 L (men)", "checked": [], "verified": False},
    "exer": {"low": 21, "high": None, "critical_low": None, "critical_high": None,
             "source": "WHO 2020 physical activity guidelines: 150 min a week of moderate activity, about 21 min a day", "checked": [], "verified": False},
    "grip": {"low": {"F": 16, "M": 27}, "high": None, "critical_low": None, "critical_high": None,
             "source": "EWGSOP2 2019 sarcopenia cut-offs: grip below 16 kg (women) or 27 kg (men) is low strength", "checked": [], "verified": False},
    "kss": {"low": None, "high": 6, "critical_low": None, "critical_high": None,
            "source": "Karolinska Sleepiness Scale (Åkerstedt and Gillberg 1990): 7 or more means sleepy", "checked": [], "verified": False},
    "react": {"low": 150, "high": 500, "critical_low": None, "critical_high": None,
              "source": ASSUMPTION + ": wide on purpose, the result depends on the device and screen lag", "checked": [], "verified": False},
    "dsst": {"low": 20, "high": 100, "critical_low": None, "critical_high": None,
             "source": ASSUMPTION + ": wide on purpose, depends on the task version and device", "checked": [], "verified": False},
    "span": {"low": 4, "high": 10, "critical_low": None, "critical_high": None,
             "source": ASSUMPTION + ": wide on purpose; forward digit span of adults is usually 5 to 9", "checked": [], "verified": False},
}
NO_RANGE_SOURCE = "No population range: the scale is personal or relative to your own pre-flight."


# Sex policy (DATA-08). A reference range that differs by sex is read for "F" or "M". Any other value ("Other", or no sex
# registered) has no range of its own, so it takes the WIDEST combined range: the lowest lower limit and the highest upper
# limit of the two. A person is then never flagged by a limit that only one sex has; the check says so in `sex_policy`.
SEX_POLICY = "widest combined range (F and M) for a sex other than F or M, or none registered"
_SIDE_WIDEST = {"low": min, "critical_low": min, "high": max, "critical_high": max}


def _pick(v: Sexed, sex: Optional[str], side: str = "low") -> Num:
    """The limit of one side for one sex. A pair with no F or M value for `sex` gives the widest of the pair."""
    if not isinstance(v, dict):
        return v
    if sex in v:
        return v[sex]
    vals = [x for x in v.values() if x is not None]
    return _SIDE_WIDEST.get(side, min)(vals) if vals else None


def sex_policy(sex: Optional[str]) -> Optional[str]:
    """None when the sex has its own ranges, else the text of the policy (only "F" and "M" have their own)."""
    return None if sex in ("F", "M") else SEX_POLICY


def pick_sex(v: Sexed, sex: Optional[str], side: str = "low") -> Num:
    """Public form of the sex policy, for the other modules that read a sex-dependent range (exam ranges in risk.py)."""
    return _pick(v, sex, side)


def check(ind: str, sex: Optional[str], value: float) -> dict:
    """{"low","high","status","source","verified","sex_policy"}. status: "in", "out" or "critical". No entry: always "in".
    `sex_policy` is None for F and M, else the widest-range text (DATA-08)."""
    P = POPULATION.get(ind)
    if value is None:  # no reading: no verdict
        return {"low": None, "high": None, "status": "no_data", "source": None, "verified": False, "sex_policy": None}
    if P is None:
        return {"low": None, "high": None, "status": "in", "source": NO_RANGE_SOURCE, "verified": False, "sex_policy": None}
    v = round(value, INDICATORS[ind]["dp"])
    low, high = _pick(P["low"], sex, "low"), _pick(P["high"], sex, "high")
    cl, ch = _pick(P["critical_low"], sex, "critical_low"), _pick(P["critical_high"], sex, "critical_high")
    if (cl is not None and v < cl) or (ch is not None and v > ch):
        status = "critical"
    elif (low is not None and v < low) or (high is not None and v > high):
        status = "out"
    else:
        status = "in"
    return {"low": low, "high": high, "status": status, "source": P["source"], "verified": P["verified"], "sex_policy": sex_policy(sex)}


def _fmt(v: Sexed, unit: str) -> str:
    if isinstance(v, dict):
        return " / ".join(f"{k} {x:g}" for k, x in v.items())
    return "-" if v is None else f"{v:g}"


def table_md() -> str:
    """The README table, generated from POPULATION."""
    L = ["| Indicator | Unit | Low | High | Critical (below / above) | Source | Verified |", "| --- | --- | --- | --- | --- | --- | :---: |"]
    for ind, P in POPULATION.items():
        crit = f"{_fmt(P['critical_low'], '')} / {_fmt(P['critical_high'], '')}"
        ver = "yes" if P["verified"] else "partly" if P.get("checked") else "no"
        L.append(f"| `{ind}` {INDICATORS[ind]['name']} | {INDICATORS[ind]['unit']} | {_fmt(P['low'], '')} | {_fmt(P['high'], '')} | "
                 f"{'-' if crit == '- / -' else crit} | {P['source']} | {ver} |")
    L.append(f"\nNo population range (personal or relative scales): {', '.join(f'`{i}`' for i in INDICATORS if i not in POPULATION)}.")
    return "\n".join(L)
