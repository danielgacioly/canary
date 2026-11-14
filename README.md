# Canary

**A crew health system for when Earth is too far to answer.**
NASA Space Apps Challenge 2026 · *Create Health Monitoring Software for Astronauts on Space Missions*

For a century, miners carried a canary underground. The bird felt bad air before people did, and when it went quiet the miners knew to leave. A spacecraft is a sealed mine: radiation, isolation, distance, altered gravity and a closed cabin. On the way to Mars a question to the flight surgeon takes up to 24 minutes to arrive and as long to come back. Canary stays on board for that gap.

It compares every astronaut with **their own normal**, turns early warnings into **goals**, and **guides the crew step by step** when something goes wrong. Physical and mental health sit side by side, on a holographic body you can turn and click.

---

## Contents

1. [Run it](#run-it)
2. [What it does](#what-it-does)
3. [No accounts: how crew and mission get on board](#no-accounts-how-crew-and-mission-get-on-board)
4. [The demo story](#the-demo-story)
5. [Architecture](#architecture)
6. [The AI slot](#the-ai-slot)
7. [NASA data](#nasa-data)
8. [The 3D body](#the-3d-body)
9. [Project layout](#project-layout)
10. [API](#api)
11. [How it maps to the judging criteria](#how-it-maps-to-the-judging-criteria)
12. [What to build next](#what-to-build-next)
13. [Limits, honestly](#limits-honestly)
14. [Credits and licences](#credits-and-licences)

---

## Run it

Needs **Python 3.9+** and **Node 18+**.

```bash
make setup     # backend venv + npm install
make dev       # API on :8000 and web app on :5173
```

Open <http://localhost:5173>. The intro plays once and ends on the mission as mission control configured it (itinerary drawn in, crew introduced), then Canary opens on the **crew**: goals, hazards and crew missions, never anyone's health or status. To see your own health, open **My space**: choose your profile and type your **4-digit PIN**. Mission setup and astronaut registration belong to a future **mission-admin flow**; a preview of setup lives at `/setup` (not linked from the crew screens). The **Demo story** bar at the bottom walks through the six scenes and offers "Enter as …", which opens the PIN pad for the person each scene follows (it never skips the PIN).

Demo PINs (public, for the demo only): Helena `1001`, Kenji `1002`, Amara `1003`, Tomás `1004`; medical console `1961`; Mission Control (Canary Control) `4242`.

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
| `make test` | backend tests (alerts, risks, advice, story, mission plan, setup and conditions, goals, privacy, hazards, PINs and sessions, Mission Control, assistant guard, API) and the frontend type check |
| `make serve` | builds the web app and serves everything from one process on <http://localhost:8000> |
| `http://localhost:8000/docs` | interactive API documentation (OpenAPI) |
| Medical console PIN | `1961` (demo only, set `CANARY_MEDICAL_PIN` anywhere else; always exactly 4 digits) |
| Mission Control PIN | `4242` for Canary Control (demo only, set `CANARY_CONTROL_PIN`) |

### Settings (environment variables)

| Variable | Default | Meaning |
| --- | --- | --- |
| `CANARY_DB` | `backend/canary.db` | SQLite file (created on start) |
| `CANARY_MEDICAL_PIN` | `1961` | PIN of the medical console (4 digits) |
| `CANARY_CONTROL_PIN` | `4242` | PIN of Canary Control, the Mission Control mode (4 digits) |
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
| **Mission** (`/mission`, the callsign chip in the top bar) | The mission and the crew as a whole, public on board: callsign and name, launch date, today's mission date, destination, where the crew is now, a card per astronaut (role, agency, home, nationality, languages, previous flights; no health) and the itinerary. From here, **Switch to Mission Control mode** |
| **Canary Control** (`/control`, Mission Control mode) | The other side of the system, in its own mode with its own accent. Opens with the Mission Control PIN (demo `4242`). **Dashboard**: callsign, mission time, signal delay and dose; each astronaut with the operational status the ship's medical team reports, goals today and the last self-test; the five hazards; emergencies; **Start from zero** clears crew and mission. **Register crew and mission**: four seats with every field of My information plus each person's first PIN, a **Fill with the demo crew and mission** button, then callsign, name, launch date and mission profile, then review and **Save and activate Canary**. **Messages**: write to the ship's medical team and read the traffic coming down, all with the real signal delay |
| **Crew** (home) | The four astronauts as neutral dots with today's routine. **Hazards here today**: NASA's five hazards of spaceflight (radiation, isolation, distance, gravity, closed environment) rated low, moderate or high for the current place, a solar storm warning on top when one hits; tap a hazard to see which body systems it acts on. **Crew missions** in their own full-width section with the crew streak. **Who sees what** folded at the bottom. No status, no scores, no vitals, no averages |
| **My space** (private, under Your health) | Locked, it shows only a padlock, **Choose your profile** and four profile buttons; a profile asks for its 4-digit PIN. Inside, seven tabs: **Health**, **Goals**, **Suggestions**, **Patches**, **Dashboard** (every chart), **My information** and **Settings** (profile photo, Change PIN, Lock). Signed in, your profile at the foot of the sidebar opens a menu with **Open my space**, **My settings** and **Lock my space** |
| My space · **Health** | Top: the 3D body and, beside it, one sentence on how you are, up to three numbered steps and your Physical and Mental scores. The **Physical / Mental** switch changes the body's lens and the numbers below it: Physical shows only the physical systems, Mental only the mental facets, always as number tiles (value, your normal, status colour). Click a part of the body or a tile and the top area becomes that system (what it means, what to do, a check to run), without repeating the numbers; the body column always matches the height of that panel. Charts are on the Dashboard tab |
| My space · **Goals** | One line of summary (done today, streak, 7-day completion), then **Physical** and **Mental** as separate, roomy lists with their own progress, then the crew missions. No points, no levels: goals are goals |
| My space · **Suggestions** | The AI slot's third entry. Personal recommendations built from your numbers against your own normal, how often you met each goal this week, your test results and the next leg of the plan: protect your sleep window, more time with the crew, read more (or keep going with the book you logged), start a small hobby (sketching the view, a crewmate's language, the plant chamber), breathing after shift, exercise, hydration, preparing for the next gravity change, staying close to home, talking to someone. Each card says why with your own numbers, gives three steps and can be added to your goals for 7 days |
| My space · **My information** | The personal record Mission Control registered before flight, read-only: identity (name, date of birth, age that follows the mission clock, sex, nationality, home, languages), body (height, weight, BMI, blood type, Fitzpatrick skin type, dominant hand, vision), medical (allergies, medications, conditions, diet, vaccinations) and mission (role, agency, previous flights and days in space, emergency contact through family support). Private to the astronaut and the medical team; corrections go through the flight surgeon |
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
- Operational status (shown only to the person and the medical team) comes from personal alerts only: any act-level alert means off critical tasks; watch-level alerts that change what someone may do (pulse, pressure, oxygen, temperature, reaction time, space sickness, re-adaptation, Amsler) mean no EVA. Slow trends such as bone are followed in private. Storms are crew hazards, not personal status. After a closed emergency the status is at least the protocol's `ops` until the end of the care window, with `reason` and `until_day` (see [After an emergency](#after-an-emergency-and-who-is-told)).
- **Critical alerts are delivered.** A personal level-2 alert writes one `alert` message to the crew medical officer, once per episode (`crew_id`, `alert_id`, `since_day`); if the medical officer is the patient, it goes to the substitute (the commander). One `alert_earth` note with the briefing facts is queued for Earth with the place's delay. Both kinds are visible only to their recipient and the medical console (the `/api/messages` filter is the same as for `advice`); the crew sees nothing. The list is in `GET /api/medical/overview` → `notices`.
- Guided Response itself is a crew-wide event (the whole crew is alerted, and `GET /api/emergencies` lists protocol, patient and outcome as before). What follows it, the care window, the restricted status and the tightened thresholds, is private to the person and the medical team (`care_events` in `GET /api/crew/{id}` and the medical overview).

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

## No accounts: how crew and mission get on board

Nobody creates an account in Canary. **Mission Control registers** the four astronauts (their record and a first PIN) and the mission (callsign, name, launch date, profile) in Canary Control; the crew terminals simply use what was registered. Before that, every crew screen says **Waiting for Mission Control**.

- Each astronaut opens their space with the PIN Mission Control set and can change it on board. The medical console and Canary Control have their own PINs and their own tokens; one never opens the other.
- Seats keep fixed ids, so a newly registered astronaut takes over that seat's simulated pre-flight baseline and the demo story still works.
- A demo reset brings back the demo crew and mission; **Start from zero** in Canary Control clears them for a live registration.
- Next step for a real mission: the registration travels to the ship as a signed mission package (Mission Control holds the private key, the ship only the public one), with signed incremental updates during flight.

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
| Personal baseline (z-score) **and** population range | Astronauts are fit outliers, so their own normal gives the early warning; the population range stays as the safety limit | Either one alone |
| Protocols as JSON | The medical team can review and replace them without code | Protocols in code |
| No accounts for the crew, a 4-digit PIN per private space | A shared terminal in a cabin: a PIN is fast, and Guided Response needs no sign-in | Logins with passwords: friction in an emergency; trusting a plain id: anyone could open anyone's health |
| PIN + signed token for doctors | Only the medical team writes prescriptions and rules | Full identity system: out of scope for a prototype |
| AI only explains | Deterministic rules decide alerts and emergencies | Letting a model diagnose or triage |
| React + plain Three.js, no UI kit | Full control of the mission-console look and the hologram | Component libraries: generic look |

### How a number becomes an alert

```
observation(day) ─►  recent = 60% today + 25% yesterday + 15% day before
 (check-in or file)     │
baseline (pre-flight) ──┤  z = (recent − baseline) / personal spread
                        ▼
              level 0 / 1 / 2  by the medical team's thresholds (default 1.5σ / 2.5σ)
                        │  (× 0.8 for the patient inside the care window after an emergency)
slow slide? ────────────┤  a line through the last 14 days crosses the level-1 limit within 10 days  →  "drifting towards your limit"
                        ▼
RISK (domain/risk.py) ──┤  evidence from every related indicator and check-in, added up with a weight table
 e.g. fatigue           │  → level 0 / 1 / 2 · score · trend (rising / stable / falling) · since_day · evidence list
                        ▼
cross-signal rules ─────┤  fatigue level 2  →  the `behaviour` alert (`risk: "fatigue"`); the other rules are unchanged
  missing data ─────────┤  no mood check-in for 3 days  →  `missing_mood` (level 1, never counts as a health risk)
                        ▼
         alert = { what it means, what to do now, goals added, sources }
                        │
   personal level 2 ────┤  one message to the medical officer (or the substitute) per episode, one delayed note for Earth
      (domain/notify.py)│
                        ▼
   advice accepted ──────┤  goal + what to verify (indicator, days)  →  checked on its day: improved / same / worse
      (domain/advice.py)│  two rounds in a row without improvement  →  another suggestion + one message to the medical officer
                        ▼
   body system status = the highest risk level acting on it (one indicator alone: watch at most,
   unless past the population safety limit)  →  colour on the 3D body  →  physical / mental readiness score
```

### Risks

A risk is a function of the day, never a stored value, so the demo clock can jump anywhere and the same day always gives the same answer. `GET /api/crew/{id}` and the snapshot carry `risks: [{id, name, nasa_red, systems, clock_days, level, score, trend, evidence, since_day}]`; each evidence is `{indicator | checkin, text, value, baseline, z, origin, source, points}`. There are eight risks (`risk.RISKS`): **`fatigue`** below, and the seven in "Risks, evidence and data origin".

| Fatigue evidence | Points |
| --- | --- |
| each of sleep, reaction time, mood | 1.0 × the indicator's level (0, 1 or 2) |
| processing speed (`dsst`) | 0.75 × level |
| stress, time with crew, working memory, sleepiness (`kss`), workload (`tlx`) | 0.5 × level |
| wellbeing check-in (PHQ-2 or GAD-2 of 3 or more in 14 days) | 1.0 |
| no mood check-in for 3 days | 0.5 |
| drifting towards the limit (level 0 but sliding) | 0.5 each, 1.0 at most |

Level 1 from 2.0 points. Level 2 from 4.0 points **and** at least 3 distinct signals (drift does not count) **and** level 1 or more two days earlier, so one bad night, or two tired check-ins, never reaches level 2. The trend compares the score with 3 days ago (±0.5). `since_day` is found by walking back day by day and re-evaluating (cached, at most 60 days), never stored. Every weight and cut is a prototype assumption (`verified: false`, see [Limits, honestly](#limits-honestly)); the tables are at the top of `risk.py`. The AI never scores a risk: rules decide, the assistant only explains (`get_risks`).

#### Risks, evidence and data origin

Each risk adds up evidence Canary already has, with a weight table that is a prototype assumption (`source: "prototype assumption"`, `verified: false`). Four are NASA's red risks for a journey to Mars (Patel et al., npj Microgravity 2020) and carry `nasa_red: true`. `data` says where the evidence comes from: `real` (all measured: NASA data or typed in the app), `partial` (a mix with simulated numbers) or `simulated` (none measured). With no active evidence it is read from the data the risk looks at.

| Risk | NASA red | Body systems | Evidence | Level 1 / level 2 | Clock | Data today |
| --- | :---: | --- | --- | --- | --- | --- |
| `fatigue` | yes | brain | sleep, reaction, mood, stress, social, tests, wellbeing, drift (table above) | 2.0 points / 4.0 and 3 signals | 14 days | simulated, plus check-ins |
| `radiation` | yes | skin | mission dose against the 600 mSv career limit and the day the plan is projected to pass it; a storm in progress; a **low** lymphocyte count | from 50% of the limit **with** a projected crossing (the evidence says "projected to pass the career limit on day N") or a low count / a storm, or the limit passed | 1 day | dose simulated (the same for everyone: Canary does not invent a dose per person), storm real (DONKI, Curiosity RAD), lymphocytes real or simulated |
| `sans` | yes | eyes | Amsler grid with distortion (2 points), vision symptoms (1 point) in the last 7 days. The Amsler grid is a weak indicator: a clear grid does not rule SANS out | 1 / 2 points | 7 days | check-ins (user) |
| `nutrition` | yes | gut | weight below the person's pre-flight mean (5% = 1 point, 10% = 2), fasting glucose against the person's normal | 1 / 3 points and 2 signals | 7 days | simulated |
| `renal` | no | kidneys | water, the model's bone-loss rate (1% or more in 30 days), creatinine and 24 h urine volume against a range | 1 / 3 points and 2 signals | 15 days | simulated |
| `immune` | no | immune | temperature, blood count out of range (0.5 each, 1.5 at most), the days after a storm | 1 / 3 points and 2 signals | 30 days | blood count real and simulated |
| `cardio` | no | heart, lungs | pulse, pressure, oxygen; the re-adaptation pattern after the change to partial gravity (the `regravity` alert belongs here) | 1 / 4 points and 3 signals | 1 day | simulated, plus check-ins |
| `bone_muscle` | no | skeleton, muscles | bone estimate, grip, exercise | 1 / 4 points and 3 signals | 30 days | simulated |

A risk colours only the body system its evidence is about (grip colours the muscles, not the bones). Exams have their own frequency (`risk.PANELS`: blood every 30 days, urine every 15): an exam older than that is shown as `stale` evidence with its age and the risk says `panel_due`, but an old exam is never counted as a health signal. A blood value that was already outside the usual range before launch is the person's normal, not a new signal. Existing alerts keep their ids and texts and gain `risk`.

**Hazard labels.** Every risk and every alert has `hazards: ["I", "E", ...]` and a `hazard_note` ("Possible factors here: Isolation & confinement, Distance from Earth. Not a cause."). A hazard is listed when the team's matrix (`catalog.HAZARDS_BY_INDICATOR`, from the document *matriz-perigos-indicadores*) links it to one of the risk's evidence and it is moderate or high at the current place and day in the RIDGE below. `hazard_links` lists each link with its `why` and `source`. The links are possible factors, never a cause, and none is `verified`: the "HRP" and "Patel 2020" sources are still to be checked against the HRP risk pages and the article. Four indicators the matrix does not cover (`dsst`, `span`, `kss`, `tlx` and `urine_volume`) borrow the hazard of their body system and are marked `prototype assumption`; the cytokines row has no indicator in the catalog yet.

**The five hazards (RIDGE) come from the plan.** `privacy.ridge(location, storm, day)` computes each level instead of reading a table (cuts in `privacy.RIDGE_CUTS`, all prototype assumptions): **R** from the place's dose rate (moderate from 0.1 mSv/day, high from 1.0; a storm away from Earth is high); **I** from the days since launch (moderate up to day 90, high after) and the crew size; **D** from the Earth delay (high from 60 s) and the days to a hospital (moderate from 2); **G** from the place's gravity (0 g high, partial moderate) and the 30 days after a change of gravity (high on arrival in partial gravity); **E** stays set per place and is marked `assumption`. Each hazard answers `basis` (why this level). On the reference mission day 147, in transit, the levels are the same as the old table (R, I, D, G high, E moderate). Differences: isolation now grows with the days since launch, and the first 30 days on Mars read gravity as high (readaptation) instead of moderate.

The suggestions use the same layer: each one is decided by the level of the indicator it cites, the risk evidence and the weekly goal counts, with no limits of their own, so a suggestion never contradicts an alert.

Every day of the 60/25/15 blend is read the same way, through `telemetry.observation(crew, indicator, day)`. A check-in made on day D therefore shows in that day's chart and weighs on the value for D, D+1 and D+2. The baseline in that formula is the person's pre-flight mean, and a population range can raise the level by itself (see "Reference ranges and their sources"). Missing data is not a risk: `missing_mood` appears when the daily mood goal (`goals.is_done`, real tick or simulated history) was not met today, yesterday and the day before, but it does not change anyone's level, status or score. The wording does not blame the person. Not raised before launch (learning).

### The advice loop

Every alert goal and every suggestion says what it is meant to move: `verify: {indicator, after_days}` (for example `al_screens` verifies `sleep` after 3 days, the sleep suggestion verifies `sleep` after 7). When the person ticks an alert goal for the first time, or accepts a suggestion, Canary opens a small experiment in the `advice` table: trigger, action, `start_day`, `check_day = start_day + after_days` and `start_bad`, how far the indicator was from the person's own normal (mean of the last three days, in personal spreads, higher is worse). The rows are written only by routes that change something, never by a GET.

An outcome is a function of the mission day asked about, so the demo clock can jump anywhere: before `check_day` it is `pending`; from `check_day` on it compares the deviation at `check_day` with `start_bad`: `improved` (0.5 spreads better or more), `worse` (0.5 or more) or `same`. The same day always gives the same answer.

Two **rounds** in a row without improvement for the same risk (a round is what was started on the same day; one improved advice saves the round) escalate: the suggestions list gets one different step from a per-risk list (`advice.ALTERNATIVES`, id `alt_fatigue`), and **one** message of kind `advice` goes to the crew medical officer (or the substitute when the patient is the medical officer), written the first time a write route sees it. It never repeats. Advice messages are not shown to the rest of the crew, only to the recipient and the medical console.

Example, Helena:

1. **Day 147.** The fatigue risk is at level 2. She accepts *Protect your sleep window*. Canary stores `start_bad` 2.81 and `check_day` 154. On day 149 `GET /api/advice/h` says `pending`, and the goal carries `advice: {status: "pending", check_day: 154}`.
2. **Day 154.** The check runs: her sleep is 4.11 spreads from normal against 2.81 at the start, `worse`. The goal row reads "Checked on day 154: worse".
3. **Round two.** She tries another step on day 154 (say breathing, verifying stress after 7 days). In the simulation Helena starts to recover around day 160, so in the demo this round ends well. If it did not (the tests build that case on purpose), it would be a second round without improvement.
4. **Escalation.** The suggestions list then shows *Change one thing in your day, not three* (or another alternative), and Kenji's inbox has one `advice` message. Asking again for the same day, or any later day until a new round ends, shows the same alternative and sends nothing more.

Alerts also last: each has `since_day`, `days_active` (found by walking back day by day, at most 60 days, cached, never stored) and `seen`. `POST /api/alerts/{crew}/{alert}/seen` marks the current episode; if the alert goes away and comes back it is a new episode and not seen. While the fatigue risk is at level 1 or 2 the day's exercise goal is lighter and says why (`adjusted: {pct, minutes, target, reason, max_pct}`), by the percentage the medical team sets in `PUT /api/medical/exercise-adjust` (default 15% at level 1 and 30% at level 2, never above `max_pct`). Canary never goes beyond that limit and does not prescribe.

### After an emergency, and who is told

Each protocol in `data/protocols.json` carries `window_days` (the care window, whole days, rounded up from the text of `after`), `ops` (`full`, `limited` or `rest`) and `after_days` (days of each follow-up item; empty means the window). `GET /api/protocols` returns them as `window_days`, `ops` and `after_items: [{title, days}]` next to the unchanged `after`. Closing an emergency on day D (`POST /api/emergencies/{id}` with `close`, once; closing again changes nothing):

- each follow-up goal lasts its own days (seizure: glucose 1 day, no critical task 3 days, medication review 1 day; radiation: blood count 7 days);
- a row in `care_events` records protocol, day and outcome (origin `user`, source `emergency:{id}`); it is shown as `care_events` in `GET /api/crew/{id}` and in the medical overview, newest first;
- the window runs from D to D + `window_days`, both days included. The mission clock has a resolution of one day, so a seizure closed on day 153 restricts days 153 to 156 and the patient is back to normal on 157. Everything is a function of the day asked about: moving the clock back before D shows no event;
- `ops` in the patient's `operational status` is at least the protocol's, and says `reason` and `until_day` (the last restricted day);
- the patient's thresholds are multiplied by `factor` (default 0.8: 1.5σ becomes 1.2σ and 2.5σ becomes 2.0σ) for every indicator, and `sensitive_until` appears on those indicators. Nobody else's thresholds change. The medical team sets it with `PUT /api/medical/care-sensitivity {factor}` (0.5 to 1.0).

`notify.sync` runs in the routes that write (`PUT /api/mission`, `POST /api/checkins` for that person, and the close of an emergency), never in a GET, and writes nothing twice: the `notices` primary key is the episode. An alert that stays active longer than the 60-day look-back is the same episode for notices.

### Where a value comes from and how old it is

`telemetry.observation()` returns `{value, origin, source, day}` and is the only reader behind `current()`, `series()` and the assistant's trends:

1. A self check-in of that day wins: `origin: "user"`, `source: "checkin:<crew>:<kind>:day<D>"`. Fields read: mood (mood, stress), pvt (ms), sleep (hours), vitals (hr, bp, temp, spo2), dsst (correct), span (span), kss (level), tlx (raw). Other tests are stored but are not indicators (amsler, symptoms and wellbeing feed their own alert rules; reading and journal only complete goals).
2. Otherwise the last row of the observation file up to that day, with the origin of the row (`simulated` or `real`).

Each indicator in `GET /api/crew/{id}` also says `origin` (where today's value came from), `last_measured_day` and `age_days` (days since the person last measured it themselves; `null` if never). The four cognitive and self-report indicators (`dsst`, `span`, `kss`, `tlx`, Brain & mind) follow the same baseline, spread and thresholds as the others.

### Reference ranges and their sources

Canary compares every number with two references. The **population range** is the safety limit: outside it the indicator is at least level 1, and past a *critical* limit it is level 2 on its own (even before launch, even when the personal numbers look fine; it is judged on the day's reading, not the three-day blend). The **personal baseline** is the early warning: mean of the person's measurements on the plan's pre-flight days (file rows plus their own check-ins; the mean is shown at the app's precision, the spread never goes below the catalog's `sd`; with fewer than 5 pre-flight measurements, or no pre-flight leg, the catalog seed is used). Inside the population range the personal z-score still decides, as before. Thresholds can be overridden for one indicator with the setting `thresholds_by_indicator` (`{"sleep": {"watch": 1.0, "act": 2.0}}`); there is no screen for it.

<!-- reference-table:start (generated from backend/canary/domain/reference.py) -->
| Indicator | Unit | Low | High | Critical (below / above) | Source | Verified |
| --- | --- | --- | --- | --- | --- | :---: |
| `hr` Resting pulse | bpm | 40 | 100 | 30 / 150 | AHA: resting heart rate 60 to 100 bpm in adults, 40 to 60 is common in trained people. Critical limits: prototype assumption | no |
| `bp` Blood pressure | mmHg | 90 | 139 | 70 / 180 | Systolic pressure. Below 90 is low blood pressure; 140 or more is hypertension (ESC/ESH 2018); above 180 is the AHA hypertensive-crisis line. Critical low: prototype assumption | no |
| `spo2` Blood oxygen | % | 95 | 100 | 90 / - | Usual pulse-oximetry range 95 to 100%; below 90% is hypoxaemia (WHO pulse oximetry training manual) | no |
| `temp` Temperature | °C | 36.1 | 37.2 | 35 / 40 | MedlinePlus: normal body temperature about 36.1 to 37.2 °C; below 35 °C is hypothermia; above 40 °C is hyperpyrexia | no |
| `gluc` Fasting glucose | mg/dL | 70 | 99 | 54 / - | ADA Standards of Care: fasting normal below 100 mg/dL; level 2 hypoglycaemia below 54 mg/dL. Low edge 70: ADA level 1 | no |
| `sleep` Sleep | h | 6 | 10 | - | National Sleep Foundation 2015: 7 to 9 h recommended for adults, 6 to 10 h may be appropriate | no |
| `water` Water | L | F 1.6 / M 2 | - | - | EFSA 2010: adequate intake from drinks about 1.6 L (women) and 2.0 L (men) | no |
| `exer` Exercise | min | 21 | - | - | WHO 2020 physical activity guidelines: 150 min a week of moderate activity, about 21 min a day | no |
| `grip` Grip strength | kg | F 16 / M 27 | - | - | EWGSOP2 2019 sarcopenia cut-offs: grip below 16 kg (women) or 27 kg (men) is low strength | no |
| `kss` Sleepiness | /9 | - | 6 | - | Karolinska Sleepiness Scale (Åkerstedt and Gillberg 1990): 7 or more means sleepy | no |
| `react` Reaction time | ms | 150 | 500 | - | prototype assumption: wide on purpose, the result depends on the device and screen lag | no |
| `dsst` Processing speed | correct | 20 | 100 | - | prototype assumption: wide on purpose, depends on the task version and device | no |
| `span` Working memory | digits | 4 | 10 | - | prototype assumption: wide on purpose; forward digit span of adults is usually 5 to 9 | no |

No population range (personal or relative scales): `mood`, `stress`, `social`, `tlx`, `bone`.
<!-- reference-table:end -->

None of these ranges is `verified`: they are known clinical references written down for the prototype, to be checked by the team before the pitch. Critical limits without a guideline are marked as prototype assumptions, and the PVT, DSST and span ranges are wide on purpose because they depend on the device. They are risk limits, not diagnoses.

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
| `assistant/tools.py` | Read-only tools a model can call (`get_status`, `get_indicator`, `explain_system`, `get_risks`, `get_protocol`, `list_goals`); each result carries source ids. `route()` is the rule-based stand-in for tool choice |
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
| [OSDR OSD-569](https://osdr.nasa.gov/bio/repo/data/studies/OSD-569) Inspiration4 blood counts | Real blood counts across 7 time points, shown as each crew member's reference, in `data/real/osd569_cbc.csv`, and read by the `immune` and `radiation` risks (low lymphocytes) | Blood & immunity panel, risks |
| [NASA HRP hazards and risks](https://www.nasa.gov/hrp/hazards/) | The five hazards (RIDGE) behind every body system | System cards, assistant knowledge |

**Real and simulated, today.** Real: the blood count (OSD-569), the storm days (DONKI, Curiosity RAD). Simulated and labelled so: the mission dose (the same for every crew member), weight, glucose, creatinine, urine, vital signs and everything else in `observations.csv`. **Pending:** the Inspiration4 metabolic panel (OSD-575, glucose and creatinine) is not in the repository yet; when its file is added to `data/raw`, `data/prepare_nasa_data.py` will read it into `data/real/` and `nutrition` and `renal` will turn from `simulated` to `partial`. Cytokines (OSD-575/656) and sex hormones have no open source wired in.

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
    domain/              catalog, registry (crew and mission registered by Mission Control), plan, telemetry, simdata, health, risk, advice, goals, privacy, protocols, nasa, mission, selftests
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
    pages/               Intro, Setup (admin preview), Crew (home), Astronaut (public card or medical view), MySpace (Health, Goals, Suggestions, Patches, Dashboard, My information, Settings), MissionInfo, Control (Canary Control), Tests, Settings, Ranking, MissionPlan, Medical, About
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
| `GET /api/mission/overview` | The mission and the crew as a whole (public on board, no health data) |
| `POST /api/control/session` · `GET /api/control/overview` · `GET /api/control/demo` · `POST /api/control/register` · `POST /api/control/clear` | Canary Control (Mission Control PIN, its own token): sign in, follow the crew, the demo form, register crew and mission, start from zero |
| `GET /api/crew/{id}/record` | My information: the personal record (the astronaut and the medical team) |
| `GET /api/suggestions/{id}` · `POST /api/suggestions/{id}/{sid}/accept` | Personal suggestions (the astronaut only) · turn one into a goal for 7 days |
| `POST /api/checkins` · `GET /api/checkins/{id}` | Save a test or log, returns `conclusion` {population, personal, text} (self only; vitals outside the typing limits, such as a pulse of 900, return 400) · every test with its latest result and the recent log (self and medical team) |
| `GET /api/crew/photos` · `PUT/DELETE /api/crew/{id}/photo` | Profile photos (the astronaut sets their own) |
| `GET /api/leaderboard` | Ranking and crew missions |
| `GET /api/protocols` · `POST /api/emergencies` · `POST /api/emergencies/{id}` | Guided Response bank resolved for the place · open · log, close |
| `GET/POST /api/messages` | Messages with communication delay |
| `GET /api/plan/conditions` | Each leg's five hazards (computed from the plan, with `basis`) and dose, plus the projected mission dose against the career limit |
| `GET /api/crew/{id}` → `risks[]` | Eight risks with `nasa_red`, `data`, `hazards`, `hazard_links`, `hazard_note`, `panel_due`; each alert gains `risk`, `hazards`, `hazard_note` |
| `GET /api/space-weather` · `GET /api/nasa/rad` | NASA data (used by alerts and the story; no page of their own) |
| `GET /api/advice/{id}` | The advice loop: advice in progress and concluded with the outcome, and the escalation (the person and the medical team only) |
| `POST /api/alerts/{id}/{alert}/seen` | Mark today's episode of an alert as seen (the person only) |
| `GET/PUT /api/medical/exercise-adjust` | Maximum lightening of the day's exercise under fatigue (medical console) |
| `GET/PUT /api/medical/care-sensitivity` | How much tighter the patient's thresholds are during the care window after an emergency (medical console) |
| `GET /api/medical/overview` → `notices`, `care_events` | Critical alerts sent to the medical officer, and each person's closed emergencies (medical console) |
| `GET /api/crew/{id}` → `risks` | Risk layer: level, score, trend, since_day and evidence (fatigue so far) |
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
- **Prototype assumptions of this layer (`verified: false`):** the baselines, spreads and fatigue effects of `dsst`, `span`, `kss`, `tlx` (see `catalog.INDICATOR_NOTES`; the KSS and NASA-TLX scales are published, the numbers are not), and the vitals typing limits in `selftests.VITALS_LIMITS` (hr 20 to 250, bp 50 to 260, temp 30 to 45, spo2 50 to 100). The limits only catch typos; they are not clinical ranges.
- **Risk layer (prototype assumptions, `verified: false`):** the fatigue weights, the cuts (2.0 and 4.0 points), the minimum of 3 signals, the 2-day sustain rule, the 3-day trend (±0.5), the drift window (14 days, 10 days ahead, minimum slope 0.08 spreads a day) and the 60-day look-back. They were tuned on the simulated crew, not on flight data. The Physical and Mental readiness scores are also a design choice (18 points per spread beyond 0.6, minus 6 per level of eyes, skin and immune), not a published score.
- **Advice loop (prototype assumptions, `verified: false`):** the `verify` pairs (indicator and days for each alert goal and suggestion), the 0.5-spread margin and the 3-day average that decide improved / same / worse, the rule of two rounds, the alternative steps per risk, the 60-day look-back of `days_active` and the default exercise reductions (15% and 30%, at most 30%). The reductions are placeholders for the flight surgeon; nothing here has been clinically reviewed.
- **Care windows (prototype assumptions, `verified: false`):** every `window_days`, `ops` and `after_days` in `protocols.json` is read from the illustrative text of `after` and rounded up to whole days (`care_note`); the 0.8 sensitivity factor (adjustable, no published rule says how much tighter a recovering patient should be watched); the radiation protocol as `full` (follow-up tests, no restriction). Windows are in whole days because the mission clock is. Critical alerts reach the medical officer when a write route runs `notify.sync`, not by a background clock, because nothing in the system depends on real time.
- **Risks (prototype assumptions, `verified: false`):** every weight and cut of the seven new risks (table above), the weight-loss cuts (5% and 10%), the 1%-in-30-days bone rate, the creatinine range (usual laboratory reference, from memory) and the 1,500 mL/24 h urine volume, the panel intervals (30 and 15 days), the RIDGE cuts and the per-place environment level, and every link of the hazard matrix (sources "HRP" and "Patel 2020" still to be checked, plus the five prototype-assumption links). The mission dose is the same for everyone. Hormones and other data without an open source are left out.
- **Reference ranges to verify:** every entry of `reference.POPULATION` is `verified: false` (table above). Simulated glucose of Tomás sits just above 99 mg/dL on a few isolated days (level 1, none in a story scene).
- **Tests never taken:** the Tests page still says "Not done yet" for a test the person never did, even when the file has simulated history for that indicator. No check-ins are invented for the past.
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
