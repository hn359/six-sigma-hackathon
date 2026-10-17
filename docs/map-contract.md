# Map contract: what the back end sends the station map

The station map (`app/frontend/src/map/`) draws whatever the back end sends it, and checks every
response against the rules below before it draws anything. If the back end's output follows this
page, the map works with it. The back end owns every statistic: the control chart, its centre
line, the run rules and the number of bikes to move. The map recomputes none of them.

A full worked example is in [`map-frame.example.json`](map-frame.example.json). It is **invented
sample data** (five made-up stations at real Ithaca places), not real readings.

## Endpoints

| Route | Takes | Returns | Used by |
|---|---|---|---|
| `POST /replay` | multipart form: `readings` (CSV of 15-min readings) and `stations` (CSV: `station_id, name, lat, lon, capacity`) | `{"frames": [Frame, ...]}`, one frame per 15-min reading time, oldest first | the replay slider (demo): one step = one reading |
| `GET /latest` | nothing | one `Frame`, for the newest reading the server holds | Live mode: asked once a minute; the map changes only when `as_of` moves to the next 15-min reading |

If you name the routes differently, only `app/frontend/src/api.js` changes.

## Frame

```json
{ "as_of": "2026-10-12T08:30", "stations": [ Station, ... ] }
```

`as_of` is an ISO date-time, the time of the readings in this frame.

## Station

| Field | Type | Meaning |
|---|---|---|
| `station_id` | text | unique within the frame |
| `name` | text | shown to the dispatcher |
| `lat`, `lon` | number | position on the map (from `stations.csv`) |
| `capacity` | whole number > 0 | number of docks |
| `bikes` | whole number, 0 to `capacity` | bikes docked now |
| `occupancy` | number, 0 to 1 | `bikes / capacity` |
| `gap` | number | how far the charted value is from its centre line (sorts the list) |
| `direction` | `"empty"`, `"full"` or `"ok"` | which way the station drifted |
| `severity` | 0, 1, 2 or 3 | 0 in control; 1 eight in a row on one side; 2 two of three beyond 2 sigma; 3 one point beyond 3 sigma |
| `rule` | text or `null` | the run rule that fired, in words |
| `target_occupancy` | number 0 to 1, or `null` | the chart's centre line as an occupancy, the level a move aims for |
| `bikes_to_move` | whole number or `null` | `+` add this many bikes, `-` remove this many; `null` when in control |
| `chronic_flag` | true/false, optional | the H-03 p-chart flag (chronically unusable station). **Not shown on the map for now**; the map ignores it |
| `availability` | number 0 to 1, or `null` | from H-03 |

## Rules the map checks

A frame that breaks a rule is still drawn, but a red banner names the station and the rule.

1. `occupancy` equals `bikes / capacity`, within 0.01.
2. `severity` is 0, 1, 2 or 3, and `direction` is `"ok"` exactly when `severity` is 0.
3. `bikes_to_move` is `null` when `severity` is 0, and a non-zero whole number otherwise. Only
   out-of-control stations get a move. Moving bikes at a station that shows only normal noise
   over-adjusts the system and wastes van trips.
4. The sign matches the direction: `"empty"` needs a positive move (add), and `"full"` a negative one (remove).
5. The move is possible: `-bikes <= bikes_to_move <= capacity - bikes`.
6. `lat` and `lon` are numbers in range. A station without them is listed under the map, not drawn.

## Version 2 (added by the back end, Oct 16)

The back end (`app/app.py`, `app/engine.py`, statistics in `app/qc.py`) now sends v2 frames. Every v1
rule above still holds, and v1 frames (like `sampleFrames.js`) still pass. A station that has a
`trigger` field is also checked against these rules:

| Field | Type | Meaning |
|---|---|---|
| `trigger` | `"rule 1"`-`"rule 4"`, `"out of spec"` or `null` | why the van should go: a Western Electric rule on the station's chart, or a reading outside 4-16 bikes (the safety net) |
| `expected_bikes` | number, 0 to `capacity` | where the night plan expects the station now; `target_occupancy` = this / capacity |
| `x` | number or `null` | the control-chart point: rider net flow minus the usual for this 15-minute slot |
| `chart_x` | number or `null` | the point the **chart** draws: as `x`, but with the usual flow from the chart's limits (see `limits` below) |
| `chart_rule` | `"rule 1"`-`"rule 4"` or `null` | the rule that fired on the **chart's** limits (red point). The van's own `trigger` keeps the week-1 limits |
| `van_moved` | whole number | bikes the van dropped (+) or took (−) right after this reading |
| `bikes_after_van` | whole number | `bikes + van_moved` |

Severity for v2: rule 1 = 3, rule 2 = 2, rules 3 and 4 = 1, out of spec with no rule = 2.

- **Rule 2 (v2):** `severity` is 0 exactly when `trigger` is `null`.
- **Rule 3 (v2):** a triggered station may have `bikes_to_move` = 0: it is already past its expected
  path in the direction of the drift, so there is nothing to move.

Frame fields: `slot` (0-63, 06:00-21:45), `reserve` (bikes in the depot after this reading's van
stop), and `van`, the stop the van made after this reading, or `null`:
`{"station_id", "bikes_moved", "partner", "partner_bikes", "reserve_bikes"}`. Bikes come from (or go
to) `partner` and the depot.

Routes: `GET /frames/{week1|week2|event}?day=0..6` (64 frames and the chart's x-bar and sigma per
station), `GET /latest`, `POST /replay`, `GET /summary` (night plan, rush slots, weekly p-charts).
All 960 frames the simulation produces pass `validateFrame()`.

## Chart limits (`GET /frames/{scenario}?limits=`, Oct 17)

- `limits=rolling` (default): each day's charts use the **last 7 days before it**, cleaned with
  `qc.clean_baseline` (readings beyond 3σ removed and the limits recomputed until none remain), so
  the limits update every day. With fewer than 2 earlier days, a station keeps the week-1 history.
- `limits=week1`: the fixed week-1 limits, for comparison (then `chart_x` = `x`).
- The reply carries `"limits"` and, per station in `chart`, `basis`, `basis_days` and `removed`.
- The van's decisions (`x`, `severity`, `trigger`, `bikes_to_move`, `van`) always use week 1, so the
  simulated data and van log stay valid; only the drawn chart changes.

## Still to decide (back end)
- Decided: the chart is on rider net flow minus the station's usual for that 15-minute slot, and the
  move aims at the night plan's expected path for this time of day.
- Decided: `bikes_to_move` rounds half up, at most 10 bikes a stop (`app/qc.py: van_move`).

## How the back end can test against this
Make your endpoint return a frame for `data/` input, save it as JSON, and run the map's own checker:

```
cd app/frontend && npx vitest run src/map/contract.test.js
```

That test already checks `docs/map-frame.example.json`. Copy your output over a scratch copy of it
and run the test again, or call `validateFrame()` from `src/map/contract.js` on it.
