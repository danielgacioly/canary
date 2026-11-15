"""Match what a person says they see to the closest protocols. Rules only, and every point is visible.

Each emergency protocol carries `keywords` in data/protocols.json: `strong` ones (a word or phrase that names the
problem: "seizure", "not breathing") score 3, `weak` ones (a clue: "not responding", "rash") score 1. A phrase matches
when its words appear in the text in that order, with at most two words in between. Words are compared after a light
stemming (breathing, breathes, breathe -> breath), and a word of 5+ letters may have one typo (two from 9 letters),
if it starts with the same letter. Ties go to the protocol that comes first in the bank (the most urgent first).

Nothing here is a diagnosis. The answer lists the words that matched so the person can see why, and the person
always starts the protocol themselves (the web app never starts one on its own).
"""
import re
from typing import Dict, List, Optional

from . import protocols

STRONG, WEAK = 3, 1
MAX_GAP = 2   # words allowed between the words of a phrase
LIMIT = 3     # the best match and up to two alternatives
FILLER = {"a", "an", "the", "in", "on", "of", "my", "his", "her", "their", "is", "to", "and", "something", "with"}  # not shown as a match
FALLBACK = "cpr"  # nothing matched: basic life support starts with "is the person responding and breathing?"


def _words(text: str) -> List[str]:
    return re.findall(r"[a-z]+", text.lower().replace("’", "").replace("'", ""))


def _stem(w: str) -> str:
    for suf in ("ing", "ed", "es", "s"):
        if len(w) > len(suf) + 2 and w.endswith(suf):
            w = w[: -len(suf)]
            break
    return w[:-1] if len(w) > 3 and w.endswith("e") else w


def _dist(a: str, b: str) -> int:
    """Edit distance, with a swap of two neighbouring letters counting as one edit."""
    prev2, prev = None, list(range(len(b) + 1))
    for i in range(1, len(a) + 1):
        cur = [i] + [0] * len(b)
        for j in range(1, len(b) + 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (a[i - 1] != b[j - 1]))
            if prev2 is not None and i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                cur[j] = min(cur[j], prev2[j - 2] + 1)
        prev2, prev = prev, cur
    return prev[-1]


def _same(t, k) -> bool:
    """`t` and `k` are (word, stem): the same word after stemming, or close to it as typed."""
    return _close(t[1], k[1]) or _close(t[0], k[0])


def _close(t: str, k: str) -> bool:
    if t == k:
        return True
    n = len(k)
    allowed = 2 if n >= 9 else 1 if n >= 5 else 0
    return bool(allowed) and t[:1] == k[:1] and abs(len(t) - n) <= allowed and _dist(t, k) <= allowed


def _find(stems: list, phrase: list) -> Optional[List[int]]:
    """Positions in the text of the words of `phrase`, in order and close together, or None."""
    for start, s in enumerate(stems):
        if not _same(s, phrase[0]):
            continue
        pos, at = [start], start
        for k in phrase[1:]:
            nxt = next((j for j in range(at + 1, min(len(stems), at + 2 + MAX_GAP)) if _same(stems[j], k)), None)
            if nxt is None:
                break
            pos.append(nxt)
            at = nxt
        if len(pos) == len(phrase):
            return pos
    return None


def match(text: str) -> dict:
    """{"matches": [{id, name, sign, score, matched}], "fallback": {...} or None}. `matched` lists the words of the text that counted."""
    words = _words(text)
    stems = [(w, _stem(w)) for w in words]
    bank = protocols.bank()["protocols"]
    found: Dict[str, dict] = {}
    for pid in protocols.order():
        kw = bank[pid].get("keywords") or {}
        hit: Dict[int, int] = {}  # position in the text -> the points it earned (the best one: a word counts once)
        for weight, group in ((STRONG, kw.get("strong", [])), (WEAK, kw.get("weak", []))):
            for phrase in group:
                ks = [(w, _stem(w)) for w in _words(phrase)]
                pos = _find(stems, ks) if ks else None
                for i in pos or []:
                    hit[i] = max(hit.get(i, 0), weight)
        if hit:
            seen = [words[i] for i in sorted(hit) if words[i] not in FILLER]
            found[pid] = {"id": pid, "name": bank[pid]["n"], "sign": bank[pid]["s"], "score": sum(hit.values()),
                          "matched": list(dict.fromkeys(seen))}
    ranked = sorted(found.values(), key=lambda m: (-m["score"], protocols.order().index(m["id"])))[:LIMIT]
    fb = bank[FALLBACK]
    return {"matches": ranked, "fallback": None if ranked else {"id": FALLBACK, "name": fb["n"], "sign": fb["s"]}}
