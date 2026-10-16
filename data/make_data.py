"""Rebuild the invented test datasets. Run from the repo root: python data/make_data.py

Every file is simulated, not real. A station's empty/full state follows a
two-state Markov chain so outages come in runs, the way real stations do:
  P(usable -> unusable) = a,  P(unusable -> unusable) = s,
  long-run share unusable = a / (a + 1 - s).
"""

import csv
import random
from datetime import datetime, timedelta
from pathlib import Path

OUT = Path(__file__).resolve().parent
START = datetime(2026, 10, 5)          # a Monday
HEADER = ["station_id", "timestamp", "bikes_available", "docks_available"]


def simulate(rng, station, capacity, days, a, s, p_empty, start=START):
    """Readings every 15 min, 06:00-19:45, for `days` days from `start`."""
    rows, down = [], False
    for day in range(days):
        t = start + timedelta(days=day, hours=6)
        while t.hour < 20:
            down = rng.random() < (s if down else a)
            if down and rng.random() < p_empty:
                bikes = 0
            elif down:
                bikes = capacity
            else:
                bikes = rng.randint(1, capacity - 1)
            rows.append([station, t.isoformat(timespec="minutes"), bikes, capacity - bikes])
            t += timedelta(minutes=15)
    return rows


def write(name, rows):
    with open(OUT / name, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(HEADER)
        w.writerows(rows)


def main():
    # 10 stations, 5 weekdays, every station behaves the same: ~12% unusable.
    rng = random.Random(5300)
    caps = [15, 19, 23, 15, 19, 23, 15, 19, 23, 15]
    normal = []
    for i, cap in enumerate(caps, start=1):
        normal += simulate(rng, f"S{i:02d}", cap, 5, a=0.07, s=0.5, p_empty=0.5)
    write("normal_week.csv", normal)

    # Same network, but S07 (a residential station) runs empty most rush hours.
    rng = random.Random(5300)
    hot = []
    for i, cap in enumerate(caps, start=1):
        if i == 7:
            hot += simulate(rng, "S07", cap, 5, a=0.35, s=0.7, p_empty=0.9)
        else:
            hot += simulate(rng, f"S{i:02d}", cap, 5, a=0.07, s=0.5, p_empty=0.5)
    write("hot_station.csv", hot)

    # One day, three stations: blanks from a feed glitch, a station that never
    # fails (E02), and a Saturday reading that the tool must ignore.
    rng = random.Random(42)
    edge = simulate(rng, "E01", 15, 1, a=0.10, s=0.5, p_empty=0.5)
    edge += simulate(rng, "E02", 20, 1, a=0.0, s=0.0, p_empty=0.5)
    edge += simulate(rng, "E03", 12, 1, a=0.15, s=0.5, p_empty=0.3)
    for k in (8, 9, 70):                 # feed dropped the counts on these rows
        edge[k][2] = edge[k][3] = ""
    edge.append(["E01", "2026-10-10T08:00", 0, 15])   # Saturday: excluded
    write("edge_case.csv", edge)


if __name__ == "__main__":
    main()
