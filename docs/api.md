# API reference

Canary's API is one FastAPI process. The interactive documentation, with every request and response shape, is at <http://localhost:8000/docs> while the backend runs. This page lists all 95 routes, grouped, with who may call them. It is generated from `backend/canary/main.py`.

**Conventions**

- Every sign-in (crew, medical, control) returns a signed token `{kind}.{id}.{roles}.{exp}.{jti}.{sig}` (HMAC-SHA256, `CANARY_TOKEN_TTL`, default one hour), sent as `Authorization: Bearer <token>`. `POST /api/session/logout` revokes it at once.
- A missing, forged, expired or revoked token is nobody: 401, or 403 on a private route.
- Wrong PINs lock the account and the client address (stored in SQLite, so a restart does not clear them): after every 5 failures the wait grows 1, 5, 15, then 60 minutes (429).
- Bad input returns **422** with `detail: [{"field": "crew.1.dob", "message": "Date of birth is required"}]`, and nothing is written.
- Every `/api` response is `Cache-Control: no-store`.

## Sign-in and sessions

Anyone can call these; the PIN is the check. Every sign-in returns a token sent as `Authorization: Bearer <token>`.

| Method | Path | What it does |
| --- | --- | --- |
| `POST` | `/api/medical/session` | Sign in to the medical console: the crew medical officer (their crew id) or a ground flight surgeon, with the account's PIN. |
| `POST` | `/api/crew/{crew_id}/session` | Sign in to a private space with the 4-digit PIN. |
| `POST` | `/api/control/session` | Sign in to Canary Control. |
| `POST` | `/api/session/logout` | End the session this header carries: the token is revoked at once and stops working everywhere. |
| `GET` | `/api/accounts/public` | Who can sign in, for the sign-in pickers: crew {id, name, role, initials, cmo} and ground {id, name, role}. |
| `PUT` | `/api/crew/{crew_id}/pin` | Change your own PIN: needs your session token and the current PIN. |

## Health checks and metrics

Live and ready are public. Metrics need a Mission Control sign-in.

| Method | Path | What it does |
| --- | --- | --- |
| `GET` | `/api/health` | Liveness shortcut: the process answers. |
| `GET` | `/api/health/live` | Liveness: the process answers. |
| `GET` | `/api/health/ready` | Readiness: the database and the knowledge base answer. |
| `GET` | `/api/metrics` | Request counts, errors and p50/p95 latency per route, for this process since it started (in memory, not kept). |

## Mission, plan and catalog

Read by anyone on board; changes need Canary Control.

| Method | Path | What it does |
| --- | --- | --- |
| `GET` | `/api/catalog` | The mission's reference data. |
| `GET` | `/api/mission` | The mission clock: day, date, place, current leg and mode (simulated or real date). |
| `PUT` | `/api/mission` | Demo only: the story step, the simulated day and the place. |
| `GET` | `/api/plan` | The mission plan: itinerary legs. |
| `GET` | `/api/plan/conditions` | Health conditions along the registered plan: hazards per leg and the projected mission dose. |
| `PUT` | `/api/plan` | Save a mission plan (Canary Control). |
| `POST` | `/api/plan/preset` | Load one of the three plan presets (Canary Control). |
| `POST` | `/api/setup` | First-run mission setup (demo only): validate and save the plan, mark setup done and start the mission clock over. |
| `GET` | `/api/mission/overview` | General information about the mission and the crew as a whole: no health data. |
| `GET` | `/api/scenes` | The guided demo's bookmarks (a day, a place, a person, a sentence). |

## Demo controls

Demo mode only (404 in flight mode).

| Method | Path | What it does |
| --- | --- | --- |
| `POST` | `/api/demo/reset` | Clear everything and load the configured mission package (CANARY_MISSION_PACKAGE, default odyssey1-mars). |
| `POST` | `/api/demo/start-empty` | Demo only (404 in flight mode): wipe everything and load nothing, so the intro's guided tour can register the crew and the mission from the start. |
| `POST` | `/api/demo/quickstart` | Demo only (404 in flight mode): load the demo mission package for someone who skips the intro. |

## Crew and personal health

Health detail answers only the person (crew token) and the medical team (medical token). Crew-wide routes never carry status or health.

| Method | Path | What it does |
| --- | --- | --- |
| `GET` | `/api/crew` | Full per-person health summary. |
| `GET` | `/api/crew/photos` | The crew's profile photos: for people on board (crew, medical team, Mission Control) only. |
| `GET` | `/api/crew/overview` | What everyone on board may see: hazards, participation and crew goals. |
| `GET` | `/api/crew/{crew_id}` | Full health detail: the person themself or the medical team. |
| `GET` | `/api/crew/{crew_id}/record` | My information: the personal record Mission Control registered. |
| `PUT` | `/api/crew/{crew_id}/photo` | Profile photo, set by the astronaut. |
| `DELETE` | `/api/crew/{crew_id}/photo` | Remove your profile photo. |
| `GET` | `/api/goals/{crew_id}` | Today's goals, crew missions, streak and patches (self and medical team). |
| `POST` | `/api/goals/{crew_id}/{goal_id}` | Tick or untick a goal (self). |
| `GET` | `/api/advice/{crew_id}` | The advice loop: advice in progress and concluded, with the outcome against the person's own normal. |
| `POST` | `/api/alerts/{crew_id}/{alert_id}/seen` | Mark today's episode of an alert as seen. |
| `GET` | `/api/leaderboard` | Crew rankings: for people on board (crew, medical team, Mission Control) only. |

## Tests and check-ins

Self and medical team.

| Method | Path | What it does |
| --- | --- | --- |
| `POST` | `/api/checkins` | A test or log from the Tests page (or a quick check from My space). |
| `GET` | `/api/checkins/{crew_id}` | Every test with its latest result, plus the recent log. |
| `GET` | `/api/checkins/{crew_id}/{checkin_id}/photo` | The photo of the display kept with a vitals check-in. |

## Guided Response and protocols

Opening, logging, closing and cancelling need someone on board (a crew member, or the crew medical officer in the console). The open-emergency list is public on board so every screen can show the alarm.

| Method | Path | What it does |
| --- | --- | --- |
| `GET` | `/api/protocols` | The Guided Response protocols, resolved for the current gravity and place. |
| `GET` | `/api/protocols/library` | The Protocols page: every protocol as a reference page and which ones are in force now. |
| `POST` | `/api/protocols/match` | What the person sees, in their own words -> the closest protocols with the words that matched. |
| `POST` | `/api/emergencies` | Open Guided Response. |
| `POST` | `/api/emergencies/{eid}` | Log a step, set patient or protocol, close with an outcome (`close` + `outcome`), or cancel (`cancel`). |
| `GET` | `/api/emergencies` | Recent Guided Response records: protocol, patient, outcome, log. |
| `GET` | `/api/emergencies/open` | The cabin-wide alarm banner: the patient's name and the protocol, for every emergency still open. |

## Messages

The sender is whoever the token says. Every message travels with the signal delay of the current place.

| Method | Path | What it does |
| --- | --- | --- |
| `POST` | `/api/messages` | Send a message. |
| `GET` | `/api/messages` | Messages for whoever the token says, with the signal delay applied. |

## NASA data

Public on board.

| Method | Path | What it does |
| --- | --- | --- |
| `GET` | `/api/space-weather` | NASA DONKI space weather (snapshot, or live with CANARY_LIVE_SPACE_WEATHER=1). |
| `GET` | `/api/nasa/rad` | Curiosity RAD dose-rate series (quiet day vs storm day). |
| `GET` | `/api/nasa/sources` | The NASA sources Canary uses, with links. |

## AI assistant, suggestions and briefings

Questions: self or medical team. Suggestions: the person only. Briefing approval: medical team only, once. Rate limits per person: 10 questions, 3 briefings and 6 suggestion builds a minute (429 with `Retry-After`).

| Method | Path | What it does |
| --- | --- | --- |
| `GET` | `/api/assistant/status` | Which AI provider and model are configured (never a key), the limits and the rules. |
| `POST` | `/api/assistant/ask` | Ask Canary a question about one person (self or medical team; 10 a minute). |
| `GET` | `/api/assistant/history/{crew_id}` | The person's questions and answers, with who asked. |
| `GET` | `/api/suggestions/{crew_id}` | Entry 3: personal suggestions from the person's own data. |
| `POST` | `/api/suggestions/{crew_id}/{sid}/accept` | Turn a suggestion into a goal for the next 7 days. |
| `POST` | `/api/suggestions/{crew_id}/{sid}/dismiss` | Hide a suggestion for today and remember the choice: the ranking learns from it (assistant/suggestions.py). |
| `POST` | `/api/briefings` | Build a weekly briefing draft (self; 3 a minute). |
| `POST` | `/api/briefings/{bid}/approve` | The medical team approves a briefing before it is queued for Earth. |
| `GET` | `/api/briefings/{crew_id}` | The person's briefings (self or medical team). |

## Medical console

A medical token (the crew medical officer or a flight surgeon). Every setting is versioned; nothing is deleted (a voided goal stays, marked).

| Method | Path | What it does |
| --- | --- | --- |
| `GET` | `/api/medical/overview` | The medical console: everyone with status, alerts, risks, care events. |
| `PUT` | `/api/medical/care-sensitivity` | How much tighter a patient's thresholds are during the care window after an emergency (1 = no change). |
| `GET` | `/api/medical/care-sensitivity` | Current care-window sensitivity factor. |
| `GET` | `/api/medical/observations/{crew_id}` | Recent current readings of one person (the ids the medical 'Correct a value' form needs). |
| `POST` | `/api/medical/care-windows/{eid}/review` | The medical team ends a care window with a recorded review. |
| `PUT` | `/api/medical/exercise-adjust` | How much the day's exercise may be lightened while the fatigue risk is up. |
| `GET` | `/api/medical/exercise-adjust` | Current exercise lightening under fatigue. |
| `GET` | `/api/medical/assistant-audit` | AssistantAuditEntry[]: the latest questions, how they were answered and which guards fired. |
| `PUT` | `/api/medical/thresholds` | Set the watch and act thresholds for the whole crew (versioned). |
| `GET` | `/api/medical/settings-history` | Every version of the medical settings (thresholds, care sensitivity, exercise adjustment), oldest first. |
| `POST` | `/api/medical/goals` | Prescribe a goal for one astronaut. |
| `GET` | `/api/medical/goals` | The goals the medical team prescribed. |
| `DELETE` | `/api/medical/goals/{gid}` | Void a goal. |

## Alerts and audit

Alert events: the medical team sees all, a crew member their own. The audit trail is a hash chain; `verify` reports the first altered entry.

| Method | Path | What it does |
| --- | --- | --- |
| `GET` | `/api/audit` | The audit trail, newest first, `limit` entries (max 200) from `before_id` back; `next` is the `before_id` of the following page. |
| `GET` | `/api/audit/verify` | Walk the hash chain: {ok, broken_at} with the id of the first entry that was altered or removed. |
| `GET` | `/api/alerts/events` | Stored alert events, newest first. |
| `POST` | `/api/alerts/events/{event_id}/ack` | Acknowledge an alert event. |

## Corrections

A person asks for a correction to their own record; the medical team or Mission Control makes it. The old value and the reason always stay on record.

| Method | Path | What it does |
| --- | --- | --- |
| `PUT` | `/api/corrections/crew/{crew_id}/height` | Correct a height on record (medical team or Mission Control); the old value and the reason stay. |
| `PUT` | `/api/corrections/mission/name` | Correct the mission name (medical team or Mission Control). |
| `PUT` | `/api/corrections/measurements/{obs_id}` | Correct a stored measurement (medical team or Mission Control); the old value and the reason stay. |
| `POST` | `/api/crew/{crew_id}/corrections` | A person asks for a correction to their own height, the mission name or a measurement of theirs. |
| `GET` | `/api/corrections` | Open correction requests. |

## Canary Control (Mission Control)

A Mission Control token. Never returns a health value.

| Method | Path | What it does |
| --- | --- | --- |
| `GET` | `/api/control/overview` | What Earth follows: operational status as the medical team reports it, participation, hazards, traffic. |
| `GET` | `/api/control/register-options` | What the registration form needs: the mission profiles, their itineraries and mission doses, the career limit. |
| `GET` | `/api/control/demo` | Demo only: what the 'fill with the demo crew' button puts in the form. |
| `POST` | `/api/control/register` | Register the crew (one to six people), the ground accounts and the mission, then start the mission clock from the beginning. |
| `POST` | `/api/control/demo-data` | Demo only: use the demo data: replace everything with the bundled demo mission (crew, ground accounts, itinerary, readings, goal history, space events and the demo story), the same state as a fresh start. |
| `POST` | `/api/control/devices` | Register a device that sends readings. |
| `GET` | `/api/control/devices` | Every device with when it last sent a reading. |
| `POST` | `/api/control/devices/{device_id}/revoke` | Revoke a device key. |
| `POST` | `/api/control/space-events` | One space-weather event: kind, start_day, end_day, locations, extra_dose_msv (0 to 2000), origin, source, note. |
| `PUT` | `/api/control/clock` | Move the mission clock: {"date": "YYYY-MM-DD", "time": "HH:MM"} for a simulated date (time is optional), or {"real": true} to follow today's date in UTC again. |
| `GET` | `/api/control/space-events` | List space events. |
| `GET` | `/api/control/data-status` | What Mission Control may know about the data: is ingest on, which package, how much of each kind, and when each person's indicator last arrived. |
| `POST` | `/api/control/import` | Import a mission package: a multipart upload of a .zip or of CSV files named like the package files, or JSON {"package": "odyssey1-mars"} for a bundled one. |

## Live data ingest

A device key (or the shared demo key) in `X-Canary-Key`. See [data.md](data.md#live-readings-from-devices-and-labs).

| Method | Path | What it does |
| --- | --- | --- |
| `POST` | `/api/observations` | A batch of readings: {"rows": [{crew_id, indicator, value, unit, measured_at \| day, origin, method, source, note, supersedes, reason}]}. |
