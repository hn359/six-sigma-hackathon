"""Build the invented test datasets. Run from the repo root: python data/simulate.py

Everything here is SIMULATED, not real data. Five Ithaca stations, 20 docks each, 100 bikes
(50 docked at the start, 50 in the reserve depot), a reading every 15 minutes 06:00-21:45.

Demand model (SPEC.md section 7, data/README.md):
- rentals at a station in a 15-minute slot ~ Poisson(rate[station role][period]);
- each rider rides to another station, picked with weights ATTRACT[period];
- an empty station loses the rental; a full one sends the rider on to the emptiest station.
Week 1 has no van. Week 2 and the event day run the policy with app/qc.py:
the nightly start plan, and every 15 minutes the run rules on slot-adjusted net flow, with the
van sent on a signal or when a station is out of spec.
"""

import csv
import math
import random
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from app.qc import (  # noqa: E402
    dispatch_trigger, imr_limits_days, run_rules, start_plan, van_move, VAN_MAX,
)

OUT = ROOT / "data"
CAP, FLEET, SLOTS = 20, 100, 64
STATIONS = [  # id, name, lat, lon, role
    ("S01", "North Campus (RPCC)", 42.4556, -76.4778, "residential"),
    ("S02", "Main Campus (Ho Plaza)", 42.4470, -76.4833, "campus"),
    ("S03", "Fall Creek", 42.4495, -76.4953, "residential"),
    ("S04", "Downtown (Ithaca Commons)", 42.4392, -76.4964, "transit hub"),
    ("S05", "Wegmans (Meadow St)", 42.4334, -76.5108, "shopping"),
]
N = len(STATIONS)
# Mean rentals per 15 minutes.   06-07  AM rush  10-16  PM rush  19-22
RATE = {"residential1": (0.12, 0.70, 0.15, 0.40, 0.15),
        "residential2": (0.12, 0.65, 0.15, 0.40, 0.15),
        "campus":       (0.08, 0.30, 0.18, 0.80, 0.15),
        "transit hub":  (0.12, 0.55, 0.18, 0.70, 0.15),
        "shopping":     (0.10, 0.45, 0.20, 0.50, 0.20)}
ROLE_ROWS = ["residential1", "campus", "residential2", "transit hub", "shopping"]
# Destination weights per period, in station order S01..S05.
ATTRACT = [(1, 1, 1, 1, 1),
           (0.6, 2.0, 0.6, 1.8, 1),
           (1, 1, 1, 1, 1.2),
           (2.2, 0.6, 2.2, 1, 1),
           (1.3, 0.8, 1.3, 1, 1)]
WEEK1_START = datetime(2026, 10, 5, 6, 0)     # Monday 06:00 = t0
WEEK2_START = WEEK1_START + timedelta(days=7)
EVENT_DAY = WEEK1_START + timedelta(days=14)
SLOW_DRAIN = ("S03", 17, 28)                   # +1 rental per slot, 10:15-13:00
CROWD = ("S02", 49, 52, ("S04", "S05"))        # 4 extra riders per slot 18:15-19:00 to S02


def period(k):
    return 0 if k < 4 else 1 if k < 16 else 2 if k < 40 else 3 if k < 52 else 4


def poisson(rng, lam):
    """Knuth's method; fine for the small rates used here."""
    limit, k, p = math.exp(-lam), 0, 1.0
    while True:
        p *= rng.random()
        if p <= limit:
            return k
        k += 1


def run_day(rng, day0, start, policy=None, event=False):
    """Simulate one day. Returns (rows, van_log, totals). rows: one dict per station per reading."""
    ids = [s[0] for s in STATIONS]
    bikes = list(start)
    reserve = FLEET - sum(bikes)
    hist = [[] for _ in range(N)]
    rows, log = [], []
    lost = blocked = 0

    def record(k, van):
        ts = (day0 + timedelta(minutes=15 * k)).isoformat(timespec="minutes")
        for i in range(N):
            rows.append({"station_id": ids[i], "timestamp": ts, "bikes": reading[i],
                         "capacity": CAP, "van_moved": van[i]})

    reading = bikes[:]
    van = [0] * N
    for k in range(SLOTS):
        if k > 0:
            p = period(k)
            before = bikes[:]
            trips = []
            for i in range(N):
                d = poisson(rng, RATE[ROLE_ROWS[i]][p])
                if event and ids[i] == SLOW_DRAIN[0] and SLOW_DRAIN[1] <= k <= SLOW_DRAIN[2]:
                    d += 1
                trips += [(i, None)] * d
            if event and CROWD[1] <= k <= CROWD[2]:
                dest = ids.index(CROWD[0])
                trips += [(ids.index(rng.choice(CROWD[3])), dest) for _ in range(4)]
            rng.shuffle(trips)
            for i, dest in trips:
                if bikes[i] == 0:
                    lost += 1
                    continue
                if dest is None:
                    w = [0 if j == i else ATTRACT[p][j] for j in range(N)]
                    dest = rng.choices(range(N), weights=w)[0]
                if bikes[dest] >= CAP:
                    blocked += 1
                    room = [j for j in range(N) if j != dest and bikes[j] < CAP]
                    if not room:
                        continue
                    dest = min(room, key=lambda j: bikes[j])
                bikes[i] -= 1
                bikes[dest] += 1
            reading = bikes[:]
            if policy:
                for i in range(N):
                    x = (bikes[i] - before[i]) - policy["mu"][i][k]
                    hist[i].append(x)
        else:
            reading = bikes[:]
        van = [0] * N
        if policy and k > 0:
            E = policy["path"]
            need = []
            for i in range(N):
                sig = run_rules(hist[i], policy["imr"][i]["xbar"], policy["imr"][i]["sigma"])
                why = dispatch_trigger(sig, bikes[i])
                if not why:
                    continue
                move = van_move(E[i][k], bikes[i], CAP)
                drift = sig["side"] if sig else (-1 if bikes[i] < 10 else 1)
                if move == 0 or (move > 0) == (drift > 0):
                    continue    # already on the far side of its path from the drift: nothing to move
                need.append((abs(E[i][k] - bikes[i]), i, why, sig, move))
            if need:
                need.sort(key=lambda t: (-t[0], t[1]))
                _, i, why, sig, move = need[0]
                if move:
                    parts, todo = [], abs(move)
                    partner, best = None, 0
                    for j in range(N):
                        if j == i:
                            continue
                        spare = bikes[j] - E[j][k] if move > 0 else E[j][k] - bikes[j]
                        if spare >= 1 and spare > best:
                            partner, best = j, spare
                    p_amt = r_amt = 0
                    if partner is not None:
                        room = bikes[partner] if move > 0 else CAP - bikes[partner]
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
                        "timestamp": (day0 + timedelta(minutes=15 * k)).isoformat(timespec="minutes"),
                        "station_id": ids[i], "trigger": why,
                        "direction": "empty" if (sig and sig["side"] < 0) or (not sig and bikes[i] - signed < 10) else "full",
                        "bikes_before": bikes[i] - signed, "bikes_moved": signed, "bikes_after": bikes[i],
                        "from_station": ids[partner] if p_amt and signed > 0 else "",
                        "to_station": ids[partner] if p_amt and signed < 0 else "",
                        "station_bikes": p_amt, "reserve_bikes": r_amt,
                    })
        record(k, van)
        assert sum(bikes) + reserve == FLEET, "bikes were created or lost"
    return rows, log, {"lost": lost, "blocked": blocked}


def history(rows_by_day):
    """Slot means of rider net flow, I-MR limits of x, and the start plan, from no-van days."""
    ids = [s[0] for s in STATIONS]
    flows = []  # flows[day][i][k]
    for rows in rows_by_day:
        b = {(r["station_id"], int(r["timestamp"][11:13]) * 4 + int(r["timestamp"][14:16]) // 15 - 24): r
             for r in rows}
        f = [[0.0] + [(b[(sid, k)]["bikes"] - b[(sid, k - 1)]["bikes"] - b[(sid, k - 1)]["van_moved"])
                      for k in range(1, SLOTS)] for sid in ids]
        flows.append(f)
    days = len(flows)
    mu = [[sum(flows[d][i][k] for d in range(days)) / days for k in range(SLOTS)] for i in range(N)]
    imr = [imr_limits_days([[flows[d][i][k] - mu[i][k] for k in range(1, SLOTS)] for d in range(days)])
           for i in range(N)]
    C = [[sum(mu[i][1:k + 1]) for k in range(SLOTS)] for i in range(N)]
    plans = [start_plan(c) for c in C]
    return mu, imr, C, plans


def write(name, rows, fields):
    with open(OUT / name, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def build(seed=5300):
    rng = random.Random(seed)
    week1 = [run_day(rng, WEEK1_START + timedelta(days=d), [10] * N) for d in range(7)]
    mu, imr, C, plans = history([w[0] for w in week1])
    if not all(p["feasible"] for p in plans):
        raise RuntimeError("a station's normal swing is too wide for one start plan: retune RATE")
    starts = [p["start"] for p in plans]
    policy = {"mu": mu, "imr": imr, "path": [p["path"] for p in plans]}
    week2 = [run_day(rng, WEEK2_START + timedelta(days=d), starts, policy) for d in range(7)]
    event = run_day(rng, EVENT_DAY, starts, policy, event=True)
    return {"week1": week1, "week2": week2, "event": event, "mu": mu, "imr": imr, "plans": plans}


def main():
    sim = build()
    fields = ["station_id", "timestamp", "bikes", "capacity", "van_moved"]
    write("week1_baseline.csv", [r for d in sim["week1"] for r in d[0]], fields)
    write("week2_policy.csv", [r for d in sim["week2"] for r in d[0]], fields)
    write("event_day.csv", sim["event"][0], fields)
    log_fields = ["timestamp", "station_id", "trigger", "direction", "bikes_before", "bikes_moved",
                  "bikes_after", "from_station", "to_station", "station_bikes", "reserve_bikes"]
    write("van_log.csv", [r for d in sim["week2"] for r in d[1]] + sim["event"][1], log_fields)
    write("stations.csv", [{"station_id": s[0], "name": s[1], "lat": s[2], "lon": s[3], "capacity": CAP,
                            "role": s[4]} for s in STATIONS],
          ["station_id", "name", "lat", "lon", "capacity", "role"])
    oos = lambda days: sum(1 for d in days for r in d[0] if r["bikes"] < 4 or r["bikes"] > 16)
    print(f"starts {[p['start'] for p in sim['plans']]}  sigma {[round(l['sigma'], 2) for l in sim['imr']]}")
    print(f"out-of-spec readings: week 1 {oos(sim['week1'])}, week 2 {oos(sim['week2'])}")
    print(f"lost rentals: week 1 {sum(d[2]['lost'] for d in sim['week1'])}, week 2 {sum(d[2]['lost'] for d in sim['week2'])}")
    print(f"van stops per day in week 2: {[len(d[1]) for d in sim['week2']]}")
    print("event day van log:")
    for v in sim["event"][1]:
        print(f"  {v['timestamp'][11:]} {v['station_id']} {v['trigger']:<11} {v['bikes_moved']:+d}")


if __name__ == "__main__":
    main()
