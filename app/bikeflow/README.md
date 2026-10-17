# BikeFlow QC: Analyze and Improve module

For the **rebalancing dispatcher**. It answers two questions: *is a station behaving unusually
(statistically), and which bikes should move, from where, to where?* It does not generate data and
does not draw the station map.

**Data: Yash's three simulated cities in `data/<city>/`** (branch `yash_work`; rebuilt exactly by
`python data/simulate.py`): **collegetown** (5 × 20 docks, every 15 min, 06:00-21:45), **downtown**
(6 stations of 12-31 docks, every 10 min, 06:00-21:50) and **waterfront** (4 stations of 15-30 docks,
every 15 min, 08:00-22:45). `cities.py` reads each city's `about.json`, so every city runs on its own
interval, hours and fleet; the spec range is 20-80% of each station's docks (as his `qc.spec_limits`).
Every API route takes `?dataset=<city>`; `GET /api/bikeflow/datasets` lists them.

**Phase I / Phase II.** Control limits come from week 1 (`week1_baseline.csv`, van-free) only; week 2
and the event day are charted against them, exactly as his console does: on all four stations
checked, his charted values and sigma equal ours (UCL differs in the 4th decimal: 2.66 MR-bar vs
3 MR-bar / 1.128). `GET /api/bikeflow/scorecard?dataset=` checks the chart against the problems his
simulation planted on the event day (`about.json`): every one is caught inside its window
(collegetown drain 11:15, crowd 18:15; downtown 11:20, 17:00; waterfront 09:00, 16:00), and it reports
the false-alarm rate on the ordinary week-2 days (eight tests: 5.8-8.7%; with the MR chart: 8.1-12.6%).

Run it (one command, from the repo root): `bash app/bikeflow/testme.sh` runs the tests, then serves
the dashboard on http://localhost:8000. The page replays the latest day at 5 s per 15-minute reading;
`?day=2026-10-19&at=18:30&station=S02` opens it at a given moment.

## Beside Yash's dispatch console

`python -m uvicorn app.bikeflow.combined:app --port 8000` (repo root) serves his console and API
(`app/app.py`, unchanged) at `/`, and **`/side-by-side`**: his console on top, the BikeFlow charts
below. The charts follow the day and time his console shows (the reading time next to its slider, or
`/latest` in his Live mode), so they move with his simulation. Build his console once first:
`cd app/frontend && npm ci && npm run build` (Node 20+).

## The data contract

One row per station per 15-minute reading (matched case-insensitively; common aliases accepted):

| Column | Required | Meaning |
|---|---|---|
| `station_id` | yes | text |
| `timestamp` | yes | ISO local time, `2026-10-05T08:15` |
| `bikes_available` | yes | bikes docked |
| `docks_available` | no | open docks; capacity = bikes + docks |
| `capacity` | no | docks at the station (default 20) |
| `arrivals`, `departures` | no | rider counts per 15 min; if both exist net flow uses them |
| `van_moved` | no | bikes the van dropped (+) or took (-) just after that reading; net flow then subtracts the *previous* reading's value, so it counts riders only |

Other column names: `parse_csv(text, column_map={"bikes_available": "num_bikes"})`. A row that
cannot be trusted (missing value, negative, more bikes than capacity, outside 06:00-22:00,
duplicate slot) is **skipped and listed**, never turned into a zero. A reading time with more
bikes docked than the fleet is reported too.

Settings (`config.py`, all overridable): 20 docks, 120-bike fleet, target 10 per station, target
range 5-15, 06:00-22:00, 15-minute slots, rush hours 07-10 and 16-19, 1-hour projection horizon,
2 days of history needed before a projection counts as reliable, 2-bike overnight buffer.

## What each part does

| Part | Function | Method |
|---|---|---|
| SPC chart | `qc.imr_slot_adjusted` | The course's I-MR chart (SYSEN 5300 lesson 5) on rider net flow minus the usual for that 15-min slot on comparable earlier days: CL = mean of the baseline values; sigma = MR-bar / 1.128; limits CL ± 3 sigma (± 2.66 MR-bar); MR chart UCL = 3.267 × MR-bar. Zones C, B, A at 1, 2, 3 sigma and the course's eight tests (beyond zone A; 2 of 3 beyond B; 4 of 5 beyond C; 8 on one side; 6 trending; 15 in zone C; 8 with none in zone C; 14 alternating), plus an MR point above its UCL. Runs never cross a missing reading or a day boundary. |
| Inventory chart | `analyze.inventory_view` | Bikes per station over time; empty/full marked; target range shaded; current occupancy and a projection **only when reliable**. |
| Flow chart | `analyze.flow_view` | Net flow = arrivals - departures, else the change in bikes minus the van move after the previous reading when `van_moved` exists (riders only), else the raw change in bikes (includes van moves; labelled). Summary by morning rush, evening rush, other hours, weekend. Rider routes are never inferred. |
| Plan now | `plan.plan_now` | Level = projected bikes in 1 hour (historical average) or current. Surplus/shortage = level - target. HIGH = empty/full now or projected, or recurring; MEDIUM = outside the target range or an SPC signal. |
| 10 PM plan | `plan.plan_overnight` | From each station's average rider net flow over the next morning (06:00-10:00) on earlier days: the station riders most depart from starts at 80% of its docks (bikes to take), the one they most arrive at at 20% (room to park), the others in proportion between, 50% with no history (`Settings.depart_share`, `arrive_share`). The van moves every station to its start at 10 PM; HIGH = 6+ bikes to move, MEDIUM = 3-5. |
| Matching | `plan.match_transfers` | Recipients in priority order take from shedding stations, then spare bikes (only down to target), then the depot. Each bike moves once; no station leaves 0..capacity; stations + depot conserved and never above the fleet. |

**Control limits are not targets.** Limits say what is usual for that time of day; the target range
is the operational goal. An empty or full reading is an operational state, and is a special cause
only if it is unusual for that slot. No distances, van capacity or labor limits are assumed (none
are given); a shortage with no donors says so instead of inventing bikes. Without a depot count the
daytime plan assumes 0 depot bikes, and the 10 PM plan assumes the undocked bikes are at the depot.

## API (`/api/bikeflow`)

`POST /dataset` (CSV body; optional `fleet`, `capacity`, `target`, `band_low`, `band_high`) ·
`GET /summary` · `/inventory` · `/flow` (`period`) · `/spc` (`station`, `start`, `end`, `measure`) ·
`/plan?at=2026-10-05T08:15&depot_bikes=` · `/plan/overnight?day=2026-10-05`. Set `BIKEFLOW_DATA` to
load a CSV at start-up. To add it to another FastAPI app: `app.include_router(router)`.

## Limits to know

Small integer counts are heavier-tailed than a normal curve, so expect more signals than 3 sigma
implies (0.3% of in-control points). Treat a single flag as a prompt to look, and sustained or
repeated flags as the real signal. With all eight tests, ordinary days in Yash's data (8-18 Oct) flag
9.4% of readings (MR 4.8%, test 1 3.2%, test 2 1.7%). On his event day the S03 slow drain is flagged
at 11:00 (test 3) and 11:15 (test 1), when his van went, and the S02 crowd from 18:15. The projection is a historical average, not a forecast model.
