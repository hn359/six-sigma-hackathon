# Bikeshare Dock QC (sample build)

A tool for a bikeshare **rebalancing dispatcher**: which stations are empty or full at rush hour
more often than chance explains (send a van there first), and how long they stay unusable.

## Run it

```bash
./app/testme.sh          # installs, runs the tests, then serves http://localhost:8000
```

Open http://localhost:8000 and click a test dataset, or upload your own CSV.
Interactive API docs are at http://localhost:8000/docs.

## Input

One CSV: `station_id, timestamp, bikes_available, docks_available` (see `data/README.md`).
Only weekday readings 07:00–09:59 and 16:00–18:59 count.

## The statistics (`app/qc.py`)

A reading is **unusable** if `bikes_available` = 0 (empty) or `docks_available` = 0 (full).

- **p-chart**, one point per station: p_i = d_i / n_i, p̄ = Σd / Σn,
  limits p̄ ± 3·√(p̄(1 − p̄)/n_i), lower limit floored at 0. Above the upper limit: "send a van".
- **Availability**: an outage is a run of back-to-back unusable readings in one rush window.
  MTTR = downtime / outages, MTBF = uptime / outages, A = uptime / (uptime + downtime).

Checked against hand-worked answers in `tests/test_qc.py`: counts 2, 3, 2, 3, 10 of 20 give
p̄ = 0.20, UCL = 0.46833, only station 5 flagged; `UUXXUUUXUUUU` at 15 min gives MTTR 22.5,
MTBF 67.5, A = 0.75.

**Assumptions.** Each reading is treated as an independent yes/no. Readings 15 minutes apart are
correlated, so the limits are somewhat too tight: a station just over its limit deserves a look,
not certainty. The tool warns when n·p̄ < 5. A station with no outages shows A = 1.00 and no
MTTR/MTBF (never infinity).

## Endpoints

| Route | Does |
|---|---|
| `GET /` | the dispatcher's page |
| `GET /health` | `{"status": "ok"}` |
| `POST /analyze` | body = raw CSV text; returns the p-chart, ranked "send first" list and availability |
| `GET /samples/{name}` | the same, on a bundled test dataset |

```bash
curl -X POST --data-binary @data/hot_station.csv http://localhost:8000/analyze
```

## Four-script contract

`testme.sh` (run locally), `manifestme.sh` (write `manifest.json`), `deployme.sh` (publish to
Posit Connect), this README. Before deploying, copy `data/*.csv` into `app/data/` so the sample
buttons work in the bundle.
