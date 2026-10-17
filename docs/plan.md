# Plan: Battery Ninjas bikeshare tool (v4: chart-driven dispatch)

**User:** the dispatcher running one van and a reserve depot. **Questions:** where should each
station start tomorrow, does the van need to go anywhere in the next 15 minutes, and did the policy work?
**Statistics:** live I-MR with Western Electric rules on slot-adjusted net flow (core, drives the
van); nightly start plan and expected path; weekly p-chart (proof).

## Formulas (from SPEC.md section 4)
- Network: 5 stations × 20 docks; 50 bikes in docks (10 each on day 1), 50 in reserve.
  Day = 06:00-21:45, 64 readings. **Out of spec:** bikes < LSL 4 or bikes > USL 16.
- **Start plan** (nightly): C = cumulative slot-mean net flow over the day; s = round(midpoint of
  [4 − min C, 16 − max C]); expected path E(k) = s + C(k). Empty range → reported.
- **I-MR** (every 15 min) on x = (Δbikes − van_moved) − station's slot mean. Phase I (week 1):
  x-bar, MR-bar, sigma = MR-bar/1.128, limits ± 3 sigma, MR UCL 3.267·MR-bar.
  **Rules** (same side): 1 beyond 3σ; 2 of 3 beyond 2σ; 4 of 5 beyond 1σ; 8 in a row.
- **Van** (on a signal, or a reading outside 4-16 as a safety net): move = E(k) − bikes, ≤ 10 per stop, one stop per 15 min, largest
  |E − bikes| first; source/sink = a station on the other side of its path, else reserve.
- **Rush slots:** slot mean rentals ≥ 1.5 × mean of all slots.
- **p-chart** (weekly, per station, subgroup = day, n = 64): Phase I pbar over week 1, limits
  pbar ± 3·sqrt(pbar(1 − pbar)/n), LCL ≥ 0; week 2 below LCL = "improved", above UCL = "worse".

## Tasks
1. **H-03 statistics** (`app/qc.py`, `app/requirements.txt`, `tests/`, 90 min). One function each,
   with a known-answer and a degenerate test (numbers in SPEC.md section 4):
   - `imr_limits(x)`: 2,4,3,5,6 → x-bar 4, sigma 1.3298, UCL 7.99, LCL 0.01, MR UCL 4.9005.
     Degenerate: constant x → sigma 0 + message, no signals; one value → error.
   - `run_rules(x, xbar, sigma)`: the four rule cases and the no-signal case in SPEC.md.
     Degenerate: sigma 0 → error, not a division by zero.
   - `van_move(expected, bikes, capacity)`: (8, 3) bring 5; (12, 17) take 5; (9, 22) error.
   - `start_plan(C, lsl, usl)`: 0,−3,−6,−8,−5 → 14, path 14,11,8,6,9; 0,−7,−13 → no start.
   - `rush_slots(means)`: 2,2,6,6,2,2 → slots 3, 4. Degenerate: all equal → none.
   - `p_chart_phase(d_week1, d_week2, n)` (reuse `p_chart` from branch `sample_idea1`):
     16,20,12,24,18,14,8 → pbar 0.25, UCL 0.41238, LCL 0.08762; d = 3 improved, d = 28 worse.
2. **H-02 data** (`data/`, 75 min). `data/simulate.py`, seeded, 15 minutes at a time: rentals per
   station per slot are Poisson with a time-of-day rate (residential S1, S2 drain in the morning;
   office S3 and hub S4 fill; S5 mixed; reverse in the evening), tuned so every station's normal
   swing is ≤ 12 bikes; riders go to other stations by fixed weights; rentals at an empty station
   and returns to a full one are lost. Week 2 uses `start_plan` nightly and `run_rules` +
   `van_move` every slot (history = week 1). Writes `week1_baseline.csv`, `week2_policy.csv`,
   `event_day.csv` (S5 return surge 18:00-18:45; slow extra drain at S2 from 10:00) and a van log.
   Codebook in `data/README.md`. Tests: bikes conserved every slot; week 2 has fewer out-of-spec
   readings; event day: rule 1 signals at S5, rules 2-4 at S2; week 1 false-alarm count reported.
3. **H-04 tool** (`app/`, 60 min). FastAPI loads the `data/` CSVs at startup (no database):
   `GET /health`, `GET /state/{scenario}?day=d&slot=k` (all stations, signals, van order),
   `GET /charts/{station}?scenario&day`, `GET /plan`, `GET /pchart/{station}`, `POST /analyze`
   (upload a readings CSV). `testme` runs pytest then the server. Test: curl on one slot of
   `event_day` gives the same signals and van move as pytest.
4. **H-08, first half.** Make the repo public as soon as H-04 runs.
5. **H-06 deploy** (`.github/workflows/`, `app/manifest.json`, 30 min). Public URL answers 200.
6. **H-05 page and demo** (`app/static/`, `demo/`, 90 min). Port the prototype console
   (claude.ai artifact "Dock Dispatch Console"): city map with the animated van, live feed, five
   station charts, night plan, weekly p-charts; 5 s per 15 min. It only fetches from the API.
7. **H-07 README** (30 min). **H-08 rest:** fresh-clone check, submit on Devpost.

## Decisions (2026-10-16, v4 replaces v3)
- Fleet 100 bikes: 50 in docks (10 per station at t0 on day 1), 50 in reserve. LSL 4, USL 16.
- The van moves **only** on a control-chart signal (I-MR + Western Electric rules 1-4). The
  predictable rush pattern is handled the night before by the start plan, not by the van.
- Simulated demand keeps each station's normal daily swing ≤ 12 bikes, so a start plan exists.
- Dispatch-risk score (v3) dropped. Weekly p-chart stays as the before/after proof.
- Safety net: a reading outside 4-16 also sends the van (prototype: used 3 times in week 2).
- Stack: FastAPI + plain HTML/JS in `app/static/` (no React, no Node). No database: CSV files.
- Prototype results (simulated): out-of-spec readings 499 → 8, lost rentals 7 → 0, ~13 van stops a day.
- Data: 2 simulated weeks, week 1 without rebalancing (Phase I), week 2 with the policy (Phase II).
- Same demand every day; no weekend effect.

## Risks
1. **Run rules add false alarms** (ARL about 92 vs 370 for rule 1 alone): report the week-1
   count; if it sends the van too often, drop rule 4 and say so.
2. **Scope:** six functions plus a simulation. If short on time, cut rush slots, then the event
   day's slow drain; the start plan, the chart-driven van and the p-chart stay.
3. **Rough sigma** (7 days per slot) and **correlated readings**: said in the README and on the page.
4. **Simulation bugs look like statistics:** test bike conservation every slot.
