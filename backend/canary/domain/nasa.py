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

_SNAPSHOT = json.loads((pathlib.Path(__file__).resolve().parents[1] / "data" / "nasa_snapshot.json").read_text())
_live_cache: dict = {"at": 0.0, "data": None}

SOURCES = [
    {"id": "nasa:donki", "name": "DONKI space weather", "org": "NASA CCMC / M2M",
     "url": "https://kauai.ccmc.gsfc.nasa.gov/DONKI/", "used_for": "Solar storm alerts, Kp index, CMEs (10 May 2024 replay)"},
    {"id": "nasa:rad", "name": "Curiosity RAD level 2", "org": "NASA PDS / SPDF",
     "url": "https://spdf.gsfc.nasa.gov/pub/data/aaa_planetary/msl/rad/cdf/obs-l2/", "used_for": "Mars surface dose rate, quiet day vs 20 May 2024 storm"},
    {"id": "nasa:osd569", "name": "OSD-569 Inspiration4 blood counts", "org": "NASA OSDR",
     "url": "https://osdr.nasa.gov/bio/repo/data/studies/OSD-569", "used_for": "Real lymphocyte curves before and after spaceflight"},
    {"id": "nasa:hrp", "name": "Human Research Program hazards and risks", "org": "NASA HRP",
     "url": "https://www.nasa.gov/hrp/hazards/", "used_for": "The five hazards (RIDGE) behind each body system"},
    {"id": "makehuman", "name": "MakeHuman base mesh (CC0)", "org": "MakeHuman community",
     "url": "https://github.com/makehumancommunity/makehuman", "used_for": "Body shape of the hologram"},
]


def snapshot() -> dict:
    return _SNAPSHOT


def space_weather(storm: Optional[str]) -> dict:
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
        "active": storm is not None,
        "headline": "Solar particle storm in progress" if storm == "sep" else "Radiation storm at Gale crater" if storm == "mars" else "Calm",
        "source": "nasa:donki",
    }
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


def blood(subject: str) -> dict:
    """Inspiration4 complete blood count for one crew member: the lymphocyte curve (kept for the chart) and every
    analyte with its reference range and an in/out status per collection. Real data (OSD-569). No alert uses it yet."""
    cbc = _SNAPSHOT["cbc"]
    analytes = {}
    for ind, series in cbc["crew"][subject].items():
        rng = cbc["an"][ind]
        analytes[ind] = {"unit": rng["unit"], "range": {"min": rng["min"], "max": rng["max"]}, "values": series,
                         "status": [None if v is None else "in" if rng["min"] <= v <= rng["max"] else "out" for v in series]}
    return {"subject": subject, "timepoints": cbc["tp"], "lymphocytes": cbc["crew"][subject]["lym"],
            "range": {"min": cbc["an"]["lym"]["min"], "max": cbc["an"]["lym"]["max"]}, "unit": "cells/µL",
            "analytes": analytes, "origin": "real",
            "note": "Real Inspiration4 crew data (OSD-569), shown as a reference curve for this crew member.",
            "source": "nasa:osd569"}
