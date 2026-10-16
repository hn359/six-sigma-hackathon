# Data codebook

All three files are **invented** by `make_data.py` (seeded, so `python data/make_data.py`
rebuilds them exactly). They are shaped like a real bikeshare station feed but are not real.

## Files

| File | Rows | What it shows | Expected result |
|---|---|---|---|
| `normal_week.csv` | 2,800 | 10 stations (S01-S10), Mon 5 – Fri 9 Oct 2026, all behaving alike (about 12% of readings empty or full) | p̄ ≈ 0.130, no station flagged |
| `hot_station.csv` | 2,800 | Same network, but S07 is planted to run empty most rush hours | only S07 flagged (p = 0.50 vs UCL 0.266), action "bring bikes" |
| `edge_case.csv` | 169 | 3 stations, one day: 3 rows with blank counts, a station that never fails (E02), one Saturday reading | 3 rows skipped, E02 availability 1.00 with no MTTR, small-sample warnings, nothing flagged |

## Columns (all files)

| Column | Type and units | Meaning |
|---|---|---|
| `station_id` | text | the station's ID in the feed |
| `timestamp` | ISO 8601 local time, `YYYY-MM-DDTHH:MM` | when the reading was taken |
| `bikes_available` | count of bikes | bikes ready to rent; 0 means the station is **empty** |
| `docks_available` | count of docks | open docks to return a bike to; 0 means the station is **full** |

Readings run every 15 minutes, 06:00–19:45. The tool keeps only weekday readings inside
07:00–09:59 and 16:00–18:59 (24 a day, 120 a week per station).

## How the data is simulated

Each station flips between usable and unusable with a two-state Markov chain, so outages come
in runs as they do in reality: P(usable → unusable) = a, P(stay unusable) = s, long-run share
unusable = a / (a + 1 − s). Normal stations: a = 0.07, s = 0.5 (≈ 12%). The planted S07:
a = 0.35, s = 0.7 (≈ 54%), and 90% of its outages are empty rather than full.

## Collecting this for real

Most bikeshare systems publish a public [GBFS](https://gbfs.org) feed. Its `station_status`
file gives `station_id`, `num_bikes_available`, `num_docks_available` and `last_reported` for
every station. A small script that saves that file every 15 minutes for a week gives exactly
this CSV. Disabled bikes and docks should be left out of the counts, as the feed already does.
