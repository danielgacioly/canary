#!/usr/bin/env python3
"""Generate the ship's observation table for the default mission plan.

    python data/generate_dataset.py

Writes (all deterministic, standard library only, no network):
  data/real/osd569_cbc.csv                 real Inspiration4 blood counts, converted from nasa_snapshot.json
  backend/canary/data/observations.csv     one row per measurement, with its origin
  data/DATASET.md                          what is in the file, where it came from, how it would be collected

Real files in data/real/ replace the simulated row with the same (crew_id, day, indicator).
"""
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from canary.domain import plan, simdata  # noqa: E402


def main() -> None:
    recipes = simdata.load_recipes()
    snapshot = simdata.load_snapshot()
    simdata.REAL_DIR.mkdir(parents=True, exist_ok=True)
    simdata.write_csv(simdata.osd569_rows(snapshot, recipes), simdata.REAL_DIR / "osd569_cbc.csv")

    legs = plan.PRESETS[plan.DEFAULT]["legs"]
    rows = simdata.Generator(legs, recipes, simdata.REAL_DIR, snapshot).observations()
    simdata.write_csv(rows, simdata.OBS_FILE)
    text = simdata.report(rows, recipes, plan.PRESETS[plan.DEFAULT]["name"])
    simdata.REPORT_FILE.write_text(text, encoding="utf-8", newline="")

    size = simdata.OBS_FILE.stat().st_size
    print(text)
    print(f"Wrote {simdata.OBS_FILE.relative_to(ROOT)} ({len(rows):,} rows, {size / 1e6:.2f} MB), "
          f"{simdata.REPORT_FILE.relative_to(ROOT)} and data/real/osd569_cbc.csv")


if __name__ == "__main__":
    main()
