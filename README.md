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

Open <http://localhost:5173>. The intro plays once and ends on the mission as mission control configured it (itinerary drawn in, crew introduced), then Canary opens on the **crew**: goals, hazards and crew missions, never anyone's health or status. To see your own health, open **My space**: choose your profile and type your **4-digit PIN**. Mission setup and astronaut registration belong to a future **mission-admin flow**; a preview of setup lives at `/setup` (not linked from the crew screens). The **Demo story** bar at the bottom walks through the six scenes and offers "Enter as …", which opens the PIN pad for the person each scene follows (it never skips the PIN).

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
| `make test` | 40 backend tests (alerts, story, mission plan, setup and conditions, goals, privacy, hazards, PINs and sessions, assistant guard, API) and the frontend type check |
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

A sidebar in three groups (**Crew**: Crew, Tests, Mission plan, Ranking; **Your health**: My space; **Support**: Ask Canary, Medical console, Settings, About & data), **crew first**: the system always opens on the whole crew, and your own data sits behind your private space. Each page reads top to bottom like a dashboard: the most important thing first, details further down.

| Page | What you see |
| --- | --- |
| **Intro** | Four beats of the canary story over a starfield while the body assembles, then **Your mission**: the configured itinerary draws itself in and the crew is introduced. Nothing to fill in |
| **Admin setup preview** (`/setup`) | Not part of the crew flow; a preview of the future mission-admin flow. | Full-screen, four steps: pick the destination (space station, Moon, Mars with gravity, Earth reply delay and radiation), set the length of every part with a live timeline that re-proportions as you type, meet the crew, review and launch (a 3-2-1 over the timeline). The defaults reproduce the three presets exactly; Mars can add a return trip. "Use the demo story" takes the Mars preset |
| **Crew** (home) | The four astronauts as neutral dots with today's routine. **Hazards here today**: NASA's five hazards of spaceflight (radiation, isolation, distance, gravity, closed environment) rated low, moderate or high for the current place, a solar storm warning on top when one hits; tap a hazard to see which body systems it acts on. **Crew missions** in their own full-width section with the crew streak. **Who sees what** folded at the bottom. No status, no scores, no vitals, no averages |
| **My space** (private, under Your health) | Locked, it shows only a padlock, **Choose your profile** and four profile buttons; a profile asks for its 4-digit PIN. Inside, six tabs: **Health**, **Goals**, **Suggestions**, **Patches**, **Dashboard** (every chart) and **Settings** (profile photo, Change PIN, Lock). Signed in, your profile at the foot of the sidebar opens a menu with **Open my space**, **My settings** and **Lock my space** |
| My space · **Health** | Top: the 3D body and, beside it, one sentence on how you are, up to three numbered steps and your Physical and Mental scores. The **Physical / Mental** switch changes the body's lens and the numbers below it: Physical shows only the physical systems, Mental only the mental facets, always as number tiles (value, your normal, status colour). Click a part of the body or a tile and the top area becomes that system (what it means, what to do, a check to run), without repeating the numbers; the body column always matches the height of that panel. Charts are on the Dashboard tab |
| My space · **Goals** | One line of summary (done today, streak, 7-day completion), then **Physical** and **Mental** as separate, roomy lists with their own progress, then the crew missions. No points, no levels: goals are goals |
| My space · **Suggestions** | The AI slot's third entry. Personal recommendations built from your numbers against your own normal, how often you met each goal this week, your test results and the next leg of the plan: protect your sleep window, more time with the crew, read more (or keep going with the book you logged), start a small hobby (sketching the view, a crewmate's language, the plant chamber), breathing after shift, exercise, hydration, preparing for the next gravity change, staying close to home, talking to someone. Each card says why with your own numbers, gives three steps and can be added to your goals for 7 days |
| My space · **Patches** | The nine mission patches on their own page, with progress towards the ones not earned yet |
| **Tests** (Crew group, private results) | Choose your profile and enter the PIN, then run any test or log: **Cognition** (reaction time, processing speed as a digit-symbol task, working memory as a digit span, the kinds of task in NASA's Cognition battery), **How you feel** (mood and stress, Karolinska Sleepiness Scale, NASA-TLX workload, PHQ-2 and GAD-2 wellbeing), **Body** (vital signs, Amsler grid, symptoms) and **Logs** (sleep diary, reading, a three-line journal whose text is never saved). Each row shows the last result; results feed your health, complete matching goals and can raise a gentle alert (very sleepy, a hard stretch, strong symptoms) |
| My space · **Dashboard** | The last 30 days of every indicator against your normal, goals done per day, and lymphocytes from NASA OSD-569 |
| **Settings** | For the terminal: theme (dark, light, match device), larger text, higher contrast, reduce motion, read Guided Response steps aloud, show the demo bar, replay the intro, reset the demo |
| **Ranking** | One headline (who leads, by how many goals), what counts, then one row per person: medal, goals done in the last 7 days as a bar, the gap to the person ahead, completion, streak and patches |
| **Mission plan** | The registered itinerary read for health: a timeline with every leg listed underneath (the leg the crew is on now is always open by default, also after the clock moves; pick another to look ahead), the leg's gravity, radiation, Earth delay and hospital distance, its five hazards, what the body faces, what Canary changes, and the projected mission dose against the career limit. Editing the plan belongs to the admin flow |

Always reachable: the **crew dots** and **Hold for emergency** (top right) opens Guided Response; **Where you are** (top left) simulates any place; the sidebar holds **Ask Canary**, **Medical console** (4-digit PIN) and **About & data**; the **demo bar** at the bottom drives the story.

### Who sees what

Canary follows the team's data-use draft: a visibility contract the crew agrees on day 0 (`backend/canary/domain/privacy.py`).

| Information | The astronaut | Medical team | The crew | Earth |
| --- | --- | --- | --- | --- |
| Raw data and history | Yes | Yes | No | No |
| Personal risks and advice | Yes | Yes | No | No |
| Operational status (e.g. fit for EVA) | Yes | Yes | No | Via the medical team |
| Critical alert | Immediately | Immediately | No | Delayed briefing |
| Hazards and crew goals | Yes | Yes | Yes | Yes |

How the API enforces it:

- **Operational status is medical-only.** Diagnoses such as "Fit for all duties" or "Off critical tasks" are visible to the medical team and to the person themself in their private space. The crew never sees anyone's status; the Crew page shows only whether EVA is possible at all (environment) and says the medical team clears each person.
- **Entry is by PIN.** `POST /api/crew/{id}/session {"pin"}` returns a signed token `{id}.{exp}.{sig}` (HMAC-SHA256 over `crew:{id}:{exp}`, one hour). The web app keeps it in `sessionStorage` and sends it in the `X-Canary-Viewer` header; a bare id, a forged or an expired token is nobody (403 on private routes). Five wrong PINs in 60 seconds lock that person for a minute (429). `PUT /api/crew/{id}/pin` changes your PIN (needs your token and the current PIN). The medical console works the same way with its own PIN and a bearer token.
- `GET /api/crew/overview` is the only crew-wide view: participation (goals done today, streaks), hazards, crew missions. No status, indicators, scores or alerts, and no averages, because with four people an average gives individuals away.
- `GET /api/crew/{id}` answers only the astronaut (session token) and the medical team (bearer token). There is no sharing switch: health never leaves those two.
- Goals, check-ins, Ask Canary and briefings answer only the astronaut and the medical team. `GET /api/crew` with full summaries is medical-only.
- Operational status (shown only to the person and the medical team) comes from personal alerts only: any act-level alert means off critical tasks; watch-level alerts that change what someone may do (pulse, pressure, oxygen, temperature, reaction time, space sickness, re-adaptation, Amsler) mean no EVA. Slow trends such as bone are followed in private. Storms are crew hazards, not personal status.
- If the medical officer is the patient, their alerts go to the substitute (the commander).

### Mission plan

A plan is a list of legs: place, first day, last day and what happens (day 0 is launch; negative days are pre-flight). Mission control registers it (the future admin flow; `PUT /api/plan` and three presets today: **Mars reference mission**, **Six months on the ISS**, **Lunar surface mission**). The crew only reads it.

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

The demo story bar moves the mission clock; **Where you are** in the top bar simulates any place.

### Design rules

Informed by the Impeccable (Operate mode: quieter, distill, craft floor), Emil Kowalski design-engineering and Taste skills.

- Flat surfaces, no gradients, no glow, no glass. The hologram is the only luminous thing on screen.
- Space instead of boxes: sections are separated by space and hairlines; filled cards only where something is pressable or private.
- No labels above headings. The heading speaks; context goes in a quiet line below it.
- Colour means state: green on track, amber watch, red act, slightly desaturated. One accent colour (blue) for what you can press. Places get a small coloured dot, never a coloured edge.
- Facts sit in a single strip with hairline dividers, not a row of big-number cards.
- Motion has a job: the intro is the one authored moment; pages fade in once in under 300 ms with a strong ease-out; buttons press to 97%.
- Browser surfaces are themed too: selection, caret, focus ring, scrollbars, tabular numerals.
- **Light mode** and accessibility options in Settings (remembered on the device). The hologram, the intro and Guided Response stay dark on purpose.
- Labels never sit inside narrow bars: the itinerary is a thin bar with every leg listed underneath.

### The three ideas behind it

**Goals.** Personal goals for the body (exercise by place, water, vitals, mobility, calcium, Amsler grid) and the mind (sleep, reaction test, mood check-in, meditation or prayer, reading, crew time, films and music, calls home, looking homeward, journal). Crew missions are shared weekly targets (2,400 exercise minutes, 5 crew meals, 20 meditation sessions, book club, movie nights). Streaks and nine mission patches; no points or levels.

**Warnings.** Each indicator is a z-score against the person's own pre-flight baseline. The medical team sets the thresholds. Cross-signal rules catch what single numbers miss: sleep + mood + reaction time together, high pulse + low water in the first 72 h, low pressure + high pulse back in gravity, a wavy Amsler grid, a solar particle event. Every warning says what it means, what to do now, and adds goals.

**Guided Response.** Not a panic button: a calm, deterministic guide. Protocols are data (`backend/canary/data/protocols.json`) with variants for 0 g, partial gravity and Earth, and for each place. Closing it adds follow-up goals for the patient and queues a report for Earth.

**The ranking counts effort, never vital signs.** It is the one place where individuals are compared, and only by participation: goals done (routine, check-ins, doctor and alert goals) in the last 7 days. There are no points or levels. Goals come from goals done and check-ins sent. A hard day reported honestly earns the same as a good one, so nobody gains by hiding a symptom.

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
   ├─ domain/telemetry   TelemetrySource: DatasetSource (observations.csv) today, devices tomorrow
   ├─ domain/health      baseline z-scores, alert rules, body systems, readiness scores
   ├─ domain/goals       daily goals, streaks, patches, crew missions, ranking
   ├─ domain/privacy     who sees what: operational status (medical only), profile photos, hazards, the day-0 contract
   ├─ domain/protocols   Guided Response bank, resolved by gravity and place
   ├─ domain/nasa        DONKI · Curiosity RAD · OSD-569 snapshot (+ optional live DONKI)
   ├─ domain/plan        mission plan: itinerary legs, presets, location by day
   ├─ domain/mission     mission clock, place, demo story
   ├─ assistant/         the AI slot: provider · knowledge · tools · guard · chat · briefing · suggestions
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
| Telemetry behind `TelemetrySource`, fed by an observation file | Real data replaces simulated rows by dropping in a CSV, with no code change | Formulas inside the code that nobody can open and check |
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
| `assistant/suggestions.py` | Entry 3: personal suggestions in My space. Code gathers the facts (indicators against the personal normal, goals met this week, self-tests, the next leg), rules write each suggestion with the numbers behind it, and a connected model may only rephrase the reason; `guard.unknown_numbers` rejects a rewrite with any number not in the facts. Accepted suggestions become goals for 7 days |

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

### The crew observation file

Every number the crew shows comes from one table, `backend/canary/data/observations.csv`: one row per measurement, `crew_id, day, indicator, value, unit, origin, method, source, note`. `origin` is `simulated` or `real`; `method` is `wearable`, `manual`, `test`, `blood`, `urine` or `environment`; cabin air uses the crew id `cabin`. A day without a row means nothing was measured, and the app shows the last observation (`telemetry.last_observation` also gives its age).

- **Where the simulated rows come from.** `data/recipes.json` holds one recipe per indicator (baseline, day-to-day spread, slow drift by gravity and mission day, which hidden states move it, how often it is measured, chance of a missed measurement, and a `source` with `verified`). Four hidden states (fatigue, hydration, energy, bone loss) move related signals together; the demo story is two dated events that push them. `python data/generate_dataset.py` builds the file, deterministic and standard library only, and writes `data/DATASET.md` with one table per indicator, the assumptions without a source, and how each method would be collected on a real mission.
- **What is real today.** The complete blood count (OSD-569, from the snapshot into `data/real/osd569_cbc.csv`, collections keep their label such as `R+45` in `note`; the pre-flight ones set each person's baseline). Everything else is simulated.
- **Other plans.** With the default plan the backend reads the file. With any other plan it generates the same table in memory with the same generator (cached per plan).
- **Swapping simulated for real.** Put a CSV with the same columns in `data/real/` (`crew_id, day, indicator, value` are enough) and run `python data/generate_dataset.py`. Those rows enter with `origin = real` and replace the simulated row with the same (crew_id, day, indicator). No code changes. A check-in made in the app still wins over the file for that day, and the file is never written to the `checkins` table.
- Radiation dose by place is still the function in `telemetry.cumulative_dose`, not in the file.

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
    domain/              catalog, plan, telemetry, simdata, health, goals, privacy, protocols, nasa, mission, selftests
    assistant/           the AI slot: chat, briefing, suggestions, guard
    data/                protocols.json, nasa_snapshot.json, observations.csv (generated)
  tests/test_canary.py   tests
  requirements.txt
frontend/
  src/
    api/                 typed client and response types
    state/session.tsx    mission, signed-in person, photos, preferences, refresh signal
    state/prefs.ts       theme and accessibility preferences for the terminal
    hologram/            scene, shaders, procedural anatomy, React wrapper
    components/          Shell (sidebar, profile menu, top bar, demo bar), People (crew dots, profile picker), PinPad, Timeline, Hazards, Stars, BodyView (body + observations), goals, charts, patches
    features/            Guided Response, Ask Canary, self-tests and logs (Checks)
    pages/               Intro, Setup (admin preview), Crew (home), Astronaut (public card or medical view), MySpace (Health, Goals, Suggestions, Patches, Dashboard, Settings), Tests, Settings, Ranking, MissionPlan, Medical, About
    styles/app.css       design tokens and components
  public/models/         body.glb, joints.json
data/recipes.json        one recipe per indicator: baseline, spread, drift, hidden states, frequency, gaps, source
data/real/               real observations (CSV), replace simulated rows with the same key
data/generate_dataset.py builds observations.csv, data/DATASET.md and data/real/osd569_cbc.csv
data/DATASET.md          what is in the file, where each part comes from, how it would be collected
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
| `POST /api/setup` | Mission-admin setup (future admin flow): validates and saves the plan, restarts the story. The demo mission ships configured |
| `POST /api/crew/{id}/session` · `PUT /api/crew/{id}/pin` | Sign in with the 4-digit PIN (returns the session token) · change your PIN |
| `GET /api/crew/overview` | What everyone may see: participation, hazards, crew missions, the visibility contract. Never status |
| `GET /api/crew/{id}` | One astronaut in full, with operational status: the astronaut and the medical team only |
| `GET /api/crew` | Full health summary of everyone, with operational status (medical team only) |
| `GET /api/goals/{id}` · `POST /api/goals/{id}/{goal}` | Today's goals, crew missions, streak and patches · tick a goal |
| `GET /api/suggestions/{id}` · `POST /api/suggestions/{id}/{sid}/accept` | Personal suggestions (the astronaut only) · turn one into a goal for 7 days |
| `POST /api/checkins` · `GET /api/checkins/{id}` | Save a test or log (self only) · every test with its latest result and the recent log (self and medical team) |
| `GET /api/crew/photos` · `PUT/DELETE /api/crew/{id}/photo` | Profile photos (the astronaut sets their own) |
| `GET /api/leaderboard` | Ranking and crew missions |
| `GET /api/protocols` · `POST /api/emergencies` · `POST /api/emergencies/{id}` | Guided Response bank resolved for the place · open · log, close |
| `GET/POST /api/messages` | Messages with communication delay |
| `GET /api/plan/conditions` | Each leg's five hazards and dose, plus the projected mission dose against the career limit |
| `GET /api/space-weather` · `GET /api/nasa/rad` | NASA data (used by alerts and the story; no page of their own) |
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
5. **Privacy, next steps:** a badge tap as a second factor; freeze a streak during medical leave instead of breaking it; profile photos stored as files rather than in the settings table.
6. **Pitch:** record the six-scene demo; verify the literature figures listed below.

---

## Limits, honestly

- **Simulated:** astronaut vital signs are not published as open data, so crew members, baselines, daily readings and the mission dose are simulated (deterministic, with the story written in) and labelled as such. Only the blood count is real. In `observations.csv` every row says `simulated` or `real`, and every recipe without a published source says `prototype assumption` with `verified: false`; `data/DATASET.md` lists them. Open real data exists for the metabolic panel, cytokines and dose by place and is not imported yet.
- **Sparse measurements:** a blood panel, urine panel or scale reading is only as fresh as its last collection. Blood pressure, grip and the bone estimate are daily in the file on purpose: the alert rules blend three days, and sparser readings changed the demo alerts.
- **Not clinically reviewed:** Guided Response protocols are illustrative first aid adapted to spaceflight. Real ones come from the flight surgeon.
- **To verify before quoting:** daily dose by place, the 600 mSv career limit, bone loss of about 1% per month, delays to Mars.
- **Demo shortcuts:** the PINs are public (crew `1001` to `1004`, medical `1961`, all in this README and shown as a hint on the pad), and a 4-digit PIN with a rate limit is a prototype lock, not real security; session tokens are signed with a random secret per start unless `CANARY_TOKEN_SECRET` is set; the communication delay runs 20× faster; fonts load from Google Fonts (bundle them for an offline ship).

---

## Credits and licences

- Body mesh: [MakeHuman](https://github.com/makehumancommunity/makehuman) base mesh, **CC0 1.0**.
- NASA data: DONKI, Curiosity RAD (PDS/SPDF) and OSDR OSD-569 are NASA open data.
- Fonts: Archivo, Public Sans and DM Mono from Google Fonts (SIL Open Font License).
- Built for NASA Space Apps Challenge 2026. Canary is not affiliated with or endorsed by NASA.
