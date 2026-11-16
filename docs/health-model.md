# How Canary reads health

This is the reference for the engine: how a measurement becomes an alert, how risks are scored, what happens after an emergency and where every limit comes from. The [README](../README.md#how-canary-decides) has the short version.

Every tunable number of the engine lives in one table, [`backend/canary/domain/assumptions.py`](../backend/canary/domain/assumptions.py). Each entry has a value, a unit and a source: either a citation (NASA-STD-3001, a guideline, a physical constant) or the words **"Canary prototype assumption"**, a design choice no published rule backs, there to be reviewed and never to be quoted as fact. Nothing in this document has been clinically reviewed.

## Contents

1. [Three references for every number](#three-references-for-every-number)
2. [How a number becomes an alert](#how-a-number-becomes-an-alert)
3. [Learning, adaptation, missing and stale data](#learning-adaptation-missing-and-stale-data)
4. [Reference ranges and their sources](#reference-ranges-and-their-sources)
5. [NASA-STD-3001: the flight limits](#nasa-std-3001-the-flight-limits)
6. [Risks](#risks)
7. [Hazards (RIDGE)](#hazards-ridge)
8. [The advice loop](#the-advice-loop)
9. [After an emergency](#after-an-emergency)
10. [Critical alerts: who is told, and escalation](#critical-alerts-who-is-told-and-escalation)
11. [Where a value comes from and how old it is](#where-a-value-comes-from-and-how-old-it-is)
12. [How to measure and why](#how-to-measure-and-why)

---

## Three references for every number

| Reference | What it is | What it does |
| --- | --- | --- |
| **Personal baseline** | The mean and spread of the person's own measurements before launch | The early warning: a z-score says how far today is from *their* normal. Astronauts are fit outliers, so a population average would miss their drift |
| **Population range** | The healthy adult range from a named guideline (AHA, MedlinePlus, ADA, CDC…) | The safety net: outside it the indicator is at least level 1; past a *critical* limit it is level 2 on its own, even before launch |
| **NASA-STD-3001** | NASA's flight health standard, Volume 1 Rev. C | The flight limits (strength, aerobic capacity for EVA, career radiation dose): in flight only, they can only raise a level |

## How a number becomes an alert

```
reading of the day ──►  z = (today's value − personal baseline) / personal spread        (never a smoothed value)
                          │
level by thresholds ──────┤  watch 1.5σ (level 1) · act 2.5σ (level 2), set by the medical team
                          │  persistence: level 1 needs the condition on 2 consecutive readings;
                          │               level 2 needs two in a row at the act threshold (one reading alone → level 1)
                          │  hysteresis:  a level reached stays until the distance falls 0.5σ below its entry threshold
                          │  floor:       a critical population limit or a NASA limit alerts at once, skipping both rules
                          │  care window: thresholds × 0.8 for the patient after an emergency
slow slide? ──────────────┤  a line through the last 14 days crosses the level-1 limit within 10 days → "drifting towards your limit"
                          ▼
RISK (domain/risk.py) ────┤  evidence from every related indicator and check-in, added up with a weight table
                          │  → level 0 / 1 / 2 · score · trend · since_day · evidence list
cross-signal rules ───────┤  sleep + mood + reaction together, fast pulse + low water after launch, low pressure + fast pulse back in gravity…
missing data ─────────────┤  no mood check-in for 3 days → `missing_mood` (level 1, never a health risk)
                          ▼
alert = { what it means, what to do now, goals added, sources, hazards }
                          │
personal level 2 ─────────┤  one message to the crew medical officer, one delayed note for Earth; escalates if nobody acknowledges
                          ▼
body system status = the highest level acting on it → colour on the 3D body → Physical and Mental readiness scores
```

The level is a pure function of the history (`health.indicator_level_series`): nothing is stored, so the demo clock can jump to any day and the same day always gives the same answer. Alert *events* (who was told, who acknowledged) are stored separately.

**The 60/25/15 figure you may see on screen is for display only.** `telemetry.current()` shows a weighted recent value (60% today, 25% yesterday, 15% the day before) so a tile doesn't jump with every reading. The alert level never uses it: it reads the day's own value.

Thresholds can be changed for the whole crew by the medical team (`PUT /api/medical/thresholds`) or for one indicator with the setting `thresholds_by_indicator` (`{"sleep": {"watch": 1.0, "act": 2.0}}`, no screen for it). Every medical setting is versioned, and `GET /api/medical/settings-history` lists every version.

## Learning, adaptation, missing and stale data

Canary never fills a gap.

- **Learning your normal.** A personal baseline needs 5 measurements of an indicator on the plan's pre-flight days. With fewer, the person's first 14 days of flight data are used instead (marked `early_flight`). With fewer than 5 of those too, the indicator stays `learning`: no z-score, and only the population range and NASA's limits speak. The page says "Learning your normal: 2 of 5". The pre-flight normal is frozen at launch. No seed value is ever borrowed.
- **Microgravity adaptation.** Pulse and blood pressure move with the fluid shift of the first days in orbit. Indicators flagged `adapts_in_flight` raise no level-1 alert on flight days 1 to 14, and flight days 8 to 14 can re-baseline them (4 readings needed).
- **Stale.** Each indicator has a `max_age` in days: 3 for what is measured daily, longer for weekly tests and monthly panels, and **900 for a bone DXA scan**, which is read until the next one (before launch, then after landing). An older reading is shown as the last measurement ("Last measured day 41"), never counted as today's value, and raises no alert.
- **No data.** A person or indicator with no reading shows **No data yet**: a dash, a gap in the charts, a grey system on the 3D body. A person with nothing measured sees "Canary is waiting for your first measurements".
- **No alerts before launch** except a critical population limit.

## Reference ranges and their sources

The population range is judged on the day's reading. Inside it the personal z-score decides. Each entry in [`reference.py`](../backend/canary/domain/reference.py) has `checked`: the numbers read on the guideline's own page, with the link. The pages were checked on 2026-11-14; the pulse, hypothermia, glucose-54 and sleep pages again on 2026-11-15. `verified` is **yes** when every number was checked (blood oxygen, fasting glucose, sleep), **partly** when some number is still a prototype assumption (it says which), **no** when none was checked.

Two choices keep a healthy personal normal from looking abnormal every day: temperature's low edge stays at 36.1 °C (MedlinePlus lists 36.5 to 37.3), and sleep's at 6 h (CDC asks for 7 or more, which is the app's goal). The reaction-time, processing-speed and digit-span ranges are wide on purpose because they depend on the device. These are risk limits, not diagnoses.

The table below is generated from the code (a test checks it matches):

<!-- reference-table:start (generated from backend/canary/domain/reference.py) -->
| Indicator | Unit | Low | High | Critical (below / above) | Source | Verified |
| --- | --- | --- | --- | --- | --- | :---: |
| `hr` Resting pulse | bpm | 40 | 100 | 30 / 150 | MedlinePlus: resting pulse 60 to 100 bpm for adults, 40 to 60 for well-trained athletes (the low edge 40). Critical limits: prototype assumption | partly |
| `sbp` Systolic pressure | mmHg | 90 | 129 | 70 / 180 | Systolic pressure. AHA: normal below 120, elevated 120 to 129, hypertension stage 1 from 130, stage 2 from 140, severe above 180. MedlinePlus: 90/60 to 120/80 for a healthy adult. Critical low: prototype assumption | partly |
| `dbp` Diastolic pressure | mmHg | 60 | 79 | 40 / 120 | Diastolic pressure. AHA: normal below 80, stage 1 hypertension 80 to 89, stage 2 from 90, hypertensive crisis above 120. MedlinePlus: 60 as the lower edge of 90/60 for a healthy adult. Critical low 40: prototype assumption | partly |
| `spo2` Blood oxygen | % | 95 | 100 | 89 / - | MedlinePlus: normal 95 to 100%; contact your provider at 92% or lower; 88% or lower needs immediate medical attention (critical below 89) | yes |
| `temp` Temperature | °C | 36.1 | 37.2 | 35 / 39.3 | MedlinePlus: an adult probably has a fever above 37.2 to 37.5 °C by mouth (the app flags from 37.2, the lower edge); contact a provider right away for a fever that stays at 39.4 °C or above (critical above 39.3). MedlinePlus lists 36.5 to 37.3 as the usual range; the low edge 36.1 is kept so a cool personal normal (36.4) is not flagged every day (a prototype choice). MedlinePlus: hypothermia is a body temperature below 35 °C (critical low 35) | partly |
| `gluc` Fasting glucose | mg/dL | 70 | 99 | 54 / - | ADA: below 70 mg/dL is low blood glucose and needs treatment (the 15-15 rule). High 99: the fasting reference range of the Inspiration4 laboratory (65 to 99, OSD-575). Critical 54: the ADA and EASD joint statement (2017) says below 54 mg/dL is serious, clinically important hypoglycaemia | yes |
| `sleep` Sleep | h | 6 | 10 | - | CDC: adults need 7 hours or more (the app's sleep goal is 7 h, and NASA-STD-3001 V1 6001 plans an 8.5 h sleep period). The range 6 to 10 h is the National Sleep Foundation's 2015 'may be appropriate' band for adults 26 to 64 (7 to 9 h recommended) | yes |
| `water` Water | L | F 1.6 / M 2 | - | - | EFSA 2010: adequate intake from drinks about 1.6 L (women) and 2.0 L (men) | no |
| `exer` Exercise | min | 21 | - | - | WHO 2020 physical activity guidelines: 150 min a week of moderate activity, about 21 min a day | no |
| `grip` Grip strength | kg | F 16 / M 27 | - | - | EWGSOP2 2019 sarcopenia cut-offs: grip below 16 kg (women) or 27 kg (men) is low strength | no |
| `kss` Sleepiness | /9 | - | 6 | - | Karolinska Sleepiness Scale (Åkerstedt and Gillberg 1990): 7 or more means sleepy | no |
| `react` Reaction time | ms | 150 | 500 | - | prototype assumption: wide on purpose, the result depends on the device and screen lag | no |
| `dsst` Processing speed | correct | 20 | 100 | - | prototype assumption: wide on purpose, depends on the task version and device | no |
| `span` Working memory | digits | 4 | 10 | - | prototype assumption: wide on purpose; forward digit span of adults is usually 5 to 9 | no |

No population range (personal or relative scales): `mood`, `stress`, `social`, `tlx`, `bone`, `vo2`.
<!-- reference-table:end -->

Laboratory values (blood count, creatinine, potassium, calcium) are read against the laboratory's range **for the person's registered sex**. A value already outside the usual range before launch is that person's normal, not a new signal; it counts again only if it moves 10% further out.

## NASA-STD-3001: the flight limits

[NASA-STD-3001 Volume 1, Revision C](https://www.nasa.gov/wp-content/uploads/2023/11/nasa-std-3001-vol-1-rev-c-with-signature.pdf) is implemented in [`standards.py`](../backend/canary/domain/standards.py); every number was read in the document. A NASA limit only raises a level, in flight only, and the indicator says so in `standard: {level, status, text, item, source, url, verified}`. The alert names the item (for example `nasa:std3001v1:V14024`) and the body system turns red when a limit is passed.

| Item | What NASA sets | What Canary checks | Level 2 / level 1 |
| --- | --- | --- | --- |
| V1 4001 / 4002 | VO2max ≥ 32.9 mL/kg/min for microgravity EVAs, ≥ 36.5 for surface EVAs | `vo2` (weekly cycle-ergometer test) against the EVA done **at the current place** and the person's EVA role (surface, microgravity or none) | below the minimum of this place / in 0 g, enough for microgravity but below the surface minimum ahead |
| V1 4024 | strength ≥ 80% of pre-flight | `grip` against the person's pre-flight mean (grip stands in for whole-body strength) | below 80% / below 90% (early warning, prototype assumption) |
| V1 4027 | hip and spine bone density ≥ 95% of pre-mission (femoral neck 90%) | **DXA in g/cm²**, measured before launch and after landing, never on board. The limit is read against the pre-flight scan. In flight Canary shows a model estimate (exercise and time in microgravity), labelled as one, and applies **no limit** to it | below 95% / 3% loss (early warning, prototype assumption) |
| V1 4030 | career effective dose < 600 mSv, all ages and sexes, **every earlier flight included** | the `radiation` risk and the skin system read the **career** dose: the record's `prior_dose_msv` (or an estimate from days in space, labelled) plus this mission | limit passed / from 50% with a projected crossing |
| V1 4031 | design solar particle event < 250 mSv | a vehicle and shielding design reference, compared with an event's estimated dose; not a personal limit | named in the storm evidence (shelter) |
| V1 6001 | an 8.5 h sleep period, no critical tasks 1 to 7 AM own clock | named in the sleep range's source | not a level |

What the standard sets and Canary cannot check is listed in `standards.NOT_CHECKED`: blood and immunity within the healthy population range (V1 4015 to 4017, read through the laboratory ranges instead), 100% of energy needs (V1 4020, no food log), and the organ dose limits (organ doses in mGy-Eq can't be compared with the effective dose in mSv the app has; the 30-day and 365-day totals are tracked and labelled "no limit applied by Canary"). `GET /api/catalog` returns all of it as `standards`.

## Risks

A risk is a function of the day, never a stored value. `GET /api/crew/{id}` carries `risks: [{id, name, nasa_red, systems, clock_days, level, score, trend, evidence, since_day, data, hazards, panel_due}]`; each evidence item is `{indicator | checkin, text, value, baseline, z, origin, source, points}`. There are eight risks. Four are NASA's red risks for a Mars mission ([Patel et al., npj Microgravity 2020](https://doi.org/10.1038/s41526-020-00124-6)) and carry `nasa_red: true`. The AI never scores a risk: rules decide, the assistant only explains (`get_risks`).

### Fatigue

| Evidence | Points |
| --- | --- |
| sleep, reaction time, mood | 1.0 × the indicator's level (0, 1 or 2) |
| processing speed (`dsst`) | 0.75 × level |
| stress, time with crew, working memory, sleepiness (`kss`), workload (`tlx`) | 0.5 × level |
| wellbeing check-in (PHQ-2 or GAD-2 of 3 or more in 14 days) | 1.0 |
| no mood check-in for 3 days | 0.5 |
| drifting towards the limit (level 0 but sliding) | 0.5 each, 1.0 at most |

Level 1 from 2.0 points. Level 2 from 4.0 points **and** at least 3 distinct signals (drift does not count) **and** level 1 or more two days earlier, so one bad night never reaches level 2. The trend compares the score with 3 days ago (±0.5). `since_day` is found by walking back day by day (at most 60 days), never stored. While fatigue is at level 1 or 2 the day's exercise goal is lighter and says why, by the percentage the medical team sets (`PUT /api/medical/exercise-adjust`, default 15% and 30%, never above `max_pct`).

### The other seven

`data` says where the evidence comes from: `real` (measured, typed in the app or sent by a device or lab), `partial` (a mix) or `simulated`. **In the demo package every stored reading is simulated**, so evidence is `simulated` unless it comes from a check-in made in the app.

| Risk | NASA red | Body systems | Evidence | Level 1 / level 2 | Clock |
| --- | :---: | --- | --- | --- | --- |
| `radiation` | yes | skin | **career** dose against 600 mSv and the day the plan is projected to pass it; a storm in progress; a **low** lymphocyte count | from 50% of the limit **with** a projected crossing, or a low count / a storm; level 2 when the limit is passed | 1 day |
| `sans` | yes | eyes | Amsler grid with distortion (2 points), vision symptoms (1 point) in the last 7 days. A clear grid does not rule SANS out | 1 / 2 points | 7 days |
| `nutrition` | yes | gut | weight below the pre-flight mean (5% = 1 point, 10% = 2), fasting glucose against the person's normal | 1 / 3 points and 2 signals | 7 days |
| `renal` | no | kidneys | water, the bone model's loss rate (1% or more in 30 days), creatinine and calcium against the laboratory range, 24 h urine volume | 1 / 3 points and 2 signals | 15 days |
| `immune` | no | immune | temperature, blood count out of range (0.5 each, 1.5 at most), C-reactive protein 50% or more above the pre-flight mean, the 14 days after a storm | 1 / 3 points and 2 signals | 30 days |
| `cardio` | no | heart, lungs | pulse, pressure, oxygen, aerobic capacity (NASA's EVA minimum as a floor), potassium; the re-adaptation pattern back in gravity | 1 / 4 points and 3 signals | 1 day |
| `bone_muscle` | no | skeleton, muscles | bone (DXA before launch, model estimate in flight), grip, exercise; NASA's strength limit as a floor | 1 / 4 points and 3 signals | 30 days |

A risk colours only the body system its evidence is about (grip colours the muscles, not the bones). Exams have their own frequency (`risk.PANELS`: blood every 30 days, urine every 15). An exam older than that is shown as `stale` evidence and the risk says `panel_due`; an old exam is never counted as a health signal.

## Hazards (RIDGE)

NASA's five hazards of spaceflight: **R**adiation, **I**solation and confinement, **D**istance from Earth, **G**ravity, hostile and closed **E**nvironment. `privacy.ridge(location, storm, day)` computes each level from the plan instead of reading a table (cuts in `assumptions.py`, all prototype assumptions):

- **R** from the place's dose rate (moderate from 0.1 mSv/day, high from 1.0; a storm away from Earth is high);
- **I** from the days since launch (moderate up to day 90, high after) and the crew size;
- **D** from the Earth delay and the days to a hospital;
- **G** from the gravity (0 g high, partial moderate) and the 30 days after a change of gravity;
- **E** set per place.

Each hazard says `basis` (why this level). Every risk and alert carries `hazards` and a `hazard_note` ("Possible factors here: Isolation & confinement, Distance from Earth. Not a cause."). A hazard is listed when the team's hazard–indicator matrix (`catalog.HAZARDS_BY_INDICATOR`) links it to the evidence and it is moderate or high at the current place and day. Of the 72 links, 21 were checked against Patel 2020 on 2026-11-15 and are `verified`. The others say in `checked` what the article does not support, or stay unverified until read against the HRP evidence reports. Five indicators the matrix does not cover (`dsst`, `span`, `kss`, `tlx` and `urine_volume`) borrow the hazard of their body system and are marked as a prototype assumption.

## The advice loop

Every alert goal and every suggestion says what it is meant to move: `verify: {indicator, after_days}` (for example, the sleep suggestion verifies `sleep` after 7 days). When the person ticks an alert goal for the first time, or accepts a suggestion, Canary opens a small experiment in the `advice` table: trigger, action, `start_day`, `check_day = start_day + after_days`, and `start_bad`, how far the indicator was from the person's normal (in personal spreads, higher is worse). Rows are written only by routes that change something, never by a GET.

Before `check_day` the outcome is `pending`. From `check_day` it compares the deviation then with `start_bad`: `improved` (0.5 spreads better or more), `worse` (0.5 or more) or `same`. Two **rounds** in a row without improvement for the same risk escalate: the suggestions list gets one different step (`advice.ALTERNATIVES`), and **one** message of kind `advice` goes to the crew medical officer (or the commander when the patient is the medical officer). It never repeats.

Example, Helena (demo package):

1. **Day 147.** Fatigue is at level 2. She accepts *Protect your sleep window*. Canary stores `start_bad` 2.81 and `check_day` 154. On day 149, `GET /api/advice/h` says `pending`.
2. **Day 154.** Her sleep is 4.11 spreads from normal against 2.81 at the start: `worse`. The goal row reads "Checked on day 154: worse".
3. **Round two.** She tries another step on day 154. In the simulation Helena starts to recover around day 160, so this round ends well. If it didn't (the tests build that case on purpose), the second round without improvement would escalate as above.

## After an emergency

Guided Response opens an emergency record the moment it starts, and every step is logged with its time.

- **Close with an outcome** ("stable" or "needs evacuation review") when the protocol ends. This adds the protocol's follow-up goals for the patient, opens a care window and queues a report for Earth with the place's delay.
- **Cancel** (closing before the end, or **Cancel** on the red alarm bar) ends the record with outcome `cancelled`. The log is kept, but there are no goals, no care window and no report.

Each protocol in [`protocols.json`](../backend/canary/data/protocols.json) carries `window_days` (the care window, rounded up to whole days from its `after` text), `ops` (`full`, `limited` or `rest`) and `after_days` (days of each follow-up item). During the window:

- the patient's operational status is at least the protocol's `ops`, with `reason` and `until_day`;
- the patient's thresholds are multiplied by the care sensitivity (default 0.8: 1.5σ becomes 1.2σ), and `sensitive_until` appears on those indicators. The medical team sets it with `PUT /api/medical/care-sensitivity` (0.5 to 1.0);
- **a window does not end by itself.** After its last day it stays "awaiting review", keeping its restrictions, until the medical team records a review (`POST /api/medical/care-windows/{id}/review`). The first review stands.

Everything is a function of the day asked about: moving the clock back before the emergency shows no event.

## Critical alerts: who is told, and escalation

- **A personal level-2 alert** writes one `alert` message to the crew medical officer, once per alert event (to the commander if the medical officer is the patient), and one delayed `alert_earth` note for the flight surgeon.
- **A storm or other environment alert** goes to the medical officer at once and to Earth (every flight surgeon and Mission Control account).
- **Escalation.** A level 2 nobody acknowledges goes up one step after `CANARY_ESCALATE_MINUTES` (default 10, run faster in the demo like the communication delay): first to the commander, then to the flight surgeon. Any acknowledgement (`POST /api/alerts/events/{id}/ack`, by the medical officer or a flight surgeon) stops the climb and is recorded in the audit trail.

Alert messages are visible only to their recipient and the medical console; the crew sees nothing. `GET /api/alerts/events` lists the stored events with who was told and who acknowledged.

## Where a value comes from and how old it is

`telemetry.observation()` is the only reader behind every chart, alert and assistant answer:

1. **A check-in made in the app that day wins**: `origin: "user"`. Fields read: mood (mood, stress), reaction test (ms), sleep diary (hours), vitals (pulse, pressure, temperature, oxygen), processing speed, digit span, sleepiness, workload. Other tests are stored but are not indicators: the Amsler grid, symptoms and wellbeing feed their own rules; reading and the journal only complete goals.
2. **Otherwise the last stored reading up to that day.** A device, manual or lab reading counts as `real`; a simulator row as `simulated`. Rows marked `sample` are examples for a demo and never feed a baseline or an alert. A reading older than the indicator's `max_age` is stale.

Each indicator in `GET /api/crew/{id}` says `origin`, `last_measured_day` and `age_days`, and every chart is tagged with where its numbers come from.

## How to measure and why

Each indicator can explain itself: how to measure it in flight, what spaceflight does to it, what to do at each colour and how often to check. The texts come from the team's indicator guide in [`data/indicator_guide/`](../data/indicator_guide/) (written in Portuguese for the team's research; `texts_en.json` is its English translation). The app shows them folded as **How to measure and why** on each chart, in the body-system panel of My space, and as **How and why** on each test. Every text carries the source the guide lists for it; where the guide gives none, the line reads **No source checked yet**. The guide's own numbers are not used: every limit comes from `reference.py` and `standards.py`.
