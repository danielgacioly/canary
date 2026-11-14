"""The knowledge-base corpus: every approved document, split into short quotable chunks.

Pure and deterministic: the same source data always gives the same documents, chunks and hashes.
Sources (docs/ai/schema.md §3): protocols (data/protocols.json), system cards and places (catalog),
NASA source notes (domain/nasa), the five RIDGE hazards and the visibility contract (domain/privacy)
and one card per self-test (domain/selftests). Ids and hand-written extras come from data/kb_map.json.
"""
import hashlib
import json
import pathlib
from dataclasses import asdict, dataclass, field
from typing import Dict, List

from ...domain import nasa, privacy, selftests
from ...domain.catalog import INDICATORS, LOCATIONS, SYSTEMS

DATA = pathlib.Path(__file__).resolve().parents[2] / "data"
PLACES = tuple(LOCATIONS)  # earth, rocket, iss, moon, transit, mars
GRAVITY_KEYS = ("g0", "gp", "g1")
GRAVITY_LABEL = {"g0": "0 g (zero gravity)", "gp": "partial gravity (Moon, Mars)", "g1": "1 g (Earth gravity)"}
# Bump when the chunking rules change, so the corpus hash changes with them.
CHUNKER_VERSION = 1


@dataclass
class ChunkSpec:
    chunk: str                 # summary | s2 | s2-g0 | s2-mars | after | mars | r3
    section: str               # summary | step | variant | after | place | row
    title: str
    text: str
    gravity: str = "any"
    location: str = "any"
    not_in: List[str] = field(default_factory=list)  # places where a more specific variant replaces this one
    keywords: str = ""


@dataclass
class Document:
    doc_id: str
    version: int
    kind: str
    title: str
    legacy_id: str
    reviewed: str
    source_ref: str
    chunks: List[ChunkSpec]

    @property
    def content_hash(self) -> str:
        body = {k: v for k, v in asdict(self).items() if k != "version"}
        return hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode()).hexdigest()

    def chunk_id(self, c: ChunkSpec) -> str:
        return f"kb:{self.doc_id}@{self.version}#{c.chunk}"


def load_map() -> dict:
    return json.loads((DATA / "kb_map.json").read_text())


def _bank() -> dict:
    return json.loads((DATA / "protocols.json").read_text())


def _join(items: List[str]) -> str:
    return ", ".join(items)


def _branches(bank: dict, st: dict) -> str:
    """Where a yes / no answer leads, in words. Only spelled out when it leads to another protocol."""
    out = []
    for ans in ("yes", "no"):
        to = st.get(ans)
        if isinstance(to, str):
            out.append(f"If {ans}: {bank['protocols'][to]['n']}.")
    return " ".join(out)


def _protocols(m: dict) -> List[Document]:
    bank = _bank()
    out = []
    for pid in bank["order"]:
        p = bank["protocols"][pid]
        doc_id = m["protocols"][pid]
        kw = m["keywords"].get(doc_id, "")
        head = f"{p['n']} ({p['s']})"  # the sign names the protocol the way people say it ("Start CPR")
        chunks = [ChunkSpec("summary", "summary", p["n"],
                            f"{p['n']}. Sign: {p['s']}. Kit: {_join(p['kit'])}.", keywords=kw)]
        for i, st in enumerate(p["steps"]):
            n = i + 1
            text = " ".join(x for x in (st.get("t"), f"Ask: {st['q']}" if st.get("q") else None, _branches(bank, st)) if x)
            chunks.append(ChunkSpec(f"s{n}", "step", f"{head}, step {n}", text))
            v = st.get("v") or {}
            for key in sorted(v):
                if key in GRAVITY_KEYS:
                    # A place-specific variant of the same step wins over the gravity one there (protocols.resolve).
                    overridden = sorted(pl for pl in PLACES if LOCATIONS[pl]["gravity_key"] == key and pl in v)
                    chunks.append(ChunkSpec(f"s{n}-{key}", "variant", f"{head}, step {n}, in {GRAVITY_LABEL[key]}",
                                            v[key], gravity=key, not_in=overridden))
                elif key in LOCATIONS:
                    chunks.append(ChunkSpec(f"s{n}-{key}", "variant", f"{head}, step {n}, {LOCATIONS[key]['name']}",
                                            v[key], gravity=LOCATIONS[key]["gravity_key"], location=key))
                else:
                    raise ValueError(f"protocol {pid} step {n}: unknown variant key {key!r}")
        if p["after"]:
            chunks.append(ChunkSpec("after", "after", f"{head}, afterwards", "Afterwards: " + "; ".join(p["after"]) + "."))
        out.append(Document(doc_id, int(p.get("version", 1)), "protocol", p["n"], f"protocol:{pid}",
                            p.get("reviewed", "illustrative"), f"data/protocols.json#{pid}", chunks))
    return out


def _version(m: dict, doc_id: str) -> int:
    return int(m.get("versions", {}).get(doc_id, 1))


def _cards(m: dict) -> List[Document]:
    out = []
    for sid, s in SYSTEMS.items():
        doc_id = f"CARD-{sid.upper()}"
        inds = _join(INDICATORS[i]["name"] for i in s["indicators"]) or "none yet"
        text = f"{s['name']}. {s['space']} Hazard: {s['hazard']}. Indicators Canary follows: {inds}."
        out.append(Document(doc_id, _version(m, doc_id), "system_card", s["name"], f"card:{sid}", "illustrative",
                            f"catalog.SYSTEMS.{sid}",
                            [ChunkSpec("summary", "summary", s["name"], text, keywords=m["keywords"].get(doc_id, ""))]))
    return out


def _places(m: dict) -> List[Document]:
    out = []
    for pl, p in LOCATIONS.items():
        doc_id = f"LOC-{pl.upper()}"
        reply = "live" if p["reply"] == "Live" else f"in {p['reply']}"
        text = (f"{p['name']} ({p['sub']}). Gravity: {p['gravity']}. Earth replies {reply}; "
                f"nearest hospital: {p['hospital'].lower()}. Background radiation: about {p['dose_rate']} mSv a day. "
                f"What to expect: {p['what']}")
        # A place card describes a destination, not a variant, so it is tagged "any": a crew in transit may ask
        # what Mars will be like. Place-specific variants (protocol steps, hazard levels) carry the place tag.
        out.append(Document(doc_id, _version(m, doc_id), "location", p["name"], "", "illustrative",
                            f"catalog.LOCATIONS.{pl}; dose rate: catalog.DOSE_SOURCE",
                            [ChunkSpec("summary", "summary", p["name"], text, keywords=m["keywords"].get(doc_id, ""))]))
    return out


def _nasa(m: dict) -> List[Document]:
    out = []
    for s in nasa.SOURCES:
        if not s["id"].startswith("nasa:"):
            continue  # the body mesh credit is not a knowledge source
        key = s["id"].split(":", 1)[1]
        doc_id = f"NASA-{key.upper()}"
        text = f"{s['name']}, from {s['org']}. Canary uses it for: {s['used_for']}."
        out.append(Document(doc_id, _version(m, doc_id), "nasa_source", s["name"], s["id"], "illustrative", s["url"],
                            [ChunkSpec("summary", "summary", s["name"], text, keywords=m["keywords"].get(doc_id, ""))]))
    return out


def _hazards(m: dict) -> List[Document]:
    out = []
    for h in privacy.RIDGE:
        doc_id = f"HAZARD-{h['id']}"
        names = _join(SYSTEMS[s]["name"] for s in h["systems"])
        chunks = [ChunkSpec("summary", "summary", h["name"], f"{h['name']}: {h['what']} Body systems it affects: {names}.",
                            keywords=m["keywords"].get(doc_id, ""))]
        for pl in PLACES:
            lv = privacy.RIDGE_LEVEL[pl][h["id"]]
            text = f"{h['name']} at {LOCATIONS[pl]['name']}: {privacy.LEVEL_LABEL[lv].lower()}. {privacy._here(h['id'], pl)}."
            if h["id"] == "R" and pl != "earth":
                text += " A solar storm raises it to high."
            g = privacy.HAZARD_BY_GRAVITY.get(LOCATIONS[pl]["gravity_key"]) if h["id"] == "G" else None
            if g:
                text += f" {g[0]}: {g[1]}"
            chunks.append(ChunkSpec(pl, "place", f"{h['name']}, {LOCATIONS[pl]['name']}", text,
                                    gravity=LOCATIONS[pl]["gravity_key"], location=pl))
        out.append(Document(doc_id, _version(m, doc_id), "hazard", h["name"], "", "illustrative",
                            "privacy.RIDGE, privacy.RIDGE_LEVEL, privacy.HAZARD_BY_GRAVITY; NASA HRP hazards", chunks))
    return out


def _docstring_text(doc: str) -> str:
    """The privacy module docstring as one paragraph."""
    return " ".join(line.strip().lstrip("- ").strip() for line in doc.strip().splitlines() if line.strip())


def _privacy(m: dict) -> List[Document]:
    doc_id = "PRIVACY-CONTRACT"
    chunks = [ChunkSpec("summary", "summary", "Who sees what", _docstring_text(privacy.__doc__),
                        keywords=m["keywords"].get(doc_id, ""))]
    for i, r in enumerate(privacy.CONTRACT, 1):
        text = (f"Who sees {r['info'][0].lower() + r['info'][1:]}: the astronaut: {r['self']}; the medical team: {r['doctor']}; "
                f"the rest of the crew: {r['crew']}; Earth: {r['earth']}.")
        chunks.append(ChunkSpec(f"r{i}", "row", f"Who sees what: {r['info']}", text))
    return [Document(doc_id, _version(m, doc_id), "privacy", "Who sees what", "", "illustrative",
                     "privacy.CONTRACT and the domain/privacy.py docstring", chunks)]


def _minutes(x: float) -> str:
    if x < 1:
        return f"under a minute ({round(x * 60)} s)"
    return f"about {x:g} minute{'s' if x != 1 else ''}"


def _selftests(m: dict) -> List[Document]:
    out = []
    for t in selftests.TESTS:
        doc_id = f"TEST-{t['id'].upper()}"
        text = (f"{t['name']} ({t['group'].lower()} test). It measures: {t['measures'][0].lower() + t['measures'][1:]}. "
                f"Takes {_minutes(t['minutes'])}. Based on: {t['source']}. {m['notes'].get(doc_id, '')}".strip())
        text += " Results are private to you and the medical team, and they are never a diagnosis."
        out.append(Document(doc_id, _version(m, doc_id), "self_test", t["name"], "", "illustrative",
                            f"selftests.TESTS.{t['id']}",
                            [ChunkSpec("summary", "summary", t["name"], text, keywords=m["keywords"].get(doc_id, ""))]))
    return out


def documents() -> List[Document]:
    m = load_map()
    docs = _protocols(m) + _cards(m) + _places(m) + _nasa(m) + _hazards(m) + _privacy(m) + _selftests(m)
    ids = [d.doc_id for d in docs]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate knowledge document id")
    return docs


def corpus_hash(docs: List[Document]) -> str:
    rows = sorted((d.doc_id, d.version, d.content_hash) for d in docs)
    return hashlib.sha256(json.dumps({"chunker": CHUNKER_VERSION, "docs": rows}).encode()).hexdigest()


def legacy_map() -> Dict[str, str]:
    """Legacy source id (protocol:seizure, card:brain, nasa:rad) → kb document id."""
    return dict(load_map()["legacy"])
