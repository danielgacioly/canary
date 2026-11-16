"""Alerts as stored events, and who is told.

An alert event is the record of one (person, alert) from the moment it reaches level 1 or 2 until it is back to 0. It stores
what was evaluated AT THAT TIME (the reading, the person's normal, the thresholds, the rule and `RULES_VERSION`), so a past
event is never recomputed: changing a threshold later does not rewrite history. `run` (called by every route that writes, by
the day sync and right after readings are ingested) opens, raises and closes events and tells people:

- level 2 (a personal alert): a message for the crew medical officer on board at once (the substitute when the patient is the
  officer) and a delayed one for Earth (the flight surgeon), once per event (the `level2` recipient on the stored event is the record that it was done);
- a storm or other environment alert (`env`): the officer at once, and Earth (every flight surgeon and every MCC account)
  after the signal delay, once for the crew as a whole, not once per person;
- level 1 that lasts 7 mission days: one message for the officer, once per event;
- a level 2 nobody acknowledged: `escalate(now)` raises it after `escalate_after_s()` seconds to the commander and, after the
  same wait again, to the flight surgeon. Any acknowledgement (officer on board or flight surgeon) stops the climb.

Alerts about missing data (`data`) are not health events and never open one. Messages never carry a PIN.
"""
import json
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .. import db
from . import audit, health, privacy, registry
from .catalog import CREW, CREW_BY_ID, LOCATIONS

# Version of the rules that decide an alert and who hears about it. Stored on every event. The medical engine's author bumps it
# when the rules change (thresholds, risk scoring), so an old event says which rules it was judged by.
RULES_VERSION = "2026.11-1"
PERSIST_DAYS = 7          # level 1 this long: one message for the officer
ACK_ROLES = ("cmo", "flight_surgeon")
SYSTEM = {"id": "system", "role": "system"}


def _first(crew_id: str) -> str:
    return CREW_BY_ID[crew_id]["name"].split(" ")[0]


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _ts(iso: str) -> float:
    return datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp()


def escalate_after_s() -> float:
    """Seconds a level-2 event may wait for an acknowledgement before it climbs a step (the demo runs `delay_speedup` times faster)."""
    from ..config import settings
    return settings.escalate_minutes * 60 / max(settings.delay_speedup, 1e-9)


def _delay_s(location: Optional[str] = None) -> float:
    from ..config import settings
    if location is None:
        from . import mission
        location = mission.state()["location"]
    return LOCATIONS[location]["delay_s"] / settings.delay_speedup


def _msg(sender: str, to: str, kind: str, text: str, now: float, deliver_at: Optional[float] = None) -> None:
    db.x("INSERT INTO messages(sender,recipient,kind,text,sent_at,deliver_at) VALUES(?,?,?,?,?,?)",
         (sender, to, kind, text, now, now if deliver_at is None else deliver_at))


def _grounds(role: str) -> List[str]:
    return [g["id"] for g in registry.ground() if g["role"] == role]


# ---------------------------------------------------------------- events
def _load(row: dict) -> dict:
    return {**row, "inputs": json.loads(row["inputs"]), "thresholds": json.loads(row["thresholds"]),
            "recipients": json.loads(row["recipients"]), "acks": json.loads(row["acks"])}


def _fingerprint(ev: dict) -> str:
    return json.dumps([ev["level"], ev["closed_at"], ev["closed_day"], ev["inputs"], ev["recipients"], ev["escalation_stage"], ev["acks"]],
                      sort_keys=True, default=str)


def _save(ev: dict) -> None:
    db.x("UPDATE alert_events SET level=?, closed_at=?, closed_day=?, inputs=?, recipients=?, escalation_stage=?, acks=? WHERE id=?",
         (ev["level"], ev["closed_at"], ev["closed_day"], json.dumps(ev["inputs"], default=str), json.dumps(ev["recipients"]),
          ev["escalation_stage"], json.dumps(ev["acks"]), ev["id"]))


def get(event_id: int) -> Optional[dict]:
    rows = db.q("SELECT * FROM alert_events WHERE id=?", (event_id,))
    return _load(rows[0]) if rows else None


def _evaluated(snap: dict, a: dict) -> dict:
    """What the engine said when this event opened or changed: the reading, the person's normal, the limits and the z score."""
    inputs: Dict[str, Any] = {"title": a["title"], "env": bool(a.get("env")), "sources": a.get("sources", []), "risk": a.get("risk"),
                              "day": snap["day"], "level": a["level"]}
    thresholds: Dict[str, Any] = {"watch_act": health.thresholds(), "per_indicator": health.thresholds_by_indicator()}
    rule = f"alert:{a['id']}"
    if a.get("env"):
        rule = f"environment:{a['id']}"
    elif a["id"].startswith("ind_"):
        ind = a["id"][4:]
        d = snap["indicators"].get(ind)
        if d:
            pop = d.get("population") or {}
            from . import data  # late import: data is the engine's reader of readings
            raw = data.last(snap["crew_id"], ind, snap["day"])
            inputs.update(indicator=ind, reading=None if raw is None else raw["value"], value=d["value"], unit=d["unit"], baseline=d.get("baseline"), sd=d.get("spread"), z=d.get("z"),
                          bad=d.get("bad"), origin=d.get("origin"))
            thresholds.update(population_low=pop.get("low"), population_high=pop.get("high"),
                              care_window_until=d.get("sensitive_until"), standard=d.get("standard"))
            rule = ("population_limit" if pop.get("status") == "critical" else
                    "nasa_std3001" if (d.get("standard") or {}).get("level") else "personal_z")
    return {"inputs": inputs, "thresholds": thresholds, "rule": rule}


def _open_event(crew_id: str, snap: dict, a: dict, day: int, now: float) -> dict:
    ev = _evaluated(snap, a)
    eid = db.x("INSERT INTO alert_events(crew_id,key,level,opened_at,opened_day,inputs,rule,rules_version,thresholds,recipients,escalation_stage,acks) "
               "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
               (crew_id, a["id"], a["level"], _iso(now), day, json.dumps(ev["inputs"], default=str), ev["rule"], RULES_VERSION,
                json.dumps(ev["thresholds"], default=str), "[]", 0, "[]"))
    audit.record(SYSTEM, "alert.open", f"alert_event:{eid}", after={"crew_id": crew_id, "key": a["id"], "level": a["level"], "day": day})
    return get(eid)  # type: ignore[return-value]


def _recipient(ev: dict, who: str, role: str, reason: str, now: float, deliver_at: Optional[float] = None) -> None:
    ev["recipients"].append({"id": who, "role": role, "reason": reason, "stage": ev["escalation_stage"], "at": _iso(now),
                             "deliver_at": _iso(now if deliver_at is None else deliver_at)})


def _storm_group(ev: dict) -> List[dict]:
    """The other events of one environment alert: the same key opened on the same day, one per person."""
    rows = db.q("SELECT * FROM alert_events WHERE key=? AND opened_day=? AND id!=? ORDER BY id", (ev["key"], ev["opened_day"], ev["id"]))
    return [e for e in (_load(r) for r in rows) if e["inputs"].get("env")]


def _notify_env(ev: dict, a: dict, ms: dict, now: float) -> None:
    """A storm reaches the officer at once and Earth after the delay: once for the crew, by the first person's event."""
    told = next((t for t in _storm_group(ev) if t["recipients"]), None)
    if told:
        ev["recipients"] = list(told["recipients"])
        return
    to = privacy.medical_officer() or privacy.substitute()
    text = f"Environment alert on day {ms['day']}: {a['title']} It applies to the whole crew."
    if to:
        _msg("canary", to, "alert", text + " Details are in the medical console.", now)
        _recipient(ev, to, "cmo", "environment", now)
    delay = _delay_s(ms["location"])
    for role, kind in (("flight_surgeon", "alert_earth"), ("mcc", "alert_env")):
        for gid in _grounds(role) or (["earth"] if role == "flight_surgeon" else []):
            _msg("canary", gid, kind, text, now, now + delay)
            _recipient(ev, gid, role, "environment", now, now + delay)


def _notify_personal(crew_id: str, new: List[dict], evs: Dict[str, dict], ms: dict, now: float) -> None:
    """The message for a new critical alert: officer now, Earth after the delay. The events record who was told."""
    from ..assistant import briefing  # late import: the text for Earth is the weekly briefing's
    day = ms["day"]
    to = privacy.alerts_to(crew_id)
    titles = " ".join(a["title"] for a in new)
    _msg("canary", to, "alert", f"Critical alert for {_first(crew_id)} on day {day}: {titles} Details are in the medical console.", now)
    delay = _delay_s(ms["location"])
    _msg("canary", "earth", "alert_earth", briefing.template(briefing.facts(crew_id)), now, now + delay)
    for a in new:
        ev = evs.get(a["id"])
        if ev:
            _recipient(ev, to, "cmo", "level2", now)
            _recipient(ev, "earth", "flight_surgeon", "level2", now, now + delay)


def _by_system_level(a: dict, snap: dict) -> dict:
    """The alert at the level of its body system (RULE-10: the system's colour is the one level source). An alert with no
    system (a symptom) keeps its own level. The stored event then says the level the crew see on the body."""
    sid = a.get("sys")
    if sid and sid in snap["systems"]:
        return {**a, "level": snap["systems"][sid]["level"]}
    return a


def run(ms: dict, crew_ids: Optional[List[str]] = None) -> Dict[str, int]:
    """Bring the stored events up to date with the alerts of every given person (everybody by default) and tell whoever must be
    told. Returns {"episodes": new critical events told, "opened": events opened, "closed": events closed}."""
    day, now = ms["day"], time.time()
    episodes = opened = closed = 0
    for c in CREW:
        if crew_ids is not None and c["id"] not in crew_ids:
            continue
        cid = c["id"]
        snap = health.snapshot(cid, ms)
        alerts = [_by_system_level(a, snap) for a in snap["alerts"] if not a.get("data")]
        alerts = [a for a in alerts if a["level"] >= 1]
        keys = {a["id"] for a in alerts}
        evs = {e["key"]: e for e in (_load(r) for r in db.q("SELECT * FROM alert_events WHERE crew_id=? AND closed_at IS NULL", (cid,)))}
        before = {k: _fingerprint(e) for k, e in evs.items()}
        for key in [k for k in evs if k not in keys]:  # back to level 0: the event closes
            ev = evs.pop(key)
            ev.update(closed_at=_iso(now), closed_day=day)
            _save(ev)
            audit.record(SYSTEM, "alert.close", f"alert_event:{ev['id']}", after={"crew_id": cid, "key": key, "day": day})
            closed += 1
        for a in alerts:
            ev = evs.get(a["id"])
            if ev is None:
                ev = evs[a["id"]] = _open_event(cid, snap, a, day, now)
                before[a["id"]] = _fingerprint(ev)
                opened += 1
                if a.get("env") and a["level"] >= 2:
                    _notify_env(ev, a, ms, now)
            elif a["level"] > ev["level"]:  # it got worse: raise the level and keep what the engine said then
                then = _evaluated(snap, a)["inputs"]
                ev["inputs"].setdefault("changes", []).append({"at": _iso(now), "day": day, "from": ev["level"], "to": a["level"],
                                                               **{k: then[k] for k in ("value", "unit", "baseline", "z") if k in then}})
                audit.record(SYSTEM, "alert.level", f"alert_event:{ev['id']}", before={"level": ev["level"]}, after={"level": a["level"], "day": day})
                ev["level"] = a["level"]
                if a.get("env") and a["level"] >= 2:
                    _notify_env(ev, a, ms, now)
        new = [a for a in alerts if a["level"] >= 2 and not a.get("env") and not any(r["reason"] == "level2" for r in evs[a["id"]]["recipients"])]
        if new:
            _notify_personal(cid, new, evs, ms, now)
            episodes += len(new)
        for a in alerts:  # level 1 that has lasted a week: the officer is told once
            ev = evs[a["id"]]
            if (ev["level"] == 1 and not a.get("env") and day - ev["opened_day"] >= PERSIST_DAYS
                    and not any(r["reason"] == "persisting" for r in ev["recipients"])):
                to = privacy.alerts_to(cid)
                if to:
                    _msg("canary", to, "alert", f"Watch alert for {_first(cid)} open for {day - ev['opened_day']} days: {a['title']} Details are in the medical console.", now)
                    _recipient(ev, to, "cmo", "persisting", now)
        for k, ev in evs.items():
            if before.get(k) != _fingerprint(ev):
                _save(ev)
    return {"episodes": episodes, "opened": opened, "closed": closed}


def sync(ms: dict, crew_ids: Optional[List[str]] = None) -> int:
    """`run`, returning how many new critical episodes were noticed."""
    return run(ms, crew_ids)["episodes"]


# ---------------------------------------------------------------- acknowledgement and escalation
def acknowledge(event_id: int, actor: dict) -> Optional[dict]:
    """The officer on board or a flight surgeon acknowledges an event (an environment alert: for the whole crew). Idempotent per
    person. Returns the event, or None when there is no such event."""
    ev = get(event_id)
    if ev is None:
        return None
    group = [ev] + (_storm_group(ev) if ev["inputs"].get("env") else [])
    now = _iso(time.time())
    for e in group:
        if not any(a["by"] == actor["id"] for a in e["acks"]):
            e["acks"].append({"by": actor["id"], "role": actor["role"], "at": now})
            _save(e)
    audit.record(actor, "alert.ack", f"alert_event:{event_id}", after={"crew_id": ev["crew_id"], "key": ev["key"], "level": ev["level"]})
    return get(event_id)


def _commander(patient: Optional[str]) -> Optional[str]:
    """The commander (the crew member whose role says so), else any other crew member; never the officer or the patient when
    somebody else is there."""
    cmo = privacy.medical_officer()
    others = [c for c in CREW if c["id"] != cmo]
    pool = [c for c in others if c["id"] != patient] or others
    return next((c["id"] for c in pool if "commander" in c["role"].lower()), pool[0]["id"] if pool else None)


def escalate(now: float) -> int:
    """Climb one step for every critical event nobody acknowledged for `escalate_after_s()` seconds (counted from the event or from
    its last step). Stage 1: the commander. Stage 2: the flight surgeon (after the signal delay). Returns how many steps were taken."""
    wait, steps, done = escalate_after_s(), 0, set()
    for row in db.q("SELECT * FROM alert_events WHERE closed_at IS NULL AND level>=2 AND escalation_stage<2 ORDER BY id"):
        ev = _load(row)
        env = bool(ev["inputs"].get("env"))
        if ev["acks"] or (ev["key"], ev["opened_day"]) in done:
            continue
        since = max([_ts(ev["opened_at"])] + [_ts(r["at"]) for r in ev["recipients"] if r["reason"].startswith("escalation")])
        if now - since < wait:
            continue
        group = [ev] + (_storm_group(ev) if env else [])
        if env:
            done.add((ev["key"], ev["opened_day"]))
        stage = ev["escalation_stage"] + 1
        what = ev["inputs"].get("title", ev["key"])
        who = "the whole crew" if env else _first(ev["crew_id"])
        targets = []
        if stage == 1:
            to = _commander(None if env else ev["crew_id"])
            if to:
                _msg("canary", to, "alert", f"Critical alert for {who} is not acknowledged: {what} The medical officer has not answered; please check on them.", now)
                targets.append((to, "commander", now))
        else:
            delay = _delay_s()
            for gid in _grounds("flight_surgeon") or ["earth"]:
                _msg("canary", gid, "alert_earth", f"Critical alert for {who} was not acknowledged on board: {what}", now, now + delay)
                targets.append((gid, "flight_surgeon", now + delay))
        for e in group:
            e["escalation_stage"] = stage
            for gid, role, deliver in targets or [("", "none", now)]:
                e["recipients"].append({"id": gid, "role": role, "reason": f"escalation_{stage}", "stage": stage, "at": _iso(now), "deliver_at": _iso(deliver)})
            _save(e)
        audit.record(SYSTEM, "alert.escalate", f"alert_event:{ev['id']}", after={"crew_id": ev["crew_id"], "key": ev["key"], "stage": stage})
        steps += 1
    return steps


# ---------------------------------------------------------------- reads
def event_dict(ev: dict, detail: bool = True) -> dict:
    """An event for the API. `detail` False (Canary Control): who, what, level, times and acknowledgement; no values and no text."""
    c = CREW_BY_ID.get(ev["crew_id"])
    out = {"id": ev["id"], "crew_id": ev["crew_id"], "name": c["name"] if c else ev["crew_id"], "key": ev["key"], "level": ev["level"],
           "opened_at": ev["opened_at"], "opened_day": ev["opened_day"], "closed_at": ev["closed_at"], "closed_day": ev["closed_day"],
           "escalation_stage": ev["escalation_stage"], "acknowledged": bool(ev["acks"]), "acknowledged_by": [a["by"] for a in ev["acks"]]}
    if not detail:
        return out
    return {**out, "title": ev["inputs"].get("title", ev["key"]), "env": bool(ev["inputs"].get("env")), "inputs": ev["inputs"],
            "rule": ev["rule"], "rules_version": ev["rules_version"], "thresholds": ev["thresholds"], "recipients": ev["recipients"],
            "acks": ev["acks"], "acknowledged_by_names": [_name(a["by"]) for a in ev["acks"]]}


def _name(account_id: str) -> str:
    a = registry.account(account_id)
    return a["name"] if a else account_id


def events(crew_id: Optional[str] = None, open_only: bool = False, limit: int = 100) -> List[dict]:
    sql = "SELECT * FROM alert_events WHERE 1=1" + (" AND crew_id=?" if crew_id else "") + (" AND closed_at IS NULL" if open_only else "")
    rows = db.q(sql + " ORDER BY id DESC LIMIT ?", ((crew_id,) if crew_id else ()) + (limit,))
    return [_load(r) for r in rows]
