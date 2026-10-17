"""Build the invented test datasets. Run from the repo root: python data/simulate.py

Everything here is SIMULATED, not real data. Three cities (data/<dataset>/), each with a baseline
week (no van), a policy week and an event day. They differ on purpose, to show the tool works for
any network: number of stations, docks per station, minutes between readings, operating hours
and the shape of demand.

Demand model (data/README.md):
- rentals at a station in one reading interval ~ Poisson(rate[station][period of the day]);
- each rider rides to another station, picked with weights attract[station][period];
- an empty station loses the rental; a full one sends the rider on to the emptiest station.
Spec limits are 20% and 80% of a station's docks (app/qc.py: spec_limits). The baseline week has
no van. The policy week and the event day run the policy with app/qc.py: the nightly start plan,
and after every reading the run rules on slot-adjusted net flow, with the van sent on a signal
or when a station is out of spec.
"""

import csv
import json
import math
import random
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from app.qc import (  # noqa: E402
    dispatch_trigger, imr_limits_days, run_rules, spec_limits, start_plan, van_move,
)

OUT = ROOT / "data"

# Each station: id, name, lat, lon (approximate), docks, role, rates per period, attract per period.
# Periods are set by the reading's time of day: period n covers times before bounds[n] (hours).
DATASETS = {
    "collegetown": {
        "name": "Collegetown, Ithaca: student commute",
        "seed": 5300, "interval": 15, "start": "06:00", "end": "21:45", "first_day": date(2026, 10, 5),
        "bounds": (7, 10, 16, 19, 24),       # early, AM rush, midday, PM rush, evening
        "stations": [
            ("S01", "Cascadilla Hall (dorms)", 42.4429, -76.4862, 20, "residential",
             (0.12, 0.70, 0.15, 0.40, 0.15), (1, 0.6, 1, 2.2, 1.3)),
            ("S02", "Schwartz Center (campus gate)", 42.4429, -76.4842, 20, "campus",
             (0.08, 0.30, 0.18, 0.80, 0.15), (1, 2.0, 1, 0.6, 0.8)),
            ("S03", "Dryden Rd (apartments)", 42.4416, -76.4840, 20, "residential",
             (0.12, 0.65, 0.15, 0.40, 0.15), (1, 0.6, 1, 2.2, 1.3)),
            ("S04", "College Ave (bus stop)", 42.4421, -76.4852, 20, "transit hub",
             (0.12, 0.55, 0.18, 0.70, 0.15), (1, 1.8, 1, 1, 1)),
            ("S05", "Eddy St (shops)", 42.4413, -76.4862, 20, "shopping",
             (0.10, 0.45, 0.20, 0.50, 0.20), (1, 1, 1.2, 1, 1)),
        ],
        "event": {"drain": ("S03", "10:15", "13:00", 1),
                  "crowd": ("S02", "18:15", "19:00", 4, ("S04", "S05"))},
    },
    "downtown": {
        "name": "Downtown Ithaca: office commute, mixed station sizes, readings every 10 minutes",
        "seed": 7100, "interval": 10, "start": "06:00", "end": "21:50", "first_day": date(2026, 10, 5),
        "bounds": (7, 10, 16, 19, 24),
        "stations": [
            ("D01", "Fall Creek homes", 42.4410, -76.4985, 19, "residential",
             (0.08, 0.36, 0.10, 0.22, 0.10), (1.1, 0.5, 1, 1.2, 1.0)),
            ("D02", "Court St apartments", 42.4404, -76.4960, 15, "residential",
             (0.06, 0.26, 0.08, 0.18, 0.08), (1.0, 0.5, 1, 1.0, 1.0)),
            ("D03", "Commons offices", 42.4392, -76.4968, 27, "offices",
             (0.05, 0.22, 0.20, 0.70, 0.10), (1, 2.4, 1, 0.5, 0.8)),
            ("D04", "Green St transit center", 42.4384, -76.4980, 31, "transit hub",
             (0.10, 0.55, 0.22, 0.62, 0.18), (1, 1.6, 1.1, 1.4, 1)),
            ("D05", "City Hall", 42.4396, -76.4950, 23, "offices",
             (0.04, 0.18, 0.16, 0.55, 0.08), (1, 2.0, 1, 0.5, 0.8)),
            ("D06", "State St shops", 42.4386, -76.4955, 12, "shopping",
             (0.06, 0.24, 0.26, 0.32, 0.20), (1, 0.8, 1.7, 1, 1.2)),
        ],
        "event": {"drain": ("D06", "11:00", "13:00", 1),
                  "crowd": ("D04", "17:00", "17:40", 4, ("D03", "D05"))},
    },
    "waterfront": {
        "name": "Ithaca waterfront: leisure riding, midday and evening peaks",
        "seed": 9200, "interval": 15, "start": "08:00", "end": "22:45", "first_day": date(2026, 10, 5),
        "bounds": (10, 15, 18, 21, 24),      # morning, midday, afternoon, evening, late
        "stations": [
            ("W01", "Farmers Market", 42.4510, -76.5112, 25, "market",
             (0.15, 0.55, 0.35, 0.20, 0.10), (1.3, 2.2, 1, 0.6, 0.5)),
            ("W02", "Cass Park", 42.4527, -76.5132, 30, "park",
             (0.15, 0.45, 0.60, 0.35, 0.15), (1, 1.8, 2.0, 0.8, 0.6)),
            ("W03", "Inlet hotels", 42.4492, -76.5098, 20, "lodging",
             (0.45, 0.30, 0.25, 0.20, 0.10), (0.6, 0.8, 1, 1.4, 2.4)),
            ("W04", "Steamboat Landing (dining)", 42.4503, -76.5085, 15, "dining",
             (0.06, 0.18, 0.15, 0.40, 0.25), (0.6, 0.9, 1, 2.0, 0.8)),
        ],
        "event": {"drain": ("W03", "09:00", "10:30", 1),
                  "crowd": ("W02", "16:00", "17:00", 5, ("W01", "W03"))},
    },
}


def minutes(hhmm):
    h, m = map(int, hhmm.split(":"))
    return 60 * h + m


class City:
    """One dataset's network, clock and demand, ready to simulate."""

    def __init__(self, key):
        cfg = DATASETS[key]
        self.key, self.cfg = key, cfg
        self.st = cfg["stations"]
        self.ids = [s[0] for s in self.st]
        self.cap = [s[4] for s in self.st]
        self.lim = [spec_limits(c) for c in self.cap]
        self.n = len(self.st)
        self.fleet = sum(self.cap)                  # as many bikes as docks, half of them docked
        self.base_start = [c // 2 for c in self.cap]
        self.interval = cfg["interval"]
        self.t0 = minutes(cfg["start"])
        self.slots = (minutes(cfg["end"]) - self.t0) // self.interval + 1

    def tod(self, k):
        return self.t0 + self.interval * k

    def period(self, k):
        hour = self.tod(k) / 60
        return next(n for n, b in enumerate(self.cfg["bounds"]) if hour < b)

    def in_window(self, k, frm, to):
        return minutes(frm) <= self.tod(k) <= minutes(to)

    def stamp(self, day0, k):
        return (day0 + timedelta(minutes=self.tod(k))).isoformat(timespec="minutes")


def poisson(rng, lam):
    """Knuth's method; fine for the small rates used here."""
    limit, k, p = math.exp(-lam), 0, 1.0
    while True:
        p *= rng.random()
        if p <= limit:
            return k
        k += 1


def run_day(city, rng, day0, start, policy=None, event=False, trips_out=None):
    """Simulate one day. Returns (rows, van_log, totals). rows: one dict per station per reading.
    trips_out, if given, receives one dict per completed trip (reading time, from, to); recording
    them draws no random numbers, so every other output is unchanged."""
    N, ids, cap = city.n, city.ids, city.cap
    ev = city.cfg["event"] if event else None
    bikes = list(start)
    reserve = city.fleet - sum(bikes)
    hist = [[] for _ in range(N)]
    rows, log = [], []
    lost = blocked = 0
    for k in range(city.slots):
        if k > 0:
            p = city.period(k)
            before = bikes[:]
            trips = []
            for i in range(N):
                d = poisson(rng, city.st[i][6][p])
                if ev and ids[i] == ev["drain"][0] and city.in_window(k, ev["drain"][1], ev["drain"][2]):
                    d += ev["drain"][3]
                trips += [(i, None)] * d
            if ev and city.in_window(k, ev["crowd"][1], ev["crowd"][2]):
                dest = ids.index(ev["crowd"][0])
                trips += [(ids.index(rng.choice(ev["crowd"][4])), dest) for _ in range(ev["crowd"][3])]
            rng.shuffle(trips)
            for i, dest in trips:
                if bikes[i] == 0:
                    lost += 1
                    continue
                if dest is None:
                    w = [0 if j == i else city.st[j][7][p] for j in range(N)]
                    dest = rng.choices(range(N), weights=w)[0]
                if bikes[dest] >= cap[dest]:
                    blocked += 1
                    room = [j for j in range(N) if j != dest and bikes[j] < cap[j]]
                    if not room:
                        continue
                    dest = min(room, key=lambda j: bikes[j] / cap[j])
                bikes[i] -= 1
                bikes[dest] += 1
                if trips_out is not None:
                    trips_out.append({"timestamp": city.stamp(day0, k), "from_station": ids[i],
                                      "to_station": ids[dest]})
            if policy:
                for i in range(N):
                    hist[i].append((bikes[i] - before[i]) - policy["mu"][i][k])
        reading = bikes[:]
        van = [0] * N
        if policy and k > 0:
            E = policy["path"]
            need = []
            for i in range(N):
                sig = run_rules(hist[i], policy["imr"][i]["xbar"], policy["imr"][i]["sigma"])
                why = dispatch_trigger(sig, bikes[i], *city.lim[i])
                if not why:
                    continue
                move = van_move(E[i][k], bikes[i], cap[i])
                drift = sig["side"] if sig else (-1 if bikes[i] < cap[i] / 2 else 1)
                if move == 0 or (move > 0) == (drift > 0):
                    continue    # already on the far side of its path from the drift: nothing to move
                need.append((abs(E[i][k] - bikes[i]), i, why, sig, move))
            if need:
                need.sort(key=lambda t: (-t[0], t[1]))
                _, i, why, sig, move = need[0]
                todo = abs(move)
                partner, best = None, 0
                for j in range(N):
                    if j == i:
                        continue
                    spare = bikes[j] - E[j][k] if move > 0 else E[j][k] - bikes[j]
                    if spare >= 1 and spare > best:
                        partner, best = j, spare
                p_amt = r_amt = 0
                if partner is not None:
                    room = bikes[partner] if move > 0 else cap[partner] - bikes[partner]
                    p_amt = min(todo, int(best), room)
                    if p_amt:
                        s = -p_amt if move > 0 else p_amt
                        bikes[partner] += s
                        van[partner] += s
                        todo -= p_amt
                if todo:
                    r_amt = min(todo, reserve) if move > 0 else todo
                    reserve += -r_amt if move > 0 else r_amt
                    todo -= r_amt
                done = abs(move) - todo
                signed = done if move > 0 else -done
                bikes[i] += signed
                van[i] += signed
                hist[i] = []
                if p_amt and partner is not None:
                    hist[partner] = []
                log.append({
                    "timestamp": city.stamp(day0, k), "station_id": ids[i], "trigger": why,
                    "direction": "empty" if (sig and sig["side"] < 0) or (not sig and bikes[i] - signed < cap[i] / 2) else "full",
                    "bikes_before": bikes[i] - signed, "bikes_moved": signed, "bikes_after": bikes[i],
                    "from_station": ids[partner] if p_amt and signed > 0 else "",
                    "to_station": ids[partner] if p_amt and signed < 0 else "",
                    "station_bikes": p_amt, "reserve_bikes": r_amt,
                })
        for i in range(N):
            rows.append({"station_id": ids[i], "timestamp": city.stamp(day0, k), "bikes": reading[i],
                         "capacity": cap[i], "van_moved": van[i]})
        assert sum(bikes) + reserve == city.fleet, "bikes were created or lost"
    return rows, log, {"lost": lost, "blocked": blocked}


def history(city, rows_by_day):
    """Slot means of rider net flow, I-MR limits of x, and the start plan, from no-van days."""
    flows = []  # flows[day][i][k]
    for rows in rows_by_day:
        by = {}
        for r in rows:
            by.setdefault(r["station_id"], []).append(r)
        f = [[0.0] + [(by[sid][k]["bikes"] - by[sid][k - 1]["bikes"] - by[sid][k - 1]["van_moved"])
                      for k in range(1, city.slots)] for sid in city.ids]
        flows.append(f)
    days, S, N = len(flows), city.slots, city.n
    mu = [[sum(flows[d][i][k] for d in range(days)) / days for k in range(S)] for i in range(N)]
    imr = [imr_limits_days([[flows[d][i][k] - mu[i][k] for k in range(1, S)] for d in range(days)])
           for i in range(N)]
    C = [[sum(mu[i][1:k + 1]) for k in range(S)] for i in range(N)]
    plans = [start_plan(C[i], *city.lim[i]) for i in range(N)]
    return mu, imr, C, plans


def build(key):
    city = City(key)
    rng = random.Random(city.cfg["seed"])
    day = lambda d: datetime.combine(city.cfg["first_day"], datetime.min.time()) + timedelta(days=d)
    trips = []
    week1 = [run_day(city, rng, day(d), city.base_start, trips_out=trips) for d in range(7)]
    mu, imr, C, plans = history(city, [w[0] for w in week1])
    bad = [city.ids[i] for i, p in enumerate(plans) if not p["feasible"]]
    if bad:
        raise RuntimeError(f"{key}: normal swing too wide for one start plan at {bad}: retune the rates")
    starts = [p["start"] for p in plans]
    policy = {"mu": mu, "imr": imr, "path": [p["path"] for p in plans]}
    week2 = [run_day(city, rng, day(7 + d), starts, policy, trips_out=trips) for d in range(7)]
    event = run_day(city, rng, day(14), starts, policy, event=True, trips_out=trips)
    return {"city": city, "week1": week1, "week2": week2, "event": event, "mu": mu, "imr": imr,
            "C": C, "plans": plans, "trips": trips}


def write(folder, name, rows, fields):
    folder.mkdir(parents=True, exist_ok=True)
    with open(folder / name, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def out_of_spec(sim, days):
    city = sim["city"]
    lim = dict(zip(city.ids, city.lim))
    return sum(1 for d in days for r in d[0]
               if r["bikes"] < lim[r["station_id"]][0] or r["bikes"] > lim[r["station_id"]][1])


def main(keys=None):
    for key in keys or DATASETS:
        sim = build(key)
        city, folder = sim["city"], OUT / key
        fields = ["station_id", "timestamp", "bikes", "capacity", "van_moved"]
        write(folder, "week1_baseline.csv", [r for d in sim["week1"] for r in d[0]], fields)
        write(folder, "week2_policy.csv", [r for d in sim["week2"] for r in d[0]], fields)
        write(folder, "event_day.csv", sim["event"][0], fields)
        log_fields = ["timestamp", "station_id", "trigger", "direction", "bikes_before", "bikes_moved",
                      "bikes_after", "from_station", "to_station", "station_bikes", "reserve_bikes"]
        write(folder, "van_log.csv", [r for d in sim["week2"] for r in d[1]] + sim["event"][1], log_fields)
        # every completed rider trip, stamped with the reading that ends its interval
        write(folder, "trips.csv", sim["trips"], ["timestamp", "from_station", "to_station"])
        write(folder, "stations.csv",
              [{"station_id": s[0], "name": s[1], "lat": s[2], "lon": s[3], "capacity": s[4], "role": s[5]}
               for s in city.st], ["station_id", "name", "lat", "lon", "capacity", "role"])
        about = {"id": key, "name": city.cfg["name"], "interval_minutes": city.interval,
                 "first_reading": city.cfg["start"], "last_reading": city.cfg["end"],
                 "readings_per_day": city.slots, "stations": city.n, "docks": city.cap, "fleet": city.fleet,
                 "seed": city.cfg["seed"], "simulated": True,
                 "event": {"slow_drain": {"station": city.cfg["event"]["drain"][0], "from": city.cfg["event"]["drain"][1],
                                          "to": city.cfg["event"]["drain"][2], "extra_rentals_per_reading": city.cfg["event"]["drain"][3]},
                           "crowd": {"station": city.cfg["event"]["crowd"][0], "from": city.cfg["event"]["crowd"][1],
                                     "to": city.cfg["event"]["crowd"][2], "riders_per_reading": city.cfg["event"]["crowd"][3],
                                     "coming_from": list(city.cfg["event"]["crowd"][4])}}}
        (folder / "about.json").write_text(json.dumps(about, indent=2) + "\n")
        print(f"== {key}: {city.n} stations, docks {city.cap}, every {city.interval} min, {city.slots} readings/day")
        print(f"   spec limits {city.lim}")
        print(f"   swing / allowed: {[(round(max(c) - min(c), 1), u - l) for c, (l, u) in zip(sim['C'], city.lim)]}")
        print(f"   starts {[p['start'] for p in sim['plans']]}  sigma {[round(l['sigma'], 2) for l in sim['imr']]}")
        print(f"   out-of-spec readings: baseline {out_of_spec(sim, sim['week1'])}, policy {out_of_spec(sim, sim['week2'])}")
        print(f"   lost rentals: baseline {sum(d[2]['lost'] for d in sim['week1'])}, policy {sum(d[2]['lost'] for d in sim['week2'])}")
        print(f"   van stops per day (policy): {[len(d[1]) for d in sim['week2']]}")
        print("   event day: " + "; ".join(f"{v['timestamp'][11:]} {v['station_id']} {v['trigger']} {v['bikes_moved']:+d}"
                                          for v in sim["event"][1]))


if __name__ == "__main__":
    main(sys.argv[1:] or None)
