# SPEC: Six Sigma Hackathon team project

What your tool IS. Your agent reads this before every task. Where the code and this file
disagree, the code is the bug: change this file first, then the code.

Most of this page is already decided by the event and the [rubric](docs/criteria.md).
**Only the `FILL IN` lines change, and you do not have to write them by hand:** describe your app and ask your agent to update them. They depend on the prompt your team picks at kickoff
(prompts are secret until then, see [`docs/prompts.md`](docs/prompts.md)) and on your team.
The examples after each `FILL IN` show the shape of an answer. They are not hints about the prompts.

## 1. Team and prompt
- **Team name:** Battery Ninjas
- **Track:** on-campus (24 hours). See [`docs/schedule.md`](docs/schedule.md).
- **Prompt we chose:** 1. Urban Systems, "Bikeshare Fleets" (docks full / docks empty at rush hour; vans dispatched blindly), from the [Devpost](https://six-sigma-hackathon.devpost.com/) challenge page.
- **Our public repo:** github.com/hn359/six-sigma-hackathon

## 2. User and use case (rubric: scope 5, user and use case 5)
- **User:** the rebalancing dispatcher of a small municipal bikeshare, who runs the one rebalancing van and the reserve depot.
- **Decision the tool helps them make, and when:** every 15 minutes during the day, whether to send the van and where (move bikes between stations, or bring or take reserve bikes); every night, how many bikes each station should start with at 06:00 tomorrow; and each week, whether the rebalancing policy has really reduced empty/full time.
- **Why this matches the prompt:** it tracks when and where stations are empty or full, plans each station's start so its normal day stays in spec, sends the van only when a control chart shows a station straying from that normal day, and uses a p-chart to show whether the policy worked.

## 3. Inputs (rubric: minimal inputs 5)
Only what this user can actually measure or already knows. Fewer is better; every input a user
cannot measure costs points.

| Input | Type and units | Where the user gets it |
|---|---|---|
| `readings.csv`, one row per station per 15 minutes: `station_id`, `timestamp`, `bikes`, `capacity`, `van_moved` | text, ISO datetime, count, count, signed count (+ bikes the van dropped, − bikes it took) | the system's station feed (GBFS `station_status`) polled every 15 minutes, plus the van's own log |
| Parameters: LSL = 4 bikes and USL = 16 bikes (per 20-dock station), van limit 10 bikes per stop, one stop per 15 minutes | counts | fixed by the network; the dispatcher can change them |

## 4. The statistics, and why (rubric: valid QC analysis 25)
Say the method in words before any code exists. Load the `stats-first-steering` skill first.

**Setting.** 5 stations (S1-S5), 20 docks each, 100 docks. Fleet of 100 bikes: 50 in docks at
t0 (10 per station on day 1), 50 in the reserve depot. The day runs 06:00-22:00: 64 readings, one
every 15 minutes, starting Monday 06:00 (t0). A reading is **out of spec** when `bikes` < LSL = 4
(close to empty: a few riders can empty it) or `bikes` > USL = 16 (close to full: a few returns
can fill it). The limits leave a 4-bike buffer at each end of a 20-dock station.

- **Method** (the van moves only when the control chart signals):
  1. **Every night: tomorrow's start and expected path.** For each station, C(k) = cumulative
     historical mean rider net flow from 06:00 to slot k over the whole day, C = 0 at 06:00.
     Feasible starts keep LSL ≤ s + C(k) ≤ USL for every k, so s runs from LSL − min C to
     USL − max C; the start is the midpoint, rounded. The **expected path** is E(k) = s + C(k): the
     station's normal day, rush hours included, inside 4-16 by construction. (The simulated demand
     keeps every station's normal swing, max C − min C, at 12 bikes or less, so a start always
     exists; if it does not, the tool says so.) Rush slots: a slot whose historical mean network
     rentals are at least 1.5 × the mean over all slots, shown to the dispatcher.
  2. **Every 15 minutes: I-MR chart of slot-adjusted net flow, per station** (graded core). Net
     flow = change in bikes since the last reading minus `van_moved` (riders only). x = net flow
     minus the station's historical mean for that slot, so the normal rush-hour pattern is not a
     signal. Phase I (week 1) sets x-bar, MR-bar and sigma = MR-bar / d2 (d2 = 1.128, n = 2);
     limits x-bar ± 3 sigma (= ± 2.66·MR-bar), MR UCL = 3.267·MR-bar. Every new reading is checked
     against the **Western Electric rules**, all on the same side of x-bar:
     (1) 1 point beyond 3 sigma; (2) 2 of the last 3 beyond 2 sigma; (3) 4 of the last 5 beyond
     1 sigma; (4) 8 in a row. Rule 1 catches a sudden surge, rules 2-4 a sustained drift.
  3. **Dispatch = a signal, or out of spec.** A station gets the van when its chart signals, or,
     as a safety net, when its reading is outside 4-16 (a slow drift can cross a spec limit before
     any rule fires). The van brings the station back to its expected path: move = E(k) − bikes now (positive: bring bikes; negative:
     take bikes), at most 10 bikes per stop, one stop per 15 minutes. With several signals, the
     station furthest from its expected path goes first; the van log records which trigger fired. Bikes come from (or go to) a station on
     the other side of its expected path if one exists, otherwise the reserve. After a visit the
     run-rule history for that station restarts.
  4. **End of week: p-chart, one chart per station, one point per day** (did the policy work?).
     n = 64 readings a day, d = readings out of spec, p = d / n. Phase I: pbar = sum(d) / sum(n)
     over week 1 (no rebalancing, every station starts at 10), limits pbar ± 3·sqrt(pbar(1 −
     pbar)/n), LCL floored at 0. Phase II: week 2 (nightly start + chart-driven van) against
     week 1's limits. Below LCL = the policy really reduced out-of-spec time; above UCL = worse.
- **Why it fits the use case:** the predictable part of the day (the rush-hour drain and fill) is
  handled the night before by the start plan; what is left is variation the history did not
  expect, which is exactly what a control chart detects. So the van moves on statistical evidence,
  not blindly and not on noise. Charting net flow against its usual slot value (not raw bike
  counts, which drift on purpose every rush hour) keeps the chart valid; run rules catch a slow
  drift before it empties a station. The p-chart then tests whether out-of-spec time really fell.
- **Assumptions and how the tool checks them:** (1) I-MR: the slot-adjusted net flows are roughly
  independent, normal and similar in spread all day; the tool reports their lag-1 autocorrelation
  and a normal Q-Q plot in the demo. Run rules raise false alarms more often than rule 1 alone
  (roughly one per 90 in-control points instead of one per 370), so the demo reports the week-1
  false-alarm count. (2) p-chart: readings are binomial yes/no with the same chance within a day;
  readings 15 minutes apart are correlated, so the limits are a little too tight; the tool warns
  when n·pbar < 5 or n·(1 − pbar) < 5. (3) Every day has the same demand pattern. Western
  Electric rules are not in the course textbook; source: Montgomery, *Introduction to Statistical
  Quality Control*, section 5.3.
- **Known-answer check** (worked by hand):
  - I-MR limits: x = 2, 4, 3, 5, 6. x-bar = 20/5 = 4. MR = 2, 1, 2, 1, MR-bar = 1.5, sigma =
    1.5/1.128 = 1.3298. UCL = 4 + 2.66 × 1.5 = 7.99, LCL = 4 − 3.99 = 0.01, MR UCL = 3.267 × 1.5
    = 4.9005. Nothing flagged.
  - Run rules, with x-bar = 0 and sigma = 1: rule 1: −0.5, −3.5 signals at the 2nd point; rule 2:
    −2.5, 0.5, −2.2 at the 3rd; rule 3: −1.5, −1.2, 0.3, −1.1, −1.4 at the 5th; rule 4: eight
    times −0.5 at the 8th. No signal: 0.5, −0.5, 0.8, −0.2, 1.5, −1.2.
  - Van move: expected path 8, bikes 3: bring 5. Expected 12, bikes 17: take 5. Expected 9,
    bikes 22 (impossible: above capacity): error. Two signals, 5 and 3 bikes off: the 5 goes first. Bikes 3 with
    no signal: out of spec, so the van still goes (bring 5 to a path of 8).
  - Start plan: C = 0, −3, −6, −8, −5. min C = −8, max C = 0. s from 4 + 8 = 12 to 16 − 0 = 16,
    midpoint 14; expected path 14, 11, 8, 6, 9. C = 0, −7, −13 (swing 13 > 12): no feasible start.
  - Rush hours: slot means 2, 2, 6, 6, 2, 2. Mean = 20/6 = 3.333, cut-off 5.0. Slots 3 and 4.
  - p-chart: week 1 for one station, n = 64 a day, d = 16, 20, 12, 24, 18, 14, 8. Sum d = 112,
    sum n = 448, pbar = 0.25. sigma = sqrt(0.25 × 0.75 / 64) = 0.054127, 3 sigma = 0.16238,
    UCL = 0.41238, LCL = 0.08762. All 7 days in control. A week 2 day with d = 3 (p = 0.046875)
    is below LCL: "improved". A day with d = 28 (p = 0.4375) is above UCL: "worse".

Fixed for every team:
- The statistic lives in **one plain, tested function** (`app/qc.py` or `app/qc.R`). The API, app or
  package only calls it and displays the result. No statistics inside UI code.
- Every statistic has a test against a known answer and a degenerate case (constant data, n = 1, missing values).
- You can explain every number the tool prints. If you cannot, it is not done.

## 5. Delivery (rubric: working tool 25)
- **Stack:** dashboard: a Python FastAPI back end (statistics in `app/qc.py`, the simulation in `data/simulate.py`) that serves a plain HTML/JS front end from `app/static/`. No React, no Node.js build. No database: readings, van logs and limits live in CSV files in `data/`, which the back end loads at startup.
- **Starting demo:** `demos/fastapi/` copied into `app/`; the front end is `app/static/index.html`, which only calls the API and draws what it returns.

Fixed for every team:
- Start from **one** demo in `demos/`, copied to `app/`. Keep its four-script contract
  (`testme`, `manifestme`, `deployme`, `README.md`); `testme` starts the tool with one command.
- Deployed on the course **Posit Connect** server with a public URL (publisher key handed out at the
  event). Deploy early: copy one workflow from
  [`.claude/skills/connect-publish/workflows/`](.claude/skills/connect-publish/workflows/).
- A small tool that runs beats a large tool that does not.

## 6. Outputs
- **What the user sees:** a live console that replays a day, one 15-minute reading every 5
  seconds (adjustable), with every number fetched from the API: (1) a city map of the 5 stations
  and the reserve depot, each station's bikes as a ring coloured by status (in control, signal,
  out of spec, just fixed), and the van driving along the streets to redistribute bikes; (2) a
  live feed of every reading, signal, van order and "back in control"; (3) for all five stations,
  a bikes chart (spec band, expected path, van moves) and the I-chart of slot-adjusted net flow
  with 1, 2 and 3 sigma zones, signals in red; (4) the night plan: tomorrow's 06:00 start, the expected path and the rush slots;
  (5) end of week: per-station p-charts of the daily share of readings out of spec, week 1 band
  with week 2 points, improved days in green. How to read it: a red station is straying from its
  normal day for a reason the history does not explain, so the van goes there; green p-chart
  points below the band mean the policy worked.

## 7. Test datasets and codebook (rubric: demo 10, datasets 5, codebook 5)
2-3 small CSVs in `data/`, invented but shaped like real field data, each showing one behavior.
`data/README.md` is the codebook: every file, every column with units, and what it would take to
collect this data for real.
- **Datasets** (made by a seeded simulation, `data/simulate.py`): `week1_baseline.csv` (7 days,
  no rebalancing, everyone starts at 10 bikes), `week2_policy.csv` (7 days, nightly start plan
  and chart-driven van; the p-charts should show fewer out-of-spec readings), `event_day.csv` (one
  day with the policy plus a planted surge of returns at S5 at 18:00-18:45, which the I-MR chart
  must flag with rule 1, and a slow extra drain at S2 from 10:00, which rules 2-4 must catch).

## 8. Documentation and reproducibility (rubric: docs 10, public repo 5)
- `README.md` says what the tool does, for whom, every input and parameter, how to run it in one
  command, and walks through the demo on each test dataset.
- Public GitHub repo; a fresh clone runs `testme` and the tests pass with no extra steps.
- Submit on Devpost: the repo link plus a demo.

## 9. Out of scope
What we will NOT build, so nobody (human or agent) builds it by accident.
- Default: logins, databases, real customer data, a second statistic before the first one is tested.
- No van routing or travel-time model (one van, one stop per 15 minutes); no weekend, weather or
  seasonal demand; no live feed connection (CSV upload only); no broken-dock repair model; no
  more than 5 stations.
