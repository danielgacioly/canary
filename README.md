# Canary

**A health watch-keeper for astronauts, for when Earth is too far to answer.**

Built for the NASA Space Apps Challenge 2026, challenge *Create Health Monitoring Software for Astronauts on Space Missions*.

For more than a century, miners carried canaries underground. The bird feels bad air before people do, and when it went quiet the miners knew to leave. A spacecraft is a sealed mine: no windows to open, no hospital next door. On the way to Mars a question to the flight surgeon takes up to 24 minutes to arrive and as long to come back. Canary stays on board for that gap.

## What it does

- **Goals.** Daily, crew-level goals for body, mind and spirit, and emotion and bonds. Goals are shared by the crew, never ranked per person, so nobody has a reason to hide a symptom.
- **Warnings.** Each person is compared with their own pre-flight normal, not a population average. Signals are crossed (for example sleep, mood and reaction time together), and every warning says what it means, what to do now and when to call the doctor.
- **Guided response.** Hold the emergency button for one second to get step-by-step help for ten situations (CPR, seizure, choking, chest pain, allergy, bleeding, eye injury, psychological crisis, radiation exposure, "I don't know"), with a timer, breathing pacer and spoken instructions.
- **Where you are.** Earth, rocket, ISS, Moon, transit to Mars and Mars each change gravity, radiation, communication delay, the goals and the emergency steps.
- **Medical team mode.** No accounts for astronauts. Flight surgeons open a separate mode (PIN `1961` in this prototype) to prescribe goals, tune alert rules, read protocols and send messages.

## Run it

It is a static page with no build step to view it.

```bash
cd prototype
python3 -m http.server 8765
```

Then open <http://localhost:8765>. Serve it over HTTP rather than opening the file directly, because the 3D astronaut model is loaded with `fetch`.

To change the app, edit `prototype/src/app.html` and rebuild:

```bash
python3 prototype/build.py
```

## NASA data used

| Source | Used for |
| --- | --- |
| [DONKI](https://api.nasa.gov/) space weather, 5 to 16 May 2024 | Storm alert in demo step 4 |
| Curiosity RAD level 2 ([SPDF](https://spdf.gsfc.nasa.gov/pub/data/aaa_planetary/msl/rad/cdf/obs-l2/)), 9 and 20 May 2024 | Mars radiation chart in demo step 6 |
| [OSDR OSD-569](https://osdr.nasa.gov/bio/repo/data/studies/OSD-569) Inspiration4 blood counts | Lymphocyte chart in Health |
| [NASA 3D Resources](https://github.com/nasa/NASA-3D-Resources) astronaut model | Status ring on the Today screen |

`prototype/src/nasa_data.js` holds the extracted values that the page embeds. `data/prepare_nasa_data.py` regenerates them from the original downloads (needs `numpy` and `cdflib`).

## Limits to know about

- Vital signs, crew names and messages are **simulated**, because astronaut vital signs are not published as open data.
- Emergency protocols are **illustrative** and have not been clinically reviewed. In a real mission they come from the flight surgeon.
- Communication delay runs 20 times faster than real time so the demo is watchable.
- Doses per location and other literature figures in the app still need a check against the NASA risk pages before being quoted.

## Layout

```
prototype/
  index.html          built page (single file, generated)
  Astronaut.glb       NASA astronaut model, Draco-decoded
  build.py            src/ -> index.html
  src/app.html        the whole app: styles, data, logic, views
  src/nasa_data.js    NASA values embedded into the page
data/
  prepare_nasa_data.py  rebuilds nasa_data.js from the raw NASA files
```
