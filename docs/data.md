# Data: mission packages, live readings and NASA sources

How data gets into Canary, what is real and what is simulated, and how to replace the demo with your own. The [README](../README.md#data-honestly) has the short version.

## Contents

1. [One way in](#one-way-in)
2. [Mission packages](#mission-packages)
3. [Live readings from devices and labs](#live-readings-from-devices-and-labs)
4. [The mission clock, Mars time and the signal delay](#the-mission-clock-mars-time-and-the-signal-delay)
5. [Space events and radiation dose](#space-events-and-radiation-dose)
6. [What is real and what is simulated](#what-is-real-and-what-is-simulated)
7. [NASA data used](#nasa-data-used)
8. [The demo data generator](#the-demo-data-generator)

---

## One way in

Canary reads a mission only from data. The engine has no crew, no dates, no storm days and no story of its own. Everything comes from the SQLite database, and the database is filled through one module, [`backend/canary/domain/data.py`](../backend/canary/domain/data.py), whichever way the data arrives: a mission package, a device or lab sending readings, a space event added in Canary Control, the loader script, or NASA DONKI. Every path runs the same checks in the same transaction.

## Mission packages

A **mission package** is a folder of plain spreadsheets (UTF-8 CSV with a header row; any spreadsheet program opens them). Three ship in [`data/missions/`](../data/missions/): `odyssey1-mars` (the demo), `odyssey1-moon` and `odyssey1-iss`. Each folder has its own README. Any subset of the files can be loaded.

| File | Columns | What it holds |
| --- | --- | --- |
| `mission.csv` | `callsign, name, launch_date, preset, simulated_today, simulated_time, source` | One row: the plan preset, the launch date, and the simulated "today" (empty: the clock follows the real date) |
| `legs.csv` | `start_day, end_day, location, label` | The itinerary. Day 0 is launch, negative days are pre-flight. `location` is one of `earth`, `rocket`, `iss`, `moon`, `transit`, `mars`, `moon_rover`, `mars_rover` |
| `crew.csv` | `id, name, role, initials, home, dob, sex, nationality, languages, agency, flights, days_in_space, height_cm, weight_kg, blood_type, skin_type, handedness, vision, allergies, medications, conditions, diet, vaccinations, emergency_contact, eva, prior_dose_msv, pin` | One row per astronaut, one to six. The same record Mission Control's form fills. Lists such as `languages` are joined with `;`. An empty `prior_dose_msv` means: estimate it from `days_in_space`. The `pin` is stored hashed |
| `ground.csv` | `id, name, role, pin` | The ground accounts: flight surgeons (`flight_surgeon`, sign in to the medical console) and Mission Control (`mcc`, sign in to Canary Control). The crew medical officer signs in to the medical console with their crew PIN |
| `observations.csv` | `crew_id, day, indicator, value, unit, origin, method, source, note, measured_at` | One row per measurement. `crew_id` is a person or `cabin`. `measured_at` is a UTC time; `day` alone also works. Indicators and units are the catalog's (`ACCEPT` in `catalog.py`) |
| `space_events.csv` | `id, kind, start_day, end_day, locations, extra_dose_msv, origin, source, note` | Storms and surface radiation events |
| `goal_log.csv` | `crew_id, day, goal_id, done, done_at_time` | Which daily goals each person completed. A goal not in the file was not done |
| `scenes.csv` | `index, day, location, person, storm, when, text` | The bookmarks of the Demo story bar |

**Loading a package**

- In the app: Canary Control › Data › **Load a bundled package**, or **Upload your own** (one `.zip`, or CSV files named like the package files).
- API: `POST /api/control/import` with JSON `{"package": "odyssey1-mars"}`, or a multipart upload (up to 120 MB).
- From a terminal, without a server: `CANARY_DB=/path/to/canary.db python3 scripts/load_mission.py data/missions/odyssey1-mars [--reset]`. Exit status 0 loaded, 1 refused, 2 not a folder.
- `CANARY_MISSION_PACKAGE` names the package loaded on the first start and by **Reset demo** (default `odyssey1-mars`; empty for an empty start).

Every file is validated before anything is written. One bad row refuses the whole import with the file, the line and the field (`observations.csv: Unknown crew id: x (line 12)`), and nothing is stored. Readings already stored are not stored twice, so loading the same package again adds nothing. Goal-log rows never replace a goal someone ticked in the app.

Registering a crew by hand (or **Start from zero**) also drops the package's scenes and its own space events, because they describe people who are no longer on board.

## Live readings from devices and labs

Sensors, wearables and labs send readings while the mission runs, through `POST /api/observations`, with a key in the `X-Canary-Key` header.

- **Device keys.** Mission Control registers each device (`POST /api/control/devices`). The answer carries the device's key **once**; only a hash is stored. A device bound to one astronaut can send only that person's readings. `GET /api/control/devices` lists devices with when each last sent a reading, never a key, and `POST /api/control/devices/{id}/revoke` turns one off.
- **The shared key** `CANARY_INGEST_KEY` still works in demo mode only. With no shared key and no device ever registered, ingest is off (503). A wrong key is 401.

```bash
curl -X POST http://localhost:8000/api/observations \
  -H "Content-Type: application/json" \
  -H "X-Canary-Key: YOUR-DEVICE-KEY" \
  -H "Idempotency-Key: batch-2035-06-12-0730" \
  -d '{"rows": [
        {"crew_id": "h", "indicator": "sleep", "value": 6.4, "unit": "h",
         "measured_at": "2035-06-12T07:30:00Z", "origin": "device", "method": "wearable", "source": "band:42"},
        {"crew_id": "cabin", "indicator": "co2", "value": 920, "unit": "ppm",
         "measured_at": "2035-06-12T07:30:00Z", "origin": "device", "method": "environment"}
      ]}'
```

Rules:

- `origin` is **required**: `device` (a sensor or wearable), `manual` (typed in by a person), `lab` (a laboratory result), `simulated` or `sample` (an example; never used for a baseline or an alert, and refused in flight mode).
- `method` is one of `wearable`, `manual`, `test`, `blood`, `urine`, `environment`, `dosimeter`, `lab` or `sensor` (default `sensor`).
- Batches hold up to 5,000 rows and 2 MB.
- A time more than five minutes in the future is refused.
- One bad row refuses the batch with `422` and `rows.N.field`, and nothing is stored.
- Sending the same reading twice stores it once. A *changed* value for a stored reading is a `409`: send `supersedes` and `reason` to correct it (the old value stays on record).
- With an `Idempotency-Key`, a retry with the same body returns the first answer.

The answer is `{accepted, duplicates, corrected, alerts_opened}`; the health evaluation has already run. The accepted indicators, units and plausibility ranges are the `ACCEPT` table in [`catalog.py`](../backend/canary/domain/catalog.py). The ranges catch typos and broken sensors; they are not clinical ranges.

**What Mission Control sees** (`GET /api/control/data-status`): what was loaded and when, as counts and dates per person and indicator, whether ingest is on, and the number of goal entries, events and scenes. Never a value, and nothing about anyone's health.

## The mission clock, Mars time and the signal delay

- **The mission day** is the clock's date minus the launch date. The clock runs on the **real date** (UTC) unless a **simulated date** is set, which is how the demo sits in 2035. Set it in Canary Control › Data or with `PUT /api/control/clock` (`{"date": "2035-10-31", "time": "12:00"}`, or `{"real": true}`).
- **A background thread** (`CANARY_DAY_SYNC`, every `CANARY_DAY_SYNC_SECONDS`) notices a new mission day and runs what a day triggers.
- **Day labels:** L-30 before launch, Day N in flight, Sol N on Mars counted from landing. [`spacetime.py`](../backend/canary/domain/spacetime.py) computes Mars time from the Mars Sol Date (Allison and McEwen 2000; NASA GISS Mars24) and local mean solar time at Jezero crater.
- **The Earth–Mars signal delay** comes from a simple orbit model: about 4.4 minutes at opposition and 21 at conjunction. A Sun–Earth–Mars angle below 3° is treated as the solar-conjunction blackout. The Moon is 1.28 s one way. The demo runs every delay `CANARY_DELAY_SPEEDUP` times faster (default 20).

## Space events and radiation dose

**Space events** are the storms:

- `kind` is `sep` (a solar particle event, which reaches a crew away from Earth) or `mars` (a radiation event at the Mars surface; the crew waits it out indoors);
- an event has a first and last mission day, the places it reaches, the extra dose it adds (mSv) and an origin (`real`, `simulated` or `donki`);
- a storm raises the radiation alert and risk, and the immune "blood count due" warning covers its first day and the 13 after it;
- add one in Canary Control › Data or with `POST /api/control/space-events`;
- with `CANARY_LIVE_SPACE_WEATHER=1` and the clock on the real date, NASA DONKI's solar particle events of the last 30 days are imported as events with origin `donki` when the plan has the crew away from Earth that day. Offline, nothing happens.

**Dose** says where it comes from, in `dose.origin`:

- `measured`: every day so far has a dosimeter reading;
- `partial`: some days do;
- `estimated`: none, so the dose is the daily rate of each place in the plan plus the extra dose of the events.

The daily rates were checked on 2026-11-15 (NASA LSAH newsletter 2023 for Earth and the station, Curiosity RAD for the cruise and Gale crater, Chang'E 4 LND for the Moon). The launch and rover rates are prototype assumptions. Crew-wide pages only ever see the cabin or the plan; a person's own dosimeter shows only in their space and to the medical team.

## What is real and what is simulated

Astronaut health data is not published as open data, so **no reading in the demo database is a real person's measurement**: every row of the package's `observations.csv` says `origin = simulated`.

| Part | Status |
| --- | --- |
| The crew, their daily readings, the cabin dosimeter, the goal log, the scenes | **Simulated**, deterministic, with the story written in. The crew is fictional |
| Blood count, creatinine, potassium, calcium, C-reactive protein | **Simulated, modelled on real NASA data**: the demo crew's values follow the pattern of the Inspiration4 crew's panels (NASA OSDR OSD-569 and OSD-575), labelled `modelled on Inspiration4` |
| Bone density | Simulated DXA scans (g/cm²) before launch; in flight a labelled model estimate |
| The storms in the story | **Replays** of two real events whose NASA records Canary ships: the 10 May 2024 solar storm (DONKI) and the 20 May 2024 dose spike at Gale crater (Curiosity RAD). The extra dose a storm adds to the crew is a prototype assumption |
| Limits and ranges | **Real sources**: NASA-STD-3001 for flight limits, named guidelines for population ranges, each with its link |

When a real mission sends readings (`origin` `device`, `manual` or `lab`), they count as real everywhere, and the charts, risks and data-origin tags say so.

## NASA data used

| Source | What Canary uses | Where |
| --- | --- | --- |
| [DONKI](https://ccmc.gsfc.nasa.gov/tools/DONKI/) space weather (api.nasa.gov) | 5 to 16 May 2024: 14 solar particle events, Kp up to 9, fast CMEs, linked flares | Story step 4, Mission page, storm alerts; optional live import |
| [Curiosity RAD level 2](https://spdf.gsfc.nasa.gov/pub/data/aaa_planetary/msl/rad/cdf/obs-l2/) (PDS / SPDF) | Dose rate at Gale crater: quiet 9 May 2024 (mean ≈ 164 µGy/day) vs storm 20 May 2024 (peak 8,378 µGy/day, about 51×) | Story step 6, Mission page |
| [OSDR OSD-569](https://osdr.nasa.gov/bio/repo/data/studies/OSD-569) Inspiration4 blood counts | The pattern the demo crew's blood count is modelled on (7 collections around a 3-day flight) | Blood panel, `immune` and `radiation` risks |
| [OSDR OSD-575](https://osdr.nasa.gov/bio/repo/data/studies/OSD-575) Inspiration4 metabolic panel | The pattern for creatinine, potassium, calcium and CRP, with laboratory ranges by sex | Blood panel, `renal`, `cardio` and `immune` risks |
| [NASA-STD-3001 Vol. 1 Rev. C](https://www.nasa.gov/wp-content/uploads/2023/11/nasa-std-3001-vol-1-rev-c-with-signature.pdf) | The flight limits: career and solar-event dose, strength, bone density, aerobic capacity for EVA, sleep period | Indicators, risks, alerts |
| [NASA HRP hazards](https://www.nasa.gov/hrp/hazards/) | The five hazards of spaceflight (RIDGE) behind every body system | System cards, assistant knowledge |

The records live in [`backend/canary/data/nasa_snapshot.json`](../backend/canary/data/nasa_snapshot.json), so the ship never needs a network. `data/prepare_nasa_data.py` rebuilds the space-weather and RAD parts from the original downloads (needs `numpy` and `cdflib`), and `data/prepare_blood.py` rebuilds the blood sections from the OSDR files. Glucose from the metabolic panel is left out on purpose: three of four Inspiration4 crew read 36 to 44 mg/dL on the same day (R+45), with every other collection normal, the pattern of a sample processed late.

**Corrections made to the NASA files** (asserted by `data/prepare_blood.py`):

1. C003's blood count at L-92 sat one row down from MCH on in OSD-569 (platelets 12.9, MPV 330). It was realigned and checked by arithmetic: 9.6 thousand white cells × 71.1% = 6,826 neutrophils, × 20.8% = 1,997 lymphocytes; platelets 330.
2. Each demo person follows the Inspiration4 subject **of the same sex** (C001 and C004 are men, C002 and C003 women, per the OSD-569 metadata).
3. Ranges by sex: the laboratory's female and male ranges are kept (haemoglobin 11.7 to 15.5 or 13.2 to 17.1 g/dL, haematocrit, red cells, creatinine, calcium). Haemoglobin is labelled `percent` in OSD-569; it is g/dL.

## The demo data generator

The packages are generated, not typed: `python3 data/generate_dataset.py` rewrites the three package folders, [`data/DATASET.md`](../data/DATASET.md) and the reference table `backend/canary/data/observations.csv`. It is deterministic, standard library only, with no network.

- [`data/recipes.json`](../data/recipes.json) holds one recipe per indicator: baseline, day-to-day spread, slow drift by gravity and mission day, which hidden states move it, how often it is measured, the chance of a missed measurement, and a `source` with `verified`. Four hidden states (fatigue, hydration, energy, bone loss) move related signals together; the story is dated events that push them.
- [`data/demo_crew.json`](../data/demo_crew.json) holds the demo crew, story and PINs (read only by the generator).
- [`data/modelled/`](../data/modelled/) holds the blood values modelled on Inspiration4 (`osd569_cbc.csv`, `osd575_cmp.csv`); they stay `simulated`.
- **Genuine measurements** can be put in a `data/real/` folder (none ships; `crew_id, day, indicator, value` are enough). The generator gives them `origin = real` and lets them replace the simulated row with the same crew, day and indicator. Without the generator, send them to `POST /api/observations` or load your own package.

`data/DATASET.md` lists where each recipe comes from and which ones are prototype assumptions.
