# Why the golden numbers changed (NASA engine phase)

The golden files were regenerated on purpose with `CANARY_GOLDEN_UPDATE=1 pytest tests/test_golden.py`.

- z-scores use the day's own reading, not the 3-day weighted mean; a day without a reading shows the last reading with its age.
- Alert levels need two consecutive readings (a single reading beyond the act threshold is a level 1) and keep a level until the distance falls 0.5 sd below its entry threshold; a critical population bound or a NASA limit still alerts at once.
- Every indicator now carries `n` and `confidence` (low under 10 readings, moderate 10 to 19, high 20 or more).
- Pulse and pressure: no level-1 alert in flight days 1 to 14, and from day 15 they are read against an in-flight re-baseline (days 8 to 14); the pre-flight baseline is still reported.
- Blood pressure is split into `sbp` and `dbp`; `bp` stays in the output only as an alias of `sbp`.
- Bone density is a DXA scan before launch and after landing (g/cm2): no daily in-flight reading, no `ind_bone` alert; the in-flight value is an estimate labelled `estimated`.
- Percent-of-baseline NASA limits (grip 80%, bone 95%) read the pre-flight baseline only; without one they are `not_assessable`.
- An instrument reading takes precedence over a self-report on the same day.
- Demo blood values and storm events are `origin: simulated` (source "modelled on Inspiration4 (NASA OSDR OSD-569/575)" or "simulated"); the Mars storm event carries a simulated 2 mSv.
- Storm alerts are built from the event and the dosimeter, are level 2 only when the measured rate passes 3x the place's quiet rate, and carry `escalate` and `recipients`.
- Dose: `dose_eq_rate` (mSv/day) and `dose_rate` (mGy/day) from the cabin dosimeter; 30-day and 365-day totals; career origin; the design reference for a solar particle event.
- The Mars plan has a return leg (return cruise days 721 to 930, Earth from 931); the dose projection and `plan/conditions` change with it.
- Mission state gains `met`, `gmt`, `sol`, `mars_time`, `one_way_light_s` and `blackout`; the delay of the place is computed from the Earth-Mars geometry; the sol uses the real 88,775.244 s length.
- Merged with the accounts/alerts phase: messages now include storm notices.
