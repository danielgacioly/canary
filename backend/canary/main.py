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
from datetime import date, datetime, timedelta, timezone
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
from .assistant import briefing, chat, protocol_match, providers, suggestions, tools
from .config import check_mode, settings
from .domain import advice, audit, care, data, devices, dose, goals, guide, health, live, mission, nasa, notify, plan, privacy, protocol_pages, protocols, registry, selftests, standards, telemetry, validation
from .domain import simdata
from .domain.catalog import CABIN_ID as CABIN, CAREER_LIMIT_MSV, RECORDS, CREW, CREW_BY_ID, INDICATORS, LOCATIONS, REGION_SYSTEM, SYSTEMS

def _warm_story() -> None:
    """Compute every crew member's health on the days of the scenes once, in the background, so the first click on each
    scene does not wait for the risks to walk back through their days. Read-only: it writes nothing."""
    from .domain import risk
    try:
        for day in dict.fromkeys(sc["day"] for sc in data.scenes()):
            ms = {**risk._day_ms(day), "storm": dose.active_storm(day, plan.location_at(day))}
            for c in list(CREW):
                health.snapshot(c["id"], ms)
    except Exception:  # a warm-up must never take the API down; the next request computes it anyway
        pass


ESCALATION_TICK_S = 30  # how often the background loop looks for critical alerts that nobody acknowledged


def _day_sync_loop(stop) -> None:
    """Every `day_sync_seconds`: bring in live space weather (when on) and, when the mission day changed, run the sync a
    new day triggers. Every `ESCALATION_TICK_S` seconds it also climbs the critical alerts nobody acknowledged (notify.escalate).
    Whatever happens, the loop goes on and the API stays up."""
    last_sync = 0.0
    while True:
        try:
            if time.monotonic() - last_sync >= settings.day_sync_seconds or not last_sync:
                last_sync = time.monotonic()
                live.import_donki()
                if mission.safe_sync_day():  # a write the system made on its own: it is in the audit trail
                    audit.record(audit.SYSTEM, "mission.day_sync", "mission", after={"day": mission.state()["day"]})
            notify.escalate(time.time())
        except Exception:  # noqa: BLE001
            logging.getLogger("canary").exception("day sync loop")
        if stop.wait(min(ESCALATION_TICK_S, settings.day_sync_seconds)):
            return


@asynccontextmanager
async def lifespan(_app):
    import threading
    check_mode()  # flight mode refuses to start without its secrets
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
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_methods=["*"], allow_headers=["*"])


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


@app.exception_handler(data.Conflict)
async def _on_conflict(_req: Request, exc: data.Conflict):
    return JSONResponse(status_code=409, content={"detail": exc.errors})


@app.exception_handler(validation.ValidationFailure)
async def _on_field_error(_req: Request, exc: validation.ValidationFailure):
    return _unprocessable(exc.errors)


def _crew(crew_id: str) -> dict:
    if crew_id not in CREW_BY_ID:
        raise HTTPException(404, f"unknown crew member {crew_id}")
    return CREW_BY_ID[crew_id]


# ---------------------------------------------------------------- who is signed in
# One signed token format for everybody (auth.py). A token counts only in its own header: X-Canary-Viewer (crew),
# Authorization: Bearer (the medical console: the crew medical officer or a ground flight surgeon) and X-Canary-Control
# (Canary Control: an MCC account, or the bootstrap sign-in while no MCC account exists).
BOOTSTRAP_ID = "bootstrap"


def demo_only() -> None:
    """Dependency for what exists only in demo mode: in flight mode the route does not exist (404)."""
    if settings.mode != "demo":
        raise HTTPException(404, "Not found")


def _crew_actor(token: Optional[str]) -> Optional[dict]:
    c = auth.verify(token, "crew")
    acct = registry.account(c["id"]) if c else None
    if not acct or acct["kind"] != "crew" or c["id"] not in CREW_BY_ID:
        return None
    return {"id": c["id"], "kind": "crew", "role": "cmo" if "cmo" in acct["roles"] else "crew", "roles": acct["roles"], "name": acct["name"]}


def _medical_actor(authorization: Optional[str]) -> Optional[dict]:
    c = auth.verify((authorization or "").replace("Bearer ", "", 1), "medical")
    acct = registry.account(c["id"]) if c else None
    if not acct or not ({"cmo", "flight_surgeon"} & set(acct["roles"])):
        return None
    return {"id": c["id"], "kind": "medical", "role": "cmo" if "cmo" in acct["roles"] else "flight_surgeon",
            "roles": acct["roles"], "name": acct["name"]}


def _control_actor(token: Optional[str]) -> Optional[dict]:
    c = auth.verify(token, "control")
    if not c:
        return None
    if c["id"] == BOOTSTRAP_ID:  # the first-access sign-in dies the moment an MCC account exists
        return None if registry.has_mcc() else {"id": BOOTSTRAP_ID, "kind": "control", "role": "bootstrap", "roles": ["bootstrap"], "name": "Canary Control first access"}
    acct = registry.account(c["id"])
    if not acct or "mcc" not in acct["roles"]:
        return None
    return {"id": c["id"], "kind": "control", "role": "mcc", "roles": acct["roles"], "name": acct["name"]}


def require_medical(authorization: Optional[str] = Header(None)) -> dict:
    """The medical console's actor `{id, role}` (role: cmo or flight_surgeon), or 401."""
    a = _medical_actor(authorization)
    if a is None:
        raise HTTPException(401, "medical team sign-in required")
    return a


def require_control(x_canary_control: Optional[str] = Header(None)) -> dict:
    """Canary Control's actor `{id, role}` (role: mcc, or bootstrap before any MCC account exists), or 401."""
    a = _control_actor(x_canary_control)
    if a is None:
        raise HTTPException(401, "Mission Control sign-in required")
    return a


def viewer(x_canary_viewer: Optional[str] = Header(None), authorization: Optional[str] = Header(None),
           x_canary_control: Optional[str] = Header(None)) -> dict:
    """Who is looking. Each header carries the token of its own sign-in; a bare id, a forged, expired or revoked token is nobody.
    `id` is the crew id (crew sign-in only), `medical` is true for the crew medical officer and flight surgeons, `roles` is
    everything the tokens grant, `actor` the first person found (crew, then medical, then control) and `me` every id signed in."""
    crew, med, ctl = _crew_actor(x_canary_viewer), _medical_actor(authorization), _control_actor(x_canary_control)
    actors = [a for a in (crew, med, ctl) if a]
    return {"id": crew["id"] if crew else None, "medical": med is not None, "control": ctl is not None,
            "roles": sorted({r for a in actors for r in a["roles"]}), "actor": actors[0] if actors else None,
            "me": {a["id"] for a in actors}}


def any_person(v: dict = Depends(viewer)) -> dict:
    """Any signed-in person (crew, medical or control): their actor, or 401."""
    if v["actor"] is None:
        raise HTTPException(401, "sign-in required")
    return v["actor"]


def require_onboard(v: dict = Depends(viewer)) -> dict:
    """Someone on board: a crew member, or the crew medical officer in the medical console. Ground accounts are not."""
    crew = v["actor"] if v["actor"] and v["actor"]["kind"] == "crew" else None
    if crew:
        return crew
    if v["actor"] and v["actor"]["kind"] == "medical" and v["actor"]["role"] == "cmo":
        return v["actor"]
    raise HTTPException(401 if v["actor"] is None else 403, "sign-in on board required" if v["actor"] is None else "only the crew on board can do this")


def require_self(crew_id: str, v: dict) -> None:
    if not (v["medical"] or v["id"] == crew_id):
        raise HTTPException(403, f"private: only {CREW_BY_ID[crew_id]['name']} and the medical team can see this")


def _locked() -> None:
    """A registered mission cannot be replaced, re-registered or re-planned through the API."""
    if registry.registered():
        raise HTTPException(409, "The mission is registered and locked.")


class PinIn(BaseModel):
    pin: str = Field(pattern=r"^\d{4}$")


class AccountPinIn(BaseModel):
    account_id: str = Field(min_length=1, max_length=20)
    pin: str = Field(pattern=r"^\d{4}$")


class ControlPinIn(BaseModel):
    account_id: Optional[str] = Field(default=None, min_length=1, max_length=20)
    pin: str = Field(pattern=r"^\d{4}$")


def _tell_cmo(text: str) -> None:
    """A security message for the crew medical officer (the substitute when there is none). Never carries a PIN."""
    to = privacy.medical_officer() or privacy.substitute()
    if to:
        now = time.time()
        db.x("INSERT INTO messages(sender,recipient,kind,text,sent_at,deliver_at) VALUES(?,?,?,?,?,?)", ("canary", to, "security", text, now, now))


def _roles_text(account_id: Optional[str]) -> str:
    acct = registry.account(account_id) if account_id else None
    return "+".join(acct["roles"]) if acct else "unknown"


def _attempt(request: Request, account_id: Optional[str], name: str, ok: bool, action: str = "auth.signin") -> None:
    """One PIN check with lockout. A wait is kept per account and per client address (SQLite: it survives a restart); after every
    5 wrong PINs it grows 1, 5, 15, then 60 minutes. Raises 429 while paused, 401 for a wrong PIN."""
    ip = "ip:" + (request.client.host if request.client else "unknown")
    key = f"acct:{account_id}" if account_id else None
    wait = auth.remaining(ip, *([key] if key else []))
    if wait:
        raise HTTPException(429, f"Too many wrong PINs. Sign-in is paused; try again in {max(1, -(-wait // 60))} min.", headers={"Retry-After": str(wait)})
    who = {"id": account_id or "unknown", "role": _roles_text(account_id)}
    if ok:
        if key:
            auth.succeed(key)
        audit.record(who, action, key or ip)
        return
    auth.fail(ip)
    locked_min = auth.fail(key) if key else None
    audit.record({"id": who["id"], "role": "unauthenticated"}, action + "_failed", key or ip, after={"ip": ip})  # never the PIN
    if locked_min:
        audit.record({"id": who["id"], "role": "unauthenticated"}, "auth.lockout", key or ip, after={"minutes": locked_min, "ip": ip})
        _tell_cmo(f"Repeated wrong PIN for {name}'s account; sign-in paused for {locked_min} min.")
    raise HTTPException(401, "wrong PIN or account")


@app.post("/api/medical/session", tags=["medical"])
def medical_session(body: AccountPinIn, request: Request):
    """Sign in to the medical console: the crew medical officer (their crew id) or a ground flight surgeon, with the account's PIN."""
    acct = registry.account(body.account_id)
    eligible = bool(acct and {"cmo", "flight_surgeon"} & set(acct["roles"]))
    _attempt(request, body.account_id if acct else None, acct["name"] if acct else "", eligible and auth.check_pin(body.account_id, body.pin))
    return auth.issue("medical", body.account_id, acct["roles"])


@app.post("/api/crew/{crew_id}/session", tags=["crew"])
def crew_session(crew_id: str, body: PinIn, request: Request):
    """Sign in to a private space with the 4-digit PIN. Returns the token for the X-Canary-Viewer header."""
    c = _crew(crew_id)
    _attempt(request, crew_id, c["name"], auth.check_pin(crew_id, body.pin))
    return auth.issue("crew", crew_id, registry.account(crew_id)["roles"])


@app.post("/api/control/session", tags=["control"])
def control_session(body: ControlPinIn, request: Request):
    """Sign in to Canary Control. With an `account_id`: an MCC account and its PIN. Without: the first-access PIN
    (CANARY_CONTROL_BOOTSTRAP_PIN), accepted only while no MCC account is registered."""
    if body.account_id is None:
        if registry.has_mcc():
            raise HTTPException(401, "Sign in with an MCC account.")
        _attempt(request, BOOTSTRAP_ID, "Canary Control first access",
                 bool(settings.control_bootstrap_pin) and hmac.compare_digest(body.pin, settings.control_bootstrap_pin))
        return auth.issue("control", BOOTSTRAP_ID, ["bootstrap"])
    acct = registry.account(body.account_id)
    mcc = bool(acct and "mcc" in acct["roles"])
    _attempt(request, body.account_id if acct else None, acct["name"] if acct else "", mcc and auth.check_pin(body.account_id, body.pin))
    return auth.issue("control", body.account_id, acct["roles"])


@app.post("/api/session/logout", tags=["system"])
def logout(x_canary_viewer: Optional[str] = Header(None), authorization: Optional[str] = Header(None),
           x_canary_control: Optional[str] = Header(None)):
    """End the sessions these headers carry: each token is revoked at once and stops working everywhere."""
    n = 0
    for t in (x_canary_viewer, (authorization or "").replace("Bearer ", "", 1), x_canary_control):
        c = auth._parse(t)
        if auth.revoke(t):
            n += 1
            audit.record({"id": c["id"], "role": c["kind"]}, "auth.logout", f"{c['kind']}:{c['id']}")
    if not n:
        raise HTTPException(401, "no session to end")
    return {"revoked": n}


@app.get("/api/accounts/public", tags=["system"])
def accounts_public():
    """Who can sign in, for the sign-in pickers: crew {id, name, role, initials, cmo} and ground {id, name, role}. Never a PIN."""
    return registry.accounts_public()


class PinChangeIn(BaseModel):
    current: str = Field(pattern=r"^\d{4}$")
    new: str = Field(pattern=r"^\d{4}$")


@app.put("/api/crew/{crew_id}/pin", tags=["crew"])
def crew_pin(crew_id: str, body: PinChangeIn, request: Request, v: dict = Depends(viewer)):
    """Change your own PIN: needs your session token and the current PIN."""
    c = _crew(crew_id)
    if v["id"] != crew_id:
        raise HTTPException(403, "only you can change your PIN")
    _attempt(request, crew_id, c["name"], auth.check_pin(crew_id, body.current), "auth.pin_check")
    auth.set_pin(crew_id, body.new)
    audit.record(v["actor"], "auth.pin_change", crew_id)  # the fact that it changed, never a PIN
    return {"crew_id": crew_id, "changed": True}


# ---------------------------------------------------------------- mission
@app.get("/api/health", tags=["system"])
def ping():
    return {"ok": True, "version": __version__, "mode": settings.mode}


@app.get("/api/catalog", tags=["mission"])
def catalog():
    return {"locations": LOCATIONS, "indicators": INDICATORS, "systems": SYSTEMS, "region_system": REGION_SYSTEM,
            "crew": [{k: c[k] for k in ("id", "name", "role", "initials", "home", "age")} for c in CREW],
            "story": mission.story(), "sources": nasa.SOURCES, "standards": standards.summary(), "guide": guide.guide(),
            "mode": settings.mode}


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
def put_mission(body: MissionIn, _demo: None = Depends(demo_only), actor: dict = Depends(require_control)):
    """Demo only: the story step, the simulated day and the place. Needs Canary Control."""
    audit.record(actor, "mission.set", "mission", before={k: mission.state()[k] for k in ("day", "location")},
                 after=body.model_dump(exclude_defaults=True))
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
def demo_reset(_demo: None = Depends(demo_only), actor: dict = Depends(require_control)):
    """Clear everything and load the configured mission package (CANARY_MISSION_PACKAGE, default odyssey1-mars).
    An empty setting starts with no data at all. Demo only (404 in flight mode); wipes the database, so it needs Canary Control."""
    _start_over(settings.mission_package)  # wipes the audit log too: the reset is the first entry of the new one
    audit.record(actor, "demo.reset", "database", after={"package": settings.mission_package or None})
    return mission.state()


DEMO_PACKAGE = "odyssey1-mars"


def _start_over(package: Optional[str]) -> None:
    """Wipe crew, mission and every reading, then load `package` (a bundled mission package) if one is named."""
    db.reset()
    plan.reset_cache()
    registry.load()
    if settings.mode == "demo":
        auth.clear_failures()  # a demo start-over also forgives wrong PINs; the failures of a flight system are never wiped
    if package:
        try:
            data.import_named(package)
        except validation.ValidationFailure as e:
            raise HTTPException(500, "Mission package not loaded: " + "; ".join(x["message"] for x in e.errors[:3]))


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
                     "limit_msv": CAREER_LIMIT_MSV, "simulated": True,
                     **dose.plan_conditions(ms["day"], [c["id"] for c in CREW], {c["id"]: standards.prior_dose(c["id"]) for c in CREW})}}


class LegIn(BaseModel):
    location: str
    start: int = Field(ge=-365, le=2000)
    end: int = Field(ge=-365, le=2000)
    label: str = ""


class PlanIn(BaseModel):
    name: str = "Mission plan"
    legs: List[LegIn]


@app.put("/api/plan", tags=["mission"])
def put_plan(body: PlanIn, _demo: None = Depends(demo_only), actor: dict = Depends(require_control)):
    _locked()
    audit.record(actor, "plan.save", "plan", before={"name": plan.get()["name"], "legs": len(plan.get()["legs"])},
                 after={"name": body.name, "legs": len(body.legs)})
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
def plan_preset(body: PresetIn, _demo: None = Depends(demo_only), actor: dict = Depends(require_control)):
    _locked()
    audit.record(actor, "plan.preset", "plan", before={"name": plan.get()["name"]}, after={"preset": body.preset})
    try:
        plan.use_preset(body.preset)
    except ValueError as e:
        raise HTTPException(400, str(e))
    data.reload_for_preset(body.preset)
    mission.set_setup_done()
    return get_plan()


@app.post("/api/setup", tags=["mission"])
def mission_setup(body: PlanIn, _demo: None = Depends(demo_only), actor: dict = Depends(require_control)):
    """First-run mission setup (demo only): validate and save the plan, mark setup done and start the mission clock over."""
    _locked()
    audit.record(actor, "plan.setup", "plan", after={"name": body.name, "legs": len(body.legs)})
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
            "space_weather": {k: v for k, v in nasa.space_weather(dose.active_event(ms["day"], ms["location"])).items() if k in ("headline", "active", "kp_max", "sep_events")}}


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
    sw = nasa.space_weather(dose.active_event(ms["day"], ms["location"]))
    return {"mission": ms, "people": people,
            "eva_open": not env and not ms["learning"] and ms["location"] not in ("earth", "rocket"),
            "hazards": privacy.hazards(ms, env), "ridge": privacy.ridge(ms["location"], ms["storm"], ms["day"]),
            "warnings": [{k: a.get(k) for k in ("id", "level", "title", "why", "todo", "sources", "protocol")} for a in env],
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
    audit.record(v["actor"], "crew.photo_set", crew_id)
    return privacy.photos()


@app.delete("/api/crew/{crew_id}/photo", tags=["crew"])
def crew_photo_delete(crew_id: str, v: dict = Depends(viewer)):
    _crew(crew_id)
    if v["id"] != crew_id:
        raise HTTPException(403, "only the astronaut changes their photo")
    privacy.set_photo(crew_id, None)
    audit.record(v["actor"], "crew.photo_delete", crew_id)
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
    audit.record(v["actor"], "goal.set", f"{crew_id}:{goal_id}", after={"done": body.done, "day": ms["day"]})
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
    audit.record(v["actor"], "checkin.add", body.crew_id, after={"id": cid, "kind": body.kind, "day": day, "photo": photo is not None})  # no values
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


@app.get("/api/protocols/library", tags=["guided response"])
def protocols_library(v: dict = Depends(viewer)):
    """The Protocols page: every protocol as a reference page and which ones are in force now. Crew-wide, no personal health data;
    the care window is listed only for the medical team."""
    ms = mission.state()
    return protocol_pages.library(ms, health.dose(ms), medical=v["medical"])


class MatchIn(BaseModel):
    text: str = Field(min_length=1, max_length=500)

    @field_validator("text")
    @classmethod
    def _not_blank(cls, t: str) -> str:
        if not t.strip():
            raise ValueError("describe what you see")
        return t


@app.post("/api/protocols/match", tags=["guided response"])
def match_protocol(body: MatchIn, actor: dict = Depends(any_person)):
    """What the person sees, in their own words -> the closest protocols with the words that matched. Rules first; a connected
    model may only re-rank them (assistant/protocol_match.py). Never starts anything."""
    return protocol_match.match(body.text)


class EmergencyIn(BaseModel):
    protocol: Optional[str] = None
    patient: Optional[str] = None
    responder: Optional[str] = None


@app.post("/api/emergencies", tags=["guided response"])
def emergency_start(body: EmergencyIn, actor: dict = Depends(require_onboard)):
    """Open Guided Response. On board only: a crew member, or the crew medical officer in the medical console."""
    ms = mission.state()
    eid = db.x("INSERT INTO emergencies(protocol,patient,responder,location,day,started_at,log) VALUES(?,?,?,?,?,?,?)",
               (body.protocol, body.patient, body.responder or actor["id"], ms["location"], ms["day"], time.time(),
                json.dumps([[0, "Guided Response opened. Crew alerted."]])))
    audit.record(actor, "emergency.open", f"emergency:{eid}", after={"protocol": body.protocol, "patient": body.patient, "day": ms["day"]})
    delay = LOCATIONS[ms["location"]]["delay_s"] / settings.delay_speedup
    db.x("INSERT INTO messages(sender,recipient,kind,text,sent_at,deliver_at) VALUES(?,?,?,?,?,?)",
         (actor["id"], "earth", "emergency", f"EMERGENCY opened on {ms['day_label']} at {LOCATIONS[ms['location']]['name']}.",
          time.time(), time.time() + delay))
    return _emergency(eid)


class EmergencyEvent(BaseModel):
    text: Optional[str] = None
    protocol: Optional[str] = None
    patient: Optional[str] = None
    outcome: Optional[str] = None
    close: bool = False


@app.post("/api/emergencies/{eid}", tags=["guided response"])
def emergency_event(eid: int, body: EmergencyEvent, actor: dict = Depends(require_onboard)):
    e = _emergency(eid)
    audit.record(actor, "emergency.close" if body.close else "emergency.update", f"emergency:{eid}",
                 after={"protocol": body.protocol, "patient": body.patient, "outcome": body.outcome, "close": body.close,
                        "log_entry": bool(body.text)})  # the text of a log entry is not copied here
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
             (actor["id"], "earth", "report", report, time.time(), time.time() + delay))
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


def emergencies():
    return [_emergency(r["id"]) for r in db.q("SELECT id FROM emergencies ORDER BY id DESC LIMIT 20")]


@app.get("/api/emergencies", tags=["guided response"])
def emergencies_route(actor: dict = Depends(any_person)):
    return emergencies()


# ---------------------------------------------------------------- messages with communication delay
class MessageIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")  # the sender is the token's, never the body's
    recipient: str = Field(min_length=1, max_length=60)
    text: str = Field(min_length=1, max_length=1000)


def _sender_of(actor: dict) -> str:
    """Who a message is from: the crew id for a crew member or the crew medical officer, the ground id for a flight surgeon or MCC."""
    if actor["role"] == "bootstrap":
        raise HTTPException(403, "Register an MCC account before sending messages")
    return actor["id"]


@app.post("/api/messages", tags=["messages"])
def send_message(body: MessageIn, v: dict = Depends(viewer)):
    """Send a message. The sender is whoever the token says: send one token only to speak for that person."""
    if v["actor"] is None:
        raise HTTPException(401, "sign-in required")
    sender = _sender_of(v["actor"])
    audit.record(v["actor"], "message.send", f"{sender}->{body.recipient}", after={"chars": len(body.text)})  # the text stays in messages
    ms = mission.state()
    delay = LOCATIONS[ms["location"]]["delay_s"] / settings.delay_speedup
    now = time.time()
    db.x("INSERT INTO messages(sender,recipient,kind,text,sent_at,deliver_at) VALUES(?,?,?,?,?,?)",
         (sender, body.recipient, "text", body.text, now, now + delay))
    return messages(None, v)


@app.get("/api/messages", tags=["messages"])
def messages_route(crew_id: Optional[str] = None, actor: dict = Depends(any_person), v: dict = Depends(viewer)):
    return messages(crew_id, v)


def messages(crew_id: Optional[str] = None, v: Optional[dict] = None):
    now = time.time()
    rows = db.q("SELECT * FROM messages ORDER BY id DESC LIMIT 40")
    # Private to the people in the message and the medical team: advice and alerts go to the medical officer, a briefing
    # carries the sender's own health facts to Earth.
    private = ("advice", "alert", "alert_earth", "briefing", "emergency", "report", "security")
    rows = [r for r in rows if r["kind"] not in private or (v and (v["medical"] or (v["me"] & {r["sender"], r["recipient"]})))]
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
    return nasa.space_weather(dose.active_event(ms["day"], ms["location"]))


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


@app.post("/api/suggestions/{crew_id}/{sid}/dismiss", tags=["assistant"])
def suggestion_dismiss(crew_id: str, sid: str, v: dict = Depends(viewer)):
    """Hide a suggestion for today and remember the choice: the ranking learns from it (assistant/suggestions.py)."""
    _crew(crew_id)
    if v["id"] != crew_id:
        raise HTTPException(403, "suggestions are for the astronaut only")
    try:
        return suggestions.dismiss(crew_id, sid)
    except ValueError as e:
        raise HTTPException(404, str(e))


@app.post("/api/briefings", tags=["assistant"])
def briefing_new(body: BriefingIn, v: dict = Depends(viewer)):
    _crew(body.crew_id)
    require_self(body.crew_id, v)
    return briefing.build(body.crew_id)


@app.post("/api/briefings/{bid}/approve", tags=["assistant"])
def briefing_approve(bid: int, v: dict = Depends(viewer)):
    """The astronaut approves their own briefing before it is queued for Earth. Nobody else can."""
    try:
        b = briefing.get(bid)
    except LookupError:
        raise HTTPException(404, "no such briefing")
    if v["id"] != b["crew_id"]:
        raise HTTPException(403, "only the astronaut approves their briefing")
    audit.record(v["actor"], "briefing.approve", f"briefing:{bid}", after={"crew_id": b["crew_id"]})
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


@app.put("/api/medical/care-sensitivity", tags=["medical"])
def put_care_sensitivity(body: CareSensitivityIn, actor: dict = Depends(require_medical)):
    """How much tighter a patient's thresholds are during the care window after an emergency (1 = no change). Every change is a
    new version in `medical_settings_history`; the earlier ones stay."""
    before = care.sensitivity()
    v = audit.set_versioned("care_sensitivity", {"factor": body.factor}, actor)
    audit.record(actor, "medical.care_sensitivity", "settings:care_sensitivity", before=before, after={"factor": body.factor, "version": v})
    return care.sensitivity()


@app.get("/api/medical/care-sensitivity", tags=["medical"], dependencies=[Depends(require_medical)])
def get_care_sensitivity():
    return care.sensitivity()


class ExerciseAdjustIn(BaseModel):
    max_pct: int = Field(ge=0, le=50)
    level1: int = Field(ge=0, le=50)
    level2: int = Field(ge=0, le=50)


@app.put("/api/medical/exercise-adjust", tags=["medical"])
def put_exercise_adjust(body: ExerciseAdjustIn, actor: dict = Depends(require_medical)):
    """How much the day's exercise may be lightened while the fatigue risk is up. Never above max_pct. Versioned like every setting."""
    before = goals.exercise_adjust()
    new = {"max_pct": body.max_pct, "by_level": {"1": body.level1, "2": body.level2}}
    v = audit.set_versioned("exercise_adjust", new, actor)
    audit.record(actor, "medical.exercise_adjust", "settings:exercise_adjust", before=before, after={**new, "version": v})
    return goals.exercise_adjust()


@app.get("/api/medical/exercise-adjust", tags=["medical"], dependencies=[Depends(require_medical)])
def get_exercise_adjust():
    return goals.exercise_adjust()


class ThresholdsIn(BaseModel):
    watch: float = Field(ge=0.5, le=4)
    act: float = Field(ge=1, le=5)


@app.put("/api/medical/thresholds", tags=["medical"])
def put_thresholds(body: ThresholdsIn, actor: dict = Depends(require_medical)):
    if body.act <= body.watch:
        raise validation.FieldError("act", f"Act ({body.act}) must be above watch ({body.watch})")
    before = health.thresholds()
    v = audit.set_versioned("thresholds", {"watch": body.watch, "act": body.act}, actor)  # a new version; the earlier ones stay
    audit.record(actor, "medical.thresholds", "settings:thresholds", before=before, after={"watch": body.watch, "act": body.act, "version": v})
    return health.thresholds()


@app.get("/api/medical/settings-history", tags=["medical"], dependencies=[Depends(require_medical)])
def settings_history(key: Optional[str] = None):
    """Every version of the medical settings (thresholds, care sensitivity, exercise adjustment), oldest first. The last one is current."""
    return audit.history(key)


class MedGoalIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    who: str
    area: str = Field(pattern="^(physical|mental)$")
    title: str = Field(min_length=3, max_length=120)
    why: str = Field(default="Prescribed by the medical team.", max_length=200)
    days: int = Field(default=7, ge=1, le=60)


@app.post("/api/medical/goals", tags=["medical"])
def add_med_goal(body: MedGoalIn, actor: dict = Depends(require_medical)):
    if body.who != "all" and body.who not in CREW_BY_ID:
        raise validation.FieldError("who", "Pick a crew member or the whole crew")
    day = mission.state()["day"]
    gid = db.x("INSERT INTO medical_goals(who,area,title,why,xp,from_day,to_day,created_at) VALUES(?,?,?,?,?,?,?,?)",
               (body.who, body.area, body.title, body.why, 0, day, day + body.days - 1, time.time()))
    audit.record(actor, "medical.goal_add", f"medical_goal:{gid}", after={"who": body.who, "area": body.area, "from_day": day, "to_day": day + body.days - 1})
    return med_goals()


@app.get("/api/medical/goals", tags=["medical"], dependencies=[Depends(require_medical)])
def med_goals(include_voided: bool = False):
    """The goals the medical team prescribed. A voided goal is kept (with who voided it and why) and shown only on request."""
    return db.q("SELECT * FROM medical_goals " + ("" if include_voided else "WHERE voided_at IS NULL ") + "ORDER BY id DESC")


class VoidIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    reason: str = Field(min_length=3, max_length=200)


@app.delete("/api/medical/goals/{gid}", tags=["medical"])
def del_med_goal(gid: int, body: Optional[VoidIn] = Body(None), actor: dict = Depends(require_medical)):
    """Void a goal. Health records are never deleted: the goal stays, marked `voided_at`, `voided_by` and `void_reason`, and the
    crew no longer sees it. A reason in the body ({"reason": "..."}) is required (422 without it)."""
    if body is None:
        raise validation.FieldError("reason", "Reason is required")
    rows = db.q("SELECT * FROM medical_goals WHERE id=?", (gid,))
    if not rows:
        raise HTTPException(404, "no such goal")
    if rows[0]["voided_at"]:
        raise HTTPException(409, "that goal is already voided")
    at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    db.x("UPDATE medical_goals SET voided_at=?, voided_by=?, void_reason=? WHERE id=?", (at, actor["id"], body.reason, gid))
    audit.record(actor, "medical.goal_void", f"medical_goal:{gid}", before={"who": rows[0]["who"], "area": rows[0]["area"], "title": rows[0]["title"]},
                 after={"voided_at": at, "reason": body.reason})
    return med_goals()


# ---------------------------------------------------------------- audit trail
def _audit_reader(authorization: Optional[str] = Header(None), x_canary_control: Optional[str] = Header(None)) -> dict:
    """Who may read the audit trail: an MCC account (health values redacted) or a flight surgeon (everything)."""
    ctl, med = _control_actor(x_canary_control), _medical_actor(authorization)
    if med and med["role"] == "flight_surgeon":
        return {**med, "redacted": False}
    if ctl and ctl["role"] == "mcc":
        return {**ctl, "redacted": True}
    raise HTTPException(401 if not (ctl or med) else 403, "audit trail: sign in as flight surgeon or MCC" if not (ctl or med) else "only a flight surgeon or an MCC account reads the audit trail")


@app.get("/api/audit", tags=["audit"])
def get_audit(limit: int = 50, before_id: Optional[int] = None, reader: dict = Depends(_audit_reader)):
    """The audit trail, newest first, `limit` entries (max 200) from `before_id` back; `next` is the `before_id` of the following page.
    Canary Control sees the same entries with any health value (keys value, values, readings, vitals, log) redacted."""
    return audit.entries(limit, before_id, reader["redacted"])


@app.get("/api/audit/verify", tags=["audit"])
def verify_audit(reader: dict = Depends(_audit_reader)):
    """Walk the hash chain: {ok, broken_at} with the id of the first entry that was altered or removed."""
    broken = audit.verify()
    return {"ok": broken is None, "broken_at": broken}


# ---------------------------------------------------------------- alert events
def _alert_viewer(x_canary_viewer: Optional[str] = Header(None), authorization: Optional[str] = Header(None),
                  x_canary_control: Optional[str] = Header(None)) -> dict:
    """{actor, scope}: `all` (crew medical officer, flight surgeon), `own` (a crew member), `ids` (Canary Control: no values)."""
    crew, med, ctl = _crew_actor(x_canary_viewer), _medical_actor(authorization), _control_actor(x_canary_control)
    if med:
        return {"actor": med, "scope": "all"}
    if crew:
        return {"actor": crew, "scope": "all" if crew["role"] == "cmo" else "own"}
    if ctl and ctl["role"] == "mcc":
        return {"actor": ctl, "scope": "ids"}
    raise HTTPException(401, "sign-in required")


@app.get("/api/alerts/events", tags=["alerts"])
def alert_events(open_only: bool = False, limit: int = 100, who: dict = Depends(_alert_viewer)):
    """Stored alert events, newest first. The crew medical officer and flight surgeons see every event with what was evaluated; a crew
    member sees their own; Canary Control sees who, which alert, level, times and acknowledgement, never a value."""
    own = who["actor"]["id"] if who["scope"] == "own" else None
    evs = notify.events(own, open_only, max(1, min(limit, 500)))
    return {"events": [notify.event_dict(e, who["scope"] != "ids") for e in evs], "rules_version": notify.RULES_VERSION,
            "escalate_after_s": notify.escalate_after_s()}


def _acker(x_canary_viewer: Optional[str] = Header(None), authorization: Optional[str] = Header(None)) -> dict:
    """The officer on board (medical console or crew sign-in) or a flight surgeon, who may acknowledge an alert."""
    for a in (_medical_actor(authorization), _crew_actor(x_canary_viewer)):
        if a and a["role"] in notify.ACK_ROLES:
            return a
    raise HTTPException(401 if not (_medical_actor(authorization) or _crew_actor(x_canary_viewer)) else 403,
                        "sign in as the crew medical officer or a flight surgeon" if not (_medical_actor(authorization) or _crew_actor(x_canary_viewer))
                        else "only the crew medical officer or a flight surgeon acknowledges an alert")


@app.post("/api/alerts/events/{event_id}/ack", tags=["alerts"])
def alert_event_ack(event_id: int, actor: dict = Depends(_acker)):
    """Acknowledge an alert event. Stops its escalation. Recorded with who and when, and in the audit trail."""
    ev = notify.acknowledge(event_id, actor)
    if ev is None:
        raise HTTPException(404, "no such alert event")
    return notify.event_dict(ev)


# ---------------------------------------------------------------- mission overview (public) and Canary Control (Mission Control)
@app.get("/api/mission/overview", tags=["mission"])
def mission_overview_route(v: dict = Depends(viewer)):
    """General information about the mission and the crew as a whole: no health data. Nationality, agency and flight history
    are shown only to someone signed in."""
    return mission_overview(detail=v["actor"] is not None)


PERSONAL_OVERVIEW = ("nationality", "agency", "flights", "days_in_space")


def mission_overview(detail: bool = True):
    ms = mission.state()
    info = registry.mission_info() or {}
    p = plan.get()
    launch = date.fromisoformat(registry.launch_date())
    dest = next((l for l in reversed(p["legs"]) if l["location"] not in ("earth", "rocket")), p["legs"][-1])
    crew = [{**{k: c[k] for k in ("id", "name", "role", "initials", "home")},
             **{k: RECORDS.get(c["id"], {}).get(k) for k in ("nationality", "agency", "languages", "flights", "days_in_space")
                if detail or k not in PERSONAL_OVERVIEW}}
            for c in CREW]
    return {"registered": registry.registered(), "callsign": info.get("callsign"), "name": p["name"],
            "launch_date": launch.isoformat(), "today_date": (launch + timedelta(days=ms["day"])).isoformat(),
            "destination": LOCATIONS[dest["location"]]["name"], "flight_days": p["legs"][-1]["end"] + 1,
            "legs": p["legs"], "mission": ms, "crew": crew}


def _earth_ops(ops: dict) -> dict:
    """Earth follows the operational status only: why a person is restricted (the care window after an emergency) stays
    with the person and the medical team."""
    return {k: v for k, v in ops.items() if k in ("key", "label", "level")}


def _career() -> dict:
    """The largest projected career dose among the crew (what they carry in plus the plan's mission dose) against the limit."""
    end = dose.curve(None, mission.state()["day"])[-1] if CREW else 0.0
    peak = max((standards.prior_dose(c["id"])["msv"] + end for c in CREW), default=0.0)
    return {"mission_msv": end, "projected_max_msv": round(peak, 1), "limit_msv": CAREER_LIMIT_MSV}


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
            "waiver": (registry.mission_info() or {}).get("waiver"), "career": _career(), "ground": registry.ground(),
            "ridge": privacy.ridge(ms["location"], ms["storm"], ms["day"]), "warnings": [{k: a[k] for k in ("title", "todo")} for a in env],
            "dose": health.dose(ms), "emergencies": emergencies()[:5]}


def _register_options() -> dict:
    return {"presets": {k: v["name"] for k, v in plan.PRESETS.items()},
            "rover_presets": [k for k in plan.PRESETS if plan.has_rover(k)], "iss_dose_msv_per_day": LOCATIONS["iss"]["dose_rate"],
            # the itinerary each profile gives, with and without its rover leg, for the review step
            "itineraries": {k: {"rover": plan.preset_legs(k, True), "plain": plan.preset_legs(k, False)} for k in plan.PRESETS},
            # the mission dose of each itinerary, so the review step can show the projected career dose and ask for the waiver
            "mission_dose_msv": {k: {"rover": round(dose.legs_dose(plan.preset_legs(k, True)), 1), "plain": round(dose.legs_dose(plan.preset_legs(k, False)), 1)} for k in plan.PRESETS},
            "career_limit_msv": CAREER_LIMIT_MSV}


@app.get("/api/control/register-options", tags=["control"], dependencies=[Depends(require_control)])
def control_register_options():
    """What the registration form needs: the mission profiles, their itineraries and mission doses, the career limit."""
    return _register_options()


@app.get("/api/control/demo", tags=["control"], dependencies=[Depends(demo_only), Depends(require_control)])
def control_demo():
    """Demo only: what the 'fill with the demo crew' button puts in the form."""
    form = data.demo_form()
    return {"crew": form["crew"], "ground": form["ground"], "mission": form["mission"], **_register_options()}


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
    seat: Optional[str] = Field(default=None, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,19}$")  # the person's id; left out, a generated c-xxxxxx
    cmo: Optional[bool] = None  # the crew medical officer; left out, the role text decides ("medical officer" or "CMO")
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
    dose_waiver: bool = False  # the risk-acceptance waiver, required when a projected career dose passes the NASA limit

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


class GroundIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    id: Optional[str] = Field(default=None, pattern=r"^g-[A-Za-z0-9_-]{1,17}$")  # left out, a generated g-xxxxxx
    name: str = Field(min_length=2, max_length=60)
    role: str = Field(pattern="^(flight_surgeon|mcc)$")
    pin: str = Field(pattern=r"^\d{4}$")


class RegisterIn(BaseModel):
    crew: List[SeatIn]  # one to six people (checked in _check_registration, which answers on the `crew` field)
    mission: MissionRegIn
    ground: List[GroundIn] = []  # flight surgeons and MCC accounts; at least one MCC (checked in _check_registration)


WAIVER_TEXT = "Projected career dose exceeds the NASA limit (NASA-STD-3001 Vol 1, 4.2.10); a risk-acceptance waiver is required."


def _check_registration(body: RegisterIn, ids: List[str]) -> None:
    """The rules that need more than one field: one to six people, the profile exists, ids and PINs differ between people, ages at
    launch, one crew medical officer, at least one MCC account, and the dose waiver when a career dose would pass the limit."""
    errs: List[dict] = []
    if not 1 <= len(body.crew) <= registry.MAX_CREW:
        errs.append({"field": "crew", "message": f"Register between 1 and {registry.MAX_CREW} people"})
    if body.mission.preset not in plan.PRESETS:
        errs.append({"field": "mission.preset", "message": "Mission profile must be one of: " + ", ".join(plan.PRESETS)})
    elif body.mission.rover and not plan.has_rover(body.mission.preset):
        errs.append({"field": "mission.rover", "message": f"{plan.PRESETS[body.mission.preset]['name']} has no rover leg; the rover is for the Moon and Mars profiles"})
    launch = date.fromisoformat(body.mission.launch_date)
    seen: dict = {}
    seen_id: dict = {}
    cmos = [i for i, p in enumerate(body.crew) if (p.cmo if p.cmo is not None else bool(registry.CMO_WORDS.search(p.role)))]
    for i in cmos[1:]:
        errs.append({"field": f"crew.{i}.cmo", "message": f"Only one crew medical officer: person {cmos[0] + 1} already is one"})
    for i, p in enumerate(body.crew):
        if ids[i] in registry.RESERVED_IDS or ids[i].startswith(registry.GROUND_PREFIX):
            errs.append({"field": f"crew.{i}.seat", "message": f"ID {ids[i]} is reserved; pick another"})
        elif ids[i] in seen_id:
            errs.append({"field": f"crew.{i}.seat", "message": f"ID is already used by person {seen_id[ids[i]] + 1}; each person needs their own"})
        seen_id.setdefault(ids[i], i)
        age = validation.age_on(date.fromisoformat(p.dob), launch)
        if not SEAT_AGE[0] <= age <= SEAT_AGE[1]:
            errs.append({"field": f"crew.{i}.dob", "message": f"Date of birth gives an age of {age} at launch; it must be between {SEAT_AGE[0]} and {SEAT_AGE[1]}"})
        if p.pin in seen:
            errs.append({"field": f"crew.{i}.pin", "message": f"PIN is already used by person {seen[p.pin] + 1}; each person needs their own"})
        seen.setdefault(p.pin, i)
    gseen: dict = {}
    gids: dict = {}
    if not any(g.role == "mcc" for g in body.ground):
        errs.append({"field": "ground", "message": "Register at least one MCC account for Canary Control"})
    for i, g in enumerate(body.ground):
        if g.pin in gseen:
            errs.append({"field": f"ground.{i}.pin", "message": f"PIN is already used by ground account {gseen[g.pin] + 1}; each account needs its own"})
        gseen.setdefault(g.pin, i)
        if g.id and g.id in gids:
            errs.append({"field": f"ground.{i}.id", "message": f"ID is already used by ground account {gids[g.id] + 1}"})
        if g.id:
            gids.setdefault(g.id, i)
    if body.mission.preset in plan.PRESETS and not body.mission.dose_waiver:
        rover = plan.has_rover(body.mission.preset) if body.mission.rover is None else bool(body.mission.rover)
        check = dose.career_check([standards.prior_dose_of(p.model_dump())["msv"] for p in body.crew], plan.preset_legs(body.mission.preset, rover))
        if check["over"]:
            errs.append({"field": "mission.dose_waiver", "message": WAIVER_TEXT})
    if errs:
        raise validation.ValidationFailure(errs)


@app.post("/api/control/register", tags=["control"])
def control_register(body: RegisterIn, actor: dict = Depends(require_control)):
    """Register the crew (one to six people), the ground accounts and the mission, then start the mission clock from the
    beginning. PINs are stored hashed. Once a mission is registered it is locked: this answers 409 until the demo is reset."""
    _locked()
    ids = registry.assign_ids([s.seat for s in body.crew], registry.used_ids())
    _check_registration(body, ids)
    audit.record(actor, "mission.register", "registry", after={"crew": len(body.crew), "ground": len(body.ground), "preset": body.mission.preset,
                                                                  "launch_date": body.mission.launch_date})  # no PINs, no medical records
    crew = [{**s.model_dump(), "seat": i} for s, i in zip(body.crew, ids)]
    rover = plan.has_rover(body.mission.preset) if body.mission.rover is None else bool(body.mission.rover)
    waiver = {"waiver": {"accepted": True, "by": actor["id"], "at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}} if body.mission.dose_waiver else {}
    info = {k: v for k, v in body.mission.model_dump().items() if k != "dose_waiver"}
    try:
        registry.register(crew, {**info, "rover": rover, **waiver}, [g.model_dump() for g in body.ground])
    except ValueError as e:
        raise HTTPException(400, str(e))
    first = data.scenes()[:1]  # the clock restarts where the story began, if there was one
    data.drop_package_story()  # the scenes and storms of a loaded package are about other people
    plan.use_preset(body.mission.preset, rover)
    plan.save({**plan.get(), "name": body.mission.name}, body.mission.preset)
    if first:
        mission.set_day(first[0]["day"])
    return control_overview()


@app.post("/api/control/demo-data", tags=["control"])
def control_demo_data(_demo: None = Depends(demo_only), actor: dict = Depends(require_control)):
    """Demo only: use the demo data: replace everything with the bundled demo mission (crew, ground accounts, itinerary, readings,
    goal history, space events and the demo story), the same state as a fresh start. Only while nothing is registered."""
    _locked()
    _start_over(settings.mission_package or DEMO_PACKAGE)
    audit.record(actor, "demo.data", "database", after={"package": settings.mission_package or DEMO_PACKAGE})
    return control_overview()


# ---------------------------------------------------------------- data entry points
# Sensors, wearables and labs send readings with a key; Mission Control adds space events and imports mission packages.
# All of them end in domain/data.py, which validates everything first and writes in one transaction.
MAX_OBS_BATCH = 5000
MAX_OBS_BYTES = 2_000_000


def require_ingest(x_canary_key: Optional[str] = Header(None)) -> dict:
    """The device behind the X-Canary-Key header: `{id, crew_id}` of an active device, or of `legacy` (the shared CANARY_INGEST_KEY,
    demo mode only). The key is never logged and never returned."""
    if not devices.legacy_on() and not devices.ever_registered():
        raise HTTPException(503, "Ingest is off")
    dev = devices.authenticate(x_canary_key)
    if dev is None:
        raise HTTPException(401, "A valid X-Canary-Key is required")
    return dev


def _ingest_now() -> datetime:
    """The 'now' a reading's time is checked against: UTC in flight, the mission clock in the demo (naive UTC either way)."""
    if settings.mode == "flight":
        return mission._now().replace(tzinfo=None)
    h, m = mission.mission_time().split(":")
    return datetime(mission.mission_date().year, mission.mission_date().month, mission.mission_date().day, int(h), int(m))


async def _read_limited(request: Request, limit: int) -> bytes:
    """The request body, refusing (413) anything over `limit` bytes before it is parsed: by Content-Length, and again while streaming."""
    try:
        declared = int(request.headers.get("content-length") or 0)
    except ValueError:
        raise HTTPException(400, "bad Content-Length")
    if declared > limit:
        raise HTTPException(413, f"The request is too large (limit {limit // 1_000_000} MB)")
    chunks, size = [], 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > limit:
            raise HTTPException(413, f"The request is too large (limit {limit // 1_000_000} MB)")
        chunks.append(chunk)
    return b"".join(chunks)


def _ingest(rows: list, device: dict) -> dict:
    res = data.add_observations(rows, device, _ingest_now(), settings.mode == "flight")
    audit.record({"id": device["id"], "role": "device"}, "observations.ingest", f"device:{device['id']}",
                 after={"rows": len(rows), "accepted": res["accepted"], "duplicates": res["duplicates"], "corrected": res["corrected"]})  # counts, never values
    opened, failed = 0, False
    who = [c["id"] for c in CREW] if CABIN in res["crew"] else [c for c in res["crew"] if c in CREW_BY_ID]
    if who:  # the evaluation runs now, so a critical reading reaches the medical officer within this request
        try:
            opened = notify.run(mission.state(), who)["opened"]
        except Exception:  # noqa: BLE001 (the readings are stored; the next sync catches up)
            logging.getLogger("canary").exception("evaluation after ingest")
            failed = True
    return {"accepted": res["accepted"], "duplicates": res["duplicates"], "corrected": res["corrected"], "alerts_opened": opened,
            **({"evaluation_failed": True} if failed else {})}


@app.post("/api/observations", tags=["data"])
async def post_observations(request: Request, device: dict = Depends(require_ingest), idempotency_key: Optional[str] = Header(None)):
    """A batch of readings: {"rows": [{crew_id, indicator, value, unit, measured_at | day, origin, method, source, note,
    supersedes, reason}]}. `origin` is required (device, manual, lab, simulated or sample). Up to 5000 rows and 2 MB. One bad row
    refuses the whole batch (422, `rows.N.field`) and nothing is stored; a changed value for a stored reading is a 409 (send
    `supersedes` and `reason` to correct it). Send an `Idempotency-Key` header and a retry with the same body returns the first answer.
    The answer is {accepted, duplicates, corrected, alerts_opened}: the evaluation has already run."""
    raw = await _read_limited(request, MAX_OBS_BYTES)
    try:
        body = json.loads(raw)
    except ValueError:
        raise validation.FieldError("body", "Send JSON like {\"rows\": [...]}")
    rows = body.get("rows") if isinstance(body, dict) else None
    if not isinstance(rows, list):
        raise validation.FieldError("rows", "Send {\"rows\": [...]}")
    if len(rows) > MAX_OBS_BATCH:
        raise validation.FieldError("rows", f"At most {MAX_OBS_BATCH} readings per request")
    digest = hashlib.sha256(raw).hexdigest()
    ikey = (idempotency_key or "").strip()[:128]
    if ikey:
        old = db.q("SELECT body_hash,response FROM idempotency WHERE device_id=? AND key=?", (device["id"], ikey))
        if old:
            if old[0]["body_hash"] != digest:
                raise HTTPException(409, "This Idempotency-Key was already used with a different body")
            return json.loads(old[0]["response"])
    res = await run_in_threadpool(_ingest, rows, device)
    if ikey:
        db.x("INSERT OR REPLACE INTO idempotency(device_id,key,body_hash,response,created_at) VALUES(?,?,?,?,?)", (device["id"], ikey, digest, json.dumps(res), time.time()))
    return res


class DeviceIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=60)
    kind: str = "sensor"
    crew_id: Optional[str] = None


@app.post("/api/control/devices", tags=["control"])
def control_add_device(body: DeviceIn, actor: dict = Depends(require_control)):
    """Register a device that sends readings. The answer carries its key once; only a hash is stored. A device bound to a crew member
    (`crew_id`) can send only that person's readings."""
    if body.kind not in devices.KINDS:
        raise validation.FieldError("kind", "Kind must be one of: " + ", ".join(devices.KINDS))
    if body.crew_id is not None and body.crew_id not in CREW_BY_ID:
        raise validation.FieldError("crew_id", "Pick a registered crew member")
    d = devices.create(body.name, body.kind, body.crew_id)
    audit.record(actor, "device.create", f"device:{d['id']}", after={"name": d["name"], "kind": d["kind"], "crew_id": d["crew_id"]})  # never the key
    return d


@app.get("/api/control/devices", tags=["control"], dependencies=[Depends(require_control)])
def control_devices():
    """Every device with when it last sent a reading. Never a key."""
    return {"devices": devices.listing(), "legacy_key": devices.legacy_on()}


@app.post("/api/control/devices/{device_id}/revoke", tags=["control"])
def control_revoke_device(device_id: str, actor: dict = Depends(require_control)):
    d = devices.revoke(device_id)
    if d is None:
        raise HTTPException(404, "no such device")
    audit.record(actor, "device.revoke", f"device:{device_id}")
    return d


@app.get("/api/scenes", tags=["data"])
def get_scenes():
    """The guided demo's bookmarks (a day, a place, a person, a sentence). Not health data. None in flight mode."""
    return data.scenes() if settings.mode == "demo" else []


@app.post("/api/control/space-events", tags=["control"])
def control_add_space_event(body: dict = Body(...), actor: dict = Depends(require_control)):
    """One space-weather event: kind, start_day, end_day, locations, extra_dose_msv (0 to 2000), origin, source, note."""
    res = data.add_space_event(body)
    audit.record(actor, "space_event.add", f"space_event:{res.get('id') if isinstance(res, dict) else ''}",
                 after={k: body.get(k) for k in ("kind", "start_day", "end_day", "locations", "extra_dose_msv")} if isinstance(body, dict) else None)
    return res


@app.put("/api/control/clock", tags=["control"])
def control_clock(body: dict = Body(...), _demo: None = Depends(demo_only), actor: dict = Depends(require_control)):
    """Move the mission clock: {"date": "YYYY-MM-DD", "time": "HH:MM"} for a simulated date (time is optional), or
    {"real": true} to follow today's date in UTC again. 422 {field, message} on bad input. Runs the day sync at once. Demo only."""
    if not isinstance(body, dict):
        raise validation.FieldError("body", "Send {\"date\": \"2035-10-31\", \"time\": \"12:00\"} or {\"real\": true}")
    real = body.get("real")
    if real is not None and not isinstance(real, bool):
        raise validation.FieldError("real", "real must be true or false")
    before = mission.clock()
    mission.set_clock(body.get("date"), body.get("time"), bool(real))
    audit.record(actor, "mission.clock", "mission", before=before, after=mission.clock())
    mission.safe_sync_day(force=True)
    return mission.state()


@app.get("/api/control/space-events", tags=["control"], dependencies=[Depends(require_control)])
def control_space_events():
    return {"events": data.events()}


@app.get("/api/control/data-status", tags=["control"], dependencies=[Depends(require_control)])
def control_data_status():
    """What Mission Control may know about the data: is ingest on, which package, how much of each kind, and when each
    person's indicator last arrived. Counts and dates only: no values and nothing about anyone's health."""
    count = lambda t: db.q(f"SELECT COUNT(*) n FROM {t}")[0]["n"]  # noqa: E731 (fixed table names)
    readings = db.q("SELECT crew_id, indicator, MAX(day) last_day, MAX(received_at) last_received_at, COUNT(*) count "
                    "FROM observations WHERE superseded_by IS NULL GROUP BY crew_id, indicator ORDER BY crew_id, indicator")
    pkg = data.loaded_package()
    return {"ingest_configured": devices.legacy_on() or any(d["active"] for d in devices.listing()), "package": (pkg or {}).get("name"),
            "counts": {"observations": count("observations"), "goal_entries": count("goal_log"),
                       "events": count("space_events"), "scenes": count("scenes")},
            "readings": [{k: r[k] for k in ("crew_id", "indicator", "last_day", "last_received_at", "count")} for r in readings]}


def _multipart_files(content_type: str, raw: bytes) -> list:
    """(filename, bytes) of every file part of a multipart/form-data body (standard library, no extra dependency)."""
    from email import policy
    from email.parser import BytesParser
    msg = BytesParser(policy=policy.HTTP).parsebytes(b"Content-Type: " + content_type.encode("latin-1") + b"\r\n\r\n" + raw)
    if not msg.is_multipart():
        raise validation.FieldError("file", "Send a multipart upload with the files")
    return [(part.get_filename(), part.get_payload(decode=True) or b"") for part in msg.iter_parts() if part.get_filename()]


@app.post("/api/control/import", tags=["control"])
async def control_import(request: Request, actor: dict = Depends(require_control)):
    """Import a mission package: a multipart upload of a .zip or of CSV files named like the package files, or JSON
    {"package": "odyssey1-mars"} for a bundled one. Any error: 422 {"errors": [...]} and nothing is written.
    Once a mission is registered only readings, goal history and space events can be added (observations.csv, goal_log.csv,
    space_events.csv): a bundled package is refused (409) and a file that defines the mission (crew, ground, mission, legs,
    scenes) is a 422 that names it."""
    ctype = request.headers.get("content-type", "")
    try:
        if ctype.startswith("application/json"):
            try:
                body = await request.json()
            except ValueError:
                raise validation.FieldError("package", "Send JSON like {\"package\": \"odyssey1-mars\"}")
            name = body.get("package") if isinstance(body, dict) else None
            folder = data.package_dir(name)  # a name that is no bundled package is a 422 whatever the state
            _locked()  # a bundled package defines the whole mission: never over a registered one
            res = await run_in_threadpool(data.import_package, folder, name, True)
        elif ctype.startswith("multipart/form-data"):
            if int(request.headers.get("content-length") or 0) > data.MAX_UPLOAD_BYTES:
                raise validation.FieldError("file", "The upload is too large")
            raw = await request.body()
            parts = _multipart_files(ctype, raw)
            files = data.files_from_upload(parts)
            if registry.registered():
                shut = [n for n in files if n not in data.OPEN_FILES]
                if shut:
                    raise validation.ValidationFailure([{"field": "file", "message": f"{n} cannot change a registered mission"} for n in shut])
            res = await run_in_threadpool(data.import_package, files, data.upload_label(parts), False)
        else:
            raise HTTPException(415, "Send multipart/form-data (a zip or CSV files) or JSON {\"package\": \"name\"}")
    except validation.ValidationFailure as e:
        return JSONResponse(status_code=422, content={"detail": e.errors, "errors": e.errors, "accepted": {}})
    audit.record(actor, "data.import", "mission-data", after={"accepted": res.get("accepted"), "duplicates": res.get("duplicates")})  # counts only
    return {**res, "errors": []}


# ---------------------------------------------------------------- the web app (after `npm run build`)
mimetypes.add_type("model/gltf-binary", ".glb")
_dist = pathlib.Path(settings.frontend_dist)
if _dist.is_dir():
    app.mount("/assets", StaticFiles(directory=_dist / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        """A file of the built app, else index.html. A path that leaves dist (`..%2f`) is never served."""
        return FileResponse(spa_file(_dist, path))


def spa_file(dist: pathlib.Path, path: str) -> pathlib.Path:
    """The file under `dist` that `path` names, or dist/index.html when there is none or it would leave `dist`."""
    root = dist.resolve()
    f = (root / path).resolve()
    return f if path and f.is_file() and f.is_relative_to(root) else root / "index.html"
