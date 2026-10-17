# Data codebook

**All files here are invented.** `simulate.py` makes them with a fixed seed (5300), so
`python data/simulate.py` rebuilds exactly the same files. They are shaped like a real bikeshare
station feed, but no number is real.

## The network

Five stations at real Ithaca places (from the map), **20 docks each** (100 docks). The fleet is 100
bikes: 50 docked at the start (10 per station on Monday 5 October 2026, 06:00, which is t0) and 50 in
the reserve depot. A reading every 15 minutes, 06:00-21:45: 64 per station per day.

## Files

| File | Rows | What it shows |
|---|---|---|
| `stations.csv` | 5 | the stations: id, name, position, docks, role in the demand model |
| `week1_baseline.csv` | 2,240 | Mon 5 – Sun 11 Oct. Every station starts at 10, **no van**. Phase I: the history the tool learns from |
| `week2_policy.csv` | 2,240 | Mon 12 – Sun 18 Oct. The night plan sets each start; the van goes on a chart signal or a reading outside 4-16 |
| `event_day.csv` | 320 | Mon 19 Oct, with the policy and two planted problems (below) |
| `van_log.csv` | one per van stop | every van stop in week 2 and on the event day |

Expected results: out-of-spec readings fall from 607 in week 1 to 19 in week 2, and lost rentals
from 19 to 0. On the event day the van is sent to S03 during its slow drain and to S02 (rule 1)
during the crowd.

## Columns

**`week1_baseline.csv`, `week2_policy.csv`, `event_day.csv`**

| Column | Type and units | Meaning |
|---|---|---|
| `station_id` | text | S01-S05, as in `stations.csv` |
| `timestamp` | ISO 8601 local time, `YYYY-MM-DDTHH:MM` | when the reading was taken |
| `bikes` | count, 0-20 | bikes docked at that moment, **before** any van move at this time |
| `capacity` | count | docks at the station (20) |
| `van_moved` | signed count | bikes the van dropped (+) or took (−) right after this reading; 0 if none |

Rider net flow between two readings = `bikes` now − `bikes` before − `van_moved` before.

**`stations.csv`**: `station_id`, `name`, `lat` and `lon` (decimal degrees), `capacity` (docks),
`role` (the demand pattern used for the station).

**`van_log.csv`**

| Column | Meaning |
|---|---|
| `timestamp`, `station_id` | when and where the van stopped |
| `trigger` | `rule 1`-`rule 4` (the Western Electric rule that fired) or `out of spec` (the safety net) |
| `direction` | `empty` (draining, bikes brought) or `full` (filling, bikes taken) |
| `bikes_before`, `bikes_moved`, `bikes_after` | the station's bikes before and after the stop, and the signed move |
| `from_station` / `to_station` | the other station the bikes came from or went to, if any |
| `station_bikes`, `reserve_bikes` | how many of the moved bikes came from (or went to) that station and the reserve depot |

## How the data is simulated

- **Rentals:** in each 15-minute slot, rentals at a station ~ Poisson(rate). Rates per 15 minutes:

  | Role (station) | 06:00-06:59 | 07:00-09:59 | 10:00-15:59 | 16:00-18:59 | 19:00-21:59 |
  |---|---|---|---|---|---|
  | residential (S01 North Campus) | 0.12 | 0.70 | 0.15 | 0.40 | 0.15 |
  | campus (S02 Ho Plaza) | 0.08 | 0.30 | 0.18 | 0.80 | 0.15 |
  | residential (S03 Fall Creek) | 0.12 | 0.65 | 0.15 | 0.40 | 0.15 |
  | transit hub (S04 Commons) | 0.12 | 0.55 | 0.18 | 0.70 | 0.15 |
  | shopping (S05 Wegmans) | 0.10 | 0.45 | 0.20 | 0.50 | 0.20 |

- **Destinations:** each rider picks another station with weights (S01..S05): morning rush 0.6, 2.0,
  0.6, 1.8, 1; evening rush 2.2, 0.6, 2.2, 1, 1; midday 1, 1, 1, 1, 1.2; otherwise 1.3, 0.8, 1.3, 1, 1.
  So homes drain and campus fills in the morning, and the reverse in the evening.
- **Limits:** a rental at an empty station is lost; a return to a full station goes on to the
  emptiest station with room. Bikes are never created or lost: the script checks
  docks + reserve = 100 after every reading.
- **Planted problems (event day only):** S03 Fall Creek gets one extra rental every 15 minutes from
  10:15 to 13:00 (a slow drain), and 4 extra riders per 15 minutes ride from S04 or S05 to S02 Ho
  Plaza from 18:15 to 19:00 (a crowd).
- **The rates were tuned** so each station's normal daily swing is at most 12 bikes. A single 06:00
  start can then keep its normal day inside 4-16, which the night plan needs. Every day has the same
  demand: no weekends and no weather.

## Collecting this for real

Bikeshare systems publish a public [GBFS](https://gbfs.org) feed. Its `station_status` file gives
`station_id`, `num_bikes_available` and `last_reported` for every station, and
`station_information` gives `name`, `lat`, `lon` and `capacity`. A script that saves
`station_status` every 15 minutes gives the readings files. `van_moved` comes from the van crew's own
log: bikes dropped or taken at each stop, with the time. Two weeks of polling give the same history
as here. Treat disabled bikes and docks as missing, and drop readings whose `last_reported` is stale.
