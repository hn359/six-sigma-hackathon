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
- **User:** the rebalancing dispatcher at a municipal bikeshare, who sends the maintenance and rebalancing vans.
- **Decision the tool helps them make, and when:** which stations the vans visit first before the next rush hour (morning and evening), and which stations are so often unusable that they need a repair crew, not a rebalance.
- **Why this matches the prompt:** it tracks when and where stations are empty or full, flags the ones statistically worse than the network, and reports each station's availability, so vans are sent by evidence instead of blindly.

## 3. Inputs (rubric: minimal inputs 5)
Only what this user can actually measure or already knows. Fewer is better; every input a user
cannot measure costs points.

| Input | Type and units | Where the user gets it |
|---|---|---|
| `snapshots.csv`, one row per station per reading: `station_id`, `timestamp`, `bikes_available`, `docks_available` | text, ISO datetime, count, count | the system's live station feed (GBFS `station_status`) polled every 15 minutes |
| Parameter: rush-hour windows (default 07:00-09:59 and 16:00-18:59, weekdays) | hours | the dispatcher's own schedule |

## 4. The statistics, and why (rubric: valid QC analysis 25)
Say the method in words before any code exists. Load the `stats-first-steering` skill first.
- **Method:** a reading is "unusable" when `bikes_available` = 0 (empty, nothing to rent) or `docks_available` = 0 (full, nowhere to return). A **p-chart with variable subgroup size**: each station is one subgroup, n_i = its rush-hour readings, d_i = its unusable readings, p_i = d_i / n_i, centre line pbar = sum(d) / sum(n), limits pbar ± 3·sqrt(pbar(1 − pbar)/n_i), LCL floored at 0. A station above its UCL is flagged "send a van". Second statistic, **availability** from reliability: an outage episode is a run of consecutive unusable readings; MTTR = downtime / episodes, MTBF = uptime / episodes, availability A = MTBF / (MTBF + MTTR) = uptime / (uptime + downtime).
- **Why it fits the use case:** the p-chart separates stations that are truly worse than the network from ordinary rush-hour noise, and availability with MTTR says how long a station stays unusable once it fails.
- **Assumptions and how the tool checks them:** (1) each reading is a yes/no with the same chance within a station (binomial); readings 15 minutes apart are correlated, so limits are somewhat too tight, and the README says so; (2) large enough subgroups: the tool warns when n_i·pbar < 5 or n_i·(1 − pbar) < 5; (3) readings are evenly spaced, so the tool reports the median gap between readings and uses it as the reading length for uptime and downtime.
- **Known-answer check** (worked by hand):
  - p-chart: 5 stations, n = 20 rush-hour readings each, unusable counts d = 2, 3, 2, 3, 10. Sum d = 20, sum n = 100, so pbar = 20/100 = 0.20. sigma = sqrt(0.20 × 0.80 / 20) = sqrt(0.008) = 0.08944. 3 sigma = 0.26833, so UCL = 0.20 + 0.26833 = 0.46833 and LCL = max(0, 0.20 − 0.26833) = 0. The p_i are 0.10, 0.15, 0.10, 0.15, 0.50. Only station 5 (0.50 > 0.46833) is flagged.
  - Availability: one station, 12 readings 15 minutes apart, U = usable, X = unusable: `U U X X U U U X U U U U`. Downtime = 3 readings × 15 = 45 min, uptime = 9 × 15 = 135 min, episodes = 2. MTTR = 45/2 = 22.5 min, MTBF = 135/2 = 67.5 min, A = 67.5/(67.5 + 22.5) = 0.75 (= 9/12).

Fixed for every team:
- The statistic lives in **one plain, tested function** (`app/qc.py` or `app/qc.R`). The API, app or
  package only calls it and displays the result. No statistics inside UI code.
- Every statistic has a test against a known answer and a degenerate case (constant data, n = 1, missing values).
- You can explain every number the tool prints. If you cannot, it is not done.

## 5. Delivery (rubric: working tool 25)
- **Stack:** dashboard: Python FastAPI back end with a React front end.
- **Starting demo:** `demos/fastapi/` copied into `app/`, with the React front end from `demos/reactfront/` in `app/frontend/`.

Fixed for every team:
- Start from **one** demo in `demos/`, copied to `app/`. Keep its four-script contract
  (`testme`, `manifestme`, `deployme`, `README.md`); `testme` starts the tool with one command.
- Deployed on the course **Posit Connect** server with a public URL (publisher key handed out at the
  event). Deploy early: copy one workflow from
  [`.claude/skills/connect-publish/workflows/`](.claude/skills/connect-publish/workflows/).
- A small tool that runs beats a large tool that does not.

## 6. Outputs
- **What the user sees:** a p-chart of the share of rush-hour readings unusable per station (proportion 0 to 1) with centre line and limits, flagged stations in red and a ranked "send a van to these first" list; a table of availability, MTTR and MTBF (minutes) per station. How to read it: a red station is unusable more often than chance explains; low availability with long MTTR means it needs repair, not just rebalancing.

## 7. Test datasets and codebook (rubric: demo 10, datasets 5, codebook 5)
2-3 small CSVs in `data/`, invented but shaped like real field data, each showing one behavior.
`data/README.md` is the codebook: every file, every column with units, and what it would take to
collect this data for real.
- **Datasets:** `normal_week.csv` (all stations in control), `hot_station.csv` (one station planted to be chronically empty at rush hour, so it is flagged), `edge_case.csv` (one station, missing readings, a station with zero outages).

## 8. Documentation and reproducibility (rubric: docs 10, public repo 5)
- `README.md` says what the tool does, for whom, every input and parameter, how to run it in one
  command, and walks through the demo on each test dataset.
- Public GitHub repo; a fresh clone runs `testme` and the tests pass with no extra steps.
- Submit on Devpost: the repo link plus a demo.

## 9. Out of scope
What we will NOT build, so nobody (human or agent) builds it by accident.
- Default: logins, databases, real customer data, a second statistic before the first one is tested.
- No forecasting of future demand; no routing or van-scheduling optimisation; no live feed connection (CSV upload only); no multi-city comparison.
