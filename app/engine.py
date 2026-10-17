"""
Turns station readings into map frames (docs/map-contract.md). All statistics come from app/qc.py;
this file only organises readings by station and time and calls those functions.

History (Phase I) comes from the no-van baseline week: each station's usual rider net flow per
15-minute slot, the I-MR limits of slot-adjusted net flow, the night plan and the rush slots.
"""

import csv
import io
import math
from datetime import datetime

try:
    from app import qc
except ImportError:  # running from inside app/ (e.g. on Posit Connect)
    import qc

SLOTS = 64            # readings per day, 06:00-21:45
DAY_START_HOUR = 6
SEVERITY = {1: 3, 2: 2, 3: 1, 4: 1}     # rule -> map severity (3 = act now)
SPEC_SEVERITY = 2                        # out of spec with no rule firing


def slot_of(ts):
    k = (ts.hour - DAY_START_HOUR) * 4 + ts.minute // 15
    return k if 0 <= k < SLOTS else None


# ---- reading files ----------------------------------------------------------------

def parse_readings(text):
    """CSV with station_id, timestamp, bikes, capacity[, van_moved] -> {date: {station: [row]*64}}."""
    reader = csv.DictReader(io.StringIO(text))
    need = {"station_id", "timestamp", "bikes", "capacity"}
    if not reader.fieldnames or not need <= set(reader.fieldnames):
        raise ValueError(f"readings CSV needs the columns {sorted(need)} (van_moved is optional)")
    days = {}
    for n, row in enumerate(reader, start=2):
        try:
            ts = datetime.fromisoformat(row["timestamp"].strip())
            bikes, cap = int(row["bikes"]), int(row["capacity"])
            van = int(row.get("van_moved") or 0)
        except (ValueError, TypeError, AttributeError):
            raise ValueError(f"line {n}: cannot read timestamp/bikes/capacity/van_moved")
        k = slot_of(ts)
        if k is None:
            continue
        if not 0 <= bikes <= cap:
            raise ValueError(f"line {n}: bikes {bikes} is outside 0..{cap}")
        day = days.setdefault(ts.date(), {})
        day.setdefault(row["station_id"].strip(), [None] * SLOTS)[k] = {
            "timestamp": ts, "bikes": bikes, "capacity": cap, "van_moved": van}
    for date, stations in days.items():
        for sid, rows in stations.items():
            missing = [i for i, r in enumerate(rows) if r is None]
            if missing:
                raise ValueError(f"{date} {sid}: {len(missing)} of {SLOTS} readings missing (first at slot {missing[0]})")
    return days


def parse_stations(text):
    reader = csv.DictReader(io.StringIO(text))
    need = {"station_id", "name", "lat", "lon", "capacity"}
    if not reader.fieldnames or not need <= set(reader.fieldnames):
        raise ValueError(f"stations CSV needs the columns {sorted(need)}")
    out = {}
    for r in reader:
        out[r["station_id"].strip()] = {"name": r["name"], "lat": float(r["lat"]), "lon": float(r["lon"]),
                                        "capacity": int(r["capacity"]), "role": r.get("role", "")}
    return out


def net_flows(day, sid):
    """Rider net flow into reading k: bikes_k - bikes_(k-1) - van_moved_(k-1); index 0 is None."""
    rows = day[sid]
    return [None] + [rows[k]["bikes"] - rows[k - 1]["bikes"] - rows[k - 1]["van_moved"] for k in range(1, SLOTS)]


# ---- Phase I history ---------------------------------------------------------------

def learn(baseline_days, station_ids, rentals=None):
    """Slot means (mu), I-MR limits of x, cumulative usual flow C and the start plan, per station."""
    days = [baseline_days[d] for d in sorted(baseline_days)]
    hist = {}
    for sid in station_ids:
        flows = [net_flows(day, sid) for day in days]
        mu = [0.0] + [sum(f[k] for f in flows) / len(flows) for k in range(1, SLOTS)]
        limits = qc.imr_limits_days([[f[k] - mu[k] for k in range(1, SLOTS)] for f in flows])
        C = [0.0]
        for k in range(1, SLOTS):
            C.append(C[-1] + mu[k])
        hist[sid] = {"mu": mu, "imr": limits, "C": C, "plan": qc.start_plan(C)}
    return hist


# ---- frames --------------------------------------------------------------------------

def _van_trip(day, k, station_ids, triggered=()):
    """What the van did right after reading k, read from van_moved (works for any upload).

    The target is a moved station that had a trigger; failing that, the largest move."""
    moved = {sid: day[sid][k]["van_moved"] for sid in station_ids if day[sid][k]["van_moved"]}
    if not moved:
        return None
    hits = [s for s in moved if s in triggered]
    target = max(hits or moved, key=lambda s: (abs(moved[s]), s))
    m = moved[target]
    partners = [s for s in moved if s != target and (moved[s] > 0) != (m > 0)]
    p_amt = sum(abs(moved[s]) for s in partners)
    return {"station_id": target, "bikes_moved": m, "partner": partners[0] if partners else None,
            "partner_bikes": p_amt, "reserve_bikes": abs(m) - p_amt}


def day_frames(day, stations, hist, policy):
    """One frame per reading for one day. policy=True: expected path = night plan; False = start as run."""
    ids = [sid for sid in sorted(day) if sid in stations]
    unknown = sorted(set(day) - set(stations))
    if unknown:
        raise ValueError(f"readings name stations not in the stations file: {unknown}")
    path = {}
    for sid in ids:
        h = hist[sid]
        start = h["plan"]["start"] if policy and h["plan"]["feasible"] else day[sid][0]["bikes"]
        path[sid] = [start + c for c in h["C"]]
    flows = {sid: net_flows(day, sid) for sid in ids}
    run = {sid: [] for sid in ids}
    fleet_docked0 = sum(day[sid][0]["bikes"] for sid in ids)
    reserve = 100 - fleet_docked0
    frames = []
    for k in range(SLOTS):
        out = []
        for sid in ids:
            r, h, st = day[sid][k], hist[sid], stations[sid]
            cap = r["capacity"]
            x = sig = None
            if k > 0:
                x = flows[sid][k] - h["mu"][k]
                run[sid].append(x)
                if h["imr"]["sigma"] > 0:
                    sig = qc.run_rules(run[sid], h["imr"]["xbar"], h["imr"]["sigma"])
            trigger = qc.dispatch_trigger(sig, r["bikes"]) if k > 0 else None
            expected = min(cap, max(0, path[sid][k]))
            if sig:
                severity, direction = SEVERITY[sig["rule"]], "empty" if sig["side"] < 0 else "full"
            elif trigger:
                severity, direction = SPEC_SEVERITY, "empty" if r["bikes"] < qc.LSL else "full"
            else:
                severity, direction = 0, "ok"
            move = None
            if trigger:
                move = qc.van_move(expected, r["bikes"], cap)
                if (direction == "empty" and move < 0) or (direction == "full" and move > 0):
                    move = 0   # on or past its path already: nothing to move against the drift
            out.append({
                "station_id": sid, "name": st["name"], "lat": st["lat"], "lon": st["lon"],
                "capacity": cap, "bikes": r["bikes"], "occupancy": round(r["bikes"] / cap, 4),
                "expected_bikes": round(expected, 2), "target_occupancy": round(expected / cap, 4),
                "gap": round((r["bikes"] - expected) / cap, 4),
                "direction": direction, "severity": severity, "trigger": trigger,
                "rule": sig["name"] if sig else ("outside 4-16 bikes" if trigger else None),
                "bikes_to_move": move,
                "x": None if x is None else round(x, 3),
                "van_moved": r["van_moved"],
                "bikes_after_van": r["bikes"] + r["van_moved"],
                "availability": None, "chronic_flag": False,
            })
        for sid in ids:
            if day[sid][k]["van_moved"]:
                run[sid] = []          # after a visit the run-rule history restarts
        trip = _van_trip(day, k, ids, {s["station_id"] for s in out if s["bikes_to_move"]})
        if trip:
            reserve -= trip["reserve_bikes"] if trip["bikes_moved"] > 0 else -trip["reserve_bikes"]
        frames.append({"as_of": day[ids[0]][k]["timestamp"].isoformat(timespec="minutes"), "slot": k,
                       "reserve": reserve, "van": trip, "stations": out})
    return frames


def chart_meta(hist):
    return {sid: {"xbar": h["imr"]["xbar"], "sigma": h["imr"]["sigma"], "mrbar": h["imr"]["mrbar"],
                  "ucl": h["imr"]["ucl"], "lcl": h["imr"]["lcl"]} for sid, h in hist.items()}


def out_of_spec_counts(day, sid):
    return sum(1 for r in day[sid] if qc.out_of_spec(r["bikes"]))


def summary(baseline, policy_days, stations, hist, rentals_by_slot=None):
    """Night plan, rush slots and the weekly p-charts (week 1 limits, week 2 judged)."""
    ids = sorted(stations)
    plan = [{"station_id": sid, "name": stations[sid]["name"], "swing": round(max(hist[sid]["C"]) - min(hist[sid]["C"]), 2),
             "lo": round(hist[sid]["plan"]["lo"], 2), "hi": round(hist[sid]["plan"]["hi"], 2),
             "start": hist[sid]["plan"]["start"], "feasible": hist[sid]["plan"]["feasible"],
             "sigma": round(hist[sid]["imr"]["sigma"], 3)} for sid in ids]
    b_days = [baseline[d] for d in sorted(baseline)]
    p_days = [policy_days[d] for d in sorted(policy_days)]
    pcharts = []
    for sid in ids:
        res = qc.p_chart_phase([out_of_spec_counts(d, sid) for d in b_days],
                               [out_of_spec_counts(d, sid) for d in p_days], SLOTS)
        pcharts.append({"station_id": sid, **res,
                        "phase1_dates": [str(d) for d in sorted(baseline)],
                        "phase2_dates": [str(d) for d in sorted(policy_days)]})
    # rentals are not in the readings, so rush slots use the total |net flow| per slot as the
    # measure of activity unless rentals are given.
    if rentals_by_slot is None:
        act = [0.0] * SLOTS
        for day in b_days:
            for sid in ids:
                f = net_flows(day, sid)
                for k in range(1, SLOTS):
                    act[k] += abs(f[k]) / len(b_days)
        rentals_by_slot = act[1:]
        offset = 1
    else:
        offset = 0
    rush = [k + offset for k in qc.rush_slots(rentals_by_slot)]
    oos = lambda days: sum(out_of_spec_counts(d, sid) for d in days for sid in ids)
    return {"plan": plan, "rush_slots": rush, "pcharts": pcharts,
            "kpis": {"out_of_spec_week1": oos(b_days), "out_of_spec_week2": oos(p_days),
                     "readings_per_week": SLOTS * len(ids) * 7}}


def clean(o):
    """JSON-safe: NaN and infinity become None."""
    if isinstance(o, float) and (math.isnan(o) or math.isinf(o)):
        return None
    if isinstance(o, dict):
        return {k: clean(v) for k, v in o.items()}
    if isinstance(o, list):
        return [clean(v) for v in o]
    return o
