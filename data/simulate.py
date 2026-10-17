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
no van. Week one estimates the 06:00-to-10:00 net flow and sets the initial 80/20 policy week.
Later weeks and the event day use the plan learned from the latest complete week. After every
reading, the run rules check slot-adjusted net flow, and the van responds to a signal or an
out-of-spec station. Each weekly learning update changes any station by at most one bike.
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
    dispatch_trigger, imr_limits_days, p_chart_phase, run_rules, spec_limits, start_plan, van_move,
)
from app.bikeflow.plan import overnight_shares  # noqa: E402

OUT = ROOT / "data"
MAX_POLICY_WEEKS = 20
STABLE_WEEKS_REQUIRED = 2
MAX_WEEKLY_SHIFT_PER_STATION = 1

# Each station: id, name, lat, lon (approximate), docks, role, rates per period, attract per period.
# Periods are set by the reading's time of day: period n covers times before bounds[n] (hours).
DATASETS = {
    "collegetown": {
        "name": "Collegetown, Ithaca: student commute",
        "seed": 5300, "interval": 15, "start": "06:00", "end": "21:45", "first_day": date(2026, 10, 5),
        "bounds": (7, 10, 16, 19, 24),       # early, AM rush, midday, PM rush, evening
        "stations": [
            ("S01", "Cascadilla Hall (dorms)", 42.4454, -76.4897, 20, "residential",
             (0.12, 0.70, 0.15, 0.40, 0.15), (1, 0.6, 1, 2.2, 1.3)),
            ("S02", "Schwartz Center (campus gate)", 42.4454, -76.4809, 20, "campus",
             (0.08, 0.30, 0.18, 0.80, 0.15), (1, 2.0, 1, 0.6, 0.8)),
            ("S03", "Dryden Rd (apartments)", 42.4396, -76.4801, 20, "residential",
             (0.12, 0.65, 0.15, 0.40, 0.15), (1, 0.6, 1, 2.2, 1.3)),
            ("S04", "College Ave (bus stop)", 42.4418, -76.4853, 20, "transit hub",
             (0.12, 0.55, 0.18, 0.70, 0.15), (1, 1.8, 1, 1, 1)),
            ("S05", "Eddy St (shops)", 42.4384, -76.4897, 20, "shopping",
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


def overnight_start(city, rows_by_day):
    """Week-two opening inventory from week one's average opening-to-rush net flow.

    Shares use BikeFlow's same 80/20 rule: the greatest average morning net loss starts at 80% of
    capacity, the greatest net gain at 20%, and stations between them are scaled proportionally.
    """
    if not rows_by_day:
        raise ValueError("week one must contain at least one day")
    end_slot = 240 // city.interval
    net = {}
    for i, sid in enumerate(city.ids):
        daily = []
        for rows in rows_by_day:
            station = [r for r in rows if r["station_id"] == sid]
            daily.append(sum(station[k]["bikes"] - station[k - 1]["bikes"] - station[k - 1]["van_moved"]
                             for k in range(1, end_slot + 1)))
        net[sid] = sum(daily) / len(daily)
    shares = overnight_shares(net, 0.8, 0.2)
    starts = [math.floor(shares[sid] * city.cap[i] + 0.5) for i, sid in enumerate(city.ids)]
    return starts, net, shares


def _rider_paths(city, days):
    """Cumulative rider-only flow for each station/day, with van moves removed."""
    paths = []
    for rows, _, _ in days:
        by_station = {sid: [] for sid in city.ids}
        for row in rows:
            by_station[row["station_id"]].append(row)
        daily = {}
        for sid in city.ids:
            points = by_station[sid]
            cumulative, path = 0, [0]
            for k in range(1, len(points)):
                cumulative += points[k]["bikes"] - points[k - 1]["bikes"] - points[k - 1]["van_moved"]
                path.append(cumulative)
            daily[sid] = path
        paths.append(daily)
    return paths


def adaptive_start(city, previous_days, preferred):
    """Choose a conserved, in-spec opening allocation that minimizes prior-week projected OOS.

    The previous week's seven rider-flow paths are replayed from each candidate integer start.
    Ties prefer the ordinary 80/20 morning-flow recommendation; the total docked bikes is held
    at the previous week's opening total. Each station can change by at most one bike per week,
    which keeps the plan from chasing random week-to-week noise.
    """
    if len(previous_days) != 7:
        raise ValueError("weekly learning needs exactly seven complete previous-week days")
    # Keep the number of docked bikes fixed while changing their station allocation.
    # Using the preceding week's actual opening total also avoids rounding drift from
    # recomputing and rounding the 80/20 preference independently at every station.
    target_total = sum(previous_days[0][0][i]["bikes"] for i in range(city.n))
    previous_starts = [previous_days[0][0][i]["bikes"] for i in range(city.n)]
    paths = _rider_paths(city, previous_days)
    candidate_counts = []
    for i, sid in enumerate(city.ids):
        low, high = city.lim[i]
        cost = {}
        for start in range(max(low, previous_starts[i] - MAX_WEEKLY_SHIFT_PER_STATION),
                           min(high, previous_starts[i] + MAX_WEEKLY_SHIFT_PER_STATION) + 1):
            outside = sum(1 for day_path in paths
                          for bikes in (min(city.cap[i], max(0, start + x)) for x in day_path[sid])
                          if bikes < low or bikes > high)
            cost[start] = (outside, abs(start - preferred[i]))
        candidate_counts.append(cost)

    # Dynamic program over stations and the fixed fleet total. Each score is ordered by projected
    # out-of-spec readings first, then distance from the prior week's 80/20 recommendation.
    states = {0: ((0, 0), [])}
    for cost in candidate_counts:
        nxt = {}
        for total, (score, chosen) in states.items():
            for bikes, local in cost.items():
                new_total = total + bikes
                if new_total > target_total:
                    continue
                new_score = (score[0] + local[0], score[1] + local[1])
                current = nxt.get(new_total)
                if current is None or new_score < current[0]:
                    nxt[new_total] = (new_score, chosen + [bikes])
        states = nxt
    if target_total not in states:
        raise ValueError(f"cannot place {target_total} bikes within all station spec bands")
    score, starts = states[target_total]
    return starts, {"projected_out_of_spec": score[0],
                    "preferred_distance": score[1], "docked_bikes": target_total,
                    "max_change_per_station": MAX_WEEKLY_SHIFT_PER_STATION}


def weekly_quality(city, days):
    """Daily network p values for readings outside the 20%-80% dock specification."""
    n = city.n * city.slots
    counts = []
    for rows, _, _ in days:
        bad = 0
        for row in rows:
            i = city.ids.index(row["station_id"])
            low, high = city.lim[i]
            bad += int(row["bikes"] < low or row["bikes"] > high)
        counts.append(bad)
    return {"daily_defects": counts, "readings_per_day": n,
            "defects": sum(counts), "readings": n * len(counts),
            "rate": sum(counts) / (n * len(counts)) if counts else 0.0}


def compare_weeks(city, weeks):
    """Attach previous-week p-chart limits and a plain stability state to each complete week."""
    results = []
    stable_run = 0
    for number, days in enumerate(weeks, start=1):
        current = weekly_quality(city, days)
        if number == 1:
            row = {"week": number, **current, "status": "baseline", "baseline_week": None,
                   "center": current["rate"], "lcl": None, "ucl": None, "signals": 0}
        else:
            prior = results[-1]
            chart = p_chart_phase(prior["daily_defects"], current["daily_defects"], current["readings_per_day"])
            statuses = [point["status"] for point in chart["phase2"]]
            signal_count = sum(status in ("worse", "improved") for status in statuses)
            # One plotted point represents all readings in this complete week. Use
            # that weekly sample size for its p-chart limits, then classify the same
            # point against those limits. The per-day statuses remain diagnostic.
            weekly_sigma = math.sqrt(prior["rate"] * (1 - prior["rate"]) / current["readings"])
            weekly_lcl = max(0.0, prior["rate"] - 3 * weekly_sigma)
            weekly_ucl = min(1.0, prior["rate"] + 3 * weekly_sigma)
            if current["rate"] > weekly_ucl:
                state = "worse"
            elif current["rate"] < weekly_lcl:
                state = "improved"
            else:
                state = "stable"
            stable_run = stable_run + 1 if state == "stable" else 0
            row = {"week": number, **current, "status": state, "baseline_week": number - 1,
                   "center": prior["rate"], "lcl": weekly_lcl, "ucl": weekly_ucl,
                   "daily_lcl": chart["lcl"], "daily_ucl": chart["ucl"],
                   "sigma": chart["sigma"], "signals": signal_count,
                   "daily_status": statuses}
        row["stable_run"] = stable_run
        results.append(row)
    return results


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
    starts, morning_net, shares = overnight_start(city, [w[0] for w in week1])
    policy = {"mu": mu, "imr": imr,
              "path": [[starts[i] + c for c in C[i]] for i in range(city.n)]}
    week2 = [run_day(city, rng, day(7 + d), starts, policy, trips_out=trips) for d in range(7)]
    weeks = [week1, week2]
    adaptive_plans = {"week2": {"source_week": 1, "targets": dict(zip(city.ids, starts)),
                                 "method": "80/20 morning-flow rule"}}
    for week_number in range(3, MAX_POLICY_WEEKS + 1):
        previous = weeks[-1]
        prev_rows = [d[0] for d in previous]
        pref, prev_morning_net, prev_shares = overnight_start(city, prev_rows)
        learned_starts, score = adaptive_start(city, previous, pref)
        mu, imr, C, _ = history(city, prev_rows)
        policy = {"mu": mu, "imr": imr,
                  "path": [[learned_starts[i] + c for c in C[i]] for i in range(city.n)]}
        current = [run_day(city, rng, day((week_number - 1) * 7 + d), learned_starts,
                           policy, trips_out=trips) for d in range(7)]
        weeks.append(current)
        adaptive_plans[f"week{week_number}"] = {
            "source_week": week_number - 1, "targets": dict(zip(city.ids, learned_starts)),
            "preferred_targets": dict(zip(city.ids, pref)),
            "morning_net": prev_morning_net, "target_shares": prev_shares,
            "optimization": score, "method": "previous-week projected availability"}
        quality = compare_weeks(city, weeks)[-1]
        # Stop only after two consecutive complete weeks show no p-chart special cause.
        if quality["stable_run"] >= STABLE_WEEKS_REQUIRED:
            break
    next_number = len(weeks) + 1
    final_rows = [d[0] for d in weeks[-1]]
    preferred, final_morning_net, final_shares = overnight_start(city, final_rows)
    next_starts, next_score = adaptive_start(city, weeks[-1], preferred)
    adaptive_plans[f"week{next_number}"] = {
        "source_week": next_number - 1, "targets": dict(zip(city.ids, next_starts)),
        "preferred_targets": dict(zip(city.ids, preferred)),
        "morning_net": final_morning_net, "target_shares": final_shares,
        "optimization": next_score, "method": "previous-week projected availability"}
    event_offset = len(weeks) * 7
    latest_rows = [d[0] for d in weeks[-1]]
    # The event is the next operating day after the final learning week, so use the
    # plan learned from that final complete week (the plan for the next policy week).
    event_starts = adaptive_plans[f"week{next_number}"]["targets"]
    event_start_list = [event_starts[sid] for sid in city.ids]
    mu, imr, C, _ = history(city, latest_rows)
    event_policy = {"mu": mu, "imr": imr,
                    "path": [[event_start_list[i] + c for c in C[i]] for i in range(city.n)]}
    event = run_day(city, rng, day(event_offset), event_start_list, event_policy,
                    event=True, trips_out=trips)
    return {"city": city, "week1": week1, "week2": week2, "weeks": weeks, "event": event,
            "mu": mu, "imr": imr, "C": C, "plans": plans, "starts": starts,
            "morning_net": morning_net, "shares": shares, "adaptive_plans": adaptive_plans,
            "weekly_quality": compare_weeks(city, weeks), "trips": trips}


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
        for name, days in [("week1_baseline.csv", sim["week1"]), ("week2_policy.csv", sim["week2"])]:
            expected = "station_id,timestamp,bikes,capacity,van_moved\n" + "".join(
                f"{r['station_id']},{r['timestamp']},{r['bikes']},{r['capacity']},{r['van_moved']}\n"
                for d in days for r in d[0])
            path = folder / name
            if path.exists() and path.read_text(encoding="utf-8") != expected:
                raise RuntimeError(f"refusing to change the frozen {path.relative_to(ROOT)}")
            if not path.exists():
                write(folder, name, [r for d in days for r in d[0]], fields)
        for number, days in enumerate(sim["weeks"][2:], start=3):
            write(folder, f"week{number}_policy.csv", [r for d in days for r in d[0]], fields)
        write(folder, "event_day.csv", sim["event"][0], fields)
        for old in folder.glob("week*_policy.csv"):
            try:
                number = int(old.name[4:old.name.index("_")])
            except ValueError:
                continue
            if number > len(sim["weeks"]):
                old.unlink()
        log_fields = ["timestamp", "station_id", "trigger", "direction", "bikes_before", "bikes_moved",
                      "bikes_after", "from_station", "to_station", "station_bikes", "reserve_bikes"]
        write(folder, "van_log.csv", [r for week in sim["weeks"][1:] for d in week for r in d[1]] + sim["event"][1], log_fields)
        # every completed rider trip, stamped with the reading that ends its interval
        write(folder, "trips.csv", sim["trips"], ["timestamp", "from_station", "to_station"])
        (folder / "adaptive_plans.json").write_text(json.dumps({
            "weeks": sim["weekly_quality"], "plans": sim["adaptive_plans"],
            "stability_rule": f"two consecutive complete weekly points inside the preceding week's 3-sigma p-chart limits (maximum {MAX_POLICY_WEEKS} weeks)",
            "next_week_plan": f"week{len(sim['weeks']) + 1}"
        }, indent=2) + "\n", encoding="utf-8")
        write(folder, "stations.csv",
              [{"station_id": s[0], "name": s[1], "lat": s[2], "lon": s[3], "capacity": s[4], "role": s[5]}
               for s in city.st], ["station_id", "name", "lat", "lon", "capacity", "role"])
        first_stamp = sim["weeks"][0][0][0][0]["timestamp"]
        last_stamp = sim["event"][0][-1]["timestamp"]
        about = {"id": key, "name": city.cfg["name"], "interval_minutes": city.interval,
                 "first_reading": first_stamp[11:], "last_reading": last_stamp[11:],
                 "project_start": first_stamp[:10], "project_weeks": len(sim["weeks"]),
                 "stable_week": next((w["week"] for w in sim["weekly_quality"] if w["stable_run"] >= STABLE_WEEKS_REQUIRED), None),
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
        print(f"   week 2 starts {sim['starts']} (80/20 morning plan); sigma {[round(l['sigma'], 2) for l in sim['imr']]}")
        print(f"   out-of-spec readings: baseline {out_of_spec(sim, sim['week1'])}, policy {out_of_spec(sim, sim['week2'])}")
        print("   weekly outside-spec rates: " + ", ".join(f"W{w['week']} {w['rate']:.1%} ({w['status']})"
                                                             for w in sim["weekly_quality"]))
        print(f"   stable week: {about['stable_week'] or 'not reached'}; event day: {last_stamp[:10]}")
        print(f"   lost rentals: baseline {sum(d[2]['lost'] for d in sim['week1'])}, policy {sum(d[2]['lost'] for d in sim['week2'])}")
        print(f"   van stops per day (policy): {[len(d[1]) for d in sim['week2']]}")
        print("   event day: " + "; ".join(f"{v['timestamp'][11:]} {v['station_id']} {v['trigger']} {v['bikes_moved']:+d}"
                                          for v in sim["event"][1]))


if __name__ == "__main__":
    main(sys.argv[1:] or None)
