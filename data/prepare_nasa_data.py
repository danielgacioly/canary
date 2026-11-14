"""Rebuild the space-weather and Mars-radiation sections of backend/canary/data/nasa_snapshot.json.

Usage: python data/prepare_nasa_data.py <download_dir> <rad_dir> backend/canary/data/nasa_snapshot.json
  <download_dir> holds donki_SEP.json, donki_GST.json, donki_CME.json (api.nasa.gov/DONKI, 2024-05-05 to 2024-05-16)
  <rad_dir>      holds msl_rad_obs-l2_2024130_v04.cdf (9 May 2024) and msl_rad_obs-l2_2024141_v04.cdf (20 May 2024)
Needs numpy and cdflib.

The blood sections (`cbc` from OSD-569, `cmp` from OSD-575) are built by data/prepare_blood.py, which also
documents the corrections made to the OSDR files; this script keeps them as they are.
"""
import json, os, pathlib, sys
import cdflib, numpy as np
D, RAD, OUT = sys.argv[1], sys.argv[2], sys.argv[3]
old = json.loads(pathlib.Path(OUT).read_text(encoding="utf-8")) if os.path.exists(OUT) else {}
# DONKI
sep = json.load(open(D + "/donki_SEP.json", encoding="utf-8")); gst = json.load(open(D + "/donki_GST.json", encoding="utf-8"))
cme = json.load(open(D + "/donki_CME.json", encoding="utf-8"))
S = [{"t": e["eventTime"], "i": e["instruments"][0]["displayName"], "n": len(e.get("linkedEvents") or [])} for e in sep]
fl = sorted({l["activityID"][:16] for e in sep for l in (e.get("linkedEvents") or []) if "-FLR-" in l["activityID"]})
K = [[k["observedTime"], k["kpIndex"]] for e in gst for k in e["allKpIndex"]]
C = []
for e in cme:
    a = [x for x in (e.get("cmeAnalyses") or []) if x.get("isMostAccurate")]
    if a and a[0].get("speed") and a[0]["speed"] >= 900: C.append({"t": e["startTime"], "v": round(a[0]["speed"]), "type": a[0].get("type")})
print("fast CMEs", len(C), C[:4]); print("flares", fl)
# RAD
def series(f):
    c = cdflib.CDF(f); d = np.array(c.varget("DOSIMETRY_TOTAL"), dtype=float)[:, 2]
    ep = cdflib.cdfepoch.to_datetime(c.varget("EPOCH"))
    out = []
    for t, v in zip(ep, d):
        if 0 < v < 1e5:
            t = str(t); out.append([round(int(t[11:13]) + int(t[14:16]) / 60, 2), round(float(v))])
    return out
quiet = series(RAD + "/msl_rad_obs-l2_2024130_v04.cdf"); storm = series(RAD + "/msl_rad_obs-l2_2024141_v04.cdf")
print("quiet n", len(quiet), quiet[:3], "storm n", len(storm), "max", max(storm, key=lambda x: x[1]))
qm = round(sum(v for _, v in quiet) / len(quiet))
data = {**{k: old[k] for k in ("cbc",) if k in old},
        "donki": {"sep": S, "flares": fl, "kp": K, "cme": C},
        "rad": {"quietMean": qm, "quiet": quiet[::3], "storm": storm, "unit": "µGy/day", "det": "detector E (tissue-equivalent plastic)"},
        **{k: old[k] for k in ("cmp",) if k in old}}
pathlib.Path(OUT).write_text(json.dumps(data, separators=(",", ":"), ensure_ascii=False), encoding="utf-8")
print("bytes", os.path.getsize(OUT))
