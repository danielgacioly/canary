# Canary

**A crew health system for when Earth is too far to answer.**
NASA Space Apps Challenge 2026 · *Create Health Monitoring Software for Astronauts on Space Missions*

For a century, miners carried a canary underground. The bird felt bad air before people did, and when it went quiet the miners knew to leave. A spacecraft is a sealed mine: radiation, isolation, distance, altered gravity and a closed cabin. On the way to Mars a question to the flight surgeon takes up to 21 minutes to arrive and as long to come back. **Canary stays on board for that gap.**

> [!IMPORTANT]
> **Ask Canary, the AI assistant, needs an API key that is not in this repository.** It was built and tested with the team's Google Gemini key, kept in a local `.env` file that is deliberately not committed. Without a key, the assistant still works, answering from rules over the same data. See **[About the AI assistant](#about-the-ai-assistant-read-this-first)** to understand why and to switch the model on in about three minutes.

---

## Contents

1. [At a glance](#at-a-glance)
2. [About the AI assistant (read this first)](#about-the-ai-assistant-read-this-first)
3. [Quick start](#quick-start)
4. [Demo accounts](#demo-accounts)
5. [A 10-minute tour](#a-10-minute-tour)
6. [Who sees what](#who-sees-what)
7. [The screens](#the-screens)
8. [How Canary decides](#how-canary-decides)
9. [Data, honestly](#data-honestly)
10. [The 3D body](#the-3d-body)
11. [Architecture](#architecture)
12. [Configuration](#configuration)
13. [Testing](#testing)
14. [API](#api)
15. [Operations](#operations)
16. [How it maps to the judging criteria](#how-it-maps-to-the-judging-criteria)
17. [What to build next](#what-to-build-next)
18. [Limits, honestly](#limits-honestly)
19. [Use of SI tools](#use-of-si-tools)
20. [Credits and licences](#credits-and-licences)

Deep reference lives in [`docs/`](docs/): [how health is read](docs/health-model.md), [data and NASA sources](docs/data.md), [every API route](docs/api.md), [operations](docs/operations.md), and the AI design ([plan](docs/ai/plan.md), [schemas](docs/ai/schema.md)).

---

## At a glance

Canary runs on board, offline, on one small server. It does five things:

- **It compares each astronaut with their own normal.** Every number is read against that person's pre-flight baseline, a healthy population range and NASA's flight standard (NASA-STD-3001), so a slow drift is caught before it becomes a problem.
- **It turns warnings into goals.** An early warning comes with what it means, what to do now, and daily goals that address it. Goals, streaks and crew missions keep healthy routines going for months.
- **It guides an emergency step by step.** Guided Response is deterministic, with no AI on that path: big buttons, one instruction at a time, protocols adapted to 0 g, partial gravity or Earth, and an optional English voice that reads the screen.
- **It shows the body.** A holographic 3D body you can turn and click: each body system takes the colour of its status, physical and mental side by side.
- **It respects the delay to Earth.** Messages, briefings and reports travel with the real signal delay of where the crew is, so the crew is never waiting on Earth to act.

Three kinds of people use it, each behind their own PIN:

| Role | Where | Sees |
| --- | --- | --- |
| **Astronaut** | My space, Tests | their own health, goals, suggestions and assistant |
| **Medical team** (the crew medical officer on board, flight surgeons on Earth) | Medical console | everyone's health, alerts, risks, emergencies; approves briefings for Earth |
| **Mission Control** | Canary Control | registers the crew and the mission, loads data, follows operational status, never health values |

**About the data:** astronaut health data is not public, so every reading in the demo is **simulated** (the blood panels are modelled on NASA's Inspiration4 records). NASA's storm records, NASA's flight limits and the population ranges are real, each with its source. See [Data, honestly](#data-honestly).

---

## About the AI assistant (read this first)

### What the assistant is

**Ask Canary** is a drawer you open from the sidebar. An astronaut (or the medical team, for that astronaut) asks a question in plain words, such as "Why is my sleep off?", and gets an answer built only from that person's own data, the body-system cards and the protocols, with a source on every sentence. It explains; it never diagnoses, never gives a medication dose, and sends emergencies to Guided Response. The same AI layer also writes the weekly **briefing** for the flight surgeon and rephrases the reasons behind personal **suggestions**.

Under the hood ([`backend/canary/assistant/`](backend/canary/assistant/)):

- a real large language model with **tool calling**: 10 strict tools such as `get_indicator`, `get_risks` and `search_knowledge`, each limited to the signed-in person;
- a **guard** that checks every answer before it is shown: each source must exist and fit the claim, numbers must come from the tool data, there are no doses, no diagnoses and no "this is safe", and nobody else's health;
- a local **knowledge base** (protocols, body-system cards, NASA sources);
- two cloud providers behind one interface: **Google Gemini** (default model `gemini-3.1-flash-lite`) and **Anthropic Claude** (default `claude-sonnet-5-5`).

### Why it isn't running in this repository

The team developed and tested Ask Canary with a **Google Gemini API key** stored in a local `.env` file at the root of the project. That file is listed in [`.gitignore`](.gitignore) on purpose, and the key is not in the repository, because:

- **An API key is a secret tied to a paid account.** Anyone who copies it from a public repository can run requests billed to the team.
- **Providers revoke keys that appear in public code.** Google and Anthropic scan public repositories and disable leaked keys, so a committed key would stop working anyway.
- **The challenge asks for the repository, not a deployment.** There is no server of ours the judges could use with the key safely kept on it.

So a fresh clone has no key, and the assistant runs in its **no-model mode**. **This is a deliberate security decision, not a missing or broken feature.**

### What you will see without a key

Canary was designed to work offline (a spacecraft can't count on a network), so the assistant never breaks when no model is available:

- **Ask Canary still answers.** The same tools run and the same guard checks the result, but the answer is built by deterministic rules instead of being written by a model. Answers are labelled **"From your data"**.
- The drawer's header shows **"No model connected: answers come from rules"**.
- Weekly briefings use their fixed template; suggestions keep their rule-written reasons.
- `GET /api/assistant/status` answers `{"provider": "none", "configured": false, "model": null, ...}`.

What changes with a key is the **language**: the model chooses which tools to call and writes a natural answer, which the guard still checks sentence by sentence.

### Switch the model on (about three minutes)

1. **Get a key** from one provider (either works):
   - Google Gemini: [Google AI Studio → Get API key](https://aistudio.google.com/apikey) ([how-to](https://ai.google.dev/gemini-api/docs/api-key));
   - Anthropic Claude: [Anthropic Console → API keys](https://console.anthropic.com/settings/keys) ([how-to](https://docs.anthropic.com/en/api/getting-started)).
2. **Create your local settings file** at the root of the project:
   ```bash
   cp .env.example .env
   ```
3. **Paste the key** into `.env`, and keep the provider on `auto`:
   ```bash
   CANARY_LLM_PROVIDER=auto
   GEMINI_API_KEY=your-gemini-key        # or leave this empty and set:
   ANTHROPIC_API_KEY=                    # your-anthropic-key
   ```
   With `auto`, the key you set picks the provider. If both are set, Gemini is used.
4. **Restart the backend** (stop `make dev` with Ctrl+C and run it again). The backend reads `.env` only when it starts.
5. **Check it is connected:**
   ```bash
   curl http://localhost:8000/api/assistant/status
   ```
   It should say `"provider": "gemini", "configured": true, "model": "gemini-3.1-flash-lite"` (or `anthropic`). In the app, the Ask Canary header now reads **"Assistant · gemini / gemini-3.1-flash-lite"**.
6. **Try it:** open **My space**, sign in as Helena (PIN `1001`), open **Ask Canary** and ask *"How am I doing today?"* or *"Why is my sleep off?"*. Model answers are labelled **"AI answer"**.

The key stays on the backend: it is never sent to the browser, never written to a log, and never returned by any route. Requests are billed by the provider to the key's account. Canary allows at most 10 questions, 3 briefings and 6 suggestion builds a minute per person.

### Check the AI layer without any key

The AI layer is tested end to end without a network, using a scripted stand-in for the model:

```bash
make test                                         # includes the tool loop, guard, providers and knowledge base
cd backend && .venv/bin/python -m evals.run --dry  # 36 adversarial cases through the real loop and guard, free
```

The eval cases cover diagnosis requests, medication doses, prompt injection, emergencies, someone else's data, off-topic questions and invented numbers. `--yes` runs the same cases against the real provider, which costs money (see [`backend/evals/README.md`](backend/evals/README.md)).

### If it still says "No model connected"

| Symptom | Cause and fix |
| --- | --- |
| Status still says `provider: none` | The backend was not restarted after editing `.env`, or `.env` is not at the repository root (next to `Makefile`) |
| `provider: gemini` but `configured: false` | `CANARY_LLM_PROVIDER=gemini` (or `anthropic`) names a provider whose key is empty. Set the key, or set the provider back to `auto` |
| Answers say "Model unavailable: rule-based answer" | The key was rejected, the provider was unreachable, or the 150 s deadline passed. The answer falls back to rules on purpose. Check the key and the network |
| A setting in `.env` seems ignored | A variable already exported in your shell wins over `.env`. Run `unset CANARY_LLM_PROVIDER CANARY_LLM_MODEL` and restart |

All assistant settings are in [Configuration](#configuration), and the design is in [docs/ai/plan.md](docs/ai/plan.md).

---

## Quick start

**You need:**

- **Python 3.10 to 3.13** (3.13 recommended). The pinned dependencies ship ready-made packages up to 3.13; the Makefile picks the newest supported Python it finds.
- **Node.js 18 or newer** and **make**.

```bash
make setup     # backend virtualenv, npm install, and the knowledge-base index
make dev       # API on http://localhost:8000 and web app on http://localhost:5173
```

Open **<http://localhost:5173>**. Interactive API documentation is at <http://localhost:8000/docs>.

**First run notes**

- The knowledge base downloads a small embedding model (BAAI bge-small-en-v1.5) the first time it is built. To stay fully offline, set `CANARY_EMBEDDER=none` (keyword search only).
- On macOS, the Python from python.org can't load SQLite extensions, so vector search turns itself off and keyword search is used (one knowledge-base test reports it). Homebrew's or pyenv's Python doesn't have this limit.
- No `.env` is needed to run the demo. It is only for an AI key or for changing settings.

**Without make**

```bash
cd backend && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m canary.assistant.kb.build              # the knowledge base, once
.venv/bin/uvicorn canary.main:app --reload --port 8000
```

```bash
cd frontend && npm install && npm run dev
```

On Windows the virtualenv keeps its programs in `.venv\Scripts` (the Makefile handles this): `py -m venv .venv`, then `.venv\Scripts\pip install -r requirements.txt` and `.venv\Scripts\uvicorn canary.main:app --reload --port 8000`.

**Other commands**

| Command | What it does |
| --- | --- |
| `make test` | backend tests and the frontend type check (no network) |
| `make index` | rebuild the knowledge base `backend/kb.db` (the API also rebuilds it at start-up when it is missing or stale) |
| `make build` | production build of the web app into `frontend/dist` |
| `make serve` | build everything and serve the app and API from one process on <http://localhost:8000> |
| `make dataset` | regenerate the demo mission packages from `data/recipes.json` |

---

## Demo accounts

All PINs below are **public and for the demo only**. They come from the demo mission package ([`crew.csv`](data/missions/odyssey1-mars/crew.csv) and [`ground.csv`](data/missions/odyssey1-mars/ground.csv)), and the sign-in pads show them as a hint in demo mode.

| Who | Role | Signs in to | PIN |
| --- | --- | --- | --- |
| Helena Duarte | Commander | My space, Tests | `1001` |
| Kenji Mori | Crew medical officer | My space, Tests, **and the Medical console** | `1002` |
| Amara Okafor | Flight engineer | My space, Tests | `1003` |
| Tomás Rivera | Geologist | My space, Tests | `1004` |
| Dr. Lena Ortiz | Flight surgeon (on Earth) | Medical console | `1961` |
| Sam Okoye | Flight Director (Mission Control) | Canary Control | `4242` |

Before any Mission Control account exists (an empty start), Canary Control accepts a first-access PIN, `4242` in demo mode (`CANARY_CONTROL_BOOTSTRAP_PIN`). **Guided Response needs no PIN**: in an emergency, anyone can open it.

---

## A 10-minute tour

When the app opens, a short intro tells the canary story in five chapters. At the end you choose:

- **Skip intro** (top right, any time) loads the demo mission and opens the crew screen. **This is the quickest way in.**
- **Start the tour** shows Canary as a real mission would start: it clears the demo, asks you to sign in to Canary Control as Sam Okoye (`4242`), and walks you through registering the demo crew, the demo devices and the demo mission. It then shows the Control dashboard and continues on board with balloons pointing at each part.

### The demo story

The **demo bar** at the bottom moves the mission clock through six scenes. Each scene sets the day, the place and the person it follows, and **Enter as …** opens that person's PIN pad.

| # | Scene | What to try |
| --- | --- | --- |
| 1 | **L-30, Earth** | Canary is learning everyone's normal: no alerts yet. Open **My space** as anyone and see "Learning your normal". |
| 2 | **Day 2, in orbit** | Tomás has a fast pulse and has barely drunk water. As Tomás (`1004`), the space-sickness alert already comes with hydration goals. |
| 3 | **Day 147, on the way to Mars** | Helena's sleep, mood, focus and crew time slip together. As Helena (`1001`): the brain glows red on the body, the Mental tiles show the slide; take the reaction test in **Tests**, or ask **Ask Canary** "Why is my sleep off?". |
| 4 | **Day 152, replaying 10 May 2024** | The strongest solar storm in 20 years, from NASA's DONKI records. Everyone to the shelter; the radiation protocol is in force. |
| 5 | **Day 153, dinner** | On Kenji's terminal, Tomás has a seizure. **Hold "Hold for emergency" for one second**, choose Tomás, choose Seizure, and follow the steps with the big **YES / NO** buttons. Close as stable, then see the follow-up goals and the care window in the **Medical console** (Kenji, `1002`). |
| 6 | **Sol 12 on Mars, replaying 20 May 2024** | Curiosity measured radiation 51 times above normal at Gale crater. Everyone re-adapts to gravity. |

**The EVA moment (scene 3, as Tomás).** In My space → Health, read **Ready for EVA?**. In deep-space transit his aerobic capacity is yellow: it meets NASA's minimum for microgravity spacewalks (32.9 mL/kg/min) but not the 36.5 he needs for the surface walks he is there to do. Change **Where you are** (top left) to Mars: the card re-reads the standard and turns red. Nothing about Tomás changed, only the place. NASA's limits depend on where the work is.

### Guided Response in an emergency

- **Open it:** press and hold the red **Hold for emergency** button for one second (or focus it and press Enter). A red alarm bar appears on every screen of the ship until the emergency ends.
- **Follow it:** answer "Who is the patient?", then "What is happening?". If unsure, choose **I don't know**, type what you see, and Canary suggests the closest protocol. Each step shows one instruction, a progress bar and big buttons: green **YES** and red **NO**, or **Done, next**.
- **Voice:** **Turn voice on** reads each screen aloud with a standard English voice. It starts off; the Settings page can turn it on for every emergency.
- **End it:** at the last step, **Stable: close and report** (green) or **Not stable: escalate** (red). This adds follow-up goals for the patient, opens a care window, and queues a report for Earth with the signal delay.
- **Cancel it:** **Cancel** (top right, or on the red alarm bar) ends an emergency opened by mistake. The log is kept, and nothing else happens.

---

## Who sees what

Canary follows a visibility contract the crew agrees on day 0 ([`privacy.py`](backend/canary/domain/privacy.py)). Health never leaves the person and the medical team.

| Information | The astronaut | Medical team | The crew | Earth (Mission Control) |
| --- | --- | --- | --- | --- |
| Raw data and history | Yes | Yes | No | No |
| Personal risks and advice | Yes | Yes | No | No |
| Operational status (for example "fit for EVA") | Yes | Yes | No | Via the medical team |
| Critical alert | Immediately | Immediately | No | Delayed note to the flight surgeon |
| Photo of a vital-signs display | Yes | Yes | No | No |
| Hazards and crew goals | Yes | Yes | Yes | Yes |
| Questions to Ask Canary and their answers | Yes | Yes (they can read them) | No | No |
| Weekly briefing | Yes (read-only) | Yes (approves it) | No | After approval, with the delay |
| Suggestions | Yes | No | No | No |

How it is enforced:

- **Every private space opens with a PIN.** The web app keeps each sign-in token for the browser tab only. Wrong PINs lock the account with a growing wait (1, 5, 15, then 60 minutes).
- **The medical session lives only inside the Medical console.** Leaving the console signs it out (the token is revoked on the server), so the next person needs the PIN again. Clicking a crew member's initials anywhere else opens only their public card; their health opens only with their own PIN, or inside the console.
- **The crew overview carries no health at all:** participation (goals done, streaks), hazards and crew missions. There are no averages, because with four people an average gives individuals away.
- **The ranking counts effort, never vital signs:** routine goals done in the last 7 days. Goals added by an alert, a prescription or a suggestion count only in the person's own space, so a jump in someone's public total can't reveal an alert.
- **Questions are not private from the medical team.** A question the medical team asks is labelled "Asked by the medical team" in the astronaut's history.
- **Guided Response is a crew-wide event** (the whole cabin sees the alarm with the patient's name and protocol); what follows it (the care window, restricted status, tighter thresholds) is private.

Tests check this contract: no crew-wide route returns another person's status, risks, dose, readiness or photo.

---

## The screens

The sidebar has three groups (**Crew**, **Your health**, **Support**). The top bar shows where the crew is, the mission time, the Earth delay, the crew's initials and the **Hold for emergency** button.

| Screen | What you find |
| --- | --- |
| **Intro** (`/welcome`) | The canary story in five chapters, then *Skip intro* or *Start the tour* |
| **Crew** (home) | Every astronaut as a neutral dot with today's routine; NASA's five hazards for the current place (with a storm warning when one hits); crew missions and the crew streak. No status, no vitals, no averages |
| **Tests** | After a PIN: cognition (reaction time, processing speed, working memory), how you feel (mood, stress, sleepiness, workload, wellbeing screens), body (vital signs with an optional photo of the device, Amsler grid, symptoms) and logs (sleep diary, reading, a three-line journal that is never saved). Each result is compared with your own normal and the population range |
| **Mission plan** | The itinerary read for health: every leg's gravity, radiation, Earth delay, hospital distance and hazards, what the body faces, and the projected mission dose against the career limit |
| **Protocols** | Every Guided Response protocol as a reference page, with the ones in force now |
| **Ranking** | Goals done in the last 7 days, one row per person |
| **Mission** (callsign chip, top bar) | The mission and the crew as a whole (roles, agencies, earlier flights), no health; the switch to Mission Control mode |
| **My space** (PIN) | Six tabs: **Health** (the 3D body, how you are in one sentence, up to three next steps, Physical and Mental scores, *Needs attention*, *Ready for EVA?*), **Goals** (physical and mental lists, patches), **Suggestions** (personal recommendations with your own numbers, each can become a goal for 7 days), **Trends** (30 days of every indicator against your normal, NASA limit lines, the blood panel), **My information** (the record Mission Control registered) and **Settings** (photo, change PIN, lock) |
| **Ask Canary** (Support) | The assistant drawer; see [About the AI assistant](#about-the-ai-assistant-read-this-first) |
| **Medical console** (Support, PIN) | Six tabs: **Triage** (one row per astronaut with status and why, care windows, top alerts, red NASA risks), **Briefings** (approve drafts for Earth), **Prescribe** (a goal for one astronaut), **Messages**, **Emergencies** (every Guided Response log) and **Assistant** (the audit of recent questions). A person's full page opens from Triage, with risks and evidence, EVA readiness, career dose, care events, vital-sign photos, and **Correct a value** |
| **Canary Control** (`/control`, Mission Control PIN) | **Dashboard** (operational status as the medical team reports it, goals, hazards, open alerts and acknowledgements, emergencies), **Register crew and mission** (one to six people, devices, mission profile), **Data** (load or upload a mission package, the mission clock, ingest status, space events) and **Messages** (with the real signal delay) |
| **Settings** | Theme (light by default, dark, or match the device), larger text, higher contrast (on by default), reduce motion, read emergency steps aloud, show the demo bar, replay the intro, reset the demo |
| **Guided Response** | Full-screen, follows the theme; see the tour above |

---

## How Canary decides

Deterministic rules decide everything that matters (alerts, risks, emergencies, thresholds). The AI only explains. Full detail is in [docs/health-model.md](docs/health-model.md).

- **Three references for every number:** the person's own pre-flight baseline (the early warning), a healthy population range from a named guideline (the safety net), and NASA-STD-3001 flight limits (in flight).
- **From a reading to an alert:**
  - Canary takes the day's own value and computes how many of the person's own standard deviations it sits from their normal (a z-score).
  - Level 1 (watch) starts at 1.5σ and level 2 (act) at 2.5σ; the medical team can change both.
  - A level needs two readings in a row (persistence) and only clears 0.5σ below where it started (hysteresis), so one odd reading neither raises nor drops an alert.
  - A critical population limit or a NASA limit alerts at once.
  - The smoothed value you see on some tiles (60% today, 25% yesterday, 15% the day before) is for display only.
- **Learning first:** a personal normal needs 5 measurements; until then only the population range and NASA's limits speak. Pulse and pressure get a 14-day grace period for the fluid shift of the first days in orbit.
- **Risks:** eight risks (fatigue, radiation, vision, nutrition, kidneys, immunity, heart, bones and muscles), four of them NASA's red risks for Mars, each adding up evidence from several signals with a weight table you can read.
- **Advice that checks itself:** every goal says what it should move and when to check. Two rounds without improvement bring a different suggestion and one message to the medical officer.
- **After an emergency:** a care window keeps the patient on restricted duty, with tighter thresholds, until the medical team records a review.
- **Critical alerts escalate:** a level-2 alert goes to the medical officer, then to the commander and then to the flight surgeon if nobody acknowledges it.

Every tunable number is in [`assumptions.py`](backend/canary/domain/assumptions.py) with its source. Anything without a published source is marked **"Canary prototype assumption"**.

---

## Data, honestly

Full detail is in [docs/data.md](docs/data.md).

- **No reading in the demo is a real person's measurement.** Astronaut health data is not published, so the demo crew is fictional and every stored reading says `origin = simulated`.
- **The blood panels are modelled on real NASA data:** the demo crew's blood count, creatinine, potassium, calcium and CRP follow the pattern of the Inspiration4 crew (NASA OSDR OSD-569 and OSD-575), each person following the subject of the same sex, labelled "modelled on Inspiration4".
- **Bone density is a DXA scan** (g/cm²) before launch, and a labelled model estimate in flight, with no limit applied to the estimate.
- **Real NASA records** ship with the app, so it never needs a network: the May 2024 solar storm from DONKI and the Curiosity RAD dose spike at Gale crater, replayed in the story.
- **Real sources for every limit:** NASA-STD-3001 for flight limits, and guidelines (AHA, MedlinePlus, ADA, CDC…) for population ranges, each with its link and the date it was checked.

**Bring your own data.** A mission is a folder of CSV spreadsheets (crew, ground accounts, itinerary, readings, storms, goals, scenes). Load one from Canary Control › Data, or send live readings from a device or lab to `POST /api/observations` with a device key. Real readings count as real everywhere, and every chart says where its numbers come from.

---

## The 3D body

- **Shape:** the MakeHuman base mesh (CC0), converted by `tools/build_body_model.py`.
- **Inside:** real anatomical meshes from BodyParts3D (bones, brain, eyes, heart, lungs, gut, kidneys…), fitted to the body by `tools/build_anatomy_model.py`. If they can't load, a procedural anatomy takes their place, so the body never disappears.
- **Look:** custom WebGL shaders in plain Three.js: an iridescent shell, glowing organs, light flowing along vessels and nerves, bloom.
- **Meaning:** each body system takes its status colour. The **Physical** lens shows organs and bones; the **Mental** lens dims the body and lights the brain and nerves. Click a part to focus on it and open its panel.

| Body part | System | Data behind it |
| --- | --- | --- |
| Brain, head, nerves | Brain & mind | sleep, reaction time, mood, stress, time with crew, cognitive tests |
| Eyes | Eyes & vision | Amsler grid (a screen for spaceflight vision changes) |
| Heart, arteries | Heart & circulation | resting pulse, blood pressure, aerobic capacity |
| Lungs | Lungs & breathing | blood oxygen |
| Skeleton | Bones | bone density (DXA before launch, estimate in flight) |
| Arms, legs, hands, feet | Muscles | exercise, grip strength |
| Liver, stomach, intestines | Gut & nutrition | fasting glucose, weight |
| Kidneys, bladder | Kidneys & hydration | water, creatinine, calcium |
| Spleen | Blood & immunity | temperature, blood count |
| Torso surface | Radiation exposure | career dose against NASA's limit, storms |

---

## Architecture

**One Python API, one SQLite file, one browser app.** A spacecraft can't depend on a network or a cluster of services. The only split worth designing for is *on board* versus *ground*: the same code, two deployments, synchronised over a delayed link.

```
 Browser: React + TypeScript + Three.js                       frontend/
   │  HTTP /api   (Vite proxies in development; FastAPI serves the build with make serve)
   ▼
 Canary API: FastAPI, one process                             backend/canary/
   ├─ domain/data          the one way in for readings, space events, scenes and goal history
   ├─ domain/telemetry     what a value is on a day, where it came from, how old it is
   ├─ domain/health        baselines, z-scores, alert levels, body systems, readiness
   ├─ domain/risk          eight risks from weighted evidence
   ├─ domain/assessment    clinical-style assessment of each reading (status, confidence)
   ├─ domain/standards     NASA-STD-3001 flight limits      domain/reference   population ranges
   ├─ domain/assumptions   every tunable number with its source
   ├─ domain/advice        the advice loop                  domain/care        care windows after an emergency
   ├─ domain/notify        critical alerts and escalation   domain/audit       hash-chained audit trail
   ├─ domain/goals         goals, streaks, patches, crew missions, ranking
   ├─ domain/privacy       who sees what, operational status, the five hazards
   ├─ domain/protocols     Guided Response protocols by gravity and place (+ protocol_match, protocol_pages)
   ├─ domain/plan, mission, spacetime    itinerary, mission clock, Mars time, signal delay
   ├─ domain/dose, nasa, live            radiation dose, NASA snapshot, optional live DONKI
   ├─ domain/registry, devices           crew and ground accounts, device keys for ingest
   ├─ assistant/           the AI layer: providers, tools, knowledge base, guard, chat, briefing, suggestions
   ├─ auth.py              PINs (hashed), session tokens, lock-outs
   └─ main.py              the routes
   ▼
 SQLite (on board, offline): readings, check-ins, goals, messages, emergencies, settings, audit trail
```

| Decision | Why |
| --- | --- |
| One FastAPI process and SQLite | Runs offline on board, one thing to deploy, test and back up |
| Readings written only through `domain/data.py` | A package, a device and a lab go through the same checks; real data replaces simulated data with no code change |
| Personal baseline **and** population range | Astronauts are fit outliers: their own normal gives the early warning, the population range stays as the safety limit |
| Protocols as JSON | The medical team can review and replace them without code |
| A 4-digit PIN per private space, no accounts to create | A shared terminal in a cabin: fast to enter, and Guided Response needs none |
| AI only explains | Deterministic rules decide alerts, risks and emergencies |
| React and plain Three.js, no UI kit | Full control of the mission-console look and the hologram |

---

## Configuration

Every setting is optional; the defaults run the demo. Copy [`.env.example`](.env.example) to `.env` at the repository root (the backend loads it from there whatever folder it starts in; variables already exported in the shell win). Restart the backend after any change. `.env` is git-ignored: never commit it.

**AI assistant**

| Variable | Default | Meaning |
| --- | --- | --- |
| `GEMINI_API_KEY` | empty | Google Gemini key; selects Gemini in `auto` mode |
| `ANTHROPIC_API_KEY` | empty | Anthropic key; selects Claude in `auto` mode when no Gemini key is set |
| `CANARY_LLM_PROVIDER` | `auto` | `auto` (the key decides), `gemini`, `anthropic`, `none` (rules only) or `local` (a slot for an on-board model, not implemented) |
| `CANARY_GEMINI_MODEL` | `gemini-3.1-flash-lite` | Gemini model |
| `CANARY_ANTHROPIC_MODEL` | `claude-sonnet-5-5` | Claude model |
| `CANARY_LLM_MODEL` | empty | one model for an explicitly named provider; ignored with `auto` |
| `CANARY_LLM_EFFORT` | `low` | effort sent to the model (`low` keeps tool calls few and answers short) |
| `CANARY_LLM_TIMEOUT_S` | `150` | one deadline per question; past it the answer falls back to rules |
| `CANARY_LLM_MAX_STEPS` / `CANARY_LLM_MAX_TOOL_CALLS` | `3` / `6` | tool-calling rounds and tool calls per question |
| `CANARY_KB` | `backend/kb.db` | knowledge-base file |
| `CANARY_EMBEDDER` | `local` | `local` (fastembed, bge-small-en-v1.5) or `none` (keyword search only, fully offline) |
| `CANARY_EVAL_PRICE_IN` / `CANARY_EVAL_PRICE_OUT` | provider default | USD per million tokens, for the paid-eval cost estimate |

**Mission, sign-in and security**

| Variable | Default | Meaning |
| --- | --- | --- |
| `CANARY_MODE` | `demo` | `demo` or `flight`. Flight loads no demo, turns off demo-only routes, runs the delay in real time, and refuses to start without the two secrets below ([details](docs/operations.md#demo-mode-and-flight-mode)) |
| `CANARY_TOKEN_SECRET` | random per start | signs session tokens; set it so sessions survive a restart (required in flight mode) |
| `CANARY_CONTROL_BOOTSTRAP_PIN` | `4242` in demo | first-access PIN of Canary Control, accepted only until a Mission Control account exists (required in flight mode) |
| `CANARY_CREW_PINS` | `h:1001,k:1002,a:1003,t:1004` in demo | fallback PIN for a crew id with no stored PIN. Registered PINs are stored salted and hashed (PBKDF2-SHA256) and always win |
| `CANARY_TOKEN_TTL` | `3600` | session lifetime in seconds |
| `CANARY_PBKDF2_ITERATIONS` | `100000` | rounds of the PIN hash; leave it alone (changing it locks out every stored PIN) |
| `CANARY_ESCALATE_MINUTES` | `10` | minutes before an unacknowledged critical alert goes up one step (run faster in the demo, like the delay) |
| `CANARY_DELAY_SPEEDUP` | `20` in demo, `1` in flight | how many times faster the communication delay runs |
| `CANARY_MISSION_PACKAGE` | `odyssey1-mars` | package loaded on the first start and by Reset demo; empty for an empty start |
| `CANARY_MISSIONS_DIR` | `data/missions` | where packages are looked up by name |
| `CANARY_INGEST_KEY` | empty | shared ingest key for `POST /api/observations`, demo mode only (flight uses per-device keys) |
| `CANARY_CORS_ORIGINS` | `http://localhost:5173,http://127.0.0.1:5173` | other web origins allowed to call the API |

**Runtime**

| Variable | Default | Meaning |
| --- | --- | --- |
| `CANARY_DB` | `backend/canary.db` | the SQLite file (created on start) |
| `CANARY_FRONTEND_DIST` | `frontend/dist` | built web app served by `make serve` |
| `CANARY_DAY_SYNC` / `CANARY_DAY_SYNC_SECONDS` | `1` / `600` | background thread that notices a new mission day, and how often it looks |
| `CANARY_WARM` | `1` | compute everyone's health at start-up so the first click is quick |
| `CANARY_LIVE_SPACE_WEATHER` | `0` | `1` also imports NASA DONKI's solar particle events of the last 30 days (only while the clock follows the real date) |
| `NASA_API_KEY` | `DEMO_KEY` | key for api.nasa.gov (DEMO_KEY is rate-limited) |
| `CANARY_SKIP_DOTENV` | unset | `1` ignores the `.env` file (the test suite sets it, so a developer's keys never reach the tests) |

---

## Testing

```bash
make test
```

`make test` runs the backend test suite (about 1,250 tests, no network) and the frontend type check. It covers:

- **The demo, number by number:** golden snapshots of every story scene.
- **The engine:** baselines, alert levels with persistence and hysteresis, risks, NASA limits, reference ranges, the advice loop, care windows, escalation, the clock, dose and storms, crews of one to six, empty and stale data.
- **Data:** mission packages, ingest and corrections.
- **Security and privacy:** PINs and lock-outs, sessions, the visibility contract, input checks (one bad value per form), the audit trail.
- **Emergencies:** opening, logging, closing and cancelling.
- **The AI layer:** contracts, tools, the knowledge base and its freshness, the guard, the model loop with a scripted model, provider selection, protocol matching, suggestions, briefing access and rate limits.

The assistant's adversarial eval runs free with `cd backend && .venv/bin/python -m evals.run --dry` (36 cases). One knowledge-base test needs a Python that can load SQLite extensions (see [Quick start](#quick-start)).

---

## API

The interactive documentation with every request and response shape is at **<http://localhost:8000/docs>**. All 95 routes, grouped, with who may call them, are in [docs/api.md](docs/api.md). The ones you meet first:

| Route | Purpose |
| --- | --- |
| `POST /api/crew/{id}/session` · `POST /api/medical/session` · `POST /api/control/session` | Sign in with a PIN; returns a token for `Authorization: Bearer` |
| `GET /api/crew/overview` | What everyone on board may see: participation, hazards, crew missions. Never status |
| `GET /api/crew/{id}` | One astronaut in full (the person and the medical team only) |
| `POST /api/checkins` | Save a test or log; returns the result against your normal and the population range |
| `POST /api/emergencies` · `POST /api/emergencies/{id}` · `GET /api/emergencies/open` | Open Guided Response · log, close or cancel · the alarm bar |
| `GET /api/assistant/status` · `POST /api/assistant/ask` | Which model is configured (never a key) · ask Ask Canary |
| `POST /api/observations` | Readings from a device or lab (`X-Canary-Key`) |
| `POST /api/control/import` | Load a mission package (Mission Control) |

---

## Operations

For anything beyond a laptop demo, see [docs/operations.md](docs/operations.md). In short:

- run **one process with one worker**;
- set `CANARY_TOKEN_SECRET`, or use `CANARY_MODE=flight`, which requires it;
- put a reverse proxy with HTTPS in front;
- back up the single SQLite file with `sqlite3 ".backup"`, and check the audit chain after a restore (`GET /api/audit/verify`);
- health checks are `GET /api/health/live` and `GET /api/health/ready`.

---

## How it maps to the judging criteria

| Award | What in Canary speaks to it |
| --- | --- |
| Best Use of Science | Personal-baseline statistics with persistence and hysteresis; NASA-STD-3001 limits by place and EVA role; NASA's five hazards per body system; protocols adapted to 0 g and partial gravity; every number with its source |
| Best Use of Data | Five NASA sources in the product (DONKI, Curiosity RAD, OSDR OSD-569 and OSD-575, NASA-STD-3001), shipped as a reproducible offline snapshot, with an optional live DONKI feed |
| Best Use of Technology | Holographic WebGL body with clickable systems, a typed API, a tool-calling assistant behind a tested guard, offline-first design |
| Galactic Impact | Works where help is far: Mars transit, the Moon, and on Earth on ships, platforms and remote communities |
| Best Mission Concept | A mission plan that re-adapts the whole system per leg (ISS, Moon, Mars), the real signal delay in every message and report, Mars time |
| Most Inspirational / Storytelling | The canary in the mine, the five-chapter intro, the six-scene story |
| Global Connection | An international crew; a system meant for any agency or commercial crew |
| Art & Technology | The hologram: iridescent shell, flowing vessels, a Mental lens that lights the nervous system |
| Local Impact | The same system for isolated workers and communities on Earth |

---

## What to build next

1. **AI:** an on-board model (the `local` provider slot, for example llama.cpp with schema-constrained output) on the same loop and guard, so the assistant works with no network at all; run the paid eval and tune the guard; a clinical review of the guard rules.
2. **Real devices:** small bridges that turn a wearable's or a lab's export into `POST /api/observations` calls (the endpoint, device keys and checks exist).
3. **Ground sync:** store-and-forward of messages, briefings and check-ins to a ground station.
4. **Clinical review:** replace the illustrative protocols and every prototype assumption with flight-surgeon-approved values.
5. **Signed mission packages** from Mission Control, with signed updates during flight.

---

## Limits, honestly

- **Simulated data.** No reading is a real person's measurement; Canary has not run on flight data. The weights, cuts and windows of the risk, advice and care rules were tuned on the simulated crew and are marked as prototype assumptions.
- **Not clinically reviewed.** Guided Response protocols are illustrative first aid adapted to spaceflight; real ones come from the flight surgeon. The assistant's guard rules (English, Portuguese and Spanish patterns) are a starting list, not reviewed by a clinician.
- **Reference ranges** are fully checked for blood oxygen, fasting glucose and sleep; the others are checked in part and say which number is still an assumption.
- **NASA limits:** the limits are NASA's; the early-warning steps before them (90% strength, 3% bone loss) are assumptions. Grip stands in for whole-body strength. The in-flight bone value is a model estimate with no limit applied. Earlier-flight dose is estimated from days in space when the record has none.
- **Dose without dosimeters is an estimate** from the plan's daily rate per place plus each storm's assumed extra dose.
- **Demo shortcuts:** the PINs are public; a 4-digit PIN with lock-outs is a prototype lock, not real security; the communication delay runs 20× faster; sessions end at a restart unless `CANARY_TOKEN_SECRET` is set.
- **The AI model needs a key and a network.** Without them, answers come from rules (see [About the AI assistant](#about-the-ai-assistant-read-this-first)). The rate limits are per process, in memory.

---

## Use of SI tools

NASA Space Apps asks every team to say where and how Super Intelligence (SI) tools were used. Canary uses them in two ways: to build it, and, optionally, inside it.

### Building Canary

| What | How SI was used | Where it is recorded |
| --- | --- | --- |
| **Code** | Much of the backend, frontend, tests and tools was written with Claude (Anthropic: Claude Code with Claude Sonnet 5.5 and Claude Opus 5.5) as a coding assistant. The team chose what to build, reviewed the changes and ran the tests. | Every commit made with it carries a `Co-Authored-By: Claude …` trailer: `git log --format='%h %an %(trailers:key=Co-Authored-By,valueonly)'` lists them |
| **Design** | Interface reviews used design skills for the coding assistant (Impeccable, Emil Kowalski's design-engineering notes, Taste); the team decided the design rules (flat surfaces, colour only for state, one accent colour) | This section |
| **Data and analysis** | SI helped write the data scripts (`data/prepare_blood.py`, `data/generate_dataset.py`), analyse the Inspiration4 blood data (OSD-569, OSD-575), and find and check the source of each clinical number. No model produced a value: the blood patterns come from the NASA files, limits and ranges from the page named next to each one, and simulated values from the deterministic generator, whose recipes are marked as prototype assumptions | The `source` and `checked` fields beside every number, and the commit trailers |
| **Text** | The README, `docs/` and on-screen text were drafted with SI help and edited by the team | This section and the commit trailers |
| **Images, video, audio** | None generated by SI. The body comes from MakeHuman (CC0) and BodyParts3D (CC BY-SA 2.1 Japan), the icons are drawn in code, and the emergency voice is the browser's built-in speech synthesis. Any SI-generated image or video added later carries a visible "SI-generated" watermark | [Credits and licences](#credits-and-licences) |

No NASA logos, flags or mission identifiers were generated with SI.

### Inside Canary (optional)

The assistant (Ask Canary, the weekly briefings and the rephrasing of suggestions) calls a large language model, Google Gemini or Anthropic Claude, **only when an API key is set on the backend**. Without a key nothing is written by a model: answers come from rules. Model output is labelled on screen ("AI answer") and in the API (`mode: "ai"`, `provider`, `model`), checked by the guard, and logged. The knowledge base can also rank its search results with a small local embedding model (BAAI bge-small-en-v1.5 through fastembed), which writes no text.

---

## Credits and licences

- Body mesh: [MakeHuman](https://github.com/makehumancommunity/makehuman) base mesh, **CC0 1.0**.
- Bones and organs: [BodyParts3D](https://dbarchive.biosciencedbc.jp/en/bodyparts3d/desc.html), © The Database Center for Life Science, **CC BY-SA 2.1 Japan** (share-alike applies to `anatomy.glb`; details in [`ANATOMY_CREDITS.md`](frontend/public/models/ANATOMY_CREDITS.md)).
- NASA data: DONKI, Curiosity RAD (PDS/SPDF), OSDR OSD-569 and OSD-575 are NASA open data. NASA-STD-3001 is a NASA technical standard, quoted by item.
- Fonts: the system's own (nothing is loaded from another server).
- Built for the NASA Space Apps Challenge 2026. Canary is not affiliated with or endorsed by NASA.
