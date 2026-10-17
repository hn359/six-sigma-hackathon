# Data codebook

Every file here is **invented** by [`simulate.py`](simulate.py). It is not real bikeshare data. It
simulates individual trips between five made-up stations placed at real Ithaca places, so bikes
really flow from station to station and the fleet never changes size.

## Make a new run

```
python data/simulate.py                                   # the official files in data/ (seed 5300)
python data/simulate.py --seed 7 --out data/runs/seed7    # different random days, same method
python data/simulate.py --seed 7 --baseline-days 40 --out data/runs/long
```

The same seed always gives byte-identical files, and a different seed gives a fresh draw from the
same model. Extra runs go in `data/runs/`, which git ignores. From Python:
`from data.simulate import run; r = run(seed=7)` returns the rows without writing files.

## Files

| File | Rows (default run) | What it is |
|---|---|---|
| `stations.csv` | 5 | the stations: id, name, position, number of docks |
| `readings_baseline.csv` | 6,500 | **Phase I**: 20 normal weekdays (Mon 7 Sep - Fri 2 Oct 2026) × 65 readings × 5 stations. Learn "normal" and set control limits from this file |
| `readings_test.csv` | 1,625 | **Phase II**: the next week (Mon 5 - Fri 9 Oct), one planted problem per day |
| `events.csv` | 6 | **the answer key**: what was planted, where, when, and what a chart should flag |

### `stations.csv`
| Column | Type and units | Meaning |
|---|---|---|
| `station_id` | text | S01-S05 |
| `name` | text | North Campus (RPCC), Main Campus (Ho Plaza), Fall Creek, Downtown (Ithaca Commons), Wegmans (Meadow St) |
| `lat`, `lon` | degrees | approximate position, used by the map |
| `capacity` | docks | 15, 23, 11, 19, 15 (83 in total) |

### `readings_baseline.csv` and `readings_test.csv`
| Column | Type and units | Meaning |
|---|---|---|
| `station_id` | text | which station |
| `timestamp` | ISO 8601 local time, `YYYY-MM-DDTHH:MM` | when the reading was taken: every 15 min, 06:00-22:00, weekdays (65 a day) |
| `bikes_available` | count of bikes | bikes ready to rent. 0 = **empty** |
| `docks_available` | count of docks | free docks to return to. 0 = **full** |

Normally `bikes_available + docks_available = capacity`. The exceptions are all on the test days and
are listed in `events.csv`:
- on broken-dock day the sum is the working docks;
- an offline station reports 0 and 0;
- a blank row has no counts.

### `events.csv`
`date, station_id, start, end, event, what_should_be_flagged`: one row per planted problem.

| Test day | Station | Planted problem | A good SPC tool should |
|---|---|---|---|
| Mon | none | a normal day | flag nothing (a false-alarm check) |
| Tue | S04 Downtown | about 4 extra trips per 15 min arrive 18:00-18:45 (an event lets out); the bikes come from other stations | flag 1 point beyond 3 sigma |
| Wed | S03 Fall Creek | extra rentals (about 0.3 per 15 min) from 10:00 on | flag a sustained drift (2 of 3 beyond 2 sigma, 8 in a row) |
| Thu | S02 Main Campus | only 12 of 23 docks work all day; the crew moved extra bikes away before 06:00 | flag a sustained shift |
| Fri | S05 Wegmans, others | Wegmans offline 12:00-14:00 (9 readings of 0 and 0); 3 blank readings (S01 09:15, S03 16:30, S04 20:00) | skip or flag the bad readings, not chart them as real |

## How the simulation works

Each 15-minute slot, for each station:
1. **Rentals ~ Poisson(λ(t) × daily factor).** The rate has a calm baseline plus bell-shaped peaks:
   `λ(t) = base + am·bump(08:00) + mid·bump(12:30) + pm·bump(17:30)`. The daily factor is uniform
   0.9-1.1, like the weather.
   - Residential stations (North Campus, Fall Creek) have a big morning peak.
   - Main Campus has a big evening peak.
   - Downtown and Wegmans are busier midday and in the evening.
   - The rates are in `RATES` in `simulate.py`.
2. **Empty station:** a rider who finds it empty is lost.
3. **Destination** is a weighted random choice that depends on the time of day (`DEST`): mornings
   go from homes to campus and downtown, evenings go back home and to shops.
4. **Ride time** is 15 min (60%) or 30 min (40%).
5. **Full station:** a bike returned to a full (or offline) station goes to the nearest station with
   a free dock.
6. **The reading** is taken at the end of the slot.

**The fleet** is 45 bikes, always 45: bikes docked plus bikes being ridden.

**Overnight** (22:00-06:00) nobody rides. Bikes still out dock at their destination, and the next
day starts where this one ended. The weights are tuned so each station's expected daily gain or loss
is under one bike (`expected_net_flow()`), but random days still make the levels wander a little
from week to week.

## Things to know before charting
- **Readings 15 minutes apart are correlated.** So is each morning with the night before,
  because of the carry-over. Raw bike counts also swing by design at every rush hour. Chart
  something with the daily pattern taken out instead, for example bikes minus that station's usual
  level for the same 15-minute slot, or the change in bikes since the last reading compared with
  its usual value for that slot.
- **The planted Tuesday surge** shows up most clearly in the 15-minute change. At Downtown in
  Phase I, the change into 18:45 has mean +0.6 and sd 1.5 bikes; on the event day it is +6.

## Collecting this for real
Most bikeshare systems publish a public [GBFS](https://gbfs.org) feed.
- **Readings:** its `station_status` file gives `num_bikes_available` and `num_docks_available`
  for every station. Saving it every 15 minutes gives exactly the readings files.
- **Stations:** the `station_information` file gives `name`, `lat`, `lon` and `capacity`.
