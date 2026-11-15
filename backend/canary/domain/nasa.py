"""NASA open data used by Canary.

- DONKI (Space Weather Database Of Notifications, Knowledge, Information): solar
  particle events, geomagnetic storms (Kp) and fast CMEs, 5 to 16 May 2024.
- Curiosity RAD level 2 (PDS / SPDF): total dose rate at Gale crater, quiet day
  9 May 2024 and storm day 20 May 2024.
- OSDR OSD-569: Inspiration4 complete blood counts, 4 crew, 7 time points.

A snapshot is bundled in data/nasa_snapshot.json (built by data/prepare_nasa_data.py)
so the ship never depends on a network. With CANARY_LIVE_SPACE_WEATHER=1 the API
also asks DONKI for the last 30 days and falls back to the snapshot on any error.
"""
import datetime as dt
import json
import pathlib
import time
from typing import Optional

from ..config import settings

_SNAPSHOT = json.loads((pathlib.Path(__file__).resolve().parents[1] / "data" / "nasa_snapshot.json").read_text(encoding="utf-8"))
_live_cache: dict = {"at": 0.0, "data": None}

SOURCES = [
    {"id": "nasa:donki", "name": "DONKI space weather", "org": "NASA CCMC / M2M",
     "url": "https://kauai.ccmc.gsfc.nasa.gov/DONKI/", "used_for": "Solar storm alerts, Kp index, CMEs (10 May 2024 replay)"},
    {"id": "nasa:rad", "name": "Curiosity RAD level 2", "org": "NASA PDS / SPDF",
     "url": "https://spdf.gsfc.nasa.gov/pub/data/aaa_planetary/msl/rad/cdf/obs-l2/", "used_for": "Mars surface dose rate, quiet day vs 20 May 2024 storm"},
    {"id": "nasa:osd569", "name": "OSD-569 Inspiration4 blood counts", "org": "NASA OSDR",
     "url": "https://osdr.nasa.gov/bio/repo/data/studies/OSD-569", "used_for": "Real lymphocyte curves before and after spaceflight"},
    {"id": "nasa:osd575", "name": "OSD-575 Inspiration4 metabolic panel and CRP", "org": "NASA OSDR",
     "url": "https://osdr.nasa.gov/bio/repo/data/studies/OSD-575", "used_for": "Real creatinine, potassium, calcium and C-reactive protein"},
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


def space_weather(event: Optional[dict] = None) -> dict:
    """The space-weather snapshot. `event` is the space event active on the mission day at the crew's place (a row of
    data.events(), found with data.event(ms["storm"])), or None."""
    d = _SNAPSHOT["donki"]
    kp_max = max(k[1] for k in d["kp"]) if d["kp"] else None
    out = {
        "mode": "replay",
        "window": "2024-05-05 to 2024-05-16",
        "sep_events": len(d["sep"]),
        "kp_max": kp_max,
        "fast_cmes": len(d["cme"]),
        "flares": len(d["flares"]),
        "kp": d["kp"],
        "sep": d["sep"],
        "cme": d["cme"],
        "active": event is not None,
        "headline": "Calm" if event is None else "Radiation storm at Gale crater" if event["source"] == "nasa:rad" else "Solar particle storm in progress",
        "source": "nasa:donki",
    }
    if event is not None:  # replayed from a record, or live from DONKI
        out["event"] = {"id": event["id"], "kind": event["kind"], "origin": event["origin"], "source": event["source"],
                        "live": event["origin"] == "donki"}
    if settings.live_space_weather:
        live = _live()
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


def blood(subject: str, sex: str) -> dict:
    """Inspiration4 lab results for one crew member: the lymphocyte curve (kept for the chart) and every analyte of
    the blood count (OSD-569) and of the metabolic panel (OSD-575) with the laboratory's range for this sex and an
    in/out status per collection. Real data. C-reactive protein has no range in its panel (status None)."""
    analytes = {}
    for section in ("cbc", "cmp"):
        lab = _SNAPSHOT.get(section)
        if not lab or subject not in lab["crew"]:
            continue
        for ind, series in lab["crew"][subject].items():
            an = lab["an"][ind]
            rng = an.get(sex)
            analytes[ind] = {"unit": an["unit"], "range": rng, "values": series, "panel": section,
                             "source": "nasa:osd569" if section == "cbc" else "nasa:osd575",
                             "status": [None if v is None or rng is None else "in" if rng["min"] <= v <= rng["max"] else "out"
                                        for v in series]}
    lym = _SNAPSHOT["cbc"]["an"]["lym"][sex]
    return {"subject": subject, "timepoints": _SNAPSHOT["cbc"]["tp"], "lymphocytes": _SNAPSHOT["cbc"]["crew"][subject]["lym"],
            "range": {"min": lym["min"], "max": lym["max"]}, "unit": "cells/µL",
            "analytes": analytes, "origin": "real",
            "note": "Real Inspiration4 crew data (OSD-569 blood count, OSD-575 metabolic panel), from the subject of the same sex, "
                    "shown as a reference for this crew member. Ranges are the laboratory's, by sex.",
            "source": "nasa:osd569"}
