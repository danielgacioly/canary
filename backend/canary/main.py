"""Canary API: one FastAPI process, modular inside (see README, Architecture).

Run:  uvicorn canary.main:app --reload --port 8000   (from backend/)
Docs: http://localhost:8000/docs
"""
import hashlib
import hmac
import json
import mimetypes
import pathlib
import time
from datetime import date, timedelta
from contextlib import asynccontextmanager
from typing import List, Optional

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import __version__, auth, db
from .assistant import briefing, chat, providers, suggestions, tools
from .config import settings
from .domain import advice, care, goals, health, mission, nasa, notify, plan, privacy, protocols, registry, selftests, telemetry
from .domain.catalog import CAREER_LIMIT_MSV, RECORDS, CREW, CREW_BY_ID, INDICATORS, LOCATIONS, REGION_SYSTEM, STORY, SYSTEMS

@asynccontextmanager
async def lifespan(_app):
    db.connect()
    registry.load()
    yield


app = FastAPI(title="Canary API", version=__version__, lifespan=lifespan,
              description="Crew health monitoring for space missions. NASA Space Apps Challenge 2026.")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


def _crew(crew_id: str) -> dict:
    if crew_id not in CREW_BY_ID:
        raise HTTPException(404, f"unknown crew member {crew_id}")
    return CREW_BY_ID[crew_id]


# ---------------------------------------------------------------- medical auth (no accounts for the crew)
def _sign(exp: int) -> str:
    return hmac.new(settings.token_secret.encode(), str(exp).encode(), hashlib.sha256).hexdigest()[:32]


def require_medical(authorization: Optional[str] = Header(None)) -> None:
    try:
        exp, sig = (authorization or "").replace("Bearer ", "").split(".")
        if int(exp) < time.time() or not hmac.compare_digest(sig, _sign(int(exp))):
            raise ValueError
    except ValueError:
        raise HTTPException(401, "medical team sign-in required")


def _is_medical(authorization: Optional[str]) -> bool:
    try:
        require_medical(authorization)
        return True
    except HTTPException:
        return False


def viewer(x_canary_viewer: Optional[str] = Header(None), authorization: Optional[str] = Header(None)) -> dict:
    """Who is looking. X-Canary-Viewer carries the token from the PIN sign-in; a bare id, a forged or an expired token is nobody."""
    cid = auth.verify(x_canary_viewer)
    return {"id": cid if cid in CREW_BY_ID else None, "medical": _is_medical(authorization)}


def require_self(crew_id: str, v: dict) -> None:
    if not (v["medical"] or v["id"] == crew_id):
        raise HTTPException(403, f"private: only {CREW_BY_ID[crew_id]['name']} and the medical team can see this")


class PinIn(BaseModel):
    pin: str = Field(pattern=r"^\d{4}$")


@app.post("/api/medical/session", tags=["medical"])
def medical_session(body: PinIn):
    if auth.locked("medical"):
        raise HTTPException(429, "too many attempts, wait a minute")
    if not hmac.compare_digest(body.pin, settings.medical_pin):
        auth.fail("medical")
        raise HTTPException(401, "wrong PIN")
    exp = int(time.time() + settings.token_ttl_s)
    return {"token": f"{exp}.{_sign(exp)}", "expires_at": exp}


@app.post("/api/crew/{crew_id}/session", tags=["crew"])
def crew_session(crew_id: str, body: PinIn):
    """Sign in to a private space with the 4-digit PIN. Returns the token for the X-Canary-Viewer header."""
    _crew(crew_id)
    if auth.locked(crew_id):
        raise HTTPException(429, "too many attempts, wait a minute")
    if not auth.check_pin(crew_id, body.pin):
        auth.fail(crew_id)
        raise HTTPException(401, "wrong PIN")
    return auth.issue(crew_id)


class PinChangeIn(BaseModel):
    current: str = Field(pattern=r"^\d{4}$")
    new: str = Field(pattern=r"^\d{4}$")


@app.put("/api/crew/{crew_id}/pin", tags=["crew"])
def crew_pin(crew_id: str, body: PinChangeIn, v: dict = Depends(viewer)):
    """Change your own PIN: needs your session token and the current PIN."""
    _crew(crew_id)
    if v["id"] != crew_id:
        raise HTTPException(403, "only you can change your PIN")
    if auth.locked(crew_id):
        raise HTTPException(429, "too many attempts, wait a minute")
    if not auth.check_pin(crew_id, body.current):
        auth.fail(crew_id)
        raise HTTPException(401, "wrong PIN")
    auth.set_pin(crew_id, body.new)
    return {"crew_id": crew_id, "changed": True}


# ---------------------------------------------------------------- mission
@app.get("/api/health", tags=["system"])
def ping():
    return {"ok": True, "version": __version__}


@app.get("/api/catalog", tags=["mission"])
def catalog():
    return {"locations": LOCATIONS, "indicators": INDICATORS, "systems": SYSTEMS, "region_system": REGION_SYSTEM,
            "crew": [{k: c[k] for k in ("id", "name", "role", "initials", "home", "age")} for c in CREW],
            "story": STORY, "sources": nasa.SOURCES}


@app.get("/api/mission", tags=["mission"])
def get_mission():
    return mission.state()


class MissionIn(BaseModel):
    step: Optional[int] = None
    day: Optional[int] = Field(default=None, ge=-365, le=2000)
    clear_day: bool = False
    location: Optional[str] = None
    clear_location: bool = False


@app.put("/api/mission", tags=["mission"])
def put_mission(body: MissionIn):
    if body.step is not None:
        mission.set_step(body.step)
    if body.day is not None or body.clear_day:
        mission.set_day(None if body.clear_day else body.day)
    if body.location is not None or body.clear_location:
        try:
            mission.set_location(None if body.clear_location else body.location)
        except ValueError as e:
            raise HTTPException(400, str(e))
    ms = mission.state()
    advice.sync_all(ms["day"])  # an advice concluded by the new day may call for a message to the medical officer
    notify.sync(ms)  # a new critical alert reaches the medical officer, once per episode
    return ms


@app.post("/api/demo/reset", tags=["mission"])
def demo_reset():
    db.reset()
    plan.reset_cache()
    registry.load()
    auth.clear_failures()
    return mission.state()


# ---------------------------------------------------------------- mission plan (itinerary)
@app.get("/api/plan", tags=["mission"])
def get_plan():
    return {**plan.get(), "presets": {k: v["name"] for k, v in plan.PRESETS.items()}}


@app.get("/api/plan/conditions", tags=["mission"])
def plan_conditions():
    """Health conditions along the registered plan: hazards per leg and the projected mission dose."""
    p, ms = plan.get(), mission.state()
    legs = []
    for l in p["legs"]:
        place = LOCATIONS[l["location"]]
        legs.append({**l, "days": l["end"] - l["start"] + 1, "gravity_key": place["gravity_key"],
                     "ridge": privacy.ridge(l["location"], None, (max(l["start"], 0) + l["end"]) // 2),
                     "dose_leg_msv": round(place["dose_rate"] * max(0, l["end"] - max(l["start"], 0) + 1), 1)})
    end = p["legs"][-1]["end"]
    step = max(1, (end + 1) // 60)
    days = sorted(set(list(range(0, end + 1, step)) + [end] + [max(0, l["start"]) for l in p["legs"]]))
    series = [[d, telemetry.cumulative_dose(d, plan.location_at(d), None)] for d in days]
    return {"name": p["name"], "legs": legs, "today": ms["day"], "leg_index": ms["leg"]["index"],
            "dose": {"series": series, "now_msv": health.dose(ms)["mission_msv"], "end_msv": series[-1][1],
                     "limit_msv": CAREER_LIMIT_MSV, "simulated": True}}


class LegIn(BaseModel):
    location: str
    start: int = Field(ge=-365, le=2000)
    end: int = Field(ge=-365, le=2000)
    label: str = ""


class PlanIn(BaseModel):
    name: str = "Mission plan"
    legs: List[LegIn]


@app.put("/api/plan", tags=["mission"])
def put_plan(body: PlanIn):
    try:
        plan.save(plan.validate(body.name, [l.model_dump() for l in body.legs]))
    except ValueError as e:
        raise HTTPException(400, str(e))
    mission.set_setup_done()
    return get_plan()


class PresetIn(BaseModel):
    preset: str


@app.post("/api/plan/preset", tags=["mission"])
def plan_preset(body: PresetIn):
    try:
        plan.use_preset(body.preset)
    except ValueError as e:
        raise HTTPException(400, str(e))
    mission.set_setup_done()
    return get_plan()


@app.post("/api/setup", tags=["mission"])
def mission_setup(body: PlanIn):
    """First-run mission setup: validate and save the plan, mark setup done and start the mission clock over."""
    try:
        plan.save(plan.validate(body.name, [l.model_dump() for l in body.legs]))
    except ValueError as e:
        raise HTTPException(400, str(e))
    mission.set_setup_done()
    return mission.set_step(0)  # the demo story bar keeps working: it starts from its first scene


# ---------------------------------------------------------------- crew and health
def _summary(c: dict, ms: dict, prof: dict) -> dict:
    s = health.snapshot(c["id"], ms)
    return {"id": c["id"], "name": c["name"], "role": c["role"], "initials": c["initials"], "home": c["home"],
            "areas": s["areas"], "level": s["level"], "status": s["status"], "ops": privacy.operational(s),
            "top_alert": s["alerts"][0]["title"] if s["alerts"] else None, "alerts": len(s["alerts"]),
            "systems": {k: v["level"] for k, v in s["systems"].items()},
            "goals_week": prof["goals_week"], "streak": prof["streak"], "rank": prof.get("rank")}


@app.get("/api/crew", tags=["medical"], dependencies=[Depends(require_medical)])
def crew_list():
    """Full per-person health summary. Medical team only."""
    ms = mission.state()
    lb = goals.leaderboard(ms["day"])
    profs = {r["crew_id"]: r for r in lb["rows"]}
    rows = [_summary(c, ms, profs[c["id"]]) for c in CREW]
    return {"mission": ms, "crew": rows, "team": lb["team"], "dose": health.dose(ms),
            "space_weather": {k: v for k, v in nasa.space_weather(ms["storm"]).items() if k in ("headline", "active", "kp_max", "sep_events")}}


@app.get("/api/crew/photos", tags=["crew"])
def crew_photos():
    return privacy.photos()


@app.get("/api/crew/overview", tags=["crew"])
def crew_overview():
    """What everyone on board may see: hazards, participation and crew goals. Never anyone's status."""
    ms = mission.state()
    board = goals.crew_board(ms["day"])
    people, env = [], []
    for c in CREW:
        snap = health.snapshot(c["id"], ms)
        env = [a for a in snap["alerts"] if a.get("env")] or env
        people.append({**{k: c[k] for k in ("id", "name", "role", "initials", "home")},
                       "today": board["people"][c["id"]]})
    sw = nasa.space_weather(ms["storm"])
    return {"mission": ms, "people": people,
            "eva_open": not env and not ms["learning"] and ms["location"] not in ("earth", "rocket"),
            "hazards": privacy.hazards(ms, env), "ridge": privacy.ridge(ms["location"], ms["storm"], ms["day"]),
            "warnings": [{k: a[k] for k in ("id", "level", "title", "why", "todo", "sources")} for a in env],
            "team": board["team"], "crew_streak": board["crew_streak"],
            "team_done": board["team_done"], "team_total": board["team_total"], "dose": health.dose(ms),
            "space_weather": {k: v for k, v in sw.items() if k in ("headline", "active", "kp_max", "sep_events")},
            "contract": privacy.CONTRACT}


@app.get("/api/crew/{crew_id}", tags=["crew"])
def crew_detail(crew_id: str, v: dict = Depends(viewer)):
    """Full health detail: the person themself or the medical team. Nobody else."""
    c = _crew(crew_id)
    if not privacy.can_see_details(v["id"], crew_id, v["medical"]):
        raise HTTPException(403, f"{c['name']}'s health is private")
    ms = mission.state()
    snap = health.snapshot(crew_id, ms)
    access = "self" if v["id"] == crew_id else "medical"
    trends = {i: telemetry.series(crew_id, i, ms["day"], 30) for i in INDICATORS}
    events = [{"kind": r["kind"], "day": r["day"], "payload": json.loads(r["payload"])}
              for r in db.q("SELECT kind,day,payload FROM checkins WHERE crew_id=? ORDER BY id DESC LIMIT 12", (crew_id,))]
    return {"crew": {k: c[k] for k in ("id", "name", "role", "initials", "home", "age")}, "mission": ms, **snap,
            "trends": trends, "goals": goals.personal_today(crew_id, ms, snap),
            "profile": goals.profile(crew_id, ms["day"]),
            "blood": nasa.blood(c["cbc_subject"]), "events": events,
            "system_info": {k: {"space": v2["space"], "hazard": v2["hazard"]} for k, v2 in SYSTEMS.items()},
            "ops": privacy.operational(snap), "care_by": privacy.care_by(crew_id), "access": access,
            "care_events": care.events(crew_id, ms["day"])}


@app.get("/api/crew/{crew_id}/record", tags=["crew"])
def crew_record(crew_id: str, v: dict = Depends(viewer)):
    """My information: the personal record Mission Control registered. Self and medical team only."""
    c = _crew(crew_id)
    require_self(crew_id, v)
    r = RECORDS[crew_id]
    ms = mission.state()
    today = date.fromisoformat(registry.launch_date()) + timedelta(days=ms["day"])
    dob = date.fromisoformat(r["dob"])
    age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
    bmi = round(r["weight_kg"] / (r["height_cm"] / 100) ** 2, 1)
    return {**r, "name": c["name"], "role": c["role"], "home": c["home"], "age": age, "bmi": bmi,
            "date_today": today.isoformat(), "registered_by": "Mission Control", "registered_on": "L-180"}


class PhotoIn(BaseModel):
    data_url: str = Field(max_length=400_000)


@app.put("/api/crew/{crew_id}/photo", tags=["crew"])
def crew_photo(crew_id: str, body: PhotoIn, v: dict = Depends(viewer)):
    """Profile photo, set by the astronaut. Visible to the crew like a name badge."""
    _crew(crew_id)
    if v["id"] != crew_id:
        raise HTTPException(403, "only the astronaut changes their photo")
    try:
        privacy.set_photo(crew_id, body.data_url)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return privacy.photos()


@app.delete("/api/crew/{crew_id}/photo", tags=["crew"])
def crew_photo_delete(crew_id: str, v: dict = Depends(viewer)):
    _crew(crew_id)
    if v["id"] != crew_id:
        raise HTTPException(403, "only the astronaut changes their photo")
    privacy.set_photo(crew_id, None)
    return privacy.photos()


# ---------------------------------------------------------------- goals and ranking
@app.get("/api/goals/{crew_id}", tags=["goals"])
def goals_for(crew_id: str, v: dict = Depends(viewer)):
    _crew(crew_id)
    require_self(crew_id, v)
    ms = mission.state()
    return {"personal": goals.personal_today(crew_id, ms), "team": goals.team_progress(ms["day"]),
            "profile": goals.profile(crew_id, ms["day"])}


class DoneIn(BaseModel):
    done: bool


@app.post("/api/goals/{crew_id}/{goal_id}", tags=["goals"])
def set_goal(crew_id: str, goal_id: str, body: DoneIn, v: dict = Depends(viewer)):
    _crew(crew_id)
    require_self(crew_id, v)
    ms = mission.state()
    goals.set_done(crew_id, goal_id, ms["day"], body.done)
    if body.done and goal_id.startswith(("al_", "sg_")):  # first tick of an advice opens its experiment
        g = next((x for x in goals.personal_today(crew_id, ms) if x["id"] == goal_id), None)
        if g:
            advice.start(crew_id, goal_id, g["by"], g.get("verify"), ms["day"])
    advice.sync(crew_id, ms["day"])
    return goals_for(crew_id, v)


@app.get("/api/advice/{crew_id}", tags=["goals"])
def advice_for(crew_id: str, v: dict = Depends(viewer)):
    """The advice loop: advice in progress and concluded, with the outcome against the person's own normal. Read-only."""
    _crew(crew_id)
    require_self(crew_id, v)
    day = mission.state()["day"]
    return {"day": day, **advice.for_crew(crew_id, day), "escalation": advice.escalation(crew_id, day),
            "margin": advice.MARGIN, "assumption": advice.SOURCE}


@app.post("/api/alerts/{crew_id}/{alert_id}/seen", tags=["crew"])
def alert_seen(crew_id: str, alert_id: str, v: dict = Depends(viewer)):
    """Mark today's episode of an alert as seen. If the alert goes away and comes back, the new episode is not seen."""
    _crew(crew_id)
    require_self(crew_id, v)
    ms = mission.state()
    a = next((x for x in health.snapshot(crew_id, ms)["alerts"] if x["id"] == alert_id), None)
    if not a:
        raise HTTPException(404, "that alert is not active today")
    health.mark_seen(crew_id, a, ms["day"])
    advice.sync(crew_id, ms["day"])
    return {"alert_id": alert_id, "since_day": a["since_day"], "days_active": a["days_active"], "seen": True}


@app.get("/api/leaderboard", tags=["goals"])
def leaderboard():
    ms = mission.state()
    lb = goals.leaderboard(ms["day"])
    for r in lb["rows"]:
        c = CREW_BY_ID[r["crew_id"]]
        r.update(name=c["name"], initials=c["initials"], role=c["role"])
    return lb


# ---------------------------------------------------------------- check-ins (self measurements)
class CheckinIn(BaseModel):
    crew_id: str
    kind: str = Field(pattern="^(" + "|".join(sorted(selftests.TEST_IDS)) + ")$")
    payload: dict


@app.post("/api/checkins", tags=["crew"])
def checkin(body: CheckinIn, v: dict = Depends(viewer)):
    """A test or log from the Tests page (or a quick check from My space). Private: self and medical team."""
    _crew(body.crew_id)
    require_self(body.crew_id, v)
    err = selftests.validate(body.kind, body.payload)
    if err:
        raise HTTPException(400, err)
    day = mission.state()["day"]
    p = selftests.normalise(body.kind, body.payload)
    db.x("INSERT INTO checkins(crew_id,day,kind,payload,created_at) VALUES(?,?,?,?,?)",
         (body.crew_id, day, body.kind, json.dumps(p), time.time()))
    g = selftests.goal_for(body.kind, p)
    if g:
        goals.set_done(body.crew_id, g, day, True)
    advice.sync(body.crew_id, day)
    notify.sync(mission.state(), [body.crew_id])
    return {"ok": True, "summary": selftests.summary(body.kind, p), "goal": g,
            "conclusion": selftests.conclusion(body.kind, p, body.crew_id),
            "snapshot": health.snapshot(body.crew_id, mission.state())}


@app.get("/api/checkins/{crew_id}", tags=["crew"])
def checkin_history(crew_id: str, v: dict = Depends(viewer)):
    """Every test with its latest result, plus the recent log. Self and medical team only."""
    _crew(crew_id)
    require_self(crew_id, v)
    rows = db.q("SELECT id,kind,day,payload,created_at FROM checkins WHERE crew_id=? ORDER BY id DESC LIMIT 200", (crew_id,))
    latest, recent = {}, []
    for r in rows:
        p = json.loads(r["payload"])
        item = {"kind": r["kind"], "day": r["day"], "at": r["created_at"], "summary": selftests.summary(r["kind"], p), "payload": p}
        latest.setdefault(r["kind"], item)
        if len(recent) < 20:
            recent.append(item)
    return {"tests": [{**t, "latest": latest.get(t["id"])} for t in selftests.TESTS], "recent": recent}


# ---------------------------------------------------------------- guided response
@app.get("/api/protocols", tags=["guided response"])
def get_protocols():
    return protocols.resolve(mission.state()["location"])


class EmergencyIn(BaseModel):
    protocol: Optional[str] = None
    patient: Optional[str] = None
    responder: Optional[str] = None


@app.post("/api/emergencies", tags=["guided response"])
def emergency_start(body: EmergencyIn):
    ms = mission.state()
    eid = db.x("INSERT INTO emergencies(protocol,patient,responder,location,day,started_at,log) VALUES(?,?,?,?,?,?,?)",
               (body.protocol, body.patient, body.responder, ms["location"], ms["day"], time.time(),
                json.dumps([[0, "Guided Response opened. Crew alerted."]])))
    delay = LOCATIONS[ms["location"]]["delay_s"] / settings.delay_speedup
    db.x("INSERT INTO messages(sender,recipient,kind,text,sent_at,deliver_at) VALUES(?,?,?,?,?,?)",
         (body.responder or "crew", "earth", "emergency", f"EMERGENCY opened on {ms['day_label']} at {LOCATIONS[ms['location']]['name']}.",
          time.time(), time.time() + delay))
    return _emergency(eid)


class EmergencyEvent(BaseModel):
    text: Optional[str] = None
    protocol: Optional[str] = None
    patient: Optional[str] = None
    outcome: Optional[str] = None
    close: bool = False


@app.post("/api/emergencies/{eid}", tags=["guided response"])
def emergency_event(eid: int, body: EmergencyEvent):
    e = _emergency(eid)
    log = e["log"]
    t = round(time.time() - e["started_at"])
    if body.protocol:
        db.x("UPDATE emergencies SET protocol=? WHERE id=?", (body.protocol, eid))
    if body.patient:
        db.x("UPDATE emergencies SET patient=? WHERE id=?", (body.patient, eid))
    if body.text:
        log.append([t, body.text])
    if body.close and not _emergency(eid)["ended_at"]:  # closing twice does not repeat goals, window or report
        ms = mission.state()
        e = _emergency(eid)
        db.x("UPDATE emergencies SET ended_at=?, outcome=? WHERE id=?", (time.time(), body.outcome or "stable", eid))
        log.append([t, f"Closed: {body.outcome or 'stable'}"])
        if e["protocol"] and e["patient"]:
            for item in protocols.care(e["protocol"])["after_items"]:  # each follow-up lasts the days its text gives
                db.x("INSERT INTO medical_goals(who,area,title,why,xp,from_day,to_day,created_at) VALUES(?,?,?,?,?,?,?,?)",
                     (e["patient"], "physical", item["title"], "Follow-up after Guided Response.", 0, ms["day"], ms["day"] + item["days"], time.time()))
            care.open_window(e, ms["day"], body.outcome or "stable")
        delay = LOCATIONS[ms["location"]]["delay_s"] / settings.delay_speedup
        report = f"Guided Response report: {e['protocol'] or 'triage'}, patient {e['patient'] or 'unknown'}, outcome {body.outcome or 'stable'}, {len(log)} logged steps."
        db.x("INSERT INTO messages(sender,recipient,kind,text,sent_at,deliver_at) VALUES(?,?,?,?,?,?)",
             (e["responder"] or "crew", "earth", "report", report, time.time(), time.time() + delay))
        db.x("UPDATE emergencies SET log=? WHERE id=?", (json.dumps(log), eid))
        notify.sync(ms)  # the window tightens the patient's thresholds: a new critical alert may follow
        return _emergency(eid)
    db.x("UPDATE emergencies SET log=? WHERE id=?", (json.dumps(log), eid))
    return _emergency(eid)


def _emergency(eid: int) -> dict:
    rows = db.q("SELECT * FROM emergencies WHERE id=?", (eid,))
    if not rows:
        raise HTTPException(404, "no such emergency")
    return {**rows[0], "log": json.loads(rows[0]["log"])}


@app.get("/api/emergencies", tags=["guided response"])
def emergencies():
    return [_emergency(r["id"]) for r in db.q("SELECT id FROM emergencies ORDER BY id DESC LIMIT 20")]


# ---------------------------------------------------------------- messages with communication delay
class MessageIn(BaseModel):
    sender: str
    recipient: str
    text: str = Field(min_length=1, max_length=2000)


@app.post("/api/messages", tags=["messages"])
def send_message(body: MessageIn):
    ms = mission.state()
    delay = LOCATIONS[ms["location"]]["delay_s"] / settings.delay_speedup
    now = time.time()
    db.x("INSERT INTO messages(sender,recipient,kind,text,sent_at,deliver_at) VALUES(?,?,?,?,?,?)",
         (body.sender, body.recipient, "text", body.text, now, now + delay))
    return messages()


@app.get("/api/messages", tags=["messages"])
def messages_route(crew_id: Optional[str] = None, v: dict = Depends(viewer)):
    return messages(crew_id, v)


def messages(crew_id: Optional[str] = None, v: Optional[dict] = None):
    now = time.time()
    rows = db.q("SELECT * FROM messages ORDER BY id DESC LIMIT 40")
    private = ("advice", "alert", "alert_earth")  # private to the medical officer and the medical team
    rows = [r for r in rows if r["kind"] not in private or (v and (v["medical"] or v["id"] == r["recipient"]))]
    if crew_id:
        rows = [r for r in rows if crew_id in (r["sender"], r["recipient"]) or r["recipient"] == "crew"]
    for r in rows:
        r["delivered"] = now >= r["deliver_at"]
        r["eta_s"] = max(0, round(r["deliver_at"] - now))
    return rows


# ---------------------------------------------------------------- NASA data
@app.get("/api/space-weather", tags=["nasa"])
def space_weather():
    return nasa.space_weather(mission.state()["storm"])


@app.get("/api/nasa/rad", tags=["nasa"])
def nasa_rad():
    return nasa.rad()


@app.get("/api/nasa/sources", tags=["nasa"])
def nasa_sources():
    return nasa.SOURCES


# ---------------------------------------------------------------- AI assistant slot
class AskIn(BaseModel):
    crew_id: str
    question: str = Field(min_length=1, max_length=500)


@app.get("/api/assistant/status", tags=["assistant"])
def assistant_status():
    return {**providers.status(), "tools": tools.schema()}


@app.post("/api/assistant/ask", tags=["assistant"])
def assistant_ask(body: AskIn, v: dict = Depends(viewer)):
    _crew(body.crew_id)
    require_self(body.crew_id, v)
    return chat.ask(body.crew_id, body.question)


@app.get("/api/assistant/history/{crew_id}", tags=["assistant"])
def assistant_history(crew_id: str, v: dict = Depends(viewer)):
    _crew(crew_id)
    require_self(crew_id, v)
    return chat.history(crew_id)


class BriefingIn(BaseModel):
    crew_id: str


@app.get("/api/suggestions/{crew_id}", tags=["assistant"])
def suggestions_for(crew_id: str, v: dict = Depends(viewer)):
    """Entry 3: personal suggestions from the person's own data. Private to the person."""
    _crew(crew_id)
    if v["id"] != crew_id:
        raise HTTPException(403, "suggestions are for the astronaut only")
    return suggestions.build(crew_id)


@app.post("/api/suggestions/{crew_id}/{sid}/accept", tags=["assistant"])
def suggestion_accept(crew_id: str, sid: str, v: dict = Depends(viewer)):
    """Turn a suggestion into a goal for the next 7 days."""
    _crew(crew_id)
    if v["id"] != crew_id:
        raise HTTPException(403, "suggestions are for the astronaut only")
    try:
        return suggestions.accept(crew_id, sid)
    except ValueError as e:
        raise HTTPException(404, str(e))


@app.post("/api/briefings", tags=["assistant"])
def briefing_new(body: BriefingIn, v: dict = Depends(viewer)):
    _crew(body.crew_id)
    require_self(body.crew_id, v)
    return briefing.build(body.crew_id)


@app.post("/api/briefings/{bid}/approve", tags=["assistant"])
def briefing_approve(bid: int):
    return briefing.approve(bid)


@app.get("/api/briefings/{crew_id}", tags=["assistant"])
def briefing_list(crew_id: str, v: dict = Depends(viewer)):
    _crew(crew_id)
    require_self(crew_id, v)
    return briefing.list_for(crew_id)


# ---------------------------------------------------------------- medical team
@app.get("/api/medical/overview", tags=["medical"], dependencies=[Depends(require_medical)])
def medical_overview():
    ms = mission.state()
    out = []
    for c in CREW:
        s = health.snapshot(c["id"], ms)
        out.append({"id": c["id"], "name": c["name"], "role": c["role"], "level": s["level"], "ops": privacy.operational(s), "areas": s["areas"],
                    "indicators": s["indicators"], "systems": s["systems"], "alerts": s["alerts"],
                    "care_events": care.events(c["id"], ms["day"])})
    return {"mission": ms, "crew": out, "thresholds": health.thresholds(), "emergencies": emergencies()[:5],
            "notices": notify.list_for(ms["day"]), "care_sensitivity": care.sensitivity()}


class CareSensitivityIn(BaseModel):
    factor: float = Field(ge=care.FACTOR_RANGE[0], le=care.FACTOR_RANGE[1])


@app.put("/api/medical/care-sensitivity", tags=["medical"], dependencies=[Depends(require_medical)])
def put_care_sensitivity(body: CareSensitivityIn):
    """How much tighter a patient's thresholds are during the care window after an emergency (1 = no change)."""
    db.set_setting("care_sensitivity", {"factor": body.factor})
    return care.sensitivity()


@app.get("/api/medical/care-sensitivity", tags=["medical"], dependencies=[Depends(require_medical)])
def get_care_sensitivity():
    return care.sensitivity()


class ExerciseAdjustIn(BaseModel):
    max_pct: int = Field(ge=0, le=50)
    level1: int = Field(ge=0, le=50)
    level2: int = Field(ge=0, le=50)


@app.put("/api/medical/exercise-adjust", tags=["medical"], dependencies=[Depends(require_medical)])
def put_exercise_adjust(body: ExerciseAdjustIn):
    """How much the day's exercise may be lightened while the fatigue risk is up. Never above max_pct."""
    db.set_setting("exercise_adjust", {"max_pct": body.max_pct, "by_level": {"1": body.level1, "2": body.level2}})
    return goals.exercise_adjust()


@app.get("/api/medical/exercise-adjust", tags=["medical"], dependencies=[Depends(require_medical)])
def get_exercise_adjust():
    return goals.exercise_adjust()


class ThresholdsIn(BaseModel):
    watch: float = Field(ge=0.5, le=4)
    act: float = Field(ge=1, le=5)


@app.put("/api/medical/thresholds", tags=["medical"], dependencies=[Depends(require_medical)])
def put_thresholds(body: ThresholdsIn):
    if body.act <= body.watch:
        raise HTTPException(400, "act must be above watch")
    db.set_setting("thresholds", {"watch": body.watch, "act": body.act})
    return health.thresholds()


class MedGoalIn(BaseModel):
    who: str
    area: str = Field(pattern="^(physical|mental)$")
    title: str = Field(min_length=3, max_length=140)
    why: str = Field(default="Prescribed by the medical team.", max_length=280)
    days: int = Field(default=7, ge=1, le=60)


@app.post("/api/medical/goals", tags=["medical"], dependencies=[Depends(require_medical)])
def add_med_goal(body: MedGoalIn):
    if body.who != "all":
        _crew(body.who)
    day = mission.state()["day"]
    db.x("INSERT INTO medical_goals(who,area,title,why,xp,from_day,to_day,created_at) VALUES(?,?,?,?,?,?,?,?)",
         (body.who, body.area, body.title, body.why, 0, day, day + body.days - 1, time.time()))
    return med_goals()


@app.get("/api/medical/goals", tags=["medical"], dependencies=[Depends(require_medical)])
def med_goals():
    return db.q("SELECT * FROM medical_goals ORDER BY id DESC")


@app.delete("/api/medical/goals/{gid}", tags=["medical"], dependencies=[Depends(require_medical)])
def del_med_goal(gid: int):
    db.x("DELETE FROM medical_goals WHERE id=?", (gid,))
    return med_goals()


# ---------------------------------------------------------------- mission overview (public) and Canary Control (Mission Control)
@app.get("/api/mission/overview", tags=["mission"])
def mission_overview():
    """General information about the mission and the crew as a whole. Public on board: no health data."""
    ms = mission.state()
    info = registry.mission_info() or {}
    p = plan.get()
    launch = date.fromisoformat(registry.launch_date())
    dest = next((l for l in reversed(p["legs"]) if l["location"] not in ("earth", "rocket")), p["legs"][-1])
    crew = [{**{k: c[k] for k in ("id", "name", "role", "initials", "home")},
             **{k: RECORDS.get(c["id"], {}).get(k) for k in ("nationality", "agency", "languages", "flights", "days_in_space")}}
            for c in CREW]
    return {"registered": registry.registered(), "callsign": info.get("callsign"), "name": p["name"],
            "launch_date": launch.isoformat(), "today_date": (launch + timedelta(days=ms["day"])).isoformat(),
            "destination": LOCATIONS[dest["location"]]["name"], "flight_days": p["legs"][-1]["end"] + 1,
            "legs": p["legs"], "mission": ms, "crew": crew}


def _control_sig(exp: int) -> str:
    return hmac.new(settings.token_secret.encode(), f"control:{exp}".encode(), hashlib.sha256).hexdigest()[:32]


def require_control(x_canary_control: Optional[str] = Header(None)) -> None:
    try:
        tag, exp, sig = (x_canary_control or "").split(".")
        if tag != "control" or int(exp) < time.time() or not hmac.compare_digest(sig, _control_sig(int(exp))):
            raise ValueError
    except ValueError:
        raise HTTPException(401, "Mission Control sign-in required")


@app.post("/api/control/session", tags=["control"])
def control_session(body: PinIn):
    if auth.locked("control"):
        raise HTTPException(429, "too many attempts, wait a minute")
    if not hmac.compare_digest(body.pin, settings.control_pin):
        auth.fail("control")
        raise HTTPException(401, "wrong PIN")
    exp = int(time.time() + settings.token_ttl_s)
    return {"token": f"control.{exp}.{_control_sig(exp)}", "expires_at": exp}


@app.get("/api/control/overview", tags=["control"], dependencies=[Depends(require_control)])
def control_overview():
    """What Earth follows: operational status as the medical team reports it, participation, hazards, traffic."""
    ms = mission.state()
    board = goals.crew_board(ms["day"]) if CREW else {"people": {}}
    people = []
    for c in CREW:
        s = health.snapshot(c["id"], ms)
        last = db.q("SELECT day FROM checkins WHERE crew_id=? ORDER BY id DESC LIMIT 1", (c["id"],))
        people.append({**{k: c[k] for k in ("id", "name", "role", "initials", "home")}, "ops": privacy.operational(s),
                       "today": board["people"].get(c["id"]), "last_checkin_day": last[0]["day"] if last else None})
    env = [a for a in (health.snapshot(CREW[0]["id"], ms)["alerts"] if CREW else []) if a.get("env")]
    return {"registered": registry.registered(), "mission": ms, "overview": mission_overview(), "people": people,
            "ridge": privacy.ridge(ms["location"], ms["storm"], ms["day"]), "warnings": [{k: a[k] for k in ("title", "todo")} for a in env],
            "dose": health.dose(ms), "emergencies": emergencies()[:5]}


@app.get("/api/control/demo", tags=["control"], dependencies=[Depends(require_control)])
def control_demo():
    """What the 'fill with the demo crew' button puts in the form."""
    return {"crew": registry.demo_form(), "mission": registry.DEMO_MISSION, "presets": {k: v["name"] for k, v in plan.PRESETS.items()}}


class SeatIn(BaseModel):
    seat: str = Field(pattern="^(h|k|a|t)$")
    name: str = Field(min_length=2, max_length=80)
    role: str = Field(min_length=2, max_length=60)
    home: str = Field(default="", max_length=80)
    pin: str = Field(pattern=r"^\d{4}$")
    dob: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    sex: str = ""
    nationality: str = ""
    languages: List[str] = []
    agency: str = ""
    flights: int = Field(default=0, ge=0, le=20)
    days_in_space: int = Field(default=0, ge=0, le=2000)
    height_cm: float = Field(default=170, ge=120, le=220)
    weight_kg: float = Field(default=70, ge=35, le=160)
    blood_type: str = ""
    skin_type: str = Field(default="III", pattern="^(I|II|III|IV|V|VI)$")
    handedness: str = "Right"
    vision: str = ""
    allergies: List[str] = []
    medications: List[str] = []
    conditions: List[str] = []
    diet: str = ""
    vaccinations: str = ""
    emergency_contact: str = ""


class MissionRegIn(BaseModel):
    callsign: str = Field(min_length=2, max_length=40)
    name: str = Field(min_length=2, max_length=80)
    launch_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    preset: str


class RegisterIn(BaseModel):
    crew: List[SeatIn]
    mission: MissionRegIn


@app.post("/api/control/register", tags=["control"], dependencies=[Depends(require_control)])
def control_register(body: RegisterIn):
    """Register the four crew seats and the mission, then start the mission clock from the beginning."""
    if body.mission.preset not in plan.PRESETS:
        raise HTTPException(400, "unknown mission profile")
    crew = [s.model_dump() for s in body.crew]
    try:
        registry.register([{k: v for k, v in p.items() if k != "pin"} for p in crew], body.mission.model_dump())
    except ValueError as e:
        raise HTTPException(400, str(e))
    for p in crew:
        auth.set_pin(p["seat"], p["pin"])
    plan.use_preset(body.mission.preset)
    plan.save({**plan.get(), "name": body.mission.name}, body.mission.preset)
    mission.set_step(0)
    return control_overview()


@app.post("/api/control/clear", tags=["control"], dependencies=[Depends(require_control)])
def control_clear():
    """Start from zero: no crew, no mission. The crew terminals wait for Mission Control."""
    registry.clear()
    return control_overview()


# ---------------------------------------------------------------- the web app (after `npm run build`)
mimetypes.add_type("model/gltf-binary", ".glb")
_dist = pathlib.Path(settings.frontend_dist)
if _dist.is_dir():
    app.mount("/assets", StaticFiles(directory=_dist / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        f = _dist / path
        return FileResponse(f if path and f.is_file() else _dist / "index.html")
