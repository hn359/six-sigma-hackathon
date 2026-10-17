# Data codebook

**Every file here is invented.** [`simulate.py`](simulate.py) writes them with a fixed seed per
city, so `python data/simulate.py` rebuilds exactly the same files. They are shaped like a real
bikeshare station feed, but no number is real. How the simulation works, step by step, is in the
main [README](../README.md#how-the-datasets-are-generated).

## Three simulated cities

Each folder is one network. They differ on purpose, to show the tool works for any network.

| Folder | Stations | Docks | Readings | Story |
|---|---|---|---|---|
| [`collegetown/`](collegetown/) | 5 (S01-S05) | 20 each (fleet 100) | every 15 min, 06:00-21:45, 64 a day | student commute around College Ave |
| [`downtown/`](downtown/) | 6 (D01-D06) | 19, 15, 27, 31, 23, 12 (fleet 127) | every 10 min, 06:00-21:50, 96 a day | office commute around the Commons |
| [`waterfront/`](waterfront/) | 4 (W01-W04) | 25, 30, 20, 15 (fleet 90) | every 15 min, 08:00-22:45, 60 a day | leisure riding by the inlet |

The fleet is as many bikes as docks. At the start of the baseline week half the docks are filled
(⌊docks/2⌋ per station) and the rest of the fleet sits in the reserve depot.

## Files in each folder

| File | Rows | What it shows |
|---|---|---|
| `stations.csv` | one per station | id, name, position, docks, role in the demand model |
| `week1_baseline.csv` | 7 days × readings × stations | Mon 5 – Sun 11 Oct 2026. **No van.** Phase I: the history the tool learns from |
| `week2_policy.csv` | 7 days x readings x stations | Mon 12 - Sun 18 Oct. Week 1's 06:00-10:00 average net flow sets the 80/20 opening targets shown by BikeFlow; each day starts at those targets. The van goes on a chart signal or a reading outside the spec limits |
| `event_day.csv` | 1 day × readings × stations | Mon 19 Oct: the policy, plus a planted slow drain and a planted crowd (see `about.json`) |
| `van_log.csv` | one per van stop | every stop in week 2 and on the event day |
| `trips.csv` | one per rider trip | every completed simulated trip, all 15 days: where it started and ended |
| `about.json` | 1 | the city's name, reading interval, hours, docks, fleet, seed and the planted event |

Expected results (checked by `tests/test_data.py`):

| City | Out-of-spec readings: baseline -> policy | Lost rentals | Event |
|---|---|---|---|
| collegetown | 607 -> 165 | 19 -> 0 | S03 slow drain gets bikes; the S02 crowd is caught by rule 1 at 18:15 |
| downtown | 838 -> 213 | 15 -> 0 | D06 slow drain gets bikes; the D04 crowd is caught by rule 1 at 17:20 |
| waterfront | 186 -> 238 | 3 -> 0 | the W03 drain gets bikes; the W02 festival crowd is caught by rule 1 at 16:15 |

## Columns

**`week1_baseline.csv`, `week2_policy.csv`, `event_day.csv`**

| Column | Type and units | Meaning |
|---|---|---|
| `station_id` | text | as in `stations.csv` |
| `timestamp` | ISO 8601 local time, `YYYY-MM-DDTHH:MM` | when the reading was taken |
| `bikes` | count, 0 to `capacity` | bikes docked at that moment, **before** any van move at this time |
| `capacity` | count | docks at the station |
| `van_moved` | signed count | bikes the van dropped (+) or took (−) right after this reading; 0 if none |

Rider net flow between two readings = `bikes` now − `bikes` before − `van_moved` before.
Spec limits for a station: LSL = round(0.2 × capacity), USL = round(0.8 × capacity).

**`stations.csv`**: `station_id`, `name`, `lat` and `lon` (decimal degrees, approximate Ithaca places),
`capacity` (docks), `role` (the demand pattern: residential, campus, offices, transit hub, shopping,
market, park, lodging, dining).

**`van_log.csv`**

| Column | Meaning |
|---|---|
| `timestamp`, `station_id` | when and where the van stopped |
| `trigger` | `rule 1`-`rule 4` (the Western Electric rule that fired) or `out of spec` (the safety net) |
| `direction` | `empty` (draining, bikes brought) or `full` (filling, bikes taken) |
| `bikes_before`, `bikes_moved`, `bikes_after` | the station's bikes before and after the stop, and the signed move |
| `from_station` / `to_station` | the other station the bikes came from or went to, if any |
| `station_bikes`, `reserve_bikes` | how many of the moved bikes came from (or went to) that station and the reserve depot |

**`trips.csv`** (added for the BikeFlow origin-destination heat map; recording it draws no random
numbers, so every other file is byte-for-byte unchanged)

| Column | Meaning |
|---|---|
| `timestamp` | the reading that ends the interval the trip happened in (trips are not timed inside it) |
| `from_station` | where the rider took the bike |
| `to_station` | where the rider docked it (if the planned station was full, the station they rode on to) |

Lost rentals (an empty station) are not trips and are not listed. A real system gets this from its
trip history (most bikeshare operators publish monthly trip files with start and end stations).

**`about.json`**: `id`, `name`, `interval_minutes`, `first_reading`, `last_reading`,
`readings_per_day`, `stations`, `docks`, `fleet`, `seed`, `simulated` (always true), and `event`
(`slow_drain`: station, window, extra rentals per reading; `crowd`: station, window, riders per
reading, where they come from).

## How the data is simulated (short)

- Rentals at a station in one reading interval ~ **Poisson**(rate for that station and time of day).
- Each rider rides to another station picked with time-of-day weights (homes in the evening,
  campus/offices in the morning, market and park midday…).
- A rental at an empty station is **lost**. A return to a full station goes on to the emptiest
  station with room.
- Bikes are never created or lost: the script checks docked + reserve = fleet after every reading.
- The rates were tuned so each station's normal daily swing fits inside its spec band. Week 2
  uses week 1's morning net-flow pattern for its 80/20 opening targets; every simulated day has the
  same demand profile, with random trip counts but no separate weekend or weather effects.

The exact rates and weights for each city are in `DATASETS` at the top of [`simulate.py`](simulate.py).

## Collecting this for real

Bikeshare systems publish a public [GBFS](https://gbfs.org) feed. Its `station_status` file gives
`station_id`, `num_bikes_available` and `last_reported` for every station, and
`station_information` gives `name`, `lat`, `lon` and `capacity`. A script that saves
`station_status` every 10-15 minutes gives the readings files. `van_moved` comes from the van crew's
own log: bikes dropped or taken at each stop, with the time. Two weeks of polling give the same
history as here: one week without rebalancing (or with the van log) to learn from, one to judge.
Treat disabled bikes and docks as missing, and drop readings whose `last_reported` is stale.
