"""Simulate bikeshare station readings for testing. Run from the repo root:

    python data/simulate.py                                  # the official files in data/
    python data/simulate.py --seed 7 --out data/runs/seed7   # another random run, same method
    python data/simulate.py --seed 7 --baseline-days 40 --out data/runs/long

Everything this writes is INVENTED, not real data. It simulates individual
trips between five made-up stations at real Ithaca places, so bikes really
flow: a station empties when riders leave faster than others arrive, and the
fleet never changes size (docked + riding = FLEET at every step).

Seeded: running it again rewrites every file byte for byte.

It computes no control-chart numbers. Limits, run rules and flags are the
SPC team's job; events.csv is the answer key to check them against.
"""

import argparse
import csv
import math
import random
from datetime import date, timedelta
from pathlib import Path

OUT = Path(__file__).resolve().parent
SEED = 5300
FLEET = 45

# station_id, name, lat, lon, docks, bikes at the very first 06:00 (sum = FLEET)
STATIONS = [
    ("S01", "North Campus (RPCC)", 42.4556, -76.4778, 15, 9),
    ("S02", "Main Campus (Ho Plaza)", 42.4470, -76.4833, 23, 9),
    ("S03", "Fall Creek", 42.4495, -76.4953, 11, 6),
    ("S04", "Downtown (Ithaca Commons)", 42.4392, -76.4964, 19, 12),
    ("S05", "Wegmans (Meadow St)", 42.4334, -76.5108, 15, 9),
]
IDS = [s[0] for s in STATIONS]
N = len(STATIONS)

# Readings every 15 minutes, 06:00-22:00: 65 readings, 64 slots of riding.
SLOT_MIN = 15
READ_MIN = [6 * 60 + SLOT_MIN * k for k in range(65)]

# Rentals per 15 minutes = base + am*bump(08:00) + mid*bump(12:30) + pm*bump(17:30),
# times a daily factor (0.9-1.1, like the weather).
RATES = {
    #      base   am    mid   pm
    "S01": (0.30, 1.60, 0.20, 0.60),  # residential: big morning exodus
    "S02": (0.40, 0.40, 0.50, 2.00),  # campus: big evening exodus
    "S03": (0.20, 1.00, 0.20, 0.40),  # residential
    "S04": (0.50, 0.60, 0.60, 1.20),  # downtown: some of everything
    "S05": (0.30, 0.20, 0.60, 0.80),  # grocery: midday and evening
}

# Where riders go: relative weights to S01..S05, by time of day (0 = no trips to itself).
DEST = {
    "morning": {  # before 11:00: homes -> campus and downtown
        "S01": (0, 6, 0.5, 2, 0.5),
        "S02": (2, 0, 1, 2, 0.5),
        "S03": (0.5, 5, 0, 3, 0.5),
        "S04": (1, 3, 1, 0, 1),
        "S05": (1, 2, 1, 3, 0),
    },
    "midday": {  # 11:00-15:00: errands, downtown and Wegmans busier
        "S01": (0, 2, 1, 3, 2.5),
        "S02": (1, 0, 1, 3, 2.5),
        "S03": (1, 2, 0, 3, 2.5),
        "S04": (1, 2, 1, 0, 2.5),
        "S05": (1, 2, 1, 3, 0),
    },
    "evening": {  # 15:00 on: back home, plus downtown and shopping
        "S01": (0, 2, 1, 3.5, 2),
        "S02": (4.6, 0, 1.7, 3.5, 1.6),
        "S03": (1, 2, 0, 3.5, 2),
        "S04": (2, 2, 1.5, 0, 2.5),
        "S05": (2, 1, 1, 3, 0),
    },
}
# These weights are tuned so every station's expected daily net flow is within
# +/-1 bike (expected_net_flow() below): with carry-over, a station that gained
# bikes every day would end up permanently full. Random days still make the
# levels wander a little from week to week, as real stations do.
RIDE_SLOTS = ((1, 0.6), (2, 0.4))  # a ride takes 15 min (60%) or 30 min (40%)

BASELINE_DAYS = 20  # Phase I: 20 weekdays from Mon 7 Sep 2026 (to Fri 2 Oct)
FIRST_DAY = date(2026, 9, 7)

# The planted problems (Phase II): one test day each, Monday to Friday of the
# week after the baseline. First field = test day 0-4. Times are reading times.
EVENTS = [
    (0, "", "", "", "normal day",
     "nothing (false-alarm check)"),
    (1, "S04", "18:00", "18:45", "surge: extra trips arriving at Downtown (an event lets out)",
     "1 point beyond 3 sigma at S04"),
    (2, "S03", "10:00", "22:00", "slow drain: extra rentals at Fall Creek",
     "sustained drift at S03 (2 of 3 beyond 2 sigma, 8 in a row)"),
    (3, "S02", "06:00", "22:00", "broken docks: Main Campus has 12 working docks instead of 23",
     "sustained shift at S02"),
    (4, "S05", "12:00", "14:00", "station offline: Wegmans reports 0 bikes and 0 docks",
     "bad readings skipped or flagged, not charted as real"),
    (4, "S01 S03 S04", "", "", "blank readings: 3 rows with no counts (S01 09:15, S03 16:30, S04 20:00)",
     "bad readings skipped or flagged, not charted as real"),
]
SURGE = {"station": "S04", "per_slot": 4.0, "rent_slots_end": ("17:45", "18:00", "18:15", "18:30")}
DRAIN = {"station": "S03", "per_slot": 0.3, "from": "10:00"}
BROKEN = {"station": "S02", "docks": 12}
OFFLINE = {"station": "S05", "from": "12:00", "to": "14:00"}
BLANKS = (("S01", "09:15"), ("S03", "16:30"), ("S04", "20:00"))


def hhmm(minute):
    return f"{minute // 60:02d}:{minute % 60:02d}"


def bump(h, centre, width):
    return math.exp(-0.5 * ((h - centre) / width) ** 2)


def rate(sid, h):
    base, am, mid, pm = RATES[sid]
    return base + am * bump(h, 8.0, 0.8) + mid * bump(h, 12.5, 1.5) + pm * bump(h, 17.5, 1.0)


def period(h):
    return "morning" if h < 11 else "midday" if h < 15 else "evening"


def poisson(rng, lam):
    """Knuth's method; fine for the small rates used here."""
    if lam <= 0:
        return 0
    limit, k, p = math.exp(-lam), 0, 1.0
    while True:
        p *= rng.random()
        if p <= limit:
            return k
        k += 1


def weighted(rng, weights):
    r = rng.random() * sum(weights)
    for i, w in enumerate(weights):
        r -= w
        if r < 0:
            return i
    return len(weights) - 1


def _dist(i, j):
    (_, _, la1, lo1, _, _), (_, _, la2, lo2, _, _) = STATIONS[i], STATIONS[j]
    return math.hypot(la1 - la2, (lo1 - lo2) * math.cos(math.radians(la1)))


NEAREST = [sorted((j for j in range(N) if j != i), key=lambda j: _dist(i, j)) for i in range(N)]


class Network:
    """Bikes docked at each station plus bikes out riding. Never gains or loses a bike."""

    def __init__(self):
        self.bikes = [s[5] for s in STATIONS]
        self.cap = [s[4] for s in STATIONS]
        self.riding = []  # [slots_left, destination]
        self.offline = [False] * N
        self.lost_rentals = 0
        self.diverted_returns = 0
        assert self.total() == FLEET

    def total(self):
        return sum(self.bikes) + len(self.riding)

    def room(self, i):
        return not self.offline[i] and self.bikes[i] < self.cap[i]

    def dock(self, dest):
        """Dock one bike at dest, or at the nearest station with room. False if nowhere."""
        if self.room(dest):
            self.bikes[dest] += 1
            return True
        for j in NEAREST[dest]:
            if self.room(j):
                self.bikes[j] += 1
                self.diverted_returns += 1
                return True
        return False

    def rent(self, i, dest, slots):
        self.bikes[i] -= 1
        self.riding.append([slots, dest])

    def arrivals(self):
        still = []
        for ride in self.riding:
            ride[0] -= 1
            if ride[0] > 0 or not self.dock(ride[1]):
                still.append(ride)
        self.riding = still

    def overnight(self):
        """No rides 22:00-06:00: bikes still out dock at (or near) their destination."""
        for _, dest in self.riding:
            if not self.dock(dest):
                raise RuntimeError("nowhere to dock overnight")  # cannot happen: FLEET < docks
        self.riding = []


def simulate_day(net, rng, day, plan=None, trace=None):
    """One weekday, 06:00-22:00. Returns rows (station_id, timestamp, bikes, docks)."""
    plan = plan or {}
    factor = rng.uniform(0.9, 1.1)
    broken = plan.get("broken")
    if broken:  # the crew moves bikes off the broken docks before 06:00
        i = IDS.index(broken["station"])
        net.cap[i] = broken["docks"]
        while net.bikes[i] > net.cap[i]:
            net.bikes[i] -= 1
            if not net.dock(i):
                raise RuntimeError("nowhere to put bikes from broken docks")
    rows = []

    def read(minute):
        stamp = f"{day.isoformat()}T{hhmm(minute)}"
        for i, sid in enumerate(IDS):
            if net.offline[i]:
                rows.append([sid, stamp, 0, 0])
            elif (sid, hhmm(minute)) in plan.get("blanks", ()):
                rows.append([sid, stamp, "", ""])
            else:
                rows.append([sid, stamp, net.bikes[i], net.cap[i] - net.bikes[i]])
        if trace is not None:
            trace.append((stamp, net.total()))

    off = plan.get("offline")
    for k, minute in enumerate(READ_MIN):
        if off:
            i = IDS.index(off["station"])
            net.offline[i] = off["from"] <= hhmm(minute) <= off["to"]
        if k > 0:  # riding in the slot that ends at this reading
            net.arrivals()
            h = (minute - SLOT_MIN / 2) / 60
            for i, sid in enumerate(IDS):
                if net.offline[i]:
                    continue
                want = poisson(rng, rate(sid, h) * factor)
                drain = plan.get("drain")
                if drain and sid == drain["station"] and hhmm(minute) > drain["from"]:
                    want += poisson(rng, drain["per_slot"])
                for _ in range(want):
                    if net.bikes[i] == 0:
                        net.lost_rentals += 1
                        continue
                    dest = weighted(rng, DEST[period(h)][sid])
                    net.rent(i, dest, RIDE_SLOTS[weighted(rng, [p for _, p in RIDE_SLOTS])][0])
            surge = plan.get("surge")
            if surge and hhmm(minute) in surge["rent_slots_end"]:
                s = IDS.index(surge["station"])
                for _ in range(poisson(rng, surge["per_slot"])):
                    origins = [j for j in range(N) if j != s and not net.offline[j] and net.bikes[j] > 0]
                    if origins:
                        j = weighted(rng, [net.bikes[o] for o in origins])
                        net.rent(origins[j], s, 1)  # arrives at the next reading
        read(minute)
    net.offline = [False] * N
    if broken:
        net.cap[IDS.index(broken["station"])] = STATIONS[IDS.index(broken["station"])][4]
    net.overnight()
    return rows


def expected_net_flow():
    """Expected bikes gained (+) or lost (-) per station over an average day,
    from RATES and DEST alone (daily factor 1, no empty or full stations)."""
    net = {sid: 0.0 for sid in IDS}
    for minute in READ_MIN[1:]:
        h = (minute - SLOT_MIN / 2) / 60
        for sid in IDS:
            lam = rate(sid, h)
            w = DEST[period(h)][sid]
            net[sid] -= lam
            for j, wj in enumerate(w):
                net[IDS[j]] += lam * wj / sum(w)
    return net


def weekdays(start, count):
    out, d = [], start
    while len(out) < count:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def test_days(baseline_days=BASELINE_DAYS):
    """Mon-Fri of the week after the last baseline day."""
    last = weekdays(FIRST_DAY, baseline_days)[-1]
    monday = last + timedelta(days=7 - last.weekday())
    return [monday + timedelta(days=k) for k in range(5)]


def run(seed=SEED, baseline_days=BASELINE_DAYS):
    """Simulate Phase I then Phase II with one network that carries over day to day.
    Same seed, same result; a different seed gives different random days from
    the same model."""
    if baseline_days < 1:
        raise ValueError("baseline_days must be at least 1")
    rng = random.Random(seed)
    net = Network()
    trace = []
    baseline = []
    for day in weekdays(FIRST_DAY, baseline_days):
        baseline += simulate_day(net, rng, day, trace=trace)
    base_lost, base_div = net.lost_rentals, net.diverted_returns
    days = test_days(baseline_days)
    plans = [{}, {"surge": SURGE}, {"drain": DRAIN}, {"broken": BROKEN},
             {"offline": OFFLINE, "blanks": BLANKS}]
    test = []
    for day, plan in zip(days, plans):
        test += simulate_day(net, rng, day, plan, trace=trace)
    return {
        "seed": seed,
        "test_days": days,
        "events": [[days[k].isoformat(), *rest] for k, *rest in EVENTS],
        "baseline": baseline,
        "test": test,
        "trace": trace,
        "summary": {
            "baseline_lost_rentals": base_lost,
            "baseline_diverted_returns": base_div,
            "test_lost_rentals": net.lost_rentals - base_lost,
            "test_diverted_returns": net.diverted_returns - base_div,
        },
    }


def write_csv(path, header, rows):
    with open(path, "w", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(header)
        w.writerows(rows)


def main(out=OUT, seed=SEED, baseline_days=BASELINE_DAYS):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    res = run(seed, baseline_days)
    write_csv(out / "stations.csv", ["station_id", "name", "lat", "lon", "capacity"],
              [[s[0], s[1], s[2], s[3], s[4]] for s in STATIONS])
    head = ["station_id", "timestamp", "bikes_available", "docks_available"]
    write_csv(out / "readings_baseline.csv", head, res["baseline"])
    write_csv(out / "readings_test.csv", head, res["test"])
    write_csv(out / "events.csv", ["date", "station_id", "start", "end", "event", "what_should_be_flagged"],
              res["events"])
    return res


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Simulate invented bikeshare readings (see data/README.md).")
    ap.add_argument("--seed", type=int, default=SEED, help=f"random seed (default {SEED}, the official files)")
    ap.add_argument("--out", default=str(OUT), help="folder to write the CSVs to (default: data/)")
    ap.add_argument("--baseline-days", type=int, default=BASELINE_DAYS,
                    help=f"weekdays of normal Phase I data (default {BASELINE_DAYS})")
    args = ap.parse_args()
    r = main(args.out, args.seed, args.baseline_days)
    print(f"seed {r['seed']}: {len(r['baseline'])} baseline rows, {len(r['test'])} test rows "
          f"(test week {r['test_days'][0]} to {r['test_days'][-1]}) -> {args.out}")
    print(r["summary"])
