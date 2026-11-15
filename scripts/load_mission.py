#!/usr/bin/env python3
"""Load a mission package (a folder of CSV files, see data/missions/odyssey1-mars/README.md) into the Canary database.

    CANARY_DB=/path/to/canary.db python scripts/load_mission.py data/missions/odyssey1-mars
    CANARY_DB=/path/to/canary.db python scripts/load_mission.py data/missions/odyssey1-mars --reset

It uses the same import as POST /api/control/import and the demo reset (backend/canary/domain/data.py), without a
server: every file is validated first, and one bad row stops the import with a message naming the file and row and
nothing written. `--reset` clears the database first (like "reset demo"). Readings already stored are not stored twice.
Without CANARY_DB the default database (backend/canary.db) is used. Exit status: 0 loaded, 1 refused, 2 not a package.
"""
import argparse
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Load a mission package folder into the Canary database.")
    ap.add_argument("folder", help="the package folder (mission.csv, legs.csv, crew.csv, observations.csv, ...)")
    ap.add_argument("--reset", action="store_true", help="clear the database first")
    args = ap.parse_args(argv)
    folder = pathlib.Path(args.folder)
    if not folder.is_dir():
        print(f"Not a folder: {folder}", file=sys.stderr)
        return 2

    from canary import db
    from canary.config import settings
    from canary.domain import data, plan, registry
    from canary.domain.validation import ValidationFailure

    db.connect()
    try:
        if args.reset:
            db.reset()
            plan.reset_cache()
            registry.load()
        bundled = folder.resolve().parent == pathlib.Path(settings.missions_dir).resolve()
        result = data.import_package(folder, name=folder.resolve().name, bundled=bundled)
    except ValidationFailure as e:
        print(f"Refused: nothing was written ({len(e.errors)} problem(s) shown).", file=sys.stderr)
        for err in e.errors:
            print(f"  {err['field']}: {err['message']}", file=sys.stderr)
        return 1
    print(f"Loaded {folder.name} into {settings.db_path}")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
