"""Entry 2: a one-page weekly briefing for the flight surgeon.

Code computes the facts; the model (when connected) only rewrites them as prose in the BriefingDraft shape
(contracts.py, schema.md §7), with no tools. The draft is kept only when it validates, every line cites a
source from the allowed list, and guard.unknown_numbers finds no number that is not in the facts; otherwise
the template text is used (mode "template"). Sections are in priority order so the first lines are enough on
a slow link. The astronaut sees the briefing and approves it before it is queued for Earth.
"""
import json
import pathlib
import time
from typing import List, Optional

from pydantic import ValidationError

from .. import db
from ..config import settings
from ..domain import goals, health, mission
from ..domain.catalog import CREW_BY_ID, LOCATIONS
from . import guard
from .contracts import BriefingDraft
from .providers import ProviderRequest, get_provider

PROMPT_VERSION = "briefing_v1"
SYSTEM_PROMPT = (pathlib.Path(__file__).resolve().parent / "prompts" / f"{PROMPT_VERSION}.md").read_text()


def facts(crew_id: str) -> dict:
    ms = mission.state()
    snap = health.snapshot(crew_id, ms)
    prof = goals.profile(crew_id, ms["day"])
    movers = sorted((i for i in snap["indicators"].values() if i["bad"] is not None and i["value"] is not None), key=lambda i: -i["bad"])[:4]  # no data, no mover
    tried = []
    for r in db.q("SELECT goal_id,day FROM goal_log WHERE crew_id=? AND done=1 AND day>? ORDER BY day", (crew_id, ms["day"] - 7)):
        if r["goal_id"].startswith(("al_", "med_")):
            tried.append(f"day {r['day']}: goal {r['goal_id']}")
    for r in db.q("SELECT kind,day FROM checkins WHERE crew_id=? AND day>? ORDER BY day", (crew_id, ms["day"] - 7)):
        tried.append(f"day {r['day']}: {r['kind']} check-in")
    for r in db.q("SELECT protocol,day,outcome FROM emergencies WHERE patient=? AND day>?", (crew_id, ms["day"] - 7)):
        tried.append(f"day {r['day']}: guided response ({r['protocol']}), {r['outcome'] or 'open'}")
    return {
        "crew": CREW_BY_ID[crew_id]["name"], "day": ms["day"], "day_label": ms["day_label"], "place": LOCATIONS[ms["location"]]["name"],
        "physical": snap["areas"]["physical"], "mental": snap["areas"]["mental"],
        "alerts": [{"title": a["title"], "level": a["level"]} for a in snap["alerts"]],
        "movers": [{"name": i["name"], "value": round(i["value"], i["dp"]), "baseline": i["baseline"], "unit": i["unit"], "z": i["z"]} for i in movers],
        "completion_7d": prof["completion_7d"], "streak": prof["streak"],
        "tried": tried or ["No alert or medical goals completed this week"],
        "dose_msv": snap["dose"]["mission_msv"],
    }


def template(f: dict) -> str:
    lines: List[str] = [f"BRIEFING {f['crew'].upper()} · {f['day_label']} · {f['place']}"]
    lines.append("1 WHAT WORRIES")
    lines += [f"- [{['ok', 'WATCH', 'ACT'][a['level']]}] {a['title']}" for a in f["alerts"][:3]] or ["- Nothing outside personal normal."]
    lines.append("2 WHAT CHANGED (vs own baseline)")
    # a mover still learning its normal says so: no "normal None" and no z score that was never computed
    lines += [f"- {m['name']}: {m['value']} {m['unit']} "
              + (f"(normal {m['baseline']}, z {m['z']})" if m["baseline"] is not None and m["z"] is not None else "(still learning your normal)")
              for m in f["movers"]]
    sc = lambda area: "no data yet" if f[area]["score"] is None else f[area]["score"]  # noqa: E731
    lines.append(f"- Readiness: physical {sc('physical')}, mental {sc('mental')}. Mission dose {f['dose_msv']} mSv (simulated).")
    lines.append("3 WHAT WAS TRIED")
    lines += [f"- {t}" for t in f["tried"][:6]]
    lines.append(f"- Goals done last 7 days: {f['completion_7d']}%, streak {f['streak']} days.")
    return "\n".join(lines)


def allowed_sources(crew_id: str, f: dict) -> List[str]:
    """Source ids a briefing line may cite: the weekly summary and this person's indicators and alerts."""
    snap = health.snapshot(crew_id, mission.state())
    ids = [f"summary:{crew_id}:day{f['day']}:7d"]
    ids += [i["source"] for i in snap["indicators"].values() if i.get("source")]
    ids += [s for a in snap["alerts"] for s in a.get("sources", [])]
    return list(dict.fromkeys(ids))


def render(f: dict, draft: BriefingDraft) -> str:
    lines: List[str] = [f"BRIEFING {f['crew'].upper()} · {f['day_label']} · {f['place']}"]
    for n, sec in enumerate(draft.sections, 1):
        lines.append(f"{n} {sec.heading.upper()}")
        lines += [f"- {ln.text}" for ln in sec.lines] or ["- Nothing to report."]
    if draft.missing_information:
        lines.append("MISSING INFORMATION")
        lines += [f"- {t}" for t in draft.missing_information]
    if draft.needs_medical_review:
        lines.append("NEEDS MEDICAL REVIEW")
        lines += [f"- {t}" for t in draft.needs_medical_review]
    return "\n".join(lines)


def check_draft(data, f: dict, allowed: List[str]) -> Optional[str]:
    """The rendered text when the draft passes every check, else None."""
    try:
        draft = BriefingDraft.model_validate(data)
    except (ValidationError, ValueError, TypeError):
        return None
    if not draft.sections or any(s not in allowed for sec in draft.sections for ln in sec.lines for s in ln.source_ids):
        return None
    written = [sec.heading for sec in draft.sections] + [ln.text for sec in draft.sections for ln in sec.lines]
    written += draft.missing_information + draft.needs_medical_review
    if guard.unknown_numbers("\n".join(written), json.dumps(f)):  # only what the model wrote; the header is ours
        return None
    return render(f, draft)


def build(crew_id: str) -> dict:
    f = facts(crew_id)
    allowed = allowed_sources(crew_id, f)
    provider = get_provider()
    out = provider.complete(ProviderRequest(
        task="briefing", system=SYSTEM_PROMPT,
        question="Write this week's briefing. Allowed source ids: " + json.dumps(allowed),
        context=[{"facts": f}]))
    text, mode = template(f), "template"
    if out.ok and out.data is not None:
        checked = check_draft(out.data, f, allowed)
        if checked:
            text, mode = checked, "ai"
    bid = db.x("INSERT INTO briefings(crew_id,day,status,facts,text,mode,created_at) VALUES(?,?,?,?,?,?,?)",
               (crew_id, f["day"], "draft", json.dumps(f), text, mode, time.time()))
    return get(bid)


def approve(bid: int) -> dict:
    b = get(bid)
    delay = LOCATIONS[mission.state()["location"]]["delay_s"] / settings.delay_speedup
    now = time.time()
    db.x("UPDATE briefings SET status='queued', sent_at=?, deliver_at=? WHERE id=?", (now, now + delay, bid))
    db.x("INSERT INTO messages(sender,recipient,kind,text,sent_at,deliver_at) VALUES(?,?,?,?,?,?)",
         (b["crew_id"], "earth", "briefing", b["text"], now, now + delay))
    return get(bid)


def get(bid: int) -> dict:
    r = db.q("SELECT * FROM briefings WHERE id=?", (bid,))[0]
    return {**r, "facts": json.loads(r["facts"]), "bytes": len(r["text"].encode())}


def list_for(crew_id: str) -> List[dict]:
    return [get(r["id"]) for r in db.q("SELECT id FROM briefings WHERE crew_id=? ORDER BY id DESC LIMIT 10", (crew_id,))]
