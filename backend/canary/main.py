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
from contextlib import asynccontextmanager
from typing import List, Optional

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import __version__, db
from .assistant import briefing, chat, providers, tools
from .config import settings
from .domain import goals, health, mission, nasa, plan, privacy, protocols, telemetry
from .domain.catalog import CREW, CREW_BY_ID, INDICATORS, LOCATIONS, REGION_SYSTEM, STORY, SYSTEMS

@asynccontextmanager
async def lifespan(_app):
    db.connect()
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
    """Who is looking. No crew accounts on board: the terminal says who entered their space."""
    return {"id": x_canary_viewer if x_canary_viewer in CREW_BY_ID else None, "medical": _is_medical(authorization)}


def require_self(crew_id: str, v: dict) -> None:
    if not (v["medical"] or v["id"] == crew_id):
        raise HTTPException(403, f"private: only {CREW_BY_ID[crew_id]['name']} and the medical team can see this")


_failed: List[float] = []


class PinIn(BaseModel):
    pin: str


@app.post("/api/medical/session", tags=["medical"])
def medical_session(body: PinIn):
    now = time.time()
    _failed[:] = [t for t in _failed if now - t < 60]
    if len(_failed) >= 5:
        raise HTTPException(429, "too many attempts, wait a minute")
    if not hmac.compare_digest(body.pin, settings.medical_pin):
        _failed.append(now)
        raise HTTPException(401, "wrong PIN")
    exp = int(now + settings.token_ttl_s)
    return {"token": f"{exp}.{_sign(exp)}", "expires_at": exp}


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
    return mission.state()


@app.post("/api/demo/reset", tags=["mission"])
def demo_reset():
    db.reset()
    plan.reset_cache()
    return mission.state()


# ---------------------------------------------------------------- mission plan (itinerary)
@app.get("/api/plan", tags=["mission"])
def get_plan():
    return {**plan.get(), "presets": {k: v["name"] for k, v in plan.PRESETS.items()}}


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
    return get_plan()


class PresetIn(BaseModel):
    preset: str


@app.post("/api/plan/preset", tags=["mission"])
def plan_preset(body: PresetIn):
    try:
        plan.use_preset(body.preset)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return get_plan()


# ---------------------------------------------------------------- crew and health
def _summary(c: dict, ms: dict, prof: dict) -> dict:
    s = health.snapshot(c["id"], ms)
    return {"id": c["id"], "name": c["name"], "role": c["role"], "initials": c["initials"], "home": c["home"],
            "areas": s["areas"], "level": s["level"], "status": s["status"],
            "top_alert": s["alerts"][0]["title"] if s["alerts"] else None, "alerts": len(s["alerts"]),
            "systems": {k: v["level"] for k, v in s["systems"].items()},
            "xp_week": prof["xp_week"], "level_xp": prof["level"], "streak": prof["streak"], "rank": prof.get("rank")}


@app.get("/api/crew", tags=["medical"], dependencies=[Depends(require_medical)])
def crew_list():
    """Full per-person health summary. Medical team only."""
    ms = mission.state()
    lb = goals.leaderboard(ms["day"])
    profs = {r["crew_id"]: r for r in lb["rows"]}
    rows = [_summary(c, ms, profs[c["id"]]) for c in CREW]
    return {"mission": ms, "crew": rows, "team": lb["team"], "dose": health.dose(ms),
            "space_weather": {k: v for k, v in nasa.space_weather(ms["storm"]).items() if k in ("headline", "active", "kp_max", "sep_events")}}


@app.get("/api/crew/overview", tags=["crew"])
def crew_overview():
    """What everyone on board may see: operational status, hazards, participation and crew goals."""
    ms = mission.state()
    board = goals.crew_board(ms["day"])
    people, env = [], []
    for c in CREW:
        snap = health.snapshot(c["id"], ms)
        env = [a for a in snap["alerts"] if a.get("env")] or env
        people.append({**{k: c[k] for k in ("id", "name", "role", "initials", "home")}, "ops": privacy.operational(snap),
                       "shared": privacy.shared(c["id"]), "today": board["people"][c["id"]]})
    sw = nasa.space_weather(ms["storm"])
    return {"mission": ms, "people": people, "fit": sum(1 for p in people if p["ops"]["key"] == "full"),
            "eva_open": not env and not ms["learning"] and ms["location"] not in ("earth", "rocket"),
            "hazards": privacy.hazards(ms, env), "team": board["team"], "crew_streak": board["crew_streak"],
            "team_done": board["team_done"], "team_total": board["team_total"], "dose": health.dose(ms),
            "space_weather": {k: v for k, v in sw.items() if k in ("headline", "active", "kp_max", "sep_events")},
            "contract": privacy.CONTRACT}


@app.get("/api/crew/{crew_id}", tags=["crew"])
def crew_detail(crew_id: str, v: dict = Depends(viewer)):
    """Full health detail: the person, the medical team, or the crew if the person chose to share."""
    c = _crew(crew_id)
    if not privacy.can_see_details(v["id"], crew_id, v["medical"]):
        raise HTTPException(403, f"{c['name']} keeps their health details private")
    ms = mission.state()
    snap = health.snapshot(crew_id, ms)
    access = "self" if v["id"] == crew_id else "medical" if v["medical"] else "shared"
    ops = privacy.operational(snap)
    if access == "shared":  # sharing opens data and history, never personal risks and advice
        snap = {**snap, "alerts": [a for a in snap["alerts"] if a.get("env")]}
    trends = {i: telemetry.series(crew_id, i, ms["day"], 30) for i in INDICATORS}
    events = [{"kind": r["kind"], "day": r["day"], "payload": json.loads(r["payload"])}
              for r in db.q("SELECT kind,day,payload FROM checkins WHERE crew_id=? ORDER BY id DESC LIMIT 12", (crew_id,))]
    return {"crew": {k: c[k] for k in ("id", "name", "role", "initials", "home", "age")}, "mission": ms, **snap,
            "trends": trends, "goals": [] if access == "shared" else goals.personal_today(crew_id, ms, snap),
            "profile": goals.profile(crew_id, ms["day"]),
            "blood": nasa.blood(c["cbc_subject"]), "events": events,
            "system_info": {k: {"space": v2["space"], "hazard": v2["hazard"]} for k, v2 in SYSTEMS.items()},
            "ops": ops, "shared": privacy.shared(crew_id), "care_by": privacy.care_by(crew_id),
            "access": access}


class ShareIn(BaseModel):
    shared: bool


@app.put("/api/crew/{crew_id}/sharing", tags=["crew"])
def crew_sharing(crew_id: str, body: ShareIn, v: dict = Depends(viewer)):
    _crew(crew_id)
    if v["id"] != crew_id:
        raise HTTPException(403, "only the astronaut decides what to share")
    privacy.set_shared(crew_id, body.shared)
    return {"crew_id": crew_id, "shared": body.shared}


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
    goals.set_done(crew_id, goal_id, mission.state()["day"], body.done)
    return goals_for(crew_id, v)


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
    kind: str = Field(pattern="^(mood|pvt|amsler|vitals)$")
    payload: dict


@app.post("/api/checkins", tags=["crew"])
def checkin(body: CheckinIn, v: dict = Depends(viewer)):
    _crew(body.crew_id)
    require_self(body.crew_id, v)
    day = mission.state()["day"]
    db.x("INSERT INTO checkins(crew_id,day,kind,payload,created_at) VALUES(?,?,?,?,?)",
         (body.crew_id, day, body.kind, json.dumps(body.payload), time.time()))
    goals.set_done(body.crew_id, body.kind, day, True)
    return {"ok": True, "snapshot": health.snapshot(body.crew_id, mission.state())}


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
    if body.close:
        ms = mission.state()
        e = _emergency(eid)
        db.x("UPDATE emergencies SET ended_at=?, outcome=? WHERE id=?", (time.time(), body.outcome or "stable", eid))
        log.append([t, f"Closed: {body.outcome or 'stable'}"])
        if e["protocol"] and e["patient"]:
            after = protocols.resolve(ms["location"])["protocols"][e["protocol"]]["after"]
            for a in after:
                db.x("INSERT INTO medical_goals(who,area,title,why,xp,from_day,to_day,created_at) VALUES(?,?,?,?,?,?,?,?)",
                     (e["patient"], "physical", a, "Follow-up after Guided Response.", 20, ms["day"], ms["day"] + 3, time.time()))
        delay = LOCATIONS[ms["location"]]["delay_s"] / settings.delay_speedup
        report = f"Guided Response report: {e['protocol'] or 'triage'}, patient {e['patient'] or 'unknown'}, outcome {body.outcome or 'stable'}, {len(log)} logged steps."
        db.x("INSERT INTO messages(sender,recipient,kind,text,sent_at,deliver_at) VALUES(?,?,?,?,?,?)",
             (e["responder"] or "crew", "earth", "report", report, time.time(), time.time() + delay))
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
def messages(crew_id: Optional[str] = None):
    now = time.time()
    rows = db.q("SELECT * FROM messages ORDER BY id DESC LIMIT 40")
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
        out.append({"id": c["id"], "name": c["name"], "role": c["role"], "level": s["level"], "areas": s["areas"],
                    "indicators": s["indicators"], "systems": s["systems"], "alerts": s["alerts"]})
    return {"mission": ms, "crew": out, "thresholds": health.thresholds(), "emergencies": emergencies()[:5]}


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
    xp: int = Field(default=20, ge=5, le=100)


@app.post("/api/medical/goals", tags=["medical"], dependencies=[Depends(require_medical)])
def add_med_goal(body: MedGoalIn):
    if body.who != "all":
        _crew(body.who)
    day = mission.state()["day"]
    db.x("INSERT INTO medical_goals(who,area,title,why,xp,from_day,to_day,created_at) VALUES(?,?,?,?,?,?,?,?)",
         (body.who, body.area, body.title, body.why, body.xp, day, day + body.days - 1, time.time()))
    return med_goals()


@app.get("/api/medical/goals", tags=["medical"], dependencies=[Depends(require_medical)])
def med_goals():
    return db.q("SELECT * FROM medical_goals ORDER BY id DESC")


@app.delete("/api/medical/goals/{gid}", tags=["medical"], dependencies=[Depends(require_medical)])
def del_med_goal(gid: int):
    db.x("DELETE FROM medical_goals WHERE id=?", (gid,))
    return med_goals()


# ---------------------------------------------------------------- the web app (after `npm run build`)
mimetypes.add_type("model/gltf-binary", ".glb")
_dist = pathlib.Path(settings.frontend_dist)
if _dist.is_dir():
    app.mount("/assets", StaticFiles(directory=_dist / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        f = _dist / path
        return FileResponse(f if path and f.is_file() else _dist / "index.html")
