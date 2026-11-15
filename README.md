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
5. [Mission data](#mission-data)
6. [Live data](#live-data)
7. [Architecture](#architecture)
8. [The AI slot](#the-ai-slot)
9. [NASA data](#nasa-data)
10. [The 3D body](#the-3d-body)
11. [Project layout](#project-layout)
12. [API](#api)
13. [How it maps to the judging criteria](#how-it-maps-to-the-judging-criteria)
14. [What to build next](#what-to-build-next)
15. [Input checks](#input-checks)
16. [Limits, honestly](#limits-honestly)
17. [Credits and licences](#credits-and-licences)

---

## Run it

Needs **Python 3.9+** and **Node 18+**.

```bash
make setup     # backend venv + npm install
make dev       # API on :8000 and web app on :5173
```

Open <http://localhost:5173>. The intro plays once and ends on the mission as mission control configured it (itinerary drawn in, crew introduced), then Canary opens on the **crew**: goals, hazards and crew missions, never anyone's health or status. To see your own health, open **My space**: choose your profile and type your **4-digit PIN**. Mission setup and astronaut registration belong to a future **mission-admin flow**; a preview of setup lives at `/setup` (not linked from the crew screens). The **Demo story** bar at the bottom walks through the scenes of the loaded mission package (six in the demo; no scenes, no bar) and offers "Enter as …", which opens the PIN pad for the person each scene follows (it never skips the PIN).

Demo PINs (public, for the demo only; they come from the demo package's `crew.csv`): Helena `1001`, Kenji `1002`, Amara `1003`, Tomás `1004`; medical console `1961`; Mission Control (Canary Control) `4242`.

Without `make`:

```bash
cd backend && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn canary.main:app --reload --port 8000
```

On Windows the virtualenv keeps its programs in `.venv\Scripts` (the Makefile picks it by itself): `py -m venv .venv`, then `.venv\Scripts\pip install -r requirements.txt` and `.venv\Scripts\uvicorn canary.main:app --reload --port 8000`. Every data file is read as UTF-8, so accents and the `°C` unit come out right on any system.

```bash
cd frontend && npm install && npm run dev
```

Other commands:

| Command | What it does |
| --- | --- |
| `make test` | backend tests (the demo's golden snapshots, ingest and import, empty and stale data, crew of 1 to 6, clock, dose and storms, alerts, risks, advice, story, mission plan, setup and conditions, goals, privacy, hazards, PINs and sessions, Mission Control, assistant guard, API) and the frontend type check |
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
| `CANARY_CREW_PINS` | `h:1001,k:1002,a:1003,t:1004` | fallback 4-digit PIN for an id that has no stored PIN. Every registered or imported person's PIN is stored salted and hashed (PBKDF2-SHA256) in the `settings` table, and so is one changed in the app; a stored PIN always wins |
| `CANARY_TOKEN_SECRET` | random per start | signs medical and crew session tokens (set it to keep sessions across restarts) |
| `CANARY_TOKEN_TTL` | `3600` | lifetime of a session token, in seconds |
| `CANARY_FRONTEND_DIST` | `frontend/dist` | folder with the built web app that the API serves (`make serve`) |
| `CANARY_DELAY_SPEEDUP` | `20` | communication delay runs this many times faster in the demo |
| `CANARY_LIVE_SPACE_WEATHER` | `0` | `1` also asks NASA DONKI for the last 30 days: each solar particle event becomes a space event, but only while the mission clock follows the real date. Offline or rate-limited, nothing happens |
| `NASA_API_KEY` | `DEMO_KEY` | key for api.nasa.gov |
| `CANARY_INGEST_KEY` | empty | secret a sensor, wearable or lab sends in the `X-Canary-Key` header of `POST /api/observations`. Empty: ingest is off (503). Control › Data only says "configured" or "off", never the key. See [Live data](#live-data) |
| `CANARY_MISSION_PACKAGE` | `odyssey1-mars` | bundled package (a folder under `data/missions`) loaded on the first start, when the database holds no data and no crew, and by **Reset demo**. Set it to `""` for an empty start: no crew, no readings, no scenes. See [Mission data](#mission-data) |
| `CANARY_MISSIONS_DIR` | `data/missions` | where bundled packages are looked up by name |
| `CANARY_DAY_SYNC` | `1` | `1` starts the background thread that notices a new mission day and runs what a new day triggers (advice follow-ups, critical-alert notices); `0` leaves that to the next write |
| `CANARY_DAY_SYNC_SECONDS` | `600` | how often that thread looks (and, with `CANARY_LIVE_SPACE_WEATHER=1`, asks DONKI) |
| `CANARY_WARM` | `1` | `1` computes each person's health once at start-up so the first click is quick; `0` skips it |
| `CANARY_PBKDF2_ITERATIONS` | `100000` | rounds of the PIN hash. Leave it alone: a stored hash does not record the count, so changing it locks every stored PIN out. The test suite sets it low to run fast |
| `CANARY_LLM_PROVIDER` | `none` | `none`, `anthropic` or `local` (see [The AI slot](#the-ai-slot)) |

---

## What it does

A sidebar in three groups (**Crew**: Crew, Tests, Mission plan, Ranking; **Your health**: My space; **Support**: Ask Canary, Medical console, Settings, About & data), **crew first**: the system always opens on the whole crew, and your own data sits behind your private space. Each page reads top to bottom like a dashboard: the most important thing first, details further down.

| Page | What you see |
| --- | --- |
| **Intro** | Four beats of the canary story over a starfield while the body assembles, then **Your mission**: the configured itinerary draws itself in and the crew is introduced. Nothing to fill in |
| **Admin setup preview** (`/setup`) | Not part of the crew flow; a preview of the future mission-admin flow. | Full-screen, four steps: pick the destination (space station, Moon, Mars with gravity, Earth reply delay and radiation), set the length of every part with a live timeline that re-proportions as you type, meet the crew, review and launch (a 3-2-1 over the timeline). The defaults reproduce the three presets exactly; Mars can add a return trip. "Use the demo story" takes the Mars preset |
| **Mission** (`/mission`, the callsign chip in the top bar) | The mission and the crew as a whole, public on board: callsign and name, launch date, today's mission date, destination, where the crew is now, a card per astronaut (role, agency, home, nationality, languages, previous flights; no health) and the itinerary. From here, **Switch to Mission Control mode** |
| **Canary Control** (`/control`, Mission Control mode) | The other side of the system, in its own mode with its own accent. Opens with the Mission Control PIN (demo `4242`). **Dashboard**: callsign, mission time, signal delay and dose; each astronaut with the operational status the ship's medical team reports, goals today and the last self-test; the five hazards; emergencies; **Start from zero** clears crew and mission (and the scenes of a loaded package). **Register crew and mission**: a list of one to six people, each with every field of My information plus a first PIN (add and remove people), a **Fill with the demo crew and mission** button, then callsign, name, launch date and mission profile, then review and **Save and activate Canary**. **Data**: load a bundled package or upload a zip or CSV files, the mission clock, whether sensor ingest is on, readings received (dates and counts, never values) and space events (see [Live data](#live-data)). **Messages**: write to the ship's medical team and read the traffic coming down, all with the real signal delay |
| **Crew** (home) | Every registered astronaut (one to six) as neutral dots with today's routine. **Hazards here today**: NASA's five hazards of spaceflight (radiation, isolation, distance, gravity, closed environment) rated low, moderate or high for the current place, a solar storm warning on top when one hits; tap a hazard to see which body systems it acts on. **Crew missions** in their own full-width section with the crew streak. **Who sees what** folded at the bottom. No status, no scores, no vitals, no averages |
| **My space** (private, under Your health) | Locked, it shows only a padlock, **Choose your profile** and four profile buttons; a profile asks for its 4-digit PIN. Inside, seven tabs: **Health**, **Goals**, **Suggestions**, **Patches**, **Dashboard** (every chart), **My information** and **Settings** (profile photo, Change PIN, Lock). Signed in, your profile at the foot of the sidebar opens a menu with **Open my space**, **My settings** and **Lock my space** |
| My space · **Health** | Top: the 3D body and, beside it, one sentence on how you are, up to three numbered steps and your Physical and Mental scores. The **Physical / Mental** switch changes the body's lens and the numbers below it: Physical shows only the physical systems, Mental only the mental facets, always as number tiles (value, your normal, status colour). Beside the body the right column stacks **Needs attention** (alerts and NASA risks above level 0, one line each, with the hazards they come from), **Ready for EVA?** (VO2max, grip strength and bone against NASA-STD-3001, for the place you are at; "No EVA in your role" when the role has none) and the scores. Click a part of the body or a tile and the top area becomes that system (what it means, what to do, a check to run, its risks and its "How to measure and why"), without repeating the numbers; for radiation it shows the career dose bar. The body column always matches the height of that panel. Charts are on the Dashboard tab |
| My space · **Goals** | One line of summary (done today, streak, 7-day completion), then **Physical** and **Mental** as separate, roomy lists with their own progress, then the crew missions. No points, no levels: goals are goals |
| My space · **Suggestions** | The AI slot's third entry. Personal recommendations built from your numbers against your own normal, how often you met each goal this week, your test results and the next leg of the plan: protect your sleep window, more time with the crew, read more (or keep going with the book you logged), start a small hobby (sketching the view, a crewmate's language, the plant chamber), breathing after shift, exercise, hydration, preparing for the next gravity change, staying close to home, talking to someone. Each card says why with your own numbers, gives three steps and can be added to your goals for 7 days |
| My space · **My information** | The personal record Mission Control registered before flight, read-only: identity (name, date of birth, age that follows the mission clock, sex, nationality, home, languages), body (height, weight, BMI, blood type, Fitzpatrick skin type, dominant hand, vision), medical (allergies, medications, conditions, diet, vaccinations) and mission (role, agency, previous flights and days in space, emergency contact through family support). Private to the astronaut and the medical team; corrections go through the flight surgeon |
| My space · **Patches** | The nine mission patches on their own page, with progress towards the ones not earned yet |
| **Tests** (Crew group, private results) | Choose your profile and enter the PIN, then run any test or log: **Cognition** (reaction time, processing speed as a digit-symbol task, working memory as a digit span, the kinds of task in NASA's Cognition battery), **How you feel** (mood and stress, Karolinska Sleepiness Scale, NASA-TLX workload, PHQ-2 and GAD-2 wellbeing), **Body** (vital signs, Amsler grid, symptoms) and **Logs** (sleep diary, reading, a three-line journal whose text is never saved). Each row shows the last result and folds a **How and why** (see [How to measure and why](#how-to-measure-and-why)); a saved check ends on a result screen that compares it with your own normal and with the population range, and the vitals form takes the optional photo described under [Who sees what](#who-sees-what). Results feed your health, complete matching goals and can raise a gentle alert (very sleepy, a hard stretch, strong symptoms) |
| My space · **Dashboard** | The last 30 days of every indicator against your normal, each chart with its own axis around the data, a NASA limit line where the standard has one (VO2max, grip, bone; bone is drawn as % of pre-flight with a 7-day average) and a tag for where the numbers come from (simulated, real NASA data, or typed by you). Then goals done in the last 14 days and **Blood**: a picker for every analyte of the real NASA blood and metabolic panels (OSD-569 and OSD-575) with the laboratory range for your sex and the out-of-range points coloured |
| **Medical console** (Support group, PIN) | Six tabs. **Triage**: one flat row per astronaut with operational status and its reason, the care window, the two top alerts and the red NASA risks, the critical alerts sent (folded) and a table of every indicator for everyone side by side, with a **NASA limit** column and a **Career dose** row. **Briefings** (drafts for Earth, approve), **Prescribe** (a goal for one astronaut), **Alert rules** (watch and act thresholds for the whole crew), **Messages** and **Emergencies**. A person's page adds Ready for EVA?, the risks with evidence and origin, the care events, the career radiation dose and the photos of the display kept with their vitals check-ins |
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
| Photo of a vitals display (check-in photo) | Yes | Yes | No | No |
| Hazards and crew goals | Yes | Yes | Yes | Yes |

Where each piece of information lives. This is the funnel: general pages say what is the same for everyone, My space and the medical console say what is personal, Canary Control registers and follows.

| Information | General pages (Crew, Mission plan, Mission) | My space | Medical console | Canary Control |
| --- | --- | --- | --- | --- |
| Hazards, place and **mission dose** (the same for everyone) | Yes | Inside the career dose bar | Inside the career dose | Yes |
| **Career dose** and earlier flights in mSv | No (one line says it is in My space) | Yes | Yes (a column) | No |
| **Ready for EVA?** (VO2max, grip, bone against NASA) | No | Yes | Yes | No (only the operational status, as before) |
| Seven risks, evidence and data origin | No | Yes | Yes | No |
| Care window after an emergency | No | One line | Yes | No |
| Check-in photos | No | Your own | Yes | No |
| **EVA role** and earlier dose (registration) | No | Read only, in My information | Yes | Yes (registered here) |
| Rover legs on the itinerary | Yes | n/a | n/a | Yes (registered here) |

Tests keep this: no crew-wide endpoint returns another person's career dose, risks, EVA readiness or photo, and `GET /api/mission/overview` carries no health at all.

How the API enforces it:

- **Operational status is medical-only.** Diagnoses such as "Fit for all duties" or "Off critical tasks" are visible to the medical team and to the person themself in their private space. The crew never sees anyone's status; the Crew page shows only whether EVA is possible at all (environment) and says the medical team clears each person.
- **Entry is by PIN.** `POST /api/crew/{id}/session {"pin"}` returns a signed token `{id}.{exp}.{sig}` (HMAC-SHA256 over `crew:{id}:{exp}`, one hour). The web app keeps it in `sessionStorage` and sends it in the `X-Canary-Viewer` header; a bare id, a forged or an expired token is nobody (403 on private routes). Five wrong PINs in 60 seconds lock that person for a minute (429). `PUT /api/crew/{id}/pin` changes your PIN (needs your token and the current PIN). The medical console works the same way with its own PIN and a bearer token.
- **Check-in photos (C2).** On a vital-signs check-in you can add a photo of the device's display (`<input capture="environment">` on a phone). The browser shrinks it to 1024 px on the long edge as a JPEG before sending; `POST /api/checkins` takes it as the optional `photo` data URL, for vitals only (PNG, JPEG or WebP checked by its first bytes, at most 600 KB, else 422 with field `photo`). It lives in its own table, `checkin_photos(checkin_id, crew_id, data_url, created_at)`, never in the check-in payload, so it feeds no chart, alert or assistant answer: the numbers typed are what counts, the photo is evidence. `GET /api/checkins/{id}` and the crew detail only say `has_photo`; `GET /api/checkins/{id}/{checkin_id}/photo` returns it to that person and the medical team (403 to anyone else), and a demo reset deletes it. It never appears in the crew overview, leaderboard, mission overview or Canary Control.
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
| Day label | L-30 before launch, Sol N on Mars counted from landing (a rover traverse does not restart the count), Day N otherwise |
| NASA flight limits | the kind of EVA done at the place (none, microgravity or surface) sets the aerobic-capacity minimum (NASA-STD-3001 V1 4001 / 4002) |

The places are Earth, launch, the space station, deep-space transit, the Moon, Mars and a **pressurized rover** on each (`moon_rover`, `mars_rover`): partial gravity, surface EVAs, the delay and hospital distance of their planet, a short exercise goal in the cabin and the Guided Response variants of their planet. The Mars reference mission has a 14-day rover traverse (days 300 to 313) inside the surface stay and the lunar mission a 5-day one (days 20 to 24). A rover is given its planet's surface dose rate (prototype assumption: no rover shielding figure is used).

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

**Goals.** Personal goals for the body (exercise by place, water, vitals, mobility, calcium, Amsler grid) and the mind (sleep, reaction test, mood check-in, meditation or prayer, reading, crew time, films and music, calls home, looking homeward, journal). Crew missions are shared weekly targets counted from routine goals ticked, never from measurements (24 exercise sessions, 5 crew meals, 20 meditation sessions, book club, movie nights). Streaks and nine mission patches; no points or levels.

**Warnings.** Each indicator is a z-score against the person's own pre-flight baseline. The medical team sets the thresholds. Cross-signal rules catch what single numbers miss: sleep + mood + reaction time together, high pulse + low water in the first 72 h, low pressure + high pulse back in gravity, a wavy Amsler grid, a solar particle event. Every warning says what it means, what to do now, and adds goals.

**Guided Response.** Not a panic button: a calm, deterministic guide. Protocols are data (`backend/canary/data/protocols.json`) with variants for 0 g, partial gravity and Earth, and for each place. Closing it adds follow-up goals for the patient and queues a report for Earth.

**The ranking counts effort, never vital signs.** It is the one place where individuals are compared, and only by participation: routine goals done (check-ins included) in the last 7 days. Goals added by an alert, the medical team or a suggestion count only in the person's own space: they come from health data, so a jump in someone's public total would tell the crew they have an alert or a prescription. The ranking API sends only what the page shows (goals, completion, streak, patch count), never the split by area, the day-by-day counts or patch progress. There are no points or levels. Goals come from goals done and check-ins sent. A hard day reported honestly earns the same as a good one, so nobody gains by hiding a symptom.

---

## No accounts: how crew and mission get on board

Nobody creates an account in Canary. **Mission Control registers** the crew, from one to six astronauts (their record and a first PIN) and the mission (callsign, name, launch date, profile) in Canary Control; the crew terminals simply use what was registered. Before that, every crew screen says **Waiting for Mission Control**.

- Each astronaut opens their space with the PIN Mission Control set and can change it on board. The medical console and Canary Control have their own PINs and their own tokens; one never opens the other.
- Each person also takes an **EVA role** (surface EVAs, microgravity EVAs or no EVA; it picks the NASA aerobic limit) and, optionally, the **dose from earlier flights** in mSv (0 to 600). Left empty, the form says "Estimated from days in space" and shows the estimate, the days already flown times the station's daily dose. Both are personal: they show in My information and to the medical team, never on the crew pages, the Mission page, the ranking or the Control dashboard (a test checks it).
- On the Moon and Mars profiles the mission step offers a **Rover leg** (on by default): a pressurized rover traverse inside the surface stay (Moon days 20 to 24, Mars days 300 to 313). Without it the same days stay surface stay, so the length and every day number are unchanged. The review step draws the itinerary. The API takes `mission.rover` (`true` or `false`) and refuses `true` on a profile with no rover (422, field `mission.rover`).
- The crew is whoever is registered. Each person has an id: the `id` column of `crew.csv`, or `s1` to `s6` in order when the form leaves it out (registering the same people in the same order keeps the ids). Ids and PINs are unique; the form answers on `crew.N.seat` (the wire name of the id) and `crew.N.pin`, and on `crew` when there are fewer than 1 or more than 6 people. A registered person carries only what was registered: their normal is learned from their own measurements, their age comes from the date of birth and their lab ranges from the sex in their record. The crew exercise target is 6 sessions per person per week (24 for four); a crew day needs three quarters of the crew.
- With nothing registered the system has no crew and no fallback crew. A demo reset loads the demo mission package, which registers the demo crew through its `crew.csv`; **Start from zero** in Canary Control clears them for a live registration. Registering a crew by hand (or starting from zero) also drops the package's scenes, its marker and its own space events, because they describe people who are no longer on board; events added through the API or imported from DONKI stay. Loading a package again brings them back.
- PINs are stored salted and hashed (PBKDF2-SHA256) and never leave the server: not in a response, not in Control › Data.
- Next step for a real mission: the registration travels to the ship as a signed mission package (Mission Control holds the private key, the ship only the public one), with signed incremental updates during flight.

---

## The demo story

The bar at the bottom of every screen drives the story of the loaded package. The story is data, not code: each scene is a row of the package's `scenes.csv` (day, place, person, sentence) and the bar reads `GET /api/scenes`. With no scenes (an empty start, a hand-registered crew) the bar does not appear. The demo package has six; each step sets the mission day, the place and the suggested crew member. The storms of scenes 4 and 6 are rows of `space_events.csv`, not special days.

| # | Scene | What to show |
| --- | --- | --- |
| 1 | **L-30, Earth** | Canary is learning everyone's normal. No alerts. |
| 2 | **Day 2, launch** | Tomás: fast pulse, little water. Space sickness alert with hydration goals. |
| 3 | **Day 147, Mars transit** | Helena: sleep, mood, focus and crew time slipping together. The brain is red on the body, the Mental tiles show the slide. Take the reaction test, or Ask why. Tomás, a geologist who will walk on Mars, gets a watch from NASA's standard (see the EVA moment below). |
| 4 | **Day 152, replay of 10 May 2024** | NASA DONKI's real storm. Everyone to the shelter, radiation protocol. |
| 5 | **Day 153, dinner** | Kenji's terminal. Tomás has a seizure: hold EMERGENCY, pick Seizure, follow the steps, close and report. Then see the follow-up goals and the report in the medical console. |
| 6 | **Sol 12 on Mars, replay of 20 May 2024** | Curiosity RAD measured 51× the normal dose. Gravity re-adaptation for everyone. |

**The EVA moment (scene 3, as Tomás).** Open My space → Health and read **Ready for EVA?**. In deep-space transit his VO2max line is yellow: it meets the 32.9 mL/kg/min minimum for microgravity EVAs (V1 4001) but not the 36.5 for the surface EVAs he is there to do (V1 4002), and the card says so. Now change **Where you are** (top left) to Mars. The card re-reads the standard for the new place and the line turns red: on the surface the minimum is V1 4002, 36.5, and his value is below it. Nothing about Tomás changed, only the place, which is the point: NASA's limits depend on where the work is. Switch back to transit and it returns to yellow. Kenji's console shows the same rows on Tomás's page.

---

## Mission data

Canary reads a mission only from data. The engine has no crew, no dates, no storm days and no story of its own: everything it shows comes from the database, and the database is filled from one path, `backend/canary/domain/data.py`, whichever way the data arrives (a package, `POST /api/observations`, a space event added in Control, the script, DONKI).

A **mission package** is a folder of plain spreadsheets (UTF-8 CSV with a header row, a spreadsheet program opens them). The demo ships three, in `data/missions/`: `odyssey1-mars`, `odyssey1-moon` and `odyssey1-iss`. Any subset of the files can be loaded.

| File | Columns | What it holds |
| --- | --- | --- |
| `mission.csv` | `callsign, name, launch_date, preset, simulated_today, simulated_time, source` | One row. The plan preset, the launch date and the simulated "today" (empty: the clock follows the real date) |
| `legs.csv` | `start_day, end_day, location, label` | The itinerary. Day 0 is launch, negative days are pre-flight. `location` is a place the catalog knows (`earth`, `rocket`, `iss`, `moon`, `transit`, `mars`, `moon_rover`, `mars_rover`) |
| `crew.csv` | `id, name, role, initials, home, dob, sex, nationality, languages, agency, flights, days_in_space, height_cm, weight_kg, blood_type, skin_type, handedness, vision, allergies, medications, conditions, diet, vaccinations, emergency_contact, eva, prior_dose_msv, pin` | One row per person, one to six. The same record Mission Control's form fills. Lists such as `languages` are joined with `;`. An empty `prior_dose_msv` means: estimate it from `days_in_space`. The `pin` is stored hashed |
| `observations.csv` | `crew_id, day, indicator, value, unit, origin, method, source, note, measured_at` | One row per measurement. `crew_id` is a person or `cabin`. `measured_at` is a UTC time (launch date plus the day, 08:00 in the demo); `day` alone also works. Indicators and units are the ones of the catalog (`ACCEPT`) |
| `space_events.csv` | `id, kind, start_day, end_day, locations, extra_dose_msv, origin, source, note` | Storms and surface radiation events (see [Live data](#live-data)) |
| `goal_log.csv` | `crew_id, day, goal_id, done, done_at_time` | Which daily goals each person completed. A goal not in the file was not done |
| `scenes.csv` | `index, day, location, person, storm, when, text` | The bookmarks of the Demo story bar |

**Mock and real.** The demo package is mock, generated and labelled as such (`mission.csv` says `mock: generated by data/generate_dataset.py`). What is real NASA data in it: the complete blood count (OSD-569, Inspiration4) and creatinine, potassium, calcium and CRP (OSD-575), which carry `origin = real`, and the two storm replays in `space_events.csv` (NASA DONKI, 10 May 2024, and Curiosity RAD, 20 May 2024). Everything else is simulated and says `origin = simulated`: the other indicators, the cabin dosimeter, the crew (fictional), the goal log, the scenes, and the extra dose of each storm. Each package folder has a README with the same table.

**Regenerate the demo packages.** `python3 data/generate_dataset.py` rewrites the three folders (deterministic, standard library only, no network), `data/DATASET.md` and the reference table `backend/canary/data/observations.csv`. Edit `data/recipes.json` (one recipe per indicator: baseline, spread, drift, how often it is measured, gaps, source) or `data/demo_crew.json` (the demo crew, story and PINs, read only by the generator) and run it again. Real rows put in `data/real/` replace the simulated row with the same crew, day and indicator.

**Load a package.**

- In the app: Canary Control › Data › **Load a bundled package**, or **Upload your own** (one `.zip`, or CSV files named like the package files). After an upload the section says what was loaded (`my-mission.zip`, `3 CSV files`).
- `POST /api/control/import`: JSON `{"package": "odyssey1-mars"}` for a bundled one, or a multipart upload.
- From a terminal, without a server: `CANARY_DB=/path/to/canary.db python3 scripts/load_mission.py data/missions/odyssey1-mars [--reset]`. `--reset` clears the database first. Exit status 0 loaded, 1 refused, 2 not a folder.
- `CANARY_MISSION_PACKAGE` names the package loaded on the first start and by **Reset demo** (default `odyssey1-mars`). Set it to the empty string for an empty start.

Every file is validated before anything is written. One bad row refuses the whole import with the file, the line and the field (`observations.csv: Unknown crew id: x (line 12)`) and nothing is stored; Control › Data lists the first 20. Readings already stored (same person, indicator, time and source) are not stored twice, so loading the same package again adds nothing. Goal-log rows never replace a goal someone ticked in the app.

---

## Live data

Sensors, wearables and labs send readings while the mission runs. They go through the same checks and the same transaction as a package.

**Send readings.** `POST /api/observations` with the ingest key in the `X-Canary-Key` header (the key is `CANARY_INGEST_KEY`; empty means ingest is off and the route answers 503; a wrong key is 401). Up to 5,000 rows per request:

```bash
curl -X POST http://localhost:8000/api/observations \
  -H "Content-Type: application/json" \
  -H "X-Canary-Key: YOUR-INGEST-KEY" \
  -d '{"rows": [
        {"crew_id": "h", "indicator": "sleep", "value": 6.4, "unit": "h",
         "measured_at": "2035-06-12T07:30:00Z", "origin": "real", "method": "wearable", "source": "band:42"},
        {"crew_id": "cabin", "indicator": "co2", "value": 920, "unit": "ppm",
         "measured_at": "2035-06-12T07:30:00Z"}
      ]}'
```

`crew_id` is a registered person or `cabin`; `measured_at` is a UTC time (or send `day`, the mission day). `origin` is `real` or `simulated` (default `real`), `method` is `wearable`, `manual`, `test`, `blood`, `urine`, `environment`, `dosimeter`, `lab` or `sensor` (default `sensor`), and `source` and `note` are free text. The answer is `{"accepted": n, "duplicates": n}`; sending the same batch twice stores it once. One bad row refuses the batch with `422` and `rows.N.field` (`rows.3.value`, "sleep must be between 0 and 24 h") and stores nothing. The accepted indicators, their units and their plausibility ranges are the `ACCEPT` table in `backend/canary/domain/catalog.py`; the ranges catch typos and broken sensors, they are not clinical ranges.

**Missing, old and new.** Canary never fills a gap.

- Each indicator has a `max_age` in days (3 for what is measured daily, 10 for every 2 to 7 days, 21 for weekly tests, 45 for a monthly panel). A reading older than that is **stale**: it is shown as the last measurement ("Last measured day 41"), never counted as today's value, and raises no alert.
- A person or indicator with no reading at all shows **No data yet**, a dash instead of a number, a gap in the charts and a grey system on the 3D body. A person with nothing measured sees "Canary is waiting for your first measurements".
- **Learning your normal**: a person's normal needs 5 measurements of an indicator (before launch, or in their first 14 days). Until then the number is read only against the population range and the NASA standard, never against a stand-in, and the page says "Learning your normal: 2 of 5".

**The mission clock.** The mission day is the clock's date minus the launch date. The clock runs on the **real date** (UTC) unless a **simulated date** is set, which is how the demo sits on 2035. Canary Control › Data shows it and sets it, or `PUT /api/control/clock` with `{"date": "2035-10-31", "time": "12:00"}` (a simulated date) or `{"real": true}` (back to the real one). A background thread (`CANARY_DAY_SYNC`, every `CANARY_DAY_SYNC_SECONDS`) notices a new mission day and runs what a day triggers.

**Space events** are the storms: `kind` `sep` is a solar particle event (it reaches a crew away from Earth), `mars` a radiation event at the Mars surface (the crew waits it out indoors). An event has a first and last mission day, the places it reaches, the extra dose it adds (mSv) and an origin (`real`, `simulated` or `donki`). A storm raises the radiation alert and risk, and the immune "blood count due" warning covers its day and the 13 after it. Add one in Control › Data or with `POST /api/control/space-events`. With `CANARY_LIVE_SPACE_WEATHER=1` and the clock on the real date, NASA DONKI's solar particle events of the last 30 days are imported as events with origin `donki`, when the plan has the crew away from Earth that day; offline, nothing happens.

**Dose** says where it comes from, in `dose.origin`. `measured`: every day so far has a `dose_rate` reading (the person's own dosimeter, else the cabin's). `partial`: some days do. `estimated`: none, so the dose is the rate of each place in the plan plus the extra dose of the events. A measured day already contains its storm, so the event adds nothing on top. Crew-wide pages only ever see the cabin or the plan; a person's own dosimeter shows only in their space and to the medical team.

**The crew** is one to six people. The crew exercise target scales with it (6 sessions per person per week), and a crew day needs three quarters of the crew.

**What Mission Control sees.** Control › Data (`GET /api/control/data-status`) shows what was loaded and when, as counts and dates: readings per person and indicator (when the last one arrived, which mission day, how many), the number of goal entries, events and scenes, and whether ingest is on. Never a value, and nothing about anyone's health.

---

## Architecture

**One Python API, modular inside, one SQLite file.** A spacecraft can't depend on a network or on a cluster of services, and a hackathon team can't maintain one. The only split worth designing for is *on board* versus *ground station*: same code, two deployments, synchronised over a delayed link.

```
 Browser (React + Three.js)                        frontend/
   │  HTTP /api   (Vite proxies in dev; FastAPI serves the build in prod)
   ▼
 Canary API (FastAPI, one process)                 backend/canary/
   ├─ domain/data        the one reader and writer of measurements, space events, scenes and goal history (every way in ends here)
   ├─ domain/telemetry   what the engine asks of the data: the last reading up to a day, its age, whether it is stale
   ├─ domain/dose        mission dose: measured by dosimeters, estimated from the plan otherwise
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
 SQLite                                            what was measured (observations, space events, scenes) and
   (on board, offline)                             what people do: check-ins, goals, messages, emergencies, settings
```

### Decisions

| Decision | Why | Alternatives set aside |
| --- | --- | --- |
| One FastAPI process | Runs offline on board, one thing to deploy and test | Microservices: more failure points, no benefit at this size |
| SQLite | A single file, no server, survives with no network | Postgres: belongs on the ground station later |
| Measurements in one table, written only through `domain/data.py` | A mission package, a sensor and a lab all go through the same checks; real data replaces simulated rows with no code change | Formulas inside the code that nobody can open and check; a reader per source |
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
   unless past the population safety limit or a NASA-STD-3001 limit)  →  colour on the 3D body  →  readiness score
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
| `radiation` | yes | skin | **career** dose (earlier flights + this mission) against NASA's 600 mSv limit (V1 4030) and the day the plan is projected to pass it; a storm in progress (with the 250 mSv event limit, V1 4031); a **low** lymphocyte count | from 50% of the limit **with** a projected crossing (the evidence says "projected to pass it on day N") or a low count / a storm, or the limit passed | 1 day | mission dose simulated and the same for everyone; the earlier-flight part from the record or estimated from days in space (labelled); storm real (DONKI, Curiosity RAD); lymphocytes real or simulated |
| `sans` | yes | eyes | Amsler grid with distortion (2 points), vision symptoms (1 point) in the last 7 days. The Amsler grid is a weak indicator: a clear grid does not rule SANS out | 1 / 2 points | 7 days | check-ins (user) |
| `nutrition` | yes | gut | weight below the person's pre-flight mean (5% = 1 point, 10% = 2), fasting glucose against the person's normal | 1 / 3 points and 2 signals | 7 days | simulated |
| `renal` | no | kidneys | water, the model's bone-loss rate (1% or more in 30 days), creatinine and calcium against the laboratory range for the person's sex, 24 h urine volume against a range | 1 / 3 points and 2 signals | 15 days | creatinine and calcium real (OSD-575) and simulated between collections; the rest simulated |
| `immune` | no | immune | temperature, blood count out of the laboratory range for the person's sex (0.5 each, 1.5 at most), C-reactive protein 50% or more above the person's pre-flight mean (0.5; its panel has no range), the days after a storm | 1 / 3 points and 2 signals | 30 days | blood count and CRP real (OSD-569, OSD-575) and simulated between collections |
| `cardio` | no | heart, lungs | pulse, pressure, oxygen, aerobic capacity (`vo2`, with NASA's EVA minimum as a floor), potassium against the laboratory range; the re-adaptation pattern after the change to partial gravity (the `regravity` alert belongs here) | 1 / 4 points and 3 signals; a NASA limit sets the floor | 1 day | simulated, plus check-ins; potassium real (OSD-575) |
| `bone_muscle` | no | skeleton, muscles | bone estimate, grip, exercise; NASA's 95% bone and 80% strength limits as a floor | 1 / 4 points and 3 signals; a NASA limit sets the floor | 30 days | simulated |

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
2. Otherwise the last stored observation up to that day, with the origin of the row (`simulated` or `real`). A reading older than the indicator's `max_age` is stale and does not count as a current value.

Each indicator in `GET /api/crew/{id}` also says `origin` (where today's value came from), `last_measured_day` and `age_days` (days since the person last measured it themselves; `null` if never). The four cognitive and self-report indicators (`dsst`, `span`, `kss`, `tlx`, Brain & mind) follow the same baseline, spread and thresholds as the others.

### How to measure and why

Each indicator can explain itself: how to measure it in flight, what spaceflight does to it, what to do at each colour and how often to check. The texts come from the team's indicator guide in `data/indicator_guide/` (`indicadores.json`, written in Portuguese for the team's research; `texts_en.json` is its English translation, nothing added; `id_map.json` maps the guide's ids to Canary's). `domain/guide.py` serves them in `GET /api/catalog` → `guide`, and the web app shows them folded as **How to measure and why** on each Dashboard chart, in the system panel of My space → Health and as **How and why** on each Tests row.

Every text carries the source the guide lists for it, and the app never invents one. The guide gives none for how to measure, so that line reads **No source checked yet**; the effect line cites the NASA risk page when the guide names one, and the actions cite the sources listed for their colour rules. The guide's own numbers are not used: every limit comes from `reference.py` and `standards.py`, and where they disagree those files win.

### Reference ranges and their sources

Canary compares every number with three references: the two below and NASA's flight limits (next section). The **population range** is the safety limit: outside it the indicator is at least level 1, and past a *critical* limit it is level 2 on its own (even before launch, even when the personal numbers look fine; it is judged on the day's reading, not the three-day blend). The **personal baseline** is the early warning: mean of the person's measurements on the plan's pre-flight days (file rows plus their own check-ins; the mean is shown at the app's precision, the spread never goes below the catalog's `sd`; with fewer than 5 pre-flight measurements the person's first 14 days of flight data are used instead, marked `early_flight`; with fewer than 5 of those too the indicator is still `learning`: no normal, no z-score, and only the population range and NASA's limits speak; no seed is ever borrowed). A reading older than the indicator's `max_age` (3 days for daily measures, 10 for every 2 to 3 days, 21 for weekly tests) is stale: it is shown as the last measurement but never counted as today's value, and an indicator with nothing current is `no_data`, never an alert. Inside the population range the personal z-score still decides, as before. Thresholds can be overridden for one indicator with the setting `thresholds_by_indicator` (`{"sleep": {"watch": 1.0, "act": 2.0}}`); there is no screen for it.

<!-- reference-table:start (generated from backend/canary/domain/reference.py) -->
| Indicator | Unit | Low | High | Critical (below / above) | Source | Verified |
| --- | --- | --- | --- | --- | --- | :---: |
| `hr` Resting pulse | bpm | 40 | 100 | 30 / 150 | MedlinePlus: resting pulse 60 to 100 bpm. The low edge 40 allows trained people (quoted from memory of AHA). Critical limits: prototype assumption | partly |
| `bp` Blood pressure | mmHg | 90 | 129 | 70 / 180 | Systolic pressure. AHA: normal below 120, elevated 120 to 129, hypertension stage 1 from 130, stage 2 from 140, severe above 180. MedlinePlus: 90/60 to 120/80 for a healthy adult. Critical low: prototype assumption | partly |
| `spo2` Blood oxygen | % | 95 | 100 | 89 / - | MedlinePlus: normal 95 to 100%; contact your provider at 92% or lower; 88% or lower needs immediate medical attention (critical below 89) | yes |
| `temp` Temperature | °C | 36.1 | 37.2 | 35 / 39.3 | MedlinePlus: an adult probably has a fever above 37.2 to 37.5 °C by mouth (the app flags from 37.2, the lower edge); contact a provider right away for a fever that stays at 39.4 °C or above (critical above 39.3). MedlinePlus lists 36.5 to 37.3 as the usual range; the low edge 36.1 is kept so a cool personal normal (36.4) is not flagged every day. Critical low 35 (hypothermia): quoted from memory | partly |
| `gluc` Fasting glucose | mg/dL | 70 | 99 | 54 / - | ADA: below 70 mg/dL is low blood glucose and needs treatment (the 15-15 rule). High 99: the fasting reference range of the Inspiration4 laboratory (65 to 99, OSD-575). Critical 54 (ADA level 2): quoted from memory | partly |
| `sleep` Sleep | h | 6 | 10 | - | CDC: adults need 7 hours or more (the app's sleep goal is 7 h, and NASA-STD-3001 V1 6001 plans an 8.5 h sleep period). The range 6 to 10 h is the National Sleep Foundation's 'may be appropriate' band, quoted from memory | partly |
| `water` Water | L | F 1.6 / M 2 | - | - | EFSA 2010: adequate intake from drinks about 1.6 L (women) and 2.0 L (men) | no |
| `exer` Exercise | min | 21 | - | - | WHO 2020 physical activity guidelines: 150 min a week of moderate activity, about 21 min a day | no |
| `grip` Grip strength | kg | F 16 / M 27 | - | - | EWGSOP2 2019 sarcopenia cut-offs: grip below 16 kg (women) or 27 kg (men) is low strength | no |
| `kss` Sleepiness | /9 | - | 6 | - | Karolinska Sleepiness Scale (Åkerstedt and Gillberg 1990): 7 or more means sleepy | no |
| `react` Reaction time | ms | 150 | 500 | - | prototype assumption: wide on purpose, the result depends on the device and screen lag | no |
| `dsst` Processing speed | correct | 20 | 100 | - | prototype assumption: wide on purpose, depends on the task version and device | no |
| `span` Working memory | digits | 4 | 10 | - | prototype assumption: wide on purpose; forward digit span of adults is usually 5 to 9 | no |

No population range (personal or relative scales): `mood`, `stress`, `social`, `tlx`, `bone`, `vo2`.
<!-- reference-table:end -->

Each entry has `checked`: the numbers read on the guideline's own page, with the link (AHA, MedlinePlus, ADA, CDC and the Inspiration4 laboratory, checked on 2026-11-14). `verified` is `yes` only when every number of the entry was checked (SpO2), `partly` when some still come from memory or are prototype assumptions (they say which), `no` when none was checked. Two choices keep a personal normal from looking abnormal every day: the temperature's low edge stays at 36.1 °C (MedlinePlus lists 36.5 to 37.3) and sleep's at 6 h (CDC asks for 7 or more, which is the app's goal). Systolic pressure now leaves the range at 130 (AHA stage 1), not 140. Critical limits without a guideline are marked as prototype assumptions, and the PVT, DSST and span ranges are wide on purpose because they depend on the device. They are risk limits, not diagnoses.

### NASA-STD-3001: the flight limits

The third reference is NASA's own standard for crew health in flight, [NASA-STD-3001 Volume 1, Revision C](https://www.nasa.gov/wp-content/uploads/2023/11/nasa-std-3001-vol-1-rev-c-with-signature.pdf) (`domain/standards.py`, every number read in the document on 2026-11-14). A NASA limit only raises a level, in flight only, and the indicator says so in `standard: {level, status, text, item, source, url, verified}`; the alert names the item (`sources` gains `nasa:std3001v1:V14027`, for example) and the body system turns red when a limit is passed.

| Item | What NASA sets | What Canary checks | Level 2 / level 1 |
| --- | --- | --- | --- |
| V1 4001 / V1 4002 | VO2max at or above 32.9 mL/kg/min for microgravity EVAs, 36.5 for surface EVAs | `vo2` (weekly cycle-ergometer test) against the EVA done **here** (`LOCATIONS[*].eva`) and the person's own role (`RECORDS[*].eva`: surface, microgravity or none) | below the minimum of this place / in 0 g, enough for microgravity but below the surface minimum ahead |
| V1 4024 | strength at or above 80% of the pre-flight value | `grip` against the person's pre-flight mean | below 80% / below 90% (early warning, prototype assumption) |
| V1 4027 | hip and spine bone density at or above 95% of pre-flight (femoral neck 90%) | the bone estimate (% change since launch) against 95% | below 95% / below 97% (early warning, prototype assumption) |
| V1 4030 | career effective dose below 600 mSv, all ages and sexes, **every earlier flight included** | `radiation` risk and the `skin` system read the **career** dose: the record's `prior_dose_msv`, or an estimate from `days_in_space` at the station's daily dose (labelled `prior_estimate`), plus the mission dose | limit passed / from 50% with a projected crossing |
| V1 4031 | the design solar particle event below 250 mSv | named in the storm evidence (shelter) | the storm itself is level 2 |
| V1 6001 | an 8.5 h sleep period in the schedule, no critical tasks 1 to 7 AM of one's own clock | named in the sleep range's source and in `standards.SLEEP` | not a level (the plan is the schedule, not a measured value) |

What the standard sets and Canary cannot check is listed in `standards.NOT_CHECKED`: blood and immunity within the healthy population's range (V1 4015 to 4017, read through the laboratory ranges instead), 100% of each person's energy needs (V1 4020, no food log) and the organ dose limits of Table 4.8-1 (organ doses in mGy-Eq cannot be compared with the effective dose in mSv the app has). `GET /api/catalog` returns all of it as `standards`; `GET /api/crew/{id}` adds `standard_profile` (EVA role, prior dose, sex).

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
| `assistant/briefing.py` | Entry 2: one-page weekly briefing for the flight surgeon. Code computes the facts, the model only writes prose, the medical team approves it before it is queued for Earth |
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
| [OSDR OSD-575](https://osdr.nasa.gov/bio/repo/data/studies/OSD-575) Inspiration4 metabolic panel and cardiovascular cytokines | Real creatinine, potassium, calcium (laboratory ranges by sex) and C-reactive protein across the same 7 time points, in `data/real/osd575_cmp.csv`, read by `renal`, `cardio` and `immune` | Blood & immunity panel, risks |
| [NASA-STD-3001 Volume 1, Rev. C](https://www.nasa.gov/wp-content/uploads/2023/11/nasa-std-3001-vol-1-rev-c-with-signature.pdf) | The flight limits: career and solar-event dose, strength, bone density, aerobic capacity for EVA, sleep period | Indicators, risks, alerts (`domain/standards.py`) |
| [NASA HRP hazards and risks](https://www.nasa.gov/hrp/hazards/) | The five hazards (RIDGE) behind every body system | System cards, assistant knowledge |

**Real and simulated, in the demo package.** Real: the blood count (OSD-569), creatinine, potassium, calcium and C-reactive protein (OSD-575), the storm days (DONKI, Curiosity RAD). Simulated and labelled so: the mission dose (the same for every crew member), weight, fingerstick glucose, urine, vital signs, aerobic capacity and everything else in the package's `observations.csv`. Glucose from the metabolic panel is left out on purpose: three of four crew read 36 to 44 mg/dL on the same day (R+45) with every other collection normal, the pattern of a sample processed late. Other cytokines (OSD-575/656) and sex hormones have no open source wired in.

**Corrections to the NASA files** (`data/prepare_blood.py` rebuilds the `cbc` and `cmp` sections of the snapshot from the OSDR downloads and asserts each one):
1. C003's blood count at L-92 sat one row down from MCH on in OSD-569 (platelets 12.9, MPV 330). Realigned and checked by arithmetic: 9.6 thousand white cells × 71.1% = 6,826 neutrophils, × 20.8% = 1,997 lymphocytes; platelets 330. Before the fix the lymphocytes of her pre-flight mean were above the range, so the radiation risk read her as "already outside the range before launch" and ignored a real drop.
2. Each demo person now reads the Inspiration4 subject **of the same sex** (C001 and C004 are men, C002 and C003 women; OSD-569 metadata): Helena reads C002 and Kenji C001 (it was the other way round).
3. Ranges by sex: the snapshot keeps the laboratory's female and male ranges (haemoglobin 11.7 to 15.5 or 13.2 to 17.1 g/dL, haematocrit, red cells, creatinine, calcium); before, everyone was read against the male range. C003's pre-flight rows carry male ranges in the files, so each sex takes the range most of its rows carry. Haemoglobin is labelled `percent` in OSD-569; it is g/dL.

The snapshot lives in `backend/canary/data/nasa_snapshot.json`, so the ship never needs a network. `data/prepare_nasa_data.py` rebuilds the same data from the original downloads (checked: identical output) (needs `numpy` and `cdflib`). With `CANARY_LIVE_SPACE_WEATHER=1` the API also queries DONKI live and falls back to the snapshot on any error.

### The demo data generator

The demo packages are generated, not typed (see [Mission data](#mission-data) for the files). `python3 data/generate_dataset.py` builds them, deterministic and standard library only.

- **Where the simulated rows come from.** `data/recipes.json` holds one recipe per indicator (baseline, day-to-day spread, slow drift by gravity and mission day, which hidden states move it, how often it is measured, chance of a missed measurement, and a `source` with `verified`). Four hidden states (fatigue, hydration, energy, bone loss) move related signals together; the demo story is dated events that push them. `data/demo_crew.json` holds the demo crew, their story and their PINs, and nothing else reads it.
- **What is real today.** The complete blood count (OSD-569, `data/real/osd569_cbc.csv`) and creatinine, potassium, calcium and CRP (OSD-575, `data/real/osd575_cmp.csv`), from the snapshot; collections keep their label such as `R+45` in `note` and the pre-flight ones set each person's baseline and spread for the simulated rows between collections. Everything else is simulated.
- **Swapping simulated for real.** Put a CSV with the same columns in `data/real/` (`crew_id, day, indicator, value` are enough) and run the generator, or skip the generator and send real rows to `POST /api/observations` or load your own package. Real rows replace the simulated row with the same (crew_id, day, indicator). A check-in made in the app still wins over a stored reading for that day.
- `backend/canary/data/observations.csv` is the generator's reference table for the default plan; the running app does not read it (it reads the database).

---

## The 3D body

- **Shape:** the MakeHuman base mesh (CC0), converted by `tools/build_body_model.py` into `frontend/public/models/body.glb` (13,380 vertices, scaled to 1.75 m) and `joints.json` (125 joint centres). Every vertex is tagged with a surface region (head, torso, arm, hand, leg, foot) so regions can be picked and coloured.
- **Inside:** the bones (skull, jaw, vertebrae, ribs, sternum, pelvis, shoulder girdle, arms, hands, legs, feet) and the organs (brain, eyes, heart, lungs and airways, liver, stomach, pancreas, intestines, kidneys, bladder, thymus, aorta and great veins) are real anatomical meshes from BodyParts3D, fitted to the body and stored in `frontend/public/models/anatomy.glb` by `tools/build_anatomy_model.py` (about 228,000 triangles, 1.1 MB, meshopt-compressed; credits and licence in `frontend/public/models/ANATOMY_CREDITS.md`). The spleen, the arteries of the limbs and the nerves are drawn procedurally from the joints (`frontend/src/hologram/anatomy.ts`). If `anatomy.glb` cannot be loaded, the whole inside is built procedurally as before, so the body never disappears.
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
    main.py              routes, PIN sign-in and the 422 answer shape for bad input
    auth.py              PINs (PBKDF2), crew session tokens, rate limit
    config.py            environment settings
    db.py                SQLite schema and helpers
    domain/              validation (input checks shared by every form), catalog, registry (crew and mission registered by Mission Control), plan, data (the one path in for measurements, events, scenes), telemetry, dose, live (DONKI), simdata (the demo generator's helpers), health, risk, standards (NASA-STD-3001), reference, advice, goals, privacy, protocols, nasa, mission, selftests
    assistant/           the AI slot: chat, briefing, suggestions, guard
    data/                protocols.json, nasa_snapshot.json, observations.csv (the generator's reference table, not read at runtime)
  tests/                 test_canary.py, test_golden.py (the demo, number by number), test_ingest.py, test_mission_package.py, test_empty_and_stale.py, test_crew_size.py, test_clock_dose_storms.py; conftest.py reuses one loaded database per session
  requirements.txt
frontend/
  src/
    api/                 typed client and response types (ApiError carries the {field, message} list)
    lib/                 validate.ts (input rules), useForm.ts (errors, focus, busy, server errors), useAction.ts (standalone buttons)
    state/session.tsx    mission, signed-in person, photos, preferences, refresh signal
    state/prefs.ts       theme and accessibility preferences for the terminal
    hologram/            scene, shaders, procedural anatomy, React wrapper
    components/          Shell (sidebar, profile menu, top bar, demo bar), People (crew dots, profile picker), PinPad, Timeline, Hazards, Stars, BodyView (body + observations), goals, charts, patches
    features/            Guided Response, Ask Canary, self-tests and logs (Checks)
    pages/               Intro, Setup (admin preview), Crew (home), Astronaut (public card or medical view), MySpace (Health, Goals, Suggestions, Patches, Dashboard, My information, Settings), MissionInfo, Control (Canary Control), Tests, Settings, Ranking, MissionPlan, Medical, About
    styles/app.css       design tokens and components
  public/models/         body.glb, joints.json, anatomy.glb, ANATOMY_CREDITS.md
data/missions/          mission packages: odyssey1-mars, odyssey1-moon, odyssey1-iss (CSV spreadsheets, generated, each with a README)
data/demo_crew.json      the demo crew, story and PINs (read only by the generator)
scripts/load_mission.py  load a package folder into a database without a server
.env.example             every environment variable, with a comment and no secret
data/recipes.json        one recipe per indicator: baseline, spread, drift, hidden states, frequency, gaps, source
data/real/               real observations (CSV), replace simulated rows with the same key
data/generate_dataset.py builds the mission packages, observations.csv (reference), data/DATASET.md and data/real/osd569_cbc.csv, osd575_cmp.csv
data/prepare_blood.py    rebuilds the blood sections of nasa_snapshot.json from the OSDR files (OSD-569, OSD-575), with the corrections
data/DATASET.md          what is in the file, where each part comes from, how it would be collected
data/prepare_nasa_data.py
tools/build_body_model.py
tools/build_anatomy_model.py
Makefile
```

---

## API

Full, interactive documentation at `/docs`. The main routes:

| Route | Purpose |
| --- | --- |
| `GET /api/mission` · `PUT /api/mission` | Mission clock (a story step or any day), its date and mode (simulated or real), place, current leg, `setup_done` |
| `GET /api/plan` · `PUT /api/plan` · `POST /api/plan/preset` | Mission plan: itinerary legs, presets |
| `POST /api/setup` | Mission-admin setup (future admin flow): validates and saves the plan, restarts the story. The demo mission ships configured |
| `POST /api/crew/{id}/session` · `PUT /api/crew/{id}/pin` | Sign in with the 4-digit PIN (returns the session token) · change your PIN |
| `GET /api/crew/overview` | What everyone may see: participation, hazards, crew missions, the visibility contract. Never status |
| `GET /api/crew/{id}` | One astronaut in full, with operational status: the astronaut and the medical team only |
| `GET /api/crew` | Full health summary of everyone, with operational status (medical team only) |
| `GET /api/goals/{id}` · `POST /api/goals/{id}/{goal}` | Today's goals, crew missions, streak and patches · tick a goal |
| `GET /api/mission/overview` | The mission and the crew as a whole (public on board, no health data) |
| `POST /api/control/session` · `GET /api/control/overview` · `GET /api/control/demo` · `POST /api/control/register` · `POST /api/control/clear` | Canary Control (Mission Control PIN, its own token): sign in, follow the crew, the demo form, register one to six people and the mission, start from zero |
| `POST /api/observations` | A batch of readings from a sensor, wearable or lab (`X-Canary-Key`, up to 5,000 rows, all or nothing). See [Live data](#live-data) |
| `GET /api/scenes` | The Demo story's scenes of the loaded package (empty: no bar) |
| `POST /api/control/import` · `GET /api/control/data-status` | Load a bundled package (JSON) or upload a zip or CSV files; counts and last-received dates of the data, never values (Mission Control) |
| `PUT /api/control/clock` · `GET/POST /api/control/space-events` | Set the mission clock (a simulated date, or `{"real": true}`) · list and add space events (Mission Control) |
| `GET /api/crew/{id}/record` | My information: the personal record (the astronaut and the medical team) |
| `GET /api/suggestions/{id}` · `POST /api/suggestions/{id}/{sid}/accept` | Personal suggestions (the astronaut only) · turn one into a goal for 7 days |
| `POST /api/checkins` · `GET /api/checkins/{id}` · `GET /api/checkins/{id}/{checkin_id}/photo` | Save a test or log (vitals take an optional `photo`), returns `conclusion` {population, personal, text} (self only; a value outside the typing limits, such as a pulse of 900, returns 422 with the field that is wrong) · every test with its latest result and the recent log (self and medical team) · the photo kept with a vitals check-in (self and medical team) |
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
| `GET /api/crew/{id}` → `risks` | Risk layer: level, score, trend, since_day and evidence |
| `GET /api/crew/{id}` → `indicators[*].standard`, `standard_profile`, `dose.career_msv` | NASA-STD-3001 check of each indicator, the person's EVA role and earlier dose, the career dose |
| `GET /api/catalog` → `standards` | What Canary checks against NASA-STD-3001, with the items, and what it cannot check |
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
2. **Real devices:** a small bridge that turns a wearable's or a lab's export into `POST /api/observations` calls (the endpoint, the checks and the key exist; the bridges do not).
3. **Ground sync:** store-and-forward of messages, briefings and check-ins to a ground station, with conflict rules.
4. **Clinical review:** replace the illustrative protocols with flight-surgeon-approved ones; per-person medication allergies in Guided Response.
5. **Privacy, next steps:** a badge tap as a second factor; freeze a streak during medical leave instead of breaking it; profile photos stored as files rather than in the settings table.
6. **Pitch:** record the six-scene demo; verify the literature figures listed below.

---

## Input checks

Every input is checked twice, and the server never trusts the page.

- **In the page.** The rules live in `frontend/src/lib/validate.ts` (required, number with range, unit and decimals, length, date, time, PIN, closed list). `useForm.ts` runs a form: a field shows its error when it is left or on the first Save, the error disappears as soon as the value is valid, a Save with errors sends nothing and puts the focus on the first wrong field, and the button reads "Saving…" and ignores a second press. `components/Field.tsx` draws the label, the hint ("25–250 bpm") and the error in plain text under the field. A button that is not part of a form (approve, remove, reset, accept, pick a place) goes through `useAction.ts`, which catches the error and shows it next to the button or as a toast. The registration form also lists what is wrong per person ("Person 2 · Date of birth is required"), and each line takes you to its field.
- **On the server.** The same rules sit in `backend/canary/domain/validation.py` and `selftests.validate` (one rule set per kind of check-in) and in the Pydantic models of `main.py` (registration, goals, messages, thresholds, questions). A bad value returns **422** with `detail: [{"field": "crew.1.dob", "message": "Date of birth is required"}]` and nothing is written. The web client reads that list and puts each message under its field; any other failure (server down, 500) becomes one line above the Save button. Auth answers (401, 403, 429) keep their plain text.
- **Tests.** `backend/tests/test_canary.py` sends one bad value per form and checks the 422, the field and that the database did not change, plus one good value that still saves.

The accepted ranges are listed in "Limits, honestly": they catch typos, they say nothing about health.

---

## Limits, honestly

- **Mock data:** astronaut vital signs are not published as open data, so the demo package is mock: its crew, daily readings and cabin dosimeter are simulated (deterministic, with the story written in) and labelled `simulated`. What a real mission loads or sends is its own; Canary has not been run on flight data. The blood count, creatinine, potassium, calcium and CRP are real (Inspiration4, before and after a 3-day flight; no collection during flight is public). In every observation row `origin` says `simulated` or `real`, and every recipe without a published source says `prototype assumption` with `verified: false`; `data/DATASET.md` lists them. Open real data exists for more cytokines and for dose by place and is not imported yet.
- **Prototype assumptions of this layer (`verified: false`):** the baselines, spreads and fatigue effects of `dsst`, `span`, `kss`, `tlx` (see `catalog.INDICATOR_NOTES`; the KSS and NASA-TLX scales are published, the numbers are not), and the input plausibility limits below. The limits only catch typos and impossible numbers; they are not clinical ranges and say nothing about what is healthy.
- **Input limits (prototype assumptions, `verified: false`):** vital signs: pulse 25 to 250 bpm, systolic pressure 60 to 260 mmHg, temperature 30 to 45 °C with one decimal, oxygen 50 to 100 % as a whole number (an empty field keeps the sensor value; all empty is refused; a comma counts as the decimal point). Sleep diary: both times, duration 1 to 16 h. Reading: title required, 1 to 600 minutes, 0 to 2000 pages. Journal: at least one line. Questionnaires: every question answered. Prescribed goal: title 3 to 120 characters, why up to 200, 1 to 60 days. Messages 1 to 1000 characters, questions to Ask Canary 1 to 500, spaces alone do not count. Alert rules: watch 0.5 to 4 σ, act 1 to 5 σ, act above watch. Registration, per person (one to six): name 2 to 60 characters, role required, four-digit PIN different for each person, age 25 to 70 at launch, height 140 to 210 cm, weight 40 to 150 kg, blood type and Fitzpatrick type from a closed list, 0 to 20 earlier flights, 0 to 1000 days in space; `eva` is surface, microgravity or none and earlier dose 0 to 600 mSv (no form field yet, the server checks them); mission: callsign 2 to 24 characters, name 2 to 80, launch date a real date between 2025 and 2100. Setup durations stay inside each field's min and max. Photos: PNG, JPEG or WebP, at most 8 MB.
- **Dose without dosimeters is an estimate.** With no `dose_rate` readings the mission dose is the plan's rate per place plus the extra dose of the space events, and the page says `estimated`; with some days measured it says `partial`. The rates per place and the extra dose of a typed or replayed storm are assumptions, not measurements.
- **Live space weather needs a network.** DONKI events arrive only with `CANARY_LIVE_SPACE_WEATHER=1`, a real-date clock and an answer from api.nasa.gov (the demo key is rate-limited); offline, Canary keeps the events it has. The ingest key is one shared secret, not an identity system.
- **Risk weights are still prototype assumptions.** Reading data from files does not make them clinical; see the next two items and the table of risks.
- **Risk layer (prototype assumptions, `verified: false`):** the fatigue weights, the cuts (2.0 and 4.0 points), the minimum of 3 signals, the 2-day sustain rule, the 3-day trend (±0.5), the drift window (14 days, 10 days ahead, minimum slope 0.08 spreads a day) and the 60-day look-back. They were tuned on the simulated crew, not on flight data. The Physical and Mental readiness scores are also a design choice (18 points per spread beyond 0.6, minus 6 per level of eyes, skin and immune), not a published score.
- **Advice loop (prototype assumptions, `verified: false`):** the `verify` pairs (indicator and days for each alert goal and suggestion), the 0.5-spread margin and the 3-day average that decide improved / same / worse, the rule of two rounds, the alternative steps per risk, the 60-day look-back of `days_active` and the default exercise reductions (15% and 30%, at most 30%). The reductions are placeholders for the flight surgeon; nothing here has been clinically reviewed.
- **Care windows (prototype assumptions, `verified: false`):** every `window_days`, `ops` and `after_days` in `protocols.json` is read from the illustrative text of `after` and rounded up to whole days (`care_note`); the 0.8 sensitivity factor (adjustable, no published rule says how much tighter a recovering patient should be watched); the radiation protocol as `full` (follow-up tests, no restriction). Windows are in whole days because the mission clock is. Critical alerts reach the medical officer when a write route runs `notify.sync`, not by a background clock, because nothing in the system depends on real time.
- **Risks (prototype assumptions, `verified: false`):** every weight and cut of the seven new risks (table above), the weight-loss cuts (5% and 10%), the 1%-in-30-days bone rate, the 50% CRP rise, the 1,500 mL/24 h urine volume, the panel intervals (30 and 15 days), the RIDGE cuts and the per-place environment level, and every link of the hazard matrix (sources "HRP" and "Patel 2020" still to be checked, plus the five prototype-assumption links). The mission dose is the same for everyone. Hormones and other data without an open source are left out.
- **Reference ranges:** SpO2 is fully checked; the others are checked in part (`checked` names the page of each number) and say which number is still from memory or a prototype assumption (table above). Simulated glucose of Tomás sits just above 99 mg/dL on a few isolated days (level 1, none in a story scene).
- **NASA-STD-3001 layer:** the limits are NASA's (checked in the document); the early-warning steps before them (90% strength, 97% bone) are prototype assumptions. Grip stands in for whole-body strength and the bone estimate for hip and spine DXA. The earlier-flight dose is estimated from `days_in_space` at the station's daily dose when the record has no `prior_dose_msv`. Aerobic capacity is simulated (weekly test, a slow loss in 0 g chosen as a prototype; NASA notes about 10% to 30% lower after flight).
- **Lab ranges follow the registered sex.** The blood panel of a person is built from their own laboratory observations (`origin` real, `method` blood), with the laboratory's range for their sex; a person with none sees an empty panel, never someone else's.
- **Tests never taken:** the Tests page still says "Not done yet" for a test the person never did, even when the file has simulated history for that indicator. No check-ins are invented for the past.
- **Sparse measurements:** a blood panel, urine panel or scale reading is only as fresh as its last collection. Blood pressure, grip and the bone estimate are daily in the file on purpose: the alert rules blend three days, and sparser readings changed the demo alerts.
- **Not clinically reviewed:** Guided Response protocols are illustrative first aid adapted to spaceflight. Real ones come from the flight surgeon.
- **To verify before quoting:** daily dose by place (and the rover's, set to its planet's surface), bone loss of about 1% per month, delays to Mars. The 600 mSv career limit and the 250 mSv solar-event limit are checked (NASA-STD-3001 V1 4030 and V1 4031).
- **Demo shortcuts:** the PINs are public (crew `1001` to `1004`, medical `1961`, all in this README and shown as a hint on the pad), and a 4-digit PIN with a rate limit is a prototype lock, not real security; session tokens are signed with a random secret per start unless `CANARY_TOKEN_SECRET` is set; the communication delay runs 20× faster; fonts load from Google Fonts (bundle them for an offline ship).

---

## Credits and licences

- Body mesh: [MakeHuman](https://github.com/makehumancommunity/makehuman) base mesh, **CC0 1.0**.
- Bones and organs: [BodyParts3D](https://dbarchive.biosciencedbc.jp/en/bodyparts3d/), (c) The Database Center for Life Science, **CC BY-SA 2.1 Japan** (share-alike applies to `anatomy.glb`; details in `frontend/public/models/ANATOMY_CREDITS.md`).
- NASA data: DONKI, Curiosity RAD (PDS/SPDF) and OSDR OSD-569 and OSD-575 are NASA open data. NASA-STD-3001 is a NASA technical standard, quoted by item.
- Fonts: Archivo, Public Sans and DM Mono from Google Fonts (SIL Open Font License).
- Built for NASA Space Apps Challenge 2026. Canary is not affiliated with or endorsed by NASA.
