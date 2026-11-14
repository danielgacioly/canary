"""Guided Response protocol bank.

Protocols are data (data/protocols.json), not code, so the medical team can review
and change them without touching the app. Each step can carry a variant `v` by
gravity (g0, gp, g1) or by place; `resolve` picks the right text for where the
crew is. Steps branch with `yes` / `no` (a step index or another protocol id).

The content is illustrative first aid adapted to spaceflight. It has NOT been
clinically reviewed and must be replaced by flight-surgeon protocols.
"""
import json
import pathlib

from .catalog import LOCATIONS

_BANK = json.loads((pathlib.Path(__file__).resolve().parents[1] / "data" / "protocols.json").read_text())


def order() -> list:
    return _BANK["order"]


def name(pid: str) -> str:
    p = _BANK["protocols"].get(pid)
    return p["n"] if p else pid


def care(pid: str) -> dict:
    """The care window a protocol leaves after it closes: whole days, what the person may do, and each `after`
    item with its own number of days (the window when the text gives none). Illustrative, see `care_note`."""
    p = _BANK["protocols"].get(pid) or {"after": []}
    window = int(p.get("window_days", 0))
    days = p.get("after_days") or [None] * len(p["after"])
    return {"window_days": window, "ops": p.get("ops", "full"),
            "after_items": [{"title": t, "days": int(d if d is not None else window)} for t, d in zip(p["after"], days)],
            "source": _BANK.get("care_note", {})}


def resolve(location: str) -> dict:
    gk = LOCATIONS[location]["gravity_key"]
    out = {}
    for pid, p in _BANK["protocols"].items():
        steps = []
        for i, st in enumerate(p["steps"]):
            v = st.get("v") or {}
            steps.append({k: st[k] for k in ("t", "q", "yes", "no", "timer", "metro", "breath", "end") if k in st}
                         | {"i": i, "variant": v.get(location) or v.get(gk)})
        out[pid] = {"id": pid, "name": p["n"], "sign": p["s"], "kit": p["kit"], "after": p["after"], "steps": steps,
                    "source": f"protocol:{pid}", **care(pid)}
    return {"order": order(), "protocols": out, "reviewed": False, "care_note": _BANK.get("care_note")}
