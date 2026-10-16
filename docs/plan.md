# Plan: Battery Ninjas bikeshare tool

**User:** the rebalancing dispatcher. **Question:** which stations do the vans visit first before the
next rush hour, and which need a repair crew instead? **Statistics:** a p-chart and availability.

## Formulas (from SPEC.md section 4)
- A reading is **unusable** if `bikes_available` = 0 or `docks_available` = 0. Only weekday rush
  windows count: 07:00-09:59 and 16:00-18:59 (12 readings each at 15 min, so 120 per station per week).
- **p-chart** (one point per station): p_i = d_i / n_i; p-bar = sum(d) / sum(n);
  UCL_i = p-bar + 3·sqrt(p-bar(1 − p-bar)/n_i); LCL_i = max(0, p-bar − 3·sqrt(p-bar(1 − p-bar)/n_i)).
  Above UCL means "send a van". Warn if n_i·p-bar < 5 or n_i·(1 − p-bar) < 5.
- **Availability** (per station): an episode is a run of back-to-back unusable readings; runs break at
  each rush-window edge. Reading length t = median gap between readings.
  downtime = unusable readings × t; uptime = usable readings × t;
  MTTR = downtime / episodes; MTBF = uptime / episodes; A = uptime / (uptime + downtime).

## Tasks
1. **H-01 SPEC** (`SPEC.md`, 5 min). Done when `grep -c "FILL IN[.,]" SPEC.md` prints 0 and every
   teammate can say the method sentence. The repo line is filled; check in after a yes.
2. **H-03 statistics** (`app/qc.py`, `app/requirements.txt`, `tests/`, 60 min). Built before the data and the app.
   - `p_chart(d, n)` returns p-bar, p_i, UCL_i, LCL_i, flag_i and warnings.
     Known answer: d = 2, 3, 2, 3, 10, n = 20 each, gives p-bar 0.20, UCL 0.46833, LCL 0, only station 5 flagged.
     Degenerate: all d = 0 gives p-bar 0, limits 0, nothing flagged, plus a message (no NaN);
     fewer than 2 stations, or any n_i = 0, raises a clear error.
   - `availability(states, t)` returns A, MTTR, MTBF and episodes.
     Known answer: `UUXXUUUXUUUU`, t = 15 gives downtime 45, uptime 135, episodes 2, MTTR 22.5, MTBF 67.5, A 0.75.
     Degenerate: all U gives A 1.0, MTTR and MTBF None, plus "no outages"; all X gives A 0.0, MTBF 0.0;
     an empty list raises an error. A run cut by a window edge counts as 2 episodes.
   - `analyze(df)` turns snapshot rows into both results (rush filter, median gap, n·p-bar warning).
3. **H-02 data** (`data/`, 40 min). The three CSVs: 10 stations, 5 weekdays, 15-min readings, made
   with a seeded script so they can be rebuilt. `normal_week.csv` flags nothing; `hot_station.csv`
   has one station chronically empty; `edge_case.csv` has missing readings and a station with zero
   outages. `data/README.md` is the codebook. Test: `analyze()` on each file gives the expected flags.
4. **H-04 tool** (`app/`, 60 min). Copy `demos/fastapi/` to `app/`. `POST /analyze` takes a CSV;
   `GET /health` answers. `testme` starts it. Test: `curl` on `data/hot_station.csv` returns the same
   numbers as `analyze()` in pytest.
5. **H-08, first half** (`.gitignore`). Make github.com/hn359/six-sigma-hackathon public as soon as H-04 runs.
6. **H-06 deploy** (`.github/workflows/`, `app/manifest.json`, 30 min). A GitHub Actions deploy to
   Posit Connect. Test: the public URL answers 200 logged out, with the H-03 numbers.
7. **H-05 page and demo** (`app/frontend/`, `demo/`, 60 min). The React page: upload, the p-chart with
   red flagged stations, the ranked "send a van first" list, and the availability/MTTR/MTBF table.
   Test: the demo walkthrough on each CSV, checked with a Playwright screenshot. Styling only after this passes.
8. **H-07 README** (`README.md`, `app/README.md`, 30 min). A teammate follows it from a fresh clone.
9. **H-08, rest.** Fresh-clone check, `git grep -i api_key` finds nothing real, submit on Devpost.

## Decisions (2026-10-16)
- SPEC: Yash's version as-is (one network p-chart plus availability); team name Battery Ninjas.
- Repo: github.com/hn359/six-sigma-hackathon.
- Outage episodes break at each rush-window edge (we never see the hours in between).
- A zero-outage station is shown as A = 1.00 and "no outages", with MTTR and MTBF None, never inf.
- Test CSVs: 10 stations, 5 weekdays, 15-min readings.
- No donor/receiver list for now; maybe H-09 later, and only with the team's yes.

## Risks
1. **Limits too tight:** readings 15 min apart are correlated, so the p-chart can flag a station that is
   not truly worse. We say so in the README and on the page, and show each station's p next to its UCL.
2. **Deploy fails late:** deploy as soon as H-04 runs (step 6), not at the end.
3. **The page eats the time:** the statistics (H-03) are reviewed and passing before any page work.
