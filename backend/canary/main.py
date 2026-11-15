"""Canary API: one FastAPI process, modular inside (see README, Architecture).

Run:  uvicorn canary.main:app --reload --port 8000   (from backend/)
Docs: http://localhost:8000/docs
"""
import hashlib
import hmac
import json
import logging
import mimetypes
import pathlib
import time
from datetime import date, timedelta
from contextlib import asynccontextmanager
from typing import List, Optional

from fastapi import Body, Depends, FastAPI, Header, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, field_validator

from . import __version__, auth, db
from .assistant import briefing, chat, providers, suggestions, tools
from .config import settings
from .domain import advice, care, data, dose, goals, guide, health, live, mission, nasa, notify, plan, privacy, protocols, registry, selftests, standards, telemetry, validation
from .domain import simdata
from .domain.catalog import CAREER_LIMIT_MSV, RECORDS, CREW, CREW_BY_ID, INDICATORS, LOCATIONS, REGION_SYSTEM, SYSTEMS

def _warm_story() -> None:
    """Compute every crew member's health on the days of the scenes once, in the background, so the first click on each
    scene does not wait for the risks to walk back through their days. Read-only: it writes nothing."""
    from .domain import risk
    try:
        for day in dict.fromkeys(sc["day"] for sc in data.scenes()):
            ms = {**risk._day_ms(day), "storm": data.storm_at(day, plan.location_at(day))}
            for c in list(CREW):
                health.snapshot(c["id"], ms)
    except Exception:  # a warm-up must never take the API down; the next request computes it anyway
        pass


def _day_sync_loop(stop) -> None:
    """Every `day_sync_seconds`: bring in live space weather (when on) and, when the mission day changed, run the sync a
    new day triggers. Whatever happens, the loop goes on and the API stays up."""
    while True:
        try:
            live.import_donki()
            mission.safe_sync_day()
        except Exception:  # noqa: BLE001
            logging.getLogger("canary").exception("day sync loop")
        if stop.wait(settings.day_sync_seconds):
            return


@asynccontextmanager
async def lifespan(_app):
    import threading
    db.connect()
    registry.load()
    try:
        data.bootstrap()  # first start with no data and no crew: load the configured mission package once
    except validation.ValidationFailure as e:  # a broken or missing package must not stop the API from starting
        print("mission package not loaded:", "; ".join(x["message"] for x in e.errors[:3]))
    stop = threading.Event()
    if settings.warm_cache:
        threading.Thread(target=_warm_story, name="canary-warm", daemon=True).start()
    if settings.day_sync:
        threading.Thread(target=_day_sync_loop, args=(stop,), name="canary-day-sync", daemon=True).start()
    yield
    stop.set()


app = FastAPI(title="Canary API", version=__version__, lifespan=lifespan,
              description="Crew health monitoring for space missions. NASA Space Apps Challenge 2026.")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


# ---------------------------------------------------------------- one error shape for every bad input
# 422 with `detail: [{"field": "crew.1.dob", "message": "Date of birth is required"}]`. The web form maps each
# item onto its field. Auth errors (401, 403, 429) and the other HTTPExceptions keep their plain-string detail.
_LABELS = {
    "pin": "PIN", "dob": "Date of birth", "name": "Name", "role": "Role", "height_cm": "Height", "weight_kg": "Weight",
    "blood_type": "Blood type", "skin_type": "Skin type", "flights": "Previous flights", "days_in_space": "Days in space",
    "callsign": "Callsign", "launch_date": "Launch date", "text": "Message", "question": "Question", "title": "Goal",
    "why": "Why", "days": "Days", "watch": "Watch threshold", "act": "Act threshold", "prior_dose_msv": "Earlier dose",
    "eva": "EVA role", "home": "Home city", "sex": "Sex", "agency": "Agency", "nationality": "Nationality", "preset": "Mission profile",
    "diet": "Diet", "vision": "Vision", "vaccinations": "Vaccinations", "emergency_contact": "Emergency contact", "handedness": "Dominant hand",
    "area": "Area", "who": "For", "data_url": "Photo", "factor": "Care sensitivity", "step": "Step", "day": "Day",
}
_UNITS = {"height_cm": "cm", "weight_kg": "kg", "days_in_space": "days", "prior_dose_msv": "mSv", "days": "days"}


def _field_of(loc) -> str:
    return ".".join(str(x) for x in loc if x not in ("body", "query", "path"))


def _friendly(err: dict) -> str:
    loc = [x for x in err.get("loc", ()) if not isinstance(x, int)]
    label = _LABELS.get(loc[-1], str(loc[-1]).replace("_", " ").capitalize()) if loc else "This"
    unit = _UNITS.get(loc[-1] if loc else "", "")
    u = f" {unit}" if unit else ""
    ctx, kind = err.get("ctx") or {}, err.get("type", "")
    if kind == "missing":
        return f"{label} is required"
    if kind == "string_too_short":
        return f"{label} is required" if ctx.get("min_length") == 1 else f"{label} must be at least {ctx.get('min_length')} characters"
    if kind == "string_too_long":
        return f"{label} must be at most {ctx.get('max_length')} characters"
    if kind in ("greater_than_equal", "less_than_equal", "greater_than", "less_than"):
        lo = {"greater_than_equal": ctx.get("ge"), "greater_than": ctx.get("gt")}
        hi = {"less_than_equal": ctx.get("le"), "less_than": ctx.get("lt")}
        return f"{label} must be {'at least' if kind in lo else 'at most'} {(lo.get(kind) if kind in lo else hi.get(kind))}{u}"
    if kind in ("int_parsing", "float_parsing", "int_from_float", "int_type", "float_type"):
        return f"{label} must be {'a whole number' if kind.startswith('int') else 'a number'}"
    if kind == "string_pattern_mismatch":
        return f"{label} must be exactly 4 digits" if loc and loc[-1] == "pin" else f"{label} has the wrong format"
    if kind == "value_error":
        return str(err.get("msg", "")).removeprefix("Value error, ")
    return f"{label}: {err.get('msg', 'not accepted')}"


def _unprocessable(errors: list) -> JSONResponse:
    return JSONResponse(status_code=422, content={"detail": errors})


@app.exception_handler(RequestValidationError)
async def _on_request_validation(_req: Request, exc: RequestValidationError):
    return _unprocessable([{"field": _field_of(e["loc"]), "message": _friendly(e)} for e in exc.errors()])


@app.exception_handler(validation.ValidationFailure)
async def _on_field_error(_req: Request, exc: validation.ValidationFailure):
    return _unprocessable(exc.errors)


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
            "story": mission.story(), "sources": nasa.SOURCES, "standards": standards.summary(), "guide": guide.guide()}


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
    mission.safe_sync_day(force=True)  # an advice concluded by the new day may call for a message to the medical officer; a new critical alert reaches the medical officer, once per episode
    return mission.state()


@app.post("/api/demo/reset", tags=["mission"])
def demo_reset():
    """Clear everything and load the configured mission package (CANARY_MISSION_PACKAGE, default odyssey1-mars).
    An empty setting starts with no data at all."""
    db.reset()
    plan.reset_cache()
    registry.load()
    auth.clear_failures()
    if settings.mission_package:
        try:
            data.import_named(settings.mission_package)
        except validation.ValidationFailure as e:
            raise HTTPException(500, "Mission package not loaded: " + "; ".join(x["message"] for x in e.errors[:3]))
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
    curve = dose.curve(None, ms["day"])  # the cabin's (or the plan's) dose: crew-wide, never a person's own dosimeter
    series = [[d, curve[d]] for d in days]
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
    _reload_for_legs(plan.get()["legs"])
    return get_plan()


def _reload_for_legs(legs: list) -> None:
    """Legs that equal a preset's are that preset: the bundled package of the preset replaces the data. A custom
    itinerary changes only the plan: real measurements do not change because the plan did."""
    sig = simdata.signature(legs)
    for key in plan.PRESETS:
        if any(simdata.signature(plan.preset_legs(key, r)) == sig for r in (True, False)):
            data.reload_for_preset(key)
            return


class PresetIn(BaseModel):
    preset: str


@app.post("/api/plan/preset", tags=["mission"])
def plan_preset(body: PresetIn):
    try:
        plan.use_preset(body.preset)
    except ValueError as e:
        raise HTTPException(400, str(e))
    data.reload_for_preset(body.preset)
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
    _reload_for_legs(plan.get()["legs"])
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
    lb = goals.leaderboard(ms["day"], public=False)
    profs = {r["crew_id"]: r for r in lb["rows"]}
    rows = [_summary(c, ms, profs[c["id"]]) for c in CREW]
    return {"mission": ms, "crew": rows, "team": lb["team"], "dose": health.dose(ms),
            "space_weather": {k: v for k, v in nasa.space_weather(data.storm_event(ms["day"], ms["location"])).items() if k in ("headline", "active", "kp_max", "sep_events")}}


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
    sw = nasa.space_weather(data.storm_event(ms["day"], ms["location"]))
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
    with_photo = {r["checkin_id"] for r in db.q("SELECT checkin_id FROM checkin_photos WHERE crew_id=?", (crew_id,))}
    events = [{"id": r["id"], "kind": r["kind"], "day": r["day"], "payload": json.loads(r["payload"]), "has_photo": r["id"] in with_photo}
              for r in db.q("SELECT id,kind,day,payload FROM checkins WHERE crew_id=? ORDER BY id DESC LIMIT 12", (crew_id,))]
    return {"crew": {k: c[k] for k in ("id", "name", "role", "initials", "home", "age")}, "mission": ms, **snap,
            "trends": trends, "goals": goals.personal_today(crew_id, ms, snap),
            "profile": goals.profile(crew_id, ms["day"]),
            "blood": nasa.blood(crew_id, c["sex"]), "events": events, "standard_profile": standards.crew_profile(crew_id),
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
            "eva": standards.eva_role(crew_id), "prior_dose": standards.prior_dose(crew_id),  # recorded, or estimated from the days in space
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
    photo: Optional[str] = None  # vitals only: the display, kept as evidence apart from the numbers


@app.post("/api/checkins", tags=["crew"])
def checkin(body: CheckinIn, v: dict = Depends(viewer)):
    """A test or log from the Tests page (or a quick check from My space). Private: self and medical team."""
    _crew(body.crew_id)
    require_self(body.crew_id, v)
    selftests.validate(body.kind, body.payload)  # raises FieldError: 422 {field, message}, nothing written
    day = mission.state()["day"]
    photo = None
    if body.photo is not None:
        if body.kind != "vitals":
            raise validation.FieldError("photo", "Only vital signs take a photo")
        photo = validation.image_data_url(body.photo, "The photo of the display")
    p = selftests.normalise(body.kind, body.payload)
    cid = db.x("INSERT INTO checkins(crew_id,day,kind,payload,created_at) VALUES(?,?,?,?,?)",
               (body.crew_id, day, body.kind, json.dumps(p), time.time()))
    if photo:  # never part of the payload: the payload feeds events, charts and the assistant
        db.x("INSERT INTO checkin_photos(checkin_id,crew_id,data_url,created_at) VALUES(?,?,?,?)", (cid, body.crew_id, photo, time.time()))
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
    with_photo = {r["checkin_id"] for r in db.q("SELECT checkin_id FROM checkin_photos WHERE crew_id=?", (crew_id,))}
    latest, recent = {}, []
    for r in rows:
        p = json.loads(r["payload"])
        item = {"id": r["id"], "kind": r["kind"], "day": r["day"], "at": r["created_at"], "summary": selftests.summary(r["kind"], p), "payload": p,
                "has_photo": r["id"] in with_photo}
        latest.setdefault(r["kind"], item)
        if len(recent) < 20:
            recent.append(item)
    return {"tests": [{**t, "latest": latest.get(t["id"])} for t in selftests.TESTS], "recent": recent}


@app.get("/api/checkins/{crew_id}/{checkin_id}/photo", tags=["crew"])
def checkin_photo(crew_id: str, checkin_id: int, v: dict = Depends(viewer)):
    """The photo of the display kept with a vitals check-in. The person and the medical team only (same rule as crew detail)."""
    c = _crew(crew_id)
    if not privacy.can_see_details(v["id"], crew_id, v["medical"]):
        raise HTTPException(403, f"{c['name']}'s health is private")
    r = db.q("SELECT data_url FROM checkin_photos WHERE checkin_id=? AND crew_id=?", (checkin_id, crew_id))
    if not r:
        raise HTTPException(404, "no photo with that check-in")
    return {"data_url": r[0]["data_url"]}


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
    model_config = ConfigDict(str_strip_whitespace=True)
    sender: str = Field(min_length=1, max_length=60)
    recipient: str = Field(min_length=1, max_length=60)
    text: str = Field(min_length=1, max_length=1000)


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
    ms = mission.state()
    return nasa.space_weather(data.storm_event(ms["day"], ms["location"]))


@app.get("/api/nasa/rad", tags=["nasa"])
def nasa_rad():
    return nasa.rad()


@app.get("/api/nasa/sources", tags=["nasa"])
def nasa_sources():
    return nasa.SOURCES


# ---------------------------------------------------------------- AI assistant slot
class AskIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
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
                    "risks": [{k: r[k] for k in ("id", "name", "nasa_red", "level", "trend", "since_day", "data")} for r in s["risks"]],
                    "dose": s["dose"], "standard_profile": standards.crew_profile(c["id"]),
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
        raise validation.FieldError("act", f"Act ({body.act}) must be above watch ({body.watch})")
    db.set_setting("thresholds", {"watch": body.watch, "act": body.act})
    return health.thresholds()


class MedGoalIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    who: str
    area: str = Field(pattern="^(physical|mental)$")
    title: str = Field(min_length=3, max_length=120)
    why: str = Field(default="Prescribed by the medical team.", max_length=200)
    days: int = Field(default=7, ge=1, le=60)


@app.post("/api/medical/goals", tags=["medical"], dependencies=[Depends(require_medical)])
def add_med_goal(body: MedGoalIn):
    if body.who != "all" and body.who not in CREW_BY_ID:
        raise validation.FieldError("who", "Pick a crew member or the whole crew")
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


def _earth_ops(ops: dict) -> dict:
    """Earth follows the operational status only: why a person is restricted (the care window after an emergency) stays
    with the person and the medical team."""
    return {k: v for k, v in ops.items() if k in ("key", "label", "level")}


@app.get("/api/control/overview", tags=["control"], dependencies=[Depends(require_control)])
def control_overview():
    """What Earth follows: operational status as the medical team reports it, participation, hazards, traffic."""
    ms = mission.state()
    board = goals.crew_board(ms["day"]) if CREW else {"people": {}}
    people = []
    for c in CREW:
        s = health.snapshot(c["id"], ms)
        last = db.q("SELECT day FROM checkins WHERE crew_id=? ORDER BY id DESC LIMIT 1", (c["id"],))
        people.append({**{k: c[k] for k in ("id", "name", "role", "initials", "home")}, "ops": _earth_ops(privacy.operational(s)),
                       "today": board["people"].get(c["id"]), "last_checkin_day": last[0]["day"] if last else None})
    env = [a for a in (health.snapshot(CREW[0]["id"], ms)["alerts"] if CREW else []) if a.get("env")]
    return {"registered": registry.registered(), "mission": ms, "overview": mission_overview(), "people": people,
            "ridge": privacy.ridge(ms["location"], ms["storm"], ms["day"]), "warnings": [{k: a[k] for k in ("title", "todo")} for a in env],
            "dose": health.dose(ms), "emergencies": emergencies()[:5]}


@app.get("/api/control/demo", tags=["control"], dependencies=[Depends(require_control)])
def control_demo():
    """What the 'fill with the demo crew' button puts in the form."""
    form = data.demo_form()
    return {"crew": form["crew"], "mission": form["mission"], "presets": {k: v["name"] for k, v in plan.PRESETS.items()},
            "rover_presets": [k for k in plan.PRESETS if plan.has_rover(k)], "iss_dose_msv_per_day": LOCATIONS["iss"]["dose_rate"],
            # the itinerary each profile gives, with and without its rover leg, for the review step
            "itineraries": {k: {"rover": plan.preset_legs(k, True), "plain": plan.preset_legs(k, False)} for k in plan.PRESETS}}


BLOOD_TYPES = ["O−", "O+", "A−", "A+", "B−", "B+", "AB−", "AB+"]
SEAT_AGE = (25, 70)       # prototype assumption: plausible astronaut age at launch
LAUNCH_YEARS = (2025, 2100)


def _trim_list(v: List[str], what: str, max_items: int = 20, max_len: int = 60) -> List[str]:
    out = [x.strip() for x in v if x.strip()]
    if len(out) > max_items or any(len(x) > max_len for x in out):
        raise ValueError(f"{what}: at most {max_items} items of {max_len} characters")
    return out


class SeatIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    seat: Optional[str] = Field(default=None, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,19}$")  # the person's id; left out, s1 to s6 in order
    name: str = Field(min_length=2, max_length=60)
    role: str = Field(min_length=2, max_length=60)
    home: str = Field(default="", max_length=80)
    pin: str = Field(pattern=r"^\d{4}$")
    dob: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    sex: str = Field(default="", pattern="^(|Female|Male|Other)$")
    nationality: str = Field(default="", max_length=60)
    languages: List[str] = []
    agency: str = Field(default="", max_length=80)
    flights: int = Field(default=0, ge=0, le=20)
    days_in_space: int = Field(default=0, ge=0, le=1000)
    height_cm: float = Field(default=170, ge=140, le=210)
    weight_kg: float = Field(default=70, ge=40, le=150)
    blood_type: str = ""
    skin_type: str = Field(default="III", pattern="^(I|II|III|IV|V|VI)$")
    handedness: str = Field(default="Right", pattern="^(Right|Left)$")
    vision: str = Field(default="", max_length=80)
    allergies: List[str] = []
    medications: List[str] = []
    conditions: List[str] = []
    diet: str = Field(default="", max_length=120)
    vaccinations: str = Field(default="", max_length=200)
    emergency_contact: str = Field(default="", max_length=200)
    eva: Optional[str] = Field(default=None, pattern="^(surface|microgravity|none)$")
    prior_dose_msv: Optional[float] = Field(default=None, ge=0, le=600)

    @field_validator("blood_type")
    @classmethod
    def _blood(cls, v: str) -> str:
        if v and v not in BLOOD_TYPES:
            raise ValueError("Blood type must be one of: " + ", ".join(BLOOD_TYPES))
        return v

    @field_validator("dob")
    @classmethod
    def _dob(cls, v: str) -> str:
        try:
            date.fromisoformat(v)
        except ValueError:
            raise ValueError("Date of birth is not a real date")
        return v

    @field_validator("languages", "allergies", "medications", "conditions")
    @classmethod
    def _lists(cls, v: List[str]) -> List[str]:
        return _trim_list(v, "This list")


class MissionRegIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    callsign: str = Field(min_length=2, max_length=24)
    name: str = Field(min_length=2, max_length=80)
    launch_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    preset: str
    rover: Optional[bool] = None  # a pressurized rover leg; left out, the profile's own default (on for Moon and Mars)

    @field_validator("launch_date")
    @classmethod
    def _launch(cls, v: str) -> str:
        try:
            d = date.fromisoformat(v)
        except ValueError:
            raise ValueError("Launch date is not a real date")
        if not LAUNCH_YEARS[0] <= d.year <= LAUNCH_YEARS[1]:
            raise ValueError(f"Launch date must be between {LAUNCH_YEARS[0]} and {LAUNCH_YEARS[1]}")
        return v


class RegisterIn(BaseModel):
    crew: List[SeatIn]  # one to six people (checked in _check_registration, which answers on the `crew` field)
    mission: MissionRegIn


def _check_registration(body: RegisterIn) -> None:
    """The rules that need more than one field: one to six people, the profile exists, ids and PINs differ between seats, ages at launch."""
    errs: List[dict] = []
    if not 1 <= len(body.crew) <= registry.MAX_CREW:
        errs.append({"field": "crew", "message": f"Register between 1 and {registry.MAX_CREW} people"})
    if body.mission.preset not in plan.PRESETS:
        errs.append({"field": "mission.preset", "message": "Mission profile must be one of: " + ", ".join(plan.PRESETS)})
    elif body.mission.rover and not plan.has_rover(body.mission.preset):
        errs.append({"field": "mission.rover", "message": f"{plan.PRESETS[body.mission.preset]['name']} has no rover leg; the rover is for the Moon and Mars profiles"})
    launch = date.fromisoformat(body.mission.launch_date)
    seen: dict = {}
    ids = registry.assign_ids([p.seat for p in body.crew])
    seen_id: dict = {}
    for i, p in enumerate(body.crew):
        if ids[i] in registry.RESERVED_IDS:
            errs.append({"field": f"crew.{i}.seat", "message": f"ID {ids[i]} is reserved; pick another"})
        elif ids[i] in seen_id:
            errs.append({"field": f"crew.{i}.seat", "message": f"ID is already used by seat {seen_id[ids[i]] + 1}; each seat needs its own"})
        seen_id.setdefault(ids[i], i)
        age = validation.age_on(date.fromisoformat(p.dob), launch)
        if not SEAT_AGE[0] <= age <= SEAT_AGE[1]:
            errs.append({"field": f"crew.{i}.dob", "message": f"Date of birth gives an age of {age} at launch; it must be between {SEAT_AGE[0]} and {SEAT_AGE[1]}"})
        if p.pin in seen:
            errs.append({"field": f"crew.{i}.pin", "message": f"PIN is already used by seat {seen[p.pin] + 1}; each seat needs its own"})
        seen.setdefault(p.pin, i)
    if errs:
        raise validation.ValidationFailure(errs)


@app.post("/api/control/register", tags=["control"], dependencies=[Depends(require_control)])
def control_register(body: RegisterIn):
    """Register the crew (one to six people) and the mission, then start the mission clock from the beginning. PINs are stored hashed."""
    _check_registration(body)
    ids = registry.assign_ids([s.seat for s in body.crew])
    crew = [{**s.model_dump(), "seat": i} for s, i in zip(body.crew, ids)]
    rover = plan.has_rover(body.mission.preset) if body.mission.rover is None else bool(body.mission.rover)
    try:
        registry.register(crew, {**body.mission.model_dump(), "rover": rover})
    except ValueError as e:
        raise HTTPException(400, str(e))
    plan.use_preset(body.mission.preset, rover)
    plan.save({**plan.get(), "name": body.mission.name}, body.mission.preset)
    data.reload_for_preset(body.mission.preset)
    mission.set_step(0)
    return control_overview()


@app.post("/api/control/clear", tags=["control"], dependencies=[Depends(require_control)])
def control_clear():
    """Start from zero: no crew, no mission. The crew terminals wait for Mission Control."""
    registry.clear()
    return control_overview()


# ---------------------------------------------------------------- data entry points
# Sensors, wearables and labs send readings with a key; Mission Control adds space events and imports mission packages.
# All of them end in domain/data.py, which validates everything first and writes in one transaction.
MAX_OBS_BATCH = 5000


def require_ingest(x_canary_key: Optional[str] = Header(None)) -> None:
    """The ingest key (CANARY_INGEST_KEY) in the X-Canary-Key header. Never logged, never returned."""
    if not settings.ingest_key:
        raise HTTPException(503, "Ingest is off")
    if not x_canary_key or not hmac.compare_digest(x_canary_key.encode(), settings.ingest_key.encode()):
        raise HTTPException(401, "A valid X-Canary-Key is required")


@app.post("/api/observations", tags=["data"], dependencies=[Depends(require_ingest)])
def post_observations(body: dict = Body(...)):
    """A batch of readings: {"rows": [{crew_id, indicator, value, unit, measured_at | day, origin, method, source, note}]}.
    Up to 5000 rows. One bad row refuses the whole batch (422, `rows.N.field`) and nothing is stored."""
    rows = body.get("rows") if isinstance(body, dict) else None
    if not isinstance(rows, list):
        raise validation.FieldError("rows", "Send {\"rows\": [...]}")
    if len(rows) > MAX_OBS_BATCH:
        raise validation.FieldError("rows", f"At most {MAX_OBS_BATCH} readings per request")
    return data.add_observations(rows)


@app.get("/api/scenes", tags=["data"])
def get_scenes():
    """The guided demo's bookmarks (a day, a place, a person, a sentence). Not health data."""
    return data.scenes()


@app.post("/api/control/space-events", tags=["control"], dependencies=[Depends(require_control)])
def control_add_space_event(body: dict = Body(...)):
    """One space-weather event: kind, start_day, end_day, locations, extra_dose_msv (0 to 2000), origin, source, note."""
    return data.add_space_event(body)


@app.put("/api/control/clock", tags=["control"], dependencies=[Depends(require_control)])
def control_clock(body: dict = Body(...)):
    """Move the mission clock: {"date": "YYYY-MM-DD", "time": "HH:MM"} for a simulated date (time is optional), or
    {"real": true} to follow today's date in UTC again. 422 {field, message} on bad input. Runs the day sync at once."""
    if not isinstance(body, dict):
        raise validation.FieldError("body", "Send {\"date\": \"2035-10-31\", \"time\": \"12:00\"} or {\"real\": true}")
    real = body.get("real")
    if real is not None and not isinstance(real, bool):
        raise validation.FieldError("real", "real must be true or false")
    mission.set_clock(body.get("date"), body.get("time"), bool(real))
    mission.safe_sync_day(force=True)
    return mission.state()


@app.get("/api/control/space-events", tags=["control"], dependencies=[Depends(require_control)])
def control_space_events():
    return {"events": data.events()}


def _multipart_files(content_type: str, raw: bytes) -> list:
    """(filename, bytes) of every file part of a multipart/form-data body (standard library, no extra dependency)."""
    from email import policy
    from email.parser import BytesParser
    msg = BytesParser(policy=policy.HTTP).parsebytes(b"Content-Type: " + content_type.encode("latin-1") + b"\r\n\r\n" + raw)
    if not msg.is_multipart():
        raise validation.FieldError("file", "Send a multipart upload with the files")
    return [(part.get_filename(), part.get_payload(decode=True) or b"") for part in msg.iter_parts() if part.get_filename()]


@app.post("/api/control/import", tags=["control"], dependencies=[Depends(require_control)])
async def control_import(request: Request):
    """Import a mission package: a multipart upload of a .zip or of CSV files named like the package files, or JSON
    {"package": "odyssey1-mars"} for a bundled one. Any error: 422 {"errors": [...]} and nothing is written."""
    ctype = request.headers.get("content-type", "")
    try:
        if ctype.startswith("application/json"):
            try:
                body = await request.json()
            except ValueError:
                raise validation.FieldError("package", "Send JSON like {\"package\": \"odyssey1-mars\"}")
            name = body.get("package") if isinstance(body, dict) else None
            res = await run_in_threadpool(data.import_package, data.package_dir(name), name, True)
        elif ctype.startswith("multipart/form-data"):
            if int(request.headers.get("content-length") or 0) > data.MAX_UPLOAD_BYTES:
                raise validation.FieldError("file", "The upload is too large")
            raw = await request.body()
            files = data.files_from_upload(_multipart_files(ctype, raw))
            res = await run_in_threadpool(data.import_package, files, "upload", False)
        else:
            raise HTTPException(415, "Send multipart/form-data (a zip or CSV files) or JSON {\"package\": \"name\"}")
    except validation.ValidationFailure as e:
        return JSONResponse(status_code=422, content={"detail": e.errors, "errors": e.errors, "accepted": {}})
    return {**res, "errors": []}


# ---------------------------------------------------------------- the web app (after `npm run build`)
mimetypes.add_type("model/gltf-binary", ".glb")
_dist = pathlib.Path(settings.frontend_dist)
if _dist.is_dir():
    app.mount("/assets", StaticFiles(directory=_dist / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        f = _dist / path
        return FileResponse(f if path and f.is_file() else _dist / "index.html")
