"""'How to measure and why': the team's indicator guide (data/indicator_guide), in English, for the system panel.

Texts come from `texts_en.json` (a translation of `indicadores.json`, nothing added). Each text carries the source the guide
lists for it, or none: the app then says "No source checked yet". `id_map.json` maps the guide's ids to Canary's. Numbers in
the guide are never used here: limits live in reference.py and standards.py.
"""
import json
import pathlib
from typing import Dict, Optional

_DIR = pathlib.Path(__file__).resolve().parents[3] / "data" / "indicator_guide"
_COLOUR = {"verde": "green", "amarelo": "amber", "vermelho": "red"}


def _load() -> Dict[str, dict]:
    raw = json.loads((_DIR / "indicadores.json").read_text(encoding="utf-8"))
    texts = json.loads((_DIR / "texts_en.json").read_text(encoding="utf-8"))
    ids = json.loads((_DIR / "id_map.json").read_text(encoding="utf-8"))["map"]
    links = raw["fontes"]
    out: Dict[str, dict] = {}
    for g in raw["indicadores"]:
        m, t = ids.get(g["id"]) or {}, texts.get(g["id"])
        # radiation has no indicator of its own: the career entry stands for the whole risk
        if not t or not m.get("v1") or m.get("kind") not in ("indicator", "risk") or m["v1"] in out:
            continue
        action_src = sorted({u for c in g["faixas"].values() if c.get("origem") in ("fonte", "nasa") for u in (c.get("fonte") or [])})
        out[m["v1"]] = {
            "how": t["how"], "effect": t["effect"], "actions": t["actions"], "frequency": t["frequency"],
            # the guide lists no source for how to measure; the NASA risk page backs the effect; the colour rules list theirs
            "sources": {"how": None,
                        "effect": g.get("risco_nasa") or None,
                        "actions": [links[s] for s in action_src if s in links]},
        }
    return out


_GUIDE: Optional[Dict[str, dict]] = None


def guide() -> Dict[str, dict]:
    global _GUIDE
    if _GUIDE is None:
        _GUIDE = _load()
    return _GUIDE
