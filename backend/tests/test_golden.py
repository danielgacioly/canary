"""Golden snapshots of the demo API: the demo must not change number by number.

    pytest tests/test_golden.py                          compare with tests/golden/scene_N.json
    CANARY_GOLDEN_UPDATE=1 pytest tests/test_golden.py   rewrite the golden files (review the diff before committing)

Fields in golden_capture.NEW_FIELDS may be added later; any other difference fails with the path of the change.
"""
import json
import os
import pathlib
import tempfile

os.environ["CANARY_DB"] = os.path.join(tempfile.mkdtemp(), "golden.db")

import pytest  # noqa: E402

from tests import golden_capture as gc  # noqa: E402

GOLDEN = pathlib.Path(__file__).parent / "golden"
UPDATE = os.environ.get("CANARY_GOLDEN_UPDATE") == "1"


@pytest.fixture(scope="module")
def captured():
    return gc.capture_all()


@pytest.mark.parametrize("i", range(gc.SCENES))
def test_scene_matches_golden(captured, i):
    now = captured[i]
    f = GOLDEN / f"scene_{i}.json"
    if UPDATE:
        GOLDEN.mkdir(exist_ok=True)
        f.write_text(gc.dump(now))
        return
    assert f.exists(), f"{f} missing: run CANARY_GOLDEN_UPDATE=1 pytest tests/test_golden.py"
    golden = json.loads(f.read_text())
    d = gc.diff(golden, now)
    assert not d, f"scene {i} differs from the golden snapshot ({len(d)} shown, max 20):\n" + "\n".join(d)


def test_diff_semantics():
    g = {"a": 1.0, "b": {"x": [1, 2]}}
    assert gc.diff(g, {"a": 1.0, "b": {"x": [1, 2]}, "stale": False, "origin": "x"}) == []
    assert gc.diff(g, {"a": 1.0, "b": {"x": [1, 2]}, "other": 1})
    assert gc.diff(g, {"a": 1.0000001, "b": {"x": [1, 2]}})
    assert gc.diff(g, {"a": 1.0, "b": {"x": [1, 3]}})[0].startswith("$.b.x[1]")
    assert gc.diff({"origin": "a"}, {"origin": "b"})  # a changed value of an existing key always fails
