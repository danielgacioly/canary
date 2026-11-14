# Canary

**A crew health system for when Earth is too far to answer.**
NASA Space Apps Challenge 2026 · *Create Health Monitoring Software for Astronauts on Space Missions*

For a century, miners carried a canary underground. The bird felt bad air before people did, and when it went quiet the miners knew to leave. A spacecraft is a sealed mine: radiation, isolation, distance, altered gravity and a closed cabin. On the way to Mars a question to the flight surgeon takes up to 24 minutes to arrive and as long to come back. Canary stays on board for that gap.

It compares every astronaut with **their own normal**, turns early warnings into **goals**, and **guides the crew step by step** when something goes wrong. Physical and mental health sit side by side, on a holographic body you can turn and click.

---

## Contents

1. [Run it](#run-it)
2. [What it does](#what-it-does)
3. [The demo story](#the-demo-story)
4. [Architecture](#architecture)
5. [The AI slot](#the-ai-slot)
6. [NASA data](#nasa-data)
7. [The 3D body](#the-3d-body)
8. [Project layout](#project-layout)
9. [API](#api)
10. [How it maps to the judging criteria](#how-it-maps-to-the-judging-criteria)
11. [What to build next](#what-to-build-next)
12. [Limits, honestly](#limits-honestly)
13. [Credits and licences](#credits-and-licences)

---

## Run it

Needs **Python 3.9+** and **Node 18+**.

```bash
make setup     # backend venv + npm install
make dev       # API on :8000 and web app on :5173
```

Open <http://localhost:5173>. The intro plays once, then **mission setup** (destination, how many days, the crew) and a short launch, and Canary opens on the **crew**: goals, hazards and crew missions, never anyone's health or status. To see your own health, enter your space under **My health**: tap your name and type your **4-digit PIN**. Setup shows again after **Reset demo** (About & data) or from the **Mission plan** page. The **Demo story** bar at the bottom walks through the six scenes and offers "Enter as …", which opens the PIN pad for the person each scene follows (it never skips the PIN).

Demo PINs (public, for the demo only): Helena `1001`, Kenji `1002`, Amara `1003`, Tomás `1004`; medical console `1961`.

Without `make`:

```bash
cd backend && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn canary.main:app --reload --port 8000
```

```bash
cd frontend && npm install && npm run dev
```

Other commands:

| Command | What it does |
| --- | --- |
| `make test` | 36 backend tests (alerts, story, mission plan and setup, goals, privacy, PINs and sessions, assistant guard, API) and the frontend type check |
| `make serve` | builds the web app and serves everything from one process on <http://localhost:8000> |
| `http://localhost:8000/docs` | interactive API documentation (OpenAPI) |
| Medical console PIN | `1961` (demo only, set `CANARY_MEDICAL_PIN` anywhere else; always exactly 4 digits) |

### Settings (environment variables)

| Variable | Default | Meaning |
| --- | --- | --- |
| `CANARY_DB` | `backend/canary.db` | SQLite file (created on start) |
| `CANARY_MEDICAL_PIN` | `1961` | PIN of the medical console (4 digits) |
| `CANARY_CREW_PINS` | `h:1001,k:1002,a:1003,t:1004` | default 4-digit PIN of each crew member's private space. A PIN changed in the app is stored salted and hashed (PBKDF2-SHA256) in the `settings` table and wins over this default until the demo is reset |
| `CANARY_TOKEN_SECRET` | random per start | signs medical and crew session tokens (set it to keep sessions across restarts) |
| `CANARY_DELAY_SPEEDUP` | `20` | communication delay runs this many times faster in the demo |
| `CANARY_LIVE_SPACE_WEATHER` | `0` | `1` also asks NASA DONKI for the last 30 days (falls back to the snapshot) |
| `NASA_API_KEY` | `DEMO_KEY` | key for api.nasa.gov |
| `CANARY_LLM_PROVIDER` | `none` | `none`, `anthropic` or `local` (see [The AI slot](#the-ai-slot)) |

---

## What it does

A sidebar with seven pages in three groups, **crew first**: the system always opens on the whole crew, and your own data sits behind your private space. Each page reads top to bottom like a dashboard: the most important thing first, details further down.

| Page | What you see |
| --- | --- |
| **Intro** | Four beats of the canary story over a starfield while the body assembles, then mission setup |
| **Setup** (`/setup`, first run) | Full-screen, four steps: pick the destination (space station, Moon, Mars with gravity, Earth reply delay and radiation), set the length of every part with a live timeline that re-proportions as you type, meet the crew, review and launch (a 3-2-1 over the timeline). The defaults reproduce the three presets exactly; Mars can add a return trip. "Use the demo story" takes the Mars preset |
| **Crew** (home) | The four astronauts as neutral dots (no status colour), today's routine and shared streak, outside-activity status for the place, hazards for everyone, crew missions and the **Who sees what** table. No status, no scores, no vitals, no averages. A dot opens that person's public card |
| **My health** (private) | Behind a gate: tap your name and enter your 4-digit PIN, Lock to leave (closing the tab also locks). A privacy bar says what the crew sees of you (only goal participation), your own medical status, who receives your alerts, and has the **Share data with the crew** switch and **Change PIN**. Then, top: the 3D body and, beside it, one sentence on how you are, up to three numbered steps and your Physical and Mental scores. Below: physical systems and mental facets as tiles (value, your normal, 14-day trend, status colour), then today's goals and the current mission leg. Click any part of the body or any tile and the top area becomes that system. |
| **My goals** (private) | Level, XP, streak and 7-day completion; physical and mental goals side by side; crew missions; patches |
| **Ranking** | Podium and weekly table by effort |
| **Mission plan** | The itinerary as a timeline, a day slider, what Canary changes at the selected place, the leg editor and **Run mission setup again** |
| **Space weather** | NASA DONKI storm (Kp) and Curiosity RAD dose on Mars |
| **Link to Earth** | Messages, briefings and reports with the real delay |

Always reachable: the **crew dots** and **Hold for emergency** (top right) opens Guided Response; **Where you are** (top left) simulates any place; the sidebar holds **Ask Canary**, **Medical console** (4-digit PIN) and **About & data**; the **demo bar** at the bottom drives the story.

### Who sees what

Canary follows the team's data-use draft: a visibility contract the crew agrees on day 0 (`backend/canary/domain/privacy.py`).

| Information | The astronaut | Medical team | The crew | Earth |
| --- | --- | --- | --- | --- |
| Raw data and history | Yes | Yes | Only if the astronaut shares | No |
| Personal risks and advice | Yes | Yes | No | No |
| Operational status (e.g. fit for EVA) | Yes | Yes | No | Via the medical team |
| Critical alert | Immediately | Immediately | No | Delayed briefing |
| Hazards and crew goals | Yes | Yes | Yes | Yes |

How the API enforces it:

- **Operational status is medical-only.** Diagnoses such as "Fit for all duties" or "Off critical tasks" are visible to the medical team and to the person themself in their private space. The crew never sees anyone's status; the Crew page shows only whether EVA is possible at all (environment) and says the medical team clears each person.
- **Entry is by PIN.** `POST /api/crew/{id}/session {"pin"}` returns a signed token `{id}.{exp}.{sig}` (HMAC-SHA256 over `crew:{id}:{exp}`, one hour). The web app keeps it in `sessionStorage` and sends it in the `X-Canary-Viewer` header; a bare id, a forged or an expired token is nobody (403 on private routes). Five wrong PINs in 60 seconds lock that person for a minute (429). `PUT /api/crew/{id}/pin` changes your PIN (needs your token and the current PIN). The medical console works the same way with its own PIN and a bearer token.
- `GET /api/crew/overview` is the only crew-wide view: participation (goals done today, streaks), hazards, crew missions. No status, indicators, scores or alerts, and no averages, because with four people an average gives individuals away.
- `GET /api/crew/{id}` answers the astronaut (session token), the medical team (bearer token) or, if the astronaut switched sharing on, the rest of the crew. Shared views drop personal alerts, advice and operational status.
- Goals, check-ins, Ask Canary and briefings answer only the astronaut and the medical team. `GET /api/crew` with full summaries is medical-only.
- Operational status (shown only to the person and the medical team) comes from personal alerts only: any act-level alert means off critical tasks; watch-level alerts that change what someone may do (pulse, pressure, oxygen, temperature, reaction time, space sickness, re-adaptation, Amsler) mean no EVA. Slow trends such as bone are followed in private. Storms are crew hazards, not personal status.
- If the medical officer is the patient, their alerts go to the substitute (the commander).

### Mission plan

A plan is a list of legs: place, first day, last day and what happens (day 0 is launch; negative days are pre-flight). Three presets ship with it: **Mars reference mission**, **Six months on the ISS** and **Lunar surface mission**, and any leg can be added, removed or edited.

Every rule that depends on where the crew is asks the plan (`backend/canary/domain/plan.py`), so saving a plan re-adapts the whole system:

| What changes | How |
| --- | --- |
| Gravity, radiation, communication delay, hospital distance | from the place of the current leg |
| Exercise and "look homeward" goals | per place (2 h on the station or in cruise, suited walks on Mars, cupola on the ISS…) |
| Alert rules | space sickness in the first 72 h of launch legs; re-adaptation in the first 30 days of partial gravity after a 0 g leg; no alerts before launch |
| Bone model | full loss rate in 0 g, about 40% in partial gravity, slow recovery on Earth, accumulated day by day along the plan |
| Mission dose | the daily dose of each place along the plan |
| Guided Response | step variants for 0 g, partial gravity or Earth, and place-specific shelters |
| Day label | L-30 before launch, Sol N on Mars counted from landing, Day N otherwise |

The slider jumps to any day; every screen follows. The demo story bar returns to the scripted scenes.

### Design rules

- Flat surfaces, no gradients, no glow, no glass. The hologram is the only luminous thing on screen.
- Colour means state: green on track, amber watch, red act. One accent colour (blue) for what you can press.
- Hierarchy by size, weight and space: one headline per screen, then the steps, then the details.
- Read top to bottom: the body and the verdict first, tiles next, details last. Clicking swaps the top area instead of opening more panels.
- Motion has a job: an intro that tells the story, and content that arrives in order when a page opens.

### The three ideas behind it

**Goals.** Personal goals for the body (exercise by place, water, vitals, mobility, calcium, Amsler grid) and the mind (sleep, reaction test, mood check-in, meditation or prayer, reading, crew time, films and music, calls home, looking homeward, journal). Crew missions are shared weekly targets (2,400 exercise minutes, 5 crew meals, 20 meditation sessions, book club, movie nights). XP, levels, streaks and nine mission patches.

**Warnings.** Each indicator is a z-score against the person's own pre-flight baseline. The medical team sets the thresholds. Cross-signal rules catch what single numbers miss: sleep + mood + reaction time together, high pulse + low water in the first 72 h, low pressure + high pulse back in gravity, a wavy Amsler grid, a solar particle event. Every warning says what it means, what to do now, and adds goals.

**Guided Response.** Not a panic button: a calm, deterministic guide. Protocols are data (`backend/canary/data/protocols.json`) with variants for 0 g, partial gravity and Earth, and for each place. Closing it adds follow-up goals for the patient and queues a report for Earth.

**The ranking counts effort, never vital signs.** It is the one place where individuals are compared, and only by participation. XP comes from goals done and check-ins sent. A hard day reported honestly earns the same as a good one, so nobody gains by hiding a symptom.

---

## The demo story

The bar at the bottom of every screen drives a six-scene story. Each step sets the mission day, the place and the suggested crew member.

| # | Scene | What to show |
| --- | --- | --- |
| 1 | **L-30, Earth** | Canary is learning everyone's normal. No alerts. |
| 2 | **Day 2, launch** | Tomás: fast pulse, little water. Space sickness alert with hydration goals. |
| 3 | **Day 147, Mars transit** | Helena: sleep, mood, focus and crew time slipping together. The brain is red on the body, the Mental tiles show the slide. Take the reaction test, or Ask why. |
| 4 | **Day 152, replay of 10 May 2024** | NASA DONKI's real storm. Everyone to the shelter, radiation protocol. |
| 5 | **Day 153, dinner** | Kenji's terminal. Tomás has a seizure: hold EMERGENCY, pick Seizure, follow the steps, close and report. Then see the follow-up goals and the report in the medical console. |
| 6 | **Sol 12 on Mars, replay of 20 May 2024** | Curiosity RAD measured 51× the normal dose. Gravity re-adaptation for everyone. |

---

## Architecture

**One Python API, modular inside, one SQLite file.** A spacecraft can't depend on a network or on a cluster of services, and a hackathon team can't maintain one. The only split worth designing for is *on board* versus *ground station*: same code, two deployments, synchronised over a delayed link.

```
 Browser (React + Three.js)                        frontend/
   │  HTTP /api   (Vite proxies in dev; FastAPI serves the build in prod)
   ▼
 Canary API (FastAPI, one process)                 backend/canary/
   ├─ domain/telemetry   TelemetrySource: SimulatedSource today, devices tomorrow
   ├─ domain/health      baseline z-scores, alert rules, body systems, readiness scores
   ├─ domain/goals       daily goals, XP, levels, streaks, patches, crew missions, ranking
   ├─ domain/privacy     who sees what: operational status (medical only), sharing, hazards, the day-0 contract
   ├─ domain/protocols   Guided Response bank, resolved by gravity and place
   ├─ domain/nasa        DONKI · Curiosity RAD · OSD-569 snapshot (+ optional live DONKI)
   ├─ domain/plan        mission plan: itinerary legs, presets, location by day
   ├─ domain/mission     mission clock, place, demo story
   ├─ assistant/         the AI slot: provider · knowledge · tools · guard · chat · briefing
   ├─ auth               PINs (hashed), crew session tokens, rate limit
   └─ main.py            routes, PIN sign-in for each private space and the medical console
   ▼
 SQLite                                            only what people do: check-ins, goals,
   (on board, offline)                             messages, emergencies, briefings, settings
```

### Decisions

| Decision | Why | Alternatives set aside |
| --- | --- | --- |
| One FastAPI process | Runs offline on board, one thing to deploy and test | Microservices: more failure points, no benefit at this size |
| SQLite | A single file, no server, survives with no network | Postgres: belongs on the ground station later |
| Telemetry behind `TelemetrySource` | Real devices plug in without touching alerts or goals | Hard-coding the simulator into the rules |
| Personal baseline (z-score) | Astronauts are fit outliers; population ranges miss their changes | Fixed clinical thresholds only |
| Protocols as JSON | The medical team can review and replace them without code | Protocols in code |
| No accounts for the crew, a 4-digit PIN per private space | A shared terminal in a cabin: a PIN is fast, and Guided Response needs no sign-in | Logins with passwords: friction in an emergency; trusting a plain id: anyone could open anyone's health |
| PIN + signed token for doctors | Only the medical team writes prescriptions and rules | Full identity system: out of scope for a prototype |
| AI only explains | Deterministic rules decide alerts and emergencies | Letting a model diagnose or triage |
| React + plain Three.js, no UI kit | Full control of the mission-console look and the hologram | Component libraries: generic look |

### How a number becomes an alert

```
reading(day)  ──►  recent = 60% today + 25% yesterday + 15% day before
                        │
baseline (pre-flight) ──┤  z = (recent − baseline) / personal spread
                        ▼
              level 0 / 1 / 2  by the medical team's thresholds (default 1.5σ / 2.5σ)
                        │
cross-signal rules ─────┤  e.g. sleep↓ + mood↓ + reaction↑  →  behavioural alert
                        ▼
         alert = { what it means, what to do now, goals added, sources }
                        │
                        ▼
   body system status  →  colour on the 3D body  →  physical / mental readiness score
```

---

## The AI slot

The assistant is **designed, wired and testable, but no model is connected.** Everything around the model exists, so plugging one in touches one class.

```
question ─► guard.precheck ─► tools (read-only) ─► LLMProvider ─► guard.validate_claims ─► log
              │ emergency → "hold EMERGENCY"          │ none connected → grounded rule-based answer
              │ diagnosis / dosing → refused          ▼
                                             {answer, claims:[{text, source_ids}]}
```

| File | Role |
| --- | --- |
| `assistant/providers.py` | `LLMProvider` interface. `NullProvider` (default), `AnthropicProvider` and `LocalProvider` are slots with a `TODO` |
| `assistant/knowledge.py` | The only knowledge allowed: body-system cards and protocols, each with an id. Small enough for a cached prompt, no vector database |
| `assistant/tools.py` | Read-only tools a model can call (`get_status`, `get_indicator`, `explain_system`, `get_protocol`, `list_goals`); each result carries source ids. `route()` is the rule-based stand-in for tool choice |
| `assistant/guard.py` | Sends emergencies to Guided Response, refuses diagnosis and doses, drops any claim citing a source the tools did not return, rejects briefing text with invented numbers |
| `assistant/chat.py` | Entry 1: an astronaut asks a question |
| `assistant/briefing.py` | Entry 2: one-page weekly briefing for the flight surgeon. Code computes the facts, the model only writes prose, the astronaut approves it before it is queued for Earth |

**To plug in a model:** implement `complete()` in `AnthropicProvider` (ground segment, needs a link; read `ANTHROPIC_API_KEY` from the environment, never commit it) or `LocalProvider` (on board, e.g. a small model through llama.cpp or Ollama), return the JSON shape in the module docstring, then run with `CANARY_LLM_PROVIDER=anthropic`. The guard and the tests stay the same.

Real-world parallel: NASA and Google are testing a Crew Medical Officer Digital Assistant (CMO-DA) as a proof of concept ([Google Cloud](https://cloud.google.com/blog/topics/public-sector/how-google-and-nasa-are-testing-ai-for-medical-care-in-space), [NASA NTRS](https://ntrs.nasa.gov/citations/20260001797)). Canary differs on purpose: it watches each person against their own normal, turns warnings into goals, guides first response deterministically, and its assistant explains without diagnosing.

---

## NASA data

| Source | What Canary uses | Where |
| --- | --- | --- |
| [DONKI](https://kauai.ccmc.gsfc.nasa.gov/DONKI/) space weather (api.nasa.gov) | 5 to 16 May 2024: 14 solar particle events, Kp up to 9, fast CMEs, linked flares | Story step 4, Mission page, storm alerts |
| [Curiosity RAD level 2](https://spdf.gsfc.nasa.gov/pub/data/aaa_planetary/msl/rad/cdf/obs-l2/) (PDS / SPDF) | Total dose rate at Gale crater: quiet 9 May 2024 (mean ≈ 164 µGy/day) vs storm 20 May 2024 (peak 8,378 µGy/day, about 51×) | Story step 6, Mission page |
| [OSDR OSD-569](https://osdr.nasa.gov/bio/repo/data/studies/OSD-569) Inspiration4 blood counts | Real lymphocyte curves across 7 time points, shown as each crew member's reference | Blood & immunity panel |
| [NASA HRP hazards and risks](https://www.nasa.gov/hrp/hazards/) | The five hazards (RIDGE) behind every body system | System cards, assistant knowledge |

The snapshot lives in `backend/canary/data/nasa_snapshot.json`, so the ship never needs a network. `data/prepare_nasa_data.py` rebuilds the same data from the original downloads (checked: identical output) (needs `numpy` and `cdflib`). With `CANARY_LIVE_SPACE_WEATHER=1` the API also queries DONKI live and falls back to the snapshot on any error.

---

## The 3D body

- **Shape:** the MakeHuman base mesh (CC0), converted by `tools/build_body_model.py` into `frontend/public/models/body.glb` (13,380 vertices, scaled to 1.75 m) and `joints.json` (125 joint centres). Every vertex is tagged with a surface region (head, torso, arm, hand, leg, foot) so regions can be picked and coloured.
- **Inside:** skeleton (vertebrae, ribs, sternum, pelvis, long bones, every finger and toe), brain, eyes, heart, lungs, liver, stomach, intestines, spleen, kidneys, bladder, arteries and nerves are built procedurally from the joints (`frontend/src/hologram/anatomy.ts`).
- **Look:** custom shaders (`materials.ts`): an iridescent fresnel shell with muscle striations and a scan line, glowing organs, light flowing along vessels and nerves, bloom, a holographic platform and particles. The body assembles from the feet up on load.
- **Meaning:** each body system takes its status colour (green / amber / red, pulsing when it needs action). The **Physical** lens shows organs and bones; the **Mental** lens dims the body to violet and lights the brain and nervous system. Click a part to focus the camera on it and open its panel.

| Body part | System | Data behind it |
| --- | --- | --- |
| Brain, head, nerves | Brain & mind | sleep, reaction time, mood, stress, time with crew |
| Eyes | Eyes & vision | Amsler grid check-ins (SANS screen) |
| Heart, arteries | Heart & circulation | resting pulse, blood pressure |
| Lungs | Lungs & breathing | blood oxygen |
| Skeleton | Bones | estimated bone density change |
| Arms, legs, hands, feet | Muscles | exercise minutes, grip strength |
| Liver, stomach, intestines | Gut & nutrition | fasting glucose |
| Kidneys, bladder | Kidneys & hydration | water |
| Spleen | Blood & immunity | temperature + NASA OSD-569 lymphocytes |
| Torso surface | Radiation exposure | mission dose vs career limit, storms |

---

## Project layout

```
backend/
  canary/
    main.py              routes and PIN sign-in
    auth.py              PINs (PBKDF2), crew session tokens, rate limit
    config.py            environment settings
    db.py                SQLite schema and helpers
    domain/              catalog, plan, telemetry, health, goals, privacy, protocols, nasa, mission
    assistant/           the AI slot
    data/                protocols.json, nasa_snapshot.json
  tests/test_canary.py   36 tests
  requirements.txt
frontend/
  src/
    api/                 typed client and response types
    state/session.tsx    mission, terminal user, refresh signal
    hologram/            scene, shaders, procedural anatomy, React wrapper
    components/          shell, People (neutral crew dots, PIN gate), PinPad, Stars, BodyView (body + observations), goals, charts, patches
    features/            Guided Response, Ask Canary, self-checks
    pages/               Intro, Setup, Crew (home), Astronaut (public card or shared view), Me (My health, private), Goals (private), Ranking, MissionPlan, Mission (space weather, link), Medical, About
    styles/app.css       design tokens and components
  public/models/         body.glb, joints.json
data/prepare_nasa_data.py
tools/build_body_model.py
Makefile
```

---

## API

Full, interactive documentation at `/docs`. The main routes:

| Route | Purpose |
| --- | --- |
| `GET /api/mission` · `PUT /api/mission` | Mission clock (story step or any day), place, current leg, `setup_done` |
| `GET /api/plan` · `PUT /api/plan` · `POST /api/plan/preset` | Mission plan: itinerary legs, presets |
| `POST /api/setup` | First-run mission setup: validates and saves the plan, marks setup done, restarts the story |
| `POST /api/crew/{id}/session` · `PUT /api/crew/{id}/pin` | Sign in with the 4-digit PIN (returns the session token) · change your PIN |
| `GET /api/crew/overview` | What everyone may see: participation, hazards, crew missions, the visibility contract. Never status |
| `GET /api/crew/{id}` · `PUT /api/crew/{id}/sharing` | One astronaut in full (self, medical team, or crew if shared; `ops` only for the first two) · the astronaut's share switch |
| `GET /api/crew` | Full health summary of everyone, with operational status (medical team only) |
| `GET /api/goals/{id}` · `POST /api/goals/{id}/{goal}` | Today's goals, crew missions, XP · tick a goal |
| `GET /api/leaderboard` | Ranking and crew missions |
| `POST /api/checkins` | Mood, reaction test, Amsler grid, vital signs |
| `GET /api/protocols` · `POST /api/emergencies` · `POST /api/emergencies/{id}` | Guided Response bank resolved for the place · open · log, close |
| `GET/POST /api/messages` | Messages with communication delay |
| `GET /api/space-weather` · `GET /api/nasa/rad` | NASA data |
| `GET /api/assistant/status` · `POST /api/assistant/ask` · `POST /api/briefings` | AI slot |
| `POST /api/medical/session` and `/api/medical/*` | Medical console (token required) |

---

## How it maps to the judging criteria

| Award | What in Canary speaks to it |
| --- | --- |
| Best Use of Science | Personal-baseline statistics, NASA HRP hazards per system, space-specific protocol variants, bone and radiation models labelled as estimates |
| Best Use of Data | Three NASA datasets in the product, reproducible snapshot script, live DONKI option |
| Best Use of Technology | Holographic WebGL body with clickable systems, typed API, tested assistant guard, offline-first design |
| Galactic Impact | Works where help is far: Mars transit, Moon, and on Earth on ships, platforms and remote communities |
| Best Mission Concept | A mission plan that re-adapts the whole system per leg (ISS, Moon, Mars), a day-147 to Sol-12 story, comm delay in every message and report |
| Most Inspirational / Storytelling | The canary in the mine, the four-beat intro, the six-scene demo |
| Global Connection | An international crew, a system meant for any agency or commercial crew |
| Art & Technology | The hologram: iridescent shell, flowing vessels, a Mental lens that lights the nervous system |
| Local Impact | The Earth edition for isolated workers and communities |

---

## What to build next

1. **AI provider:** implement `AnthropicProvider` or `LocalProvider`; keep the guard tests green.
2. **Real devices:** a `TelemetrySource` that reads a wearable or a CSV export.
3. **Ground sync:** store-and-forward of messages, briefings and check-ins to a ground station, with conflict rules.
4. **Clinical review:** replace the illustrative protocols with flight-surgeon-approved ones; per-person medication allergies in Guided Response.
5. **Privacy, next steps:** a badge tap as a second factor; freeze a streak during medical leave instead of breaking it; per-item sharing instead of all-or-nothing.
6. **Pitch:** record the six-scene demo; verify the literature figures listed below.

---

## Limits, honestly

- **Simulated:** astronaut vital signs are not published as open data, so crew members, baselines, daily readings and the mission dose are simulated (deterministic, with the story written in) and labelled as such.
- **Not clinically reviewed:** Guided Response protocols are illustrative first aid adapted to spaceflight. Real ones come from the flight surgeon.
- **To verify before quoting:** daily dose by place, the 600 mSv career limit, bone loss of about 1% per month, delays to Mars.
- **Demo shortcuts:** the PINs are public (crew `1001` to `1004`, medical `1961`, all in this README and shown as a hint on the pad), and a 4-digit PIN with a rate limit is a prototype lock, not real security; session tokens are signed with a random secret per start unless `CANARY_TOKEN_SECRET` is set; the communication delay runs 20× faster; fonts load from Google Fonts (bundle them for an offline ship).

---

## Credits and licences

- Body mesh: [MakeHuman](https://github.com/makehumancommunity/makehuman) base mesh, **CC0 1.0**.
- NASA data: DONKI, Curiosity RAD (PDS/SPDF) and OSDR OSD-569 are NASA open data.
- Fonts: Archivo, Public Sans and DM Mono from Google Fonts (SIL Open Font License).
- Built for NASA Space Apps Challenge 2026. Canary is not affiliated with or endorsed by NASA.
