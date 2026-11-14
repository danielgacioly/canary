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
                    "source": f"protocol:{pid}"}
    return {"order": order(), "protocols": out, "reviewed": False}
