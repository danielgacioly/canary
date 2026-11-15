"""The ship's observation table: one row per measurement, with where it came from.

`Generator` turns the recipes in `data/recipes.json` plus a mission plan into rows
(crew_id, day, indicator, value, unit, origin, method, source, note). It is
deterministic (same input, same rows, same bytes) and uses only the standard
library. Real rows from `data/real/*.csv` replace the simulated row with the same
key (crew_id, day, indicator), or are added when there is none.

Hidden states (fatigue, hydration, energy, bone loss) move related indicators
together. The demo story is a list of dated events that push those states.
"""
import bisect
import csv
import io
import json
import math
import pathlib
import re
import statistics
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from .catalog import INDICATORS, LOCATIONS

_HERE = pathlib.Path(__file__).resolve()
DATA_DIR = _HERE.parents[3] / "data"                       # recipes, real data, report (repository root)
RECIPES_FILE = DATA_DIR / "recipes.json"
DEMO_CREW_FILE = DATA_DIR / "demo_crew.json"              # the demo crew's seeds, for the sheet generator only
REAL_DIR = DATA_DIR / "real"                               # genuinely real rows (none ship with the demo)
MODELLED_DIR = DATA_DIR / "modelled"                       # Inspiration4-moulded blood values for the demo crew: origin simulated
I4_SOURCE = {"cbc": "modelled on Inspiration4 (NASA OSDR OSD-569)", "cmp": "modelled on Inspiration4 (NASA OSDR OSD-575)"}
REPORT_FILE = DATA_DIR / "DATASET.md"
OBS_FILE = _HERE.parents[1] / "data" / "observations.csv"  # the generated table the backend reads
SNAPSHOT_FILE = _HERE.parents[1] / "data" / "nasa_snapshot.json"

COLUMNS = ["crew_id", "day", "indicator", "value", "unit", "origin", "method", "source", "note"]
CABIN = "cabin"
Row = Tuple[str, int, str, str, str, str, str, str, str]


def h01(key: str) -> float:
    """Stable pseudo-random number in [0, 1) from a string (FNV-1a + avalanche)."""
    h = 2166136261
    for ch in key.encode():
        h ^= ch
        h = (h * 16777619) & 0xFFFFFFFF
    h ^= h >> 15
    h = (h * 2246822507) & 0xFFFFFFFF
    h ^= h >> 13
    return (h % 100000) / 100000


# ---------------------------------------------------------------- the plan, as plain data
def signature(legs: Sequence[dict]) -> tuple:
    """What matters for the data: place and days of every leg (labels do not)."""
    return tuple((l["location"], int(l["start"]), int(l["end"])) for l in legs)


def leg_index(legs: Sequence[dict], day: int) -> int:
    idx = 0
    for i, l in enumerate(legs):
        if day >= l["start"]:
            idx = i
    return idx


def location_at(legs: Sequence[dict], day: int) -> str:
    if day < legs[0]["start"]:
        return "earth"
    return legs[leg_index(legs, day)]["location"]


def gravity_at(legs: Sequence[dict], day: int) -> str:
    return LOCATIONS[location_at(legs, day)]["gravity_key"]


def days_since_gravity_change(legs: Sequence[dict], day: int) -> Optional[int]:
    """Days since arriving in partial gravity after a 0 g leg, or None (same rule as plan.py)."""
    i = leg_index(legs, day)
    if i == 0 or LOCATIONS[legs[i]["location"]]["gravity_key"] != "gp":
        return None
    if LOCATIONS[legs[i - 1]["location"]]["gravity_key"] != "g0":
        return None
    return day - legs[i]["start"]


# ---------------------------------------------------------------- files
def load_recipes(path: pathlib.Path = RECIPES_FILE) -> dict:
    return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))


def load_demo_crew(path: pathlib.Path = DEMO_CREW_FILE) -> dict:
    """The demo crew as the sheet generator uses it: people (with the `base` values and `cbc_subject` seeds), records, story.
    The engine never reads this: it knows only the people who are registered."""
    return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))


def load_snapshot(path: pathlib.Path = SNAPSHOT_FILE) -> dict:
    return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))


def format_value(v: float, decimals: int) -> str:
    s = f"{v:.{decimals}f}"
    return s.lstrip("-") if float(s) == 0 else s


def csv_text(rows: Iterable[Sequence]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(COLUMNS)
    w.writerows(rows)
    return buf.getvalue()


def write_csv(rows: Iterable[Sequence], path: pathlib.Path) -> None:
    pathlib.Path(path).write_text(csv_text(rows), encoding="utf-8", newline="")


def read_csv(path_or_text) -> List[dict]:
    if isinstance(path_or_text, pathlib.Path):
        path_or_text = path_or_text.read_text(encoding="utf-8-sig")
    return list(csv.DictReader(io.StringIO(path_or_text)))


def read_real(real_dir: Optional[pathlib.Path], recipes: dict, origin: str = "real") -> Dict[Tuple[str, int, str], Row]:
    """Rows from every CSV in `real_dir` (same columns; only crew_id, day, indicator and value are required).

    They always enter with the given origin ("real" for genuine measurements; "simulated" for the Inspiration4-moulded demo
    values in MODELLED_DIR). Missing unit and method come from the recipe.
    """
    out: Dict[Tuple[str, int, str], Row] = {}
    if real_dir is None or not pathlib.Path(real_dir).is_dir():
        return out
    for f in sorted(pathlib.Path(real_dir).glob("*.csv")):
        for r in read_csv(f):
            ind = r["indicator"].strip()
            rec = recipes["indicators"].get(ind, {})
            row = (r["crew_id"].strip(), int(r["day"]), ind, r["value"].strip(),
                   (r.get("unit") or rec.get("unit", "")).strip(), origin,
                   (r.get("method") or rec.get("method", "manual")).strip(),
                   (r.get("source") or f"real:{f.stem}").strip(), (r.get("note") or "").strip())
            out[(row[0], row[1], row[2])] = row
    return out


def _num(v: float) -> str:
    return str(int(v)) if float(v) == int(v) else repr(float(v))


def lab_range(snapshot: dict, ind: str, sex: str) -> Optional[Tuple[Optional[float], Optional[float]]]:
    """(min, max) of a real laboratory analyte for one sex, from the blood count (OSD-569) or the metabolic panel
    (OSD-575) of the snapshot; None when the analyte has no reference range there (C-reactive protein)."""
    for section in ("cbc", "cmp"):
        a = snapshot.get(section, {}).get("an", {}).get(ind)
        if a is not None:
            r = a.get(sex)
            return (r["min"], r["max"]) if r else None
    return None


def _lab_rows(snapshot: dict, recipes: dict, section: str, source: str, crew: Optional[Sequence[dict]] = None) -> List[Row]:
    """Inspiration4 lab values moulded onto the demo crew, in the observation format. Built from the snapshot, not typed.
    The values are the Inspiration4 subject's, but they are not this fictional person's measurements: origin "simulated",
    source "modelled on Inspiration4 (...)".

    Collection labels (L-92 ... R+194) are relative to launch; day 0 is launch, so L-N is day -N
    and R+N is day N + 3 (the flight lasted 3 days). The original label stays in `note`.
    Each seat reads the Inspiration4 subject of the same sex (`cbc_subject`).
    """
    lab = snapshot[section]
    out: List[Row] = []
    for c in (crew if crew is not None else load_demo_crew()["crew"]):
        subject = c["cbc_subject"]
        for ind, series in lab["crew"][subject].items():
            rec = recipes["indicators"][ind]
            for label, v in zip(lab["tp"], series):
                if v is None:
                    continue
                day = -int(label[2:]) if label.startswith("L-") else int(label[2:]) + 3
                out.append((c["id"], day, ind, _num(v), rec["unit"], "simulated", "blood", I4_SOURCE[section],
                            f"{label} Inspiration4 {subject}"))
    return sorted(out, key=lambda r: (r[0], r[1], r[2]))


def osd569_rows(snapshot: dict, recipes: dict, crew: Optional[Sequence[dict]] = None) -> List[Row]:
    """The Inspiration4 blood counts (OSD-569) as the pattern of the simulated crew blood."""
    return _lab_rows(snapshot, recipes, "cbc", "nasa:osd569", crew)


def osd575_rows(snapshot: dict, recipes: dict, crew: Optional[Sequence[dict]] = None) -> List[Row]:
    """The Inspiration4 metabolic panel and C-reactive protein (OSD-575) as the pattern of the simulated crew: creatinine, potassium, calcium, crp."""
    return _lab_rows(snapshot, recipes, "cmp", "nasa:osd575", crew)


# ---------------------------------------------------------------- generator
class Generator:
    def __init__(self, legs: Sequence[dict], recipes: Optional[dict] = None, real_dir=REAL_DIR,
                 snapshot: Optional[dict] = None, crew: Optional[Sequence[dict]] = None, modelled_dir=MODELLED_DIR):
        """`crew`: the people to generate for, each with `id`, `sex`, `cbc_subject` and `base` (default: the demo crew)."""
        self.people = {c["id"]: c for c in (crew if crew is not None else load_demo_crew()["crew"])}
        self.legs = list(legs)
        self.r = recipes or load_recipes()
        self.real = read_real(real_dir, self.r)
        self.modelled = read_real(modelled_dir, self.r, "simulated")
        self.lab = {**self.modelled, **self.real}  # the pre-flight blood values that seed the simulated rows
        self.landing = self._landing()
        self.snap = snapshot or load_snapshot()
        self.first = min(l["start"] for l in self.legs)
        self.last = max(l["end"] for l in self.legs)
        self._drift: Dict[str, List[float]] = {}
        self._bone: Dict[str, List[float]] = {}
        self._pre: Dict[Tuple[str, str], Optional[Tuple[float, Optional[float]]]] = {}

    # --- hidden states
    def state(self, crew: str, name: str, day: int) -> float:
        s = self.r["states"][name]
        if s.get("kind") == "bone_loss":
            return self._bone_loss(crew, s, day)
        v = 0.0
        if s.get("amp"):
            v += s["amp"] * math.sin(2 * math.pi * day / s["period"] + 2 * math.pi * h01(f"ph:{crew}:{name}"))
        for ev in self.r["events"]:
            if ev["state"] == name and ev["crew"] == crew:
                v += _interp(ev["points"], day)
        return v

    def _bone_loss(self, crew: str, s: dict, day: int) -> float:
        if day <= 0:
            return 0.0
        cum = self._bone.setdefault(crew, [0.0])
        if len(cum) <= day:
            exer = self.people[crew]["base"]["exer"]
            per_day = (s["max_pct_per_month"] - s["exercise_gain"] * min(1.0, exer / s["exercise_full_min"])) / 30
            for d in range(len(cum), day + 1):
                cum.append(max(0.0, cum[-1] + per_day * s["gravity_rate"][gravity_at(self.legs, d)]))
        return cum[day]

    def _slow_drift(self, ind: str, rec: dict, day: int) -> float:
        dr = rec.get("drift")
        if not dr or day <= 0:
            return 0.0
        cum = self._drift.setdefault(ind, [0.0])
        cap = dr.get("cap")
        while len(cum) <= day:
            x = cum[-1] + dr["per_day"][gravity_at(self.legs, len(cum))]
            if cap is not None:
                lo, hi = (0.0, cap) if cap > 0 else (cap, 0.0)
                x = min(hi, max(lo, x))
            cum.append(x)
        return cum[day]

    # --- recipe numbers
    def _preflight(self, crew: str, ind: str) -> Optional[Tuple[float, Optional[float]]]:
        """Mean and spread of the real measurements before launch, if there are any."""
        key = (crew, ind)
        if key not in self._pre:
            vals = [float(r[3]) for (c, d, i), r in sorted(self.lab.items()) if c == crew and i == ind and d < 0]
            if not vals:  # no real file for it (another real_dir): the pre-flight collections of the snapshot itself
                subject = self.people[crew]["cbc_subject"]
                for section in ("cbc", "cmp"):
                    lab = self.snap.get(section, {})
                    series = lab.get("crew", {}).get(subject, {}).get(ind)
                    if series:
                        vals = [float(v) for label, v in zip(lab["tp"], series) if label.startswith("L-") and v is not None]
            self._pre[key] = (statistics.mean(vals), statistics.stdev(vals) if len(vals) > 1 else None) if vals else None
        return self._pre[key]

    def _range(self, crew: str, ind: str) -> Tuple[float, float]:
        r = lab_range(self.snap, ind, self.people[crew]["sex"])
        if r is None or None in r:
            raise KeyError(f"{ind}: no reference range to seed a simulated value without real pre-flight data")
        return r

    def baseline(self, crew: str, ind: str, day: int) -> float:
        b = self.r["indicators"][ind]["baseline"]
        kind = b["kind"]
        if kind == "catalog":
            return self.people[crew]["base"][ind]
        if kind == "crew":
            return b["values"][crew]
        if kind == "location":  # a place without its own value (a rover) takes the value of its planet
            loc = location_at(self.legs, day)
            return b["values"][loc] if loc in b["values"] else b["values"][LOCATIONS[loc]["body"]]
        pre = self._preflight(crew, ind)  # real_preflight
        if pre:
            return pre[0]
        lo, hi = self._range(crew, ind)  # no real data yet: middle of the reference range of the source dataset
        return (lo + hi) / 2

    def sd(self, crew: str, ind: str) -> float:
        s = self.r["indicators"][ind]["sd"]
        if s == "catalog":
            return INDICATORS[ind]["sd"]
        if isinstance(s, (int, float)):
            return float(s)
        pre = self._preflight(crew, ind)  # real_preflight
        if pre and pre[1]:
            return max(pre[1], abs(pre[0]) * 0.01)
        lo, hi = self._range(crew, ind)  # one eighth of the reference range
        return (hi - lo) / 8

    # --- one value
    def value(self, crew: str, ind: str, day: int) -> float:
        rec = self.r["indicators"][ind]
        sd = rec["sd_pre"] if day <= 0 and "sd_pre" in rec else self.sd(crew, ind)
        key = rec.get("noise_key", "{crew}{ind}{day}").format(crew=crew, ind=ind, day=day)
        base = self.baseline(crew, ind, day)
        v = base + (h01(key) - 0.5) * 1.6 * sd
        if rec.get("relative"):  # a percentage state moves the value in proportion to the baseline (bone density)
            v = base * (1 - self.state(crew, rec["relative"], day) / 100.0) + (h01(key) - 0.5) * 1.6 * sd
        for st, w in ({} if rec.get("relative") else rec.get("states", {})).items():
            v += w * self.state(crew, st, day)
        v += self._slow_drift(ind, rec, day)
        rg = rec.get("regravity")
        if rg:
            since = days_since_gravity_change(self.legs, day)
            if since is not None and since <= rg["days"]:
                v += rg["delta"] * (1 - since / rg["days"])
        cap = rec.get("cap")
        if cap and location_at(self.legs, day) == cap["location"]:
            v = min(v, cap["base"] + cap["spread"] * h01(cap["key"].format(crew=crew, ind=ind, day=day)))
        if "clamp" in rec:
            v = min(rec["clamp"][1], max(rec["clamp"][0], v))
        return v

    def _landing(self) -> Optional[int]:
        """First day on Earth after the last leg away from it (the landing), or None when the plan does not come back."""
        legs = sorted(self.legs, key=lambda l: l["start"])
        away = [i for i, l in enumerate(legs) if l["location"] != "earth" and l["start"] >= 0]
        if not away or away[-1] + 1 >= len(legs) or legs[away[-1] + 1]["location"] != "earth":
            return None
        return legs[away[-1] + 1]["start"]

    def schedule_days(self, rec: dict) -> List[int]:
        """The days of an indicator measured on a fixed schedule: before launch (absolute days) and after landing (days after it)."""
        sch = rec["schedule"]
        days = [d for d in sch.get("preflight", []) if self.first <= d < 0]
        if self.landing is not None:
            days += [self.landing + o for o in sch.get("postflight", []) if self.landing + o <= self.last]
        return days

    # --- the table
    def observations(self) -> List[Row]:
        rows: Dict[Tuple[str, int, str], Row] = {}
        for ind, rec in self.r["indicators"].items():
            crews = [CABIN] if rec.get("subject") == CABIN else list(self.people)
            every = rec["frequency"]["every"]
            panel = rec.get("panel", ind)
            note = with_context(rec.get("row_note", ""), **rec.get("context", {}))
            for crew in crews:
                offset = int(h01(f"off:{crew}:{panel}") * every) if every > 1 else 0
                for day in (self.schedule_days(rec) if "schedule" in rec else range(self.first, self.last + 1)):
                    if "schedule" not in rec:
                        if every > 1 and (day + offset) % every:
                            continue
                        if h01(f"gap:{crew}:{panel}:{day}") < rec["gaps"]:
                            continue  # a missed measurement, on purpose
                    rows[(crew, day, ind)] = (crew, day, ind, format_value(self.value(crew, ind, day), rec["decimals"]),
                                              rec["unit"], "simulated", rec["method"],
                                              rec["source"] if rec["source"].startswith("modelled on") else f"recipe:{ind}", note)
        rows.update(self.lab)
        return sorted(rows.values(), key=lambda r: (r[0], r[1], r[2]))


def _interp(points: Sequence[Sequence[float]], day: float) -> float:
    """Piecewise-linear value of a dated event; zero outside its first and last point."""
    if day < points[0][0] or day > points[-1][0]:
        return 0.0
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        if x0 <= day <= x1:
            return y0 if x1 == x0 else y0 + (y1 - y0) * (day - x0) / (x1 - x0)
    return 0.0


# ---------------------------------------------------------------- reading the table
# `method` of the readings made by an instrument; anything else ("manual") is self-reported. On the same day an instrument
# reading takes precedence over a self-report (telemetry.pick); every reading of the day is kept.
DEVICE_METHODS = frozenset({"wearable", "test", "blood", "urine", "environment", "dosimeter", "device", "sensor"})  # "sensor" is the API default for a device-keyed sender
_CTX = re.compile(r"\[ctx ([^\]]*)\]")


def parse_context(note: str) -> Dict[str, str]:
    """The context of a reading (heart rate: activity=rest|exercise; pressure: position=seated|supine|standing), carried in
    the `note` as `[ctx activity=rest]`. {} when there is none."""
    m = _CTX.search(note or "")
    if not m:
        return {}
    return {k.strip(): v.strip() for k, _, v in (p.partition("=") for p in m.group(1).split(";")) if k.strip()}


def with_context(note: str, **ctx: str) -> str:
    """`note` with the context added: with_context("morning", position="seated") == "morning [ctx position=seated]"."""
    base = _CTX.sub("", note or "").strip()
    tag = "[ctx " + ";".join(f"{k}={v}" for k, v in ctx.items() if v) + "]" if any(ctx.values()) else ""
    return (base + " " + tag).strip()


def _row(t: tuple) -> dict:
    d, v, origin, method, source, note, unit = t
    return {"day": d, "value": v, "origin": origin, "method": method, "source": source, "note": note, "unit": unit,
            "device": method in DEVICE_METHODS, "context": parse_context(note)}


class Table:
    """Rows indexed by (crew_id, indicator) with the days sorted, for 'last observation up to day D'. Every row of a day is
    kept (`rows_on`); `last` picks the one the engine reads (instrument before self-report, then the latest)."""

    def __init__(self, rows: Iterable[Sequence]):
        by: Dict[Tuple[str, str], List[tuple]] = {}
        for r in rows:
            by.setdefault((r[0], r[2]), []).append((int(r[1]), float(r[3]), r[5], r[6], r[7], r[8], r[4]))
        self.days: Dict[Tuple[str, str], List[int]] = {}
        self.obs: Dict[Tuple[str, str], List[tuple]] = {}
        for k, lst in by.items():
            lst.sort(key=lambda t: t[0])
            self.obs[k] = lst
            self.days[k] = [t[0] for t in lst]

    def rows_on(self, crew: str, ind: str, day: int) -> List[dict]:
        """Every stored reading of one day, in the order they were stored."""
        days = self.days.get((crew, ind))
        if not days:
            return []
        lo, hi = bisect.bisect_left(days, day), bisect.bisect_right(days, day)
        return [_row(t) for t in self.obs[(crew, ind)][lo:hi]]

    def days_back(self, crew: str, ind: str, day: int, limit: int = 10 ** 6):
        """Yield (day, [readings]) for the days up to `day` that have any, newest first."""
        days = self.days.get((crew, ind)) or []
        i = bisect.bisect_right(days, day) - 1
        n = 0
        while i >= 0 and n < limit:
            d = days[i]
            lo = bisect.bisect_left(days, d, 0, i + 1)
            yield d, [_row(t) for t in self.obs[(crew, ind)][lo:i + 1]]
            i, n = lo - 1, n + 1

    def last(self, crew: str, ind: str, day: int) -> Optional[dict]:
        for d, rows in self.days_back(crew, ind, day, 1):
            r = next((x for x in reversed(rows) if x["device"]), rows[-1])  # an instrument reading of the day first
            return {"day": d, "value": r["value"], "age": day - d, "origin": r["origin"], "method": r["method"], "source": r["source"],
                    "note": r["note"]}
        return None

    def first(self, crew: str, ind: str) -> Optional[float]:
        o = self.obs.get((crew, ind))
        return o[0][1] if o else None


# ---------------------------------------------------------------- report
def frequency_label(rec: dict) -> str:
    return rec["frequency"]["label"]


def report(rows: Sequence[Sequence], recipes: dict, plan_name: str = "Mars reference mission") -> str:
    stats: Dict[str, dict] = {}
    for r in rows:
        s = stats.setdefault(r[2], {"n": 0, "origin": {}})
        s["n"] += 1
        s["origin"][r[5]] = s["origin"].get(r[5], 0) + 1
    L = ["# Crew observation dataset", "",
         "Generated by `python data/generate_dataset.py`. Do not edit by hand: change `data/recipes.json` or add real files to `data/real/`, then run the script again.", "",
         f"- Plan: {plan_name}. File: `backend/canary/data/observations.csv`, {len(rows):,} rows.",
         "- One row per measurement: `crew_id, day, indicator, value, unit, origin, method, source, note`.",
         "- `origin` is `simulated` or `real` (no real row ships with the demo). `method` is `wearable`, `manual`, `test`, `blood`, `urine` or `environment`. `source` is the recipe (`recipe:<indicator>`) or the real dataset. Cabin measures use the crew id `cabin`.",
         "- Day 0 is launch. A day without a row means nothing was measured: the app shows the last observation and its age.",
         "- Real rows replace the simulated row with the same (crew_id, day, indicator), or are added when there is none.", "",
         "## Indicators", "",
         "| Indicator | Unit | Rows | Origin | Method | Frequency | Gaps | Source | Verified |",
         "| --- | --- | ---: | --- | --- | --- | ---: | --- | :---: |"]
    for ind, rec in recipes["indicators"].items():
        s = stats.get(ind, {"n": 0, "origin": {}})
        origin = " + ".join(f"{k} {v:,}" for k, v in sorted(s["origin"].items()))
        L.append(f"| `{ind}` | {rec['unit']} | {s['n']:,} | {origin or '-'} | {rec['method']} | {frequency_label(rec)} | "
                 f"{round(rec['gaps'] * 100)}% | {rec['source']} | {'yes' if rec['verified'] else 'no'} |")
    L += ["", "## Hidden states", "",
          "Related signals move together because they share a state. The risk engine crosses them.", "",
          "| State | Moves | Events that push it |", "| --- | --- | --- |"]
    for name, st in recipes["states"].items():
        moves = ", ".join(f"`{i}`" for i, r in recipes["indicators"].items() if name in r.get("states", {}))
        evs = "; ".join(f"{e['label']} (`{e['id']}`)" for e in recipes["events"] if e["state"] == name) or "none yet"
        L.append(f"| {name}: {st['about']} | {moves} | {evs} |")
    L += ["", "## Assumptions without a source", "",
          "Every item below is a **prototype assumption** (`verified: false`): a number chosen so the prototype behaves, not a published value. None should be quoted as fact.", ""]
    for ind, rec in recipes["indicators"].items():
        if not rec["verified"]:
            L.append(f"- `{ind}`: {rec['assumption']} (source: {rec['source']})")
    for name, st in recipes["states"].items():
        if not st["verified"]:
            L.append(f"- state `{name}`: {st['assumption']} (source: {st['source']})")
    for e in recipes["events"]:
        if not e["verified"]:
            L.append(f"- event `{e['id']}`: {e['assumption']} (source: {e['source']})")
    L += ["", "## What is real today", "",
          "Nothing in the demo is a measurement of a real person: every row of the demo crew is `origin = simulated`. The blood values follow a real pattern, and that is all they share with it.", "",
          "- Complete blood count (`wbc, lym, neu, hgb, hct, plt, rbc`): simulated on the pattern of the Inspiration4 crew (NASA OSDR OSD-569; Costes et al. 2024, npj Microgravity), 4 subjects and 7 collections, converted from `backend/canary/data/nasa_snapshot.json` into `data/modelled/osd569_cbc.csv`. Source `modelled on Inspiration4 (NASA OSDR OSD-569)`, origin `simulated`. Collections keep their original label in `note` (L-92, L-44, L-3, R+1, R+45, R+82, R+194). The pre-flight ones set each person's baseline and spread for the other simulated rows.",
          "- Metabolic panel and inflammation (`creatinine, potassium, calcium, crp`): simulated on the pattern of the Inspiration4 crew (NASA OSDR OSD-575), same subjects and collections, in `data/modelled/osd575_cmp.csv`, source `modelled on Inspiration4 (NASA OSDR OSD-575)`, origin `simulated`. C-reactive protein comes from the cardiovascular multiplex panel, converted from pg/mL to mg/L; it has no reference range there, so it is read only against the person's own pre-flight values.",
          "- Each seat reads the Inspiration4 subject of the same sex (`cbc_subject` in `data/demo_crew.json`, a seed of the sheet generator only), and every range is the one of that sex. `data/prepare_blood.py` rebuilds both sections from the OSDR files and documents three corrections: C003's L-92 blood count sat one row down from MCH on (realigned and checked by arithmetic), C003's pre-flight rows carry male ranges (each sex takes the range most of its rows carry), and haemoglobin is labelled `percent` in OSD-569 (it is g/dL).",
          "- Glucose from the metabolic panel is not imported: three of four crew read 36 to 44 mg/dL on the same day (R+45) with every other collection normal, the pattern of a sample processed late. The ship's `gluc` stays the fingerstick indicator.",
          "- Open real data also exists for more cytokines and for dose by place. Not imported yet; see below.",
          "- Bone density (`bone`) is a DXA scan: two before launch and two after landing, never on board. In flight the engine infers it from exercise and time in microgravity and labels it an estimate.",
          "- Blood pressure is split into `sbp` and `dbp` (seated); pulse readings carry the context `activity=rest` (in the `note`, as `[ctx activity=rest]`).",
          "- Everything else (vital signs, sleep, cognition, weight, vision, hormones, urine, cabin air) is simulated.", "",
          "## Replacing simulated data with real data", "",
          "1. Put a CSV with the same columns in `data/real/` (only `crew_id, day, indicator, value` are required; `unit` and `method` default to the recipe's). Only genuine measurements belong there; the Inspiration4-moulded demo values live in `data/modelled/` and stay simulated.",
          "2. Run `python data/generate_dataset.py`. Rows enter with `origin = real` and replace the simulated row of the same key.",
          "3. No code changes. Commit `observations.csv` and this file.", "",
          "## How each method would be collected on a real mission", ""]
    for m, info in recipes["methods"].items():
        used = ", ".join(f"`{i}`" for i, r in recipes["indicators"].items() if r["method"] == m)
        L += [f"### {info['label']} (`{m}`)", "", info["how"], "", f"Indicators: {used}.", ""]
    return "\n".join(L).rstrip() + "\n"
