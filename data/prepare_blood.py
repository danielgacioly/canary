#!/usr/bin/env python3
"""Build the blood sections of backend/canary/data/nasa_snapshot.json from the NASA OSDR files.

    python data/prepare_blood.py <osdr_dir> backend/canary/data/nasa_snapshot.json

<osdr_dir> holds the files as downloaded from https://osdr.nasa.gov (standard library only, no network):
  LSDS-7_Complete_Blood_Count_CBC_TRANSFORMED.csv                  OSD-569, complete blood count
  LSDS-8_Comprehensive_Metabolic_Panel_CMP.upload_SUBMITTED.csv    OSD-575, metabolic panel
  LSDS-8_Multiplex_serum_cardiovascular_EvePanel_TRANSFORMED.csv   OSD-575, C-reactive protein

Only the `cbc` and `cmp` sections of the snapshot are rewritten; DONKI and RAD stay as they are
(those come from data/prepare_nasa_data.py).

Three corrections, each checked against the numbers themselves:
1. C003 at L-92 in the OSD-569 file: MCH is missing and every value after it sits one row down
   (platelets 12.9, MPV 330). The arithmetic confirms the realignment: WBC 9.6 x neutrophils 71.1% = 6826
   neutrophils, 9.6 x lymphocytes 20.8% = 1997 lymphocytes. Platelets are 330.
2. Reference ranges by sex. The files give each row its own range; the female and male ranges differ for
   haemoglobin, haematocrit, red cells, creatinine and calcium. C003 (female) has male ranges on her three
   pre-flight rows, so each sex takes the range most of its rows carry.
3. Haemoglobin is labelled `percent` in the OSD-569 file; its unit is g/dL.
Glucose from the metabolic panel is not imported: three of four crew read 36 to 44 mg/dL on the same day
(R+45) with every other collection normal, the pattern of a sample processed late, and the ship measures
glucose with its own fingerstick indicator.
"""
import csv
import json
import pathlib
import sys
from collections import Counter, defaultdict

ORDER = ["L-92", "L-44", "L-3", "R+1", "R+45", "R+82", "R+194"]
SEX = {"C001": "M", "C002": "F", "C003": "F", "C004": "M"}  # OSD-569 / OSD-575 sample metadata, Characteristics[Sex]

CBC_KEYS = {"wbc": "white_blood_cell_count", "lym": "absolute_lymphocytes", "neu": "absolute_neutrophils",
            "hgb": "hemoglobin", "hct": "hematocrit", "plt": "platelet_count", "rbc": "red_blood_cell_count"}
CBC_UNITS = {"hgb": "grams_per_deciliter"}  # the file says percent

CMP_KEYS = {"creatinine": "CREATININE", "potassium": "POTASSIUM", "calcium": "CALCIUM"}
CRP_COLUMN = "crp_concentration_picogram_per_milliliter"


def _read(path: pathlib.Path) -> list:
    return list(csv.DictReader(path.open(encoding="utf-8-sig")))


def _num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _ranges(pairs):
    """{sex: (min, max)} from (sex, min, max) triples: the range most rows of each sex carry."""
    by = defaultdict(Counter)
    for sex, lo, hi in pairs:
        if lo is not None or hi is not None:
            by[sex][(lo, hi)] += 1
    return {s: {"min": c.most_common(1)[0][0][0], "max": c.most_common(1)[0][0][1]} for s, c in sorted(by.items())}


def build_cbc(rows: list) -> dict:
    cols = list(rows[0].keys())

    def col(prefix, kind):
        return next(c for c in cols if c.startswith(prefix + "_" + kind))

    cbc = {"tp": ORDER, "an": {}, "crew": {}}
    for k, p in CBC_KEYS.items():
        v, mn, mx = col(p, "value"), col(p, "range_min"), col(p, "range_max")
        pairs = []
        for r in rows:
            subj, _, tp = r["Sample Name"].split("_")[:3]
            cbc["crew"].setdefault(subj, {}).setdefault(k, [None] * len(ORDER))
            cbc["crew"][subj][k][ORDER.index(tp)] = _num(r[v])
            pairs.append((SEX[subj], _num(r[mn]), _num(r[mx])))
        cbc["an"][k] = {"unit": CBC_UNITS.get(k, v.split("_value_")[1]), **_ranges(pairs)}

    # correction 1: C003 at L-92, values one row down from MCH on
    c3 = cbc["crew"]["C003"]
    i = ORDER.index("L-92")
    row = next(r for r in rows if r["Sample Name"].startswith("C003_") and "_L-92" in r["Sample Name"])
    mpv, mono = _num(row[col("mpv", "value")]), _num(row[col("absolute_monocytes", "value")])
    if c3["plt"][i] is not None and c3["plt"][i] < 50 and mpv and mpv > 100:
        wbc, neu_pct, lym_pct = c3["wbc"][i], _num(row[col("neutrophils", "value")]), _num(row[col("lymphocytes", "value")])
        c3["plt"][i] = mpv                   # the platelet count sat in the MPV column
        c3["neu"][i] = c3["lym"][i]          # neutrophils sat in the lymphocyte column
        c3["lym"][i] = mono                  # lymphocytes sat in the monocyte column
        assert abs(c3["neu"][i] - wbc * neu_pct * 10) < 2 and abs(c3["lym"][i] - wbc * lym_pct * 10) < 2, "C003 L-92 check failed"
    return cbc


def build_cmp(cmp_rows: list, crp_rows: list) -> dict:
    out = {"tp": ORDER, "an": {}, "crew": {}}
    for k, analyte in CMP_KEYS.items():
        pairs, unit = [], None
        for r in cmp_rows:
            if r["ANALYTE"] != analyte:
                continue
            subj, tp = r["SUBJECT_ID"], r["timepoint"]
            out["crew"].setdefault(subj, {}).setdefault(k, [None] * len(ORDER))
            out["crew"][subj][k][ORDER.index(tp)] = _num(r["VALUE"])
            pairs.append((SEX[subj], _num(r["RANGE_MIN"]), _num(r["RANGE_MAX"])))
            unit = r["UNITS"]
        out["an"][k] = {"unit": unit, **_ranges(pairs)}
    for r in crp_rows:  # pg/mL in the file; mg/L here (1 mg/L = 1,000,000 pg/mL). No reference range in this panel.
        subj, _, tp = r["Sample Name"].split("_")[:3]
        v = _num(r[CRP_COLUMN])
        out["crew"].setdefault(subj, {}).setdefault("crp", [None] * len(ORDER))
        out["crew"][subj]["crp"][ORDER.index(tp)] = None if v is None else round(v / 1e6, 3)
    out["an"]["crp"] = {"unit": "mg/L"}
    return out


def main(osdr_dir: str, snapshot_path: str) -> None:
    d = pathlib.Path(osdr_dir)
    snap_file = pathlib.Path(snapshot_path)
    snap = json.loads(snap_file.read_text(encoding="utf-8"))
    snap["cbc"] = build_cbc(_read(d / "LSDS-7_Complete_Blood_Count_CBC_TRANSFORMED.csv"))
    snap["cmp"] = build_cmp(_read(d / "LSDS-8_Comprehensive_Metabolic_Panel_CMP.upload_SUBMITTED.csv"),
                            _read(d / "LSDS-8_Multiplex_serum_cardiovascular_EvePanel_TRANSFORMED.csv"))
    snap_file.write_text(json.dumps(snap, separators=(",", ":"), ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"cbc_ranges": snap["cbc"]["an"], "cmp_ranges": snap["cmp"]["an"],
                      "C003_L-92": {k: v[0] for k, v in snap["cbc"]["crew"]["C003"].items()}}, indent=1))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
