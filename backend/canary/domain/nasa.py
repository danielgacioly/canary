"""NASA open data used by Canary.

- DONKI (Space Weather Database Of Notifications, Knowledge, Information): solar
  particle events, geomagnetic storms (Kp) and fast CMEs, 5 to 16 May 2024.
- Curiosity RAD level 2 (PDS / SPDF): total dose rate at Gale crater, quiet day
  9 May 2024 and storm day 20 May 2024.
- OSDR OSD-569: Inspiration4 complete blood counts, 4 crew, 7 time points. The demo crew's blood values are SIMULATED on
  that pattern (origin simulated, never real); only a person's own laboratory rows registered as real are real.

A snapshot is bundled in data/nasa_snapshot.json (built by data/prepare_nasa_data.py)
so the ship never depends on a network. With CANARY_LIVE_SPACE_WEATHER=1 the API
asks DONKI for the last 30 days (mode "live") and falls back to the snapshot, labelled a replay, on any error.
"""
import datetime as dt
import json
import pathlib
import re
import time
from typing import Optional

from ..config import settings

_SNAPSHOT = json.loads((pathlib.Path(__file__).resolve().parents[1] / "data" / "nasa_snapshot.json").read_text(encoding="utf-8"))
_live_cache: dict = {"at": 0.0, "data": None}

SOURCES = [
    {"id": "nasa:donki", "name": "DONKI space weather", "org": "NASA CCMC / M2M",
     "url": "https://kauai.ccmc.gsfc.nasa.gov/DONKI/", "used_for": "Solar particle events (measured at L1), Kp index and CMEs: live when enabled, otherwise the bundled May 2024 record replayed"},
    {"id": "nasa:rad", "name": "Curiosity RAD level 2", "org": "NASA PDS / SPDF",
     "url": "https://spdf.gsfc.nasa.gov/pub/data/aaa_planetary/msl/rad/cdf/obs-l2/", "used_for": "Pattern of a Mars surface radiation storm: quiet day against the 20 May 2024 storm (replayed)"},
    {"id": "nasa:osd569", "name": "OSD-569 Inspiration4 blood counts", "org": "NASA OSDR",
     "url": "https://osdr.nasa.gov/bio/repo/data/studies/OSD-569", "used_for": "Pattern for the simulated crew blood counts (lymphocytes and the rest of the count before and after spaceflight)"},
    {"id": "nasa:osd575", "name": "OSD-575 Inspiration4 metabolic panel and CRP", "org": "NASA OSDR",
     "url": "https://osdr.nasa.gov/bio/repo/data/studies/OSD-575", "used_for": "Pattern for the simulated crew creatinine, potassium, calcium and C-reactive protein"},
    {"id": "inspiration4", "name": "Inspiration4 (SpaceX, 2021)", "org": "SpaceX / NASA OSDR",
     "url": "https://www.nature.com/articles/s41526-024-00393-5",
     "used_for": "Mould for the simulated crew: blood before, during and after a three-day orbital flight"},
    {"id": "simulated", "name": "Simulated crew data", "org": "Canary", "url": "",
     "used_for": "Daily vitals, sleep, self-tests and the mission story; every reading is labelled simulated"},
    {"id": "nasa:std3001v1", "name": "NASA-STD-3001 Volume 1, Revision C", "org": "NASA OCHMO",
     "url": "https://www.nasa.gov/wp-content/uploads/2023/11/nasa-std-3001-vol-1-rev-c-with-signature.pdf",
     "used_for": "In-flight limits: career dose, solar event dose, strength, bone density, aerobic capacity for EVA, sleep period"},
    {"id": "nasa:hrp", "name": "Human Research Program hazards and risks", "org": "NASA HRP",
     "url": "https://www.nasa.gov/hrp/hazards/", "used_for": "The five hazards (RIDGE) behind each body system"},
    {"id": "makehuman", "name": "MakeHuman base mesh (CC0)", "org": "MakeHuman community",
     "url": "https://github.com/makehumancommunity/makehuman", "used_for": "Body shape of the hologram"},
]


def snapshot() -> dict:
    return _SNAPSHOT


def _snapshot_window() -> str:
    """The dates the bundled DONKI snapshot covers, read from the snapshot itself."""
    d = _SNAPSHOT["donki"]
    days = [str(x)[:10] for x in [e["t"] for e in d["sep"]] + [e["t"] for e in d["cme"]] + [k[0] for k in d["kp"]] + list(d["flares"])]
    return f"{min(days)} to {max(days)}" if days else ""


def space_weather(event: Optional[dict] = None) -> dict:
    """Space weather for the mission day. `event` is the space event active on the mission day at the crew's place (a row of
    data.events(), found with data.storm_event(day, location)), or None.

    `mode` is "live" when DONKI answered (the window is the live one, and the bundled snapshot is not presented as current
    weather) and "replay" otherwise: the bundled record of May 2024, whose own window is read from the snapshot. With live
    enabled but DONKI unreachable the mode is "replay" and `live_unavailable` is true."""
    d = _SNAPSHOT["donki"]
    live = _live() if settings.live_space_weather else None
    if live:
        out = {"mode": "live", "window": live["window"], "sep_events": live["sep_events"], "kp_max": live["kp_max"], "fast_cmes": None, "flares": None,
               "kp": [], "sep": [], "cme": []}
    else:
        out = {"mode": "replay", "window": _snapshot_window(), "sep_events": len(d["sep"]),
               "kp_max": max(k[1] for k in d["kp"]) if d["kp"] else None, "fast_cmes": len(d["cme"]), "flares": len(d["flares"]),
               "kp": d["kp"], "sep": d["sep"], "cme": d["cme"]}
        if settings.live_space_weather:
            out["live_unavailable"] = True
    out.update(active=event is not None, source="nasa:donki",
               headline="Calm" if event is None else "Radiation storm at Gale crater" if event["source"] == "nasa:rad" else "Solar particle storm in progress")
    if event is not None:  # replayed from a record, simulated, or live from DONKI
        out["event"] = {"id": event["id"], "kind": event["kind"], "origin": event["origin"], "source": event["source"],
                        "live": event["origin"] == "donki"}
    if live:
        out["live"] = live
    return out


def _live() -> Optional[dict]:
    if time.time() - _live_cache["at"] < 1800 and _live_cache["data"]:
        return _live_cache["data"]
    try:
        import httpx
        end = dt.date.today()
        start = end - dt.timedelta(days=30)
        base = "https://api.nasa.gov/DONKI"
        params = {"startDate": start.isoformat(), "endDate": end.isoformat(), "api_key": settings.nasa_api_key}
        with httpx.Client(timeout=8) as c:
            sep = c.get(f"{base}/SEP", params=params).json() or []
            gst = c.get(f"{base}/GST", params=params).json() or []
        kp = [[k["observedTime"], k["kpIndex"]] for e in gst for k in e.get("allKpIndex", [])]
        data = {"window": f"{start} to {end}", "sep_events": len(sep), "kp_max": max([k[1] for k in kp] or [0]), "fetched_at": time.time()}
        _live_cache.update(at=time.time(), data=data)
        return data
    except Exception:  # offline on board, rate limited, or API change: the snapshot is enough
        return None


def rad() -> dict:
    r = _SNAPSHOT["rad"]
    peak = max(v for _, v in r["storm"])
    return {**r, "peak": peak, "ratio": round(peak / r["quietMean"]), "source": "nasa:rad"}


_COLLECTION = re.compile(r"^((?:L-|R\+)\d+)\b")  # a collection label at the start of a note: "L-92 Inspiration4 C002"
_SUBJECT = re.compile(r"Inspiration4 (\w+)")


def blood(crew_id: str, sex: Optional[str]) -> dict:
    """The laboratory results registered for one crew member: the lymphocyte curve (kept for the chart) and every analyte of
    the blood count (OSD-569) and of the metabolic panel (OSD-575) with the laboratory's range for this person's sex and an
    in/out status per collection. Built from the person's own blood observations (`method` blood): `origin` is "real" only
    when every row is a real laboratory result, and "simulated" when the rows are modelled on the Inspiration4 pattern (the
    demo crew). Nothing is borrowed from anyone else, so a person with no laboratory results gets empty lists. C-reactive protein
    has no range in its panel (status None). The collection label and the subject come from each reading's note."""
    from . import data, simdata  # late: data imports this package's registry
    snap = _SNAPSHOT
    tbl = data.table()
    panels = {ind: sec for sec in ("cbc", "cmp") for ind in snap[sec]["an"]}
    series: dict = {}
    origins: set = set()
    for ind, sec in panels.items():
        for (day, v, origin, method, source, note, _unit) in tbl.obs.get((crew_id, ind), []):
            if method == "blood" and (origin == "real" or (origin == "simulated" and "Inspiration4" in (note or ""))):
                series.setdefault(ind, {})[day] = (v, source, note)
                origins.add(origin)
    days = sorted({d for s in series.values() for d in s})
    label = {}
    subject = None
    for d in days:
        note = next((s[d][2] for s in series.values() if d in s and s[d][2]), "")
        m = _COLLECTION.match(note or "")
        label[d] = m.group(1) if m else (f"L{d}" if d < 0 else f"Day {d}")
        subject = subject or (_SUBJECT.search(note or "") or [None, None])[1]
    analytes = {}
    for ind, by_day in series.items():
        an = snap[panels[ind]]["an"][ind]
        rng = simdata.lab_range(snap, ind, sex)
        rng = {"min": rng[0], "max": rng[1]} if rng else None
        vals = [by_day[d][0] if d in by_day else None for d in days]
        analytes[ind] = {"unit": an["unit"], "range": rng, "values": vals, "panel": panels[ind],
                         "source": next(iter(by_day.values()))[1],
                         "status": [None if v is None or rng is None else "in" if rng["min"] <= v <= rng["max"] else "out" for v in vals]}
    lym = simdata.lab_range(snap, "lym", sex)
    if not analytes:
        note = "No laboratory results registered for this crew member yet."
    elif subject and origins == {"real"}:
        note = ("Real Inspiration4 crew data (OSD-569 blood count, OSD-575 metabolic panel), from the subject of the same sex, "
                "shown as a reference for this crew member. Ranges are the laboratory's, by sex.")
    elif subject:
        note = ("Simulated blood values, modelled on the Inspiration4 crew (NASA OSDR OSD-569 blood count, OSD-575 metabolic panel): "
                "not this person's laboratory results. Ranges are the laboratory's, by sex.")
    else:
        note = "Laboratory results registered for this crew member. Ranges are the laboratory's, by sex."
    main = analytes.get("lym") or next(iter(analytes.values()), None)
    return {"subject": subject, "timepoints": [label[d] for d in days],
            "lymphocytes": analytes["lym"]["values"] if "lym" in analytes else [],
            "range": {"min": lym[0], "max": lym[1]} if lym else None, "unit": "cells/µL",
            "analytes": analytes, "origin": ("real" if origins == {"real"} else "simulated") if analytes else None, "note": note,
            "source": main["source"] if main else None}
