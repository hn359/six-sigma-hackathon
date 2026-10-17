"""
Turns station readings into map frames (docs/map-contract.md). All statistics come from app/qc.py;
this file only organises readings by station and time and calls those functions.

Works for any network: the minutes between readings and the first and last reading of the day are
read from the data, and each station's spec limits come from its own number of docks
(qc.spec_limits: 20% and 80%). History (Phase I) comes from days without van moves: each station's
usual rider net flow per time slot, the I-MR limits of slot-adjusted net flow, the night plan and
the rush slots.
"""

import csv
import io
import math
from collections import Counter
from datetime import datetime

try:
    from app import qc
    from app.bikeflow.plan import overnight_shares
except ImportError:  # running from inside app/ (e.g. on Posit Connect)
    import qc
    from bikeflow.plan import overnight_shares

SEVERITY = {1: 3, 2: 2, 3: 1, 4: 1}     # rule -> map severity (3 = act now)
SPEC_SEVERITY = 2                        # out of spec with no rule firing
MIN_BASELINE_DAYS = 5                    # fewer and the slot means are too rough: warn


# ---- reading files ----------------------------------------------------------------

def _tod(ts):
    return ts.hour * 60 + ts.minute


def parse_readings(text):
    """CSV with station_id, timestamp, bikes, capacity[, van_moved] -> {date: {station: [row] * slots}}.

    The reading interval is the most common gap between a station's readings in a day; the day
    runs from the earliest to the latest reading time in the file. Every station needs a reading
    at every slot of every day it appears in.
    """
    reader = csv.DictReader(io.StringIO(text))
    need = {"station_id", "timestamp", "bikes", "capacity"}
    if not reader.fieldnames or not need <= set(reader.fieldnames):
        raise ValueError(f"readings CSV needs the columns {sorted(need)} (van_moved is optional)")
    rows = []
    for n, row in enumerate(reader, start=2):
        try:
            ts = datetime.fromisoformat(row["timestamp"].strip())
            bikes, cap = int(row["bikes"]), int(row["capacity"])
            van = int(row.get("van_moved") or 0)
        except (ValueError, TypeError, AttributeError):
            raise ValueError(f"line {n}: cannot read timestamp/bikes/capacity/van_moved")
        if not 0 <= bikes <= cap:
            raise ValueError(f"line {n}: bikes {bikes} is outside 0..{cap}")
        rows.append((ts, row["station_id"].strip(), bikes, cap, van))
    if not rows:
        raise ValueError("readings CSV has no rows")

    by_station_day = {}
    for ts, sid, *_ in rows:
        by_station_day.setdefault((ts.date(), sid), []).append(_tod(ts))
    gaps = Counter(b - a for tods in by_station_day.values() for a, b in zip(sorted(tods), sorted(tods)[1:]) if b > a)
    if not gaps:
        raise ValueError("need at least 2 readings of a station in a day to find the reading interval")
    interval = gaps.most_common(1)[0][0]
    first, last = min(_tod(r[0]) for r in rows), max(_tod(r[0]) for r in rows)
    slots = (last - first) // interval + 1

    days = {}
    for ts, sid, bikes, cap, van in rows:
        off = _tod(ts) - first
        if off % interval:
            raise ValueError(f"{ts.isoformat()} {sid}: not on the {interval}-minute reading grid from {first // 60:02d}:{first % 60:02d}")
        days.setdefault(ts.date(), {}).setdefault(sid, [None] * slots)[off // interval] = {
            "timestamp": ts, "bikes": bikes, "capacity": cap, "van_moved": van}
    for date, stations in days.items():
        for sid, rs in stations.items():
            missing = [i for i, r in enumerate(rs) if r is None]
            if missing:
                raise ValueError(f"{date} {sid}: {len(missing)} of {slots} readings missing (first at slot {missing[0]})")
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


def slots_of(day):
    return len(next(iter(day.values())))


def net_flows(day, sid):
    """Rider net flow into reading k: bikes_k - bikes_(k-1) - van_moved_(k-1); index 0 is None."""
    rows = day[sid]
    return [None] + [rows[k]["bikes"] - rows[k - 1]["bikes"] - rows[k - 1]["van_moved"] for k in range(1, len(rows))]


def split_baseline(days):
    """Phase I days for an uploaded file: days with no van moves, else the first half of the days."""
    dates = sorted(days)
    quiet = [d for d in dates if all(r["van_moved"] == 0 for rs in days[d].values() for r in rs)]
    base = quiet if len(quiet) >= 2 else dates[:max(1, len(dates) // 2)]
    if len(base) < 2:
        raise ValueError("need at least 2 days of readings to learn a station's usual day")
    return {d: days[d] for d in base}, {d: days[d] for d in dates if d not in base}


# ---- Phase I history ---------------------------------------------------------------

def learn(baseline_days, station_ids):
    """Learn slot flows, I-MR limits, and the 80/20 opening targets from baseline days."""
    days = [baseline_days[d] for d in sorted(baseline_days)]
    S = slots_of(days[0])
    hist = {}
    interval = int((days[0][station_ids[0]][1]["timestamp"]
                    - days[0][station_ids[0]][0]["timestamp"]).total_seconds() // 60)
    morning_end = min(S - 1, 240 // interval)
    morning_net = {}
    for sid in station_ids:
        morning_net[sid] = sum(sum(f[1:morning_end + 1]) for f in (net_flows(day, sid) for day in days)) / len(days)
    shares = overnight_shares(morning_net, 0.8, 0.2)
    for sid in station_ids:
        flows = [net_flows(day, sid) for day in days]
        mu = [0.0] + [sum(f[k] for f in flows) / len(flows) for k in range(1, S)]
        limits = qc.imr_limits_days([[f[k] - mu[k] for k in range(1, S)] for f in flows])
        C = [0.0]
        for k in range(1, S):
            C.append(C[-1] + mu[k])
        lsl, usl = qc.spec_limits(days[0][sid][0]["capacity"])
        old_plan = qc.start_plan(C, lsl, usl)
        hist[sid] = {"mu": mu, "imr": limits, "C": C, "lsl": lsl, "usl": usl,
                     "plan": old_plan,
                     "overnight_start": math.floor(shares[sid] * days[0][sid][0]["capacity"] + 0.5),
                     "overnight_share": shares[sid], "morning_net": morning_net[sid],
                     "baseline_days": len(days)}
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
    """One frame per reading for one day. policy=True: expected path = night plan; False = start as run.

    The fleet is taken to be as many bikes as docks; the reserve is the fleet minus docked bikes."""
    ids = [sid for sid in sorted(day) if sid in stations]
    unknown = sorted(set(day) - set(stations))
    if unknown:
        raise ValueError(f"readings name stations not in the stations file: {unknown}")
    path = {}
    for sid in ids:
        h = hist[sid]
        start = h["overnight_start"] if policy else day[sid][0]["bikes"]
        path[sid] = [start + c for c in h["C"]]
    flows = {sid: net_flows(day, sid) for sid in ids}
    run = {sid: [] for sid in ids}
    reserve = sum(day[sid][0]["capacity"] for sid in ids) - sum(day[sid][0]["bikes"] for sid in ids)
    frames = []
    for k in range(slots_of(day)):
        out = []
        for sid in ids:
            r, h, st = day[sid][k], hist[sid], stations[sid]
            cap, lsl, usl = r["capacity"], h["lsl"], h["usl"]
            x = sig = None
            if k > 0:
                x = flows[sid][k] - h["mu"][k]
                run[sid].append(x)
                if h["imr"]["sigma"] > 0:
                    sig = qc.run_rules(run[sid], h["imr"]["xbar"], h["imr"]["sigma"])
            trigger = qc.dispatch_trigger(sig, r["bikes"], lsl, usl) if k > 0 else None
            expected = min(cap, max(0, path[sid][k]))
            if sig:
                severity, direction = SEVERITY[sig["rule"]], "empty" if sig["side"] < 0 else "full"
            elif trigger:
                severity, direction = SPEC_SEVERITY, "empty" if r["bikes"] < lsl else "full"
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
                "lsl": lsl, "usl": usl,
                "expected_bikes": round(expected, 2), "target_occupancy": round(expected / cap, 4),
                "gap": round((r["bikes"] - expected) / cap, 4),
                "direction": direction, "severity": severity, "trigger": trigger,
                "rule": sig["name"] if sig else (f"outside {lsl}-{usl} bikes" if trigger else None),
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
                  "ucl": h["imr"]["ucl"], "lcl": h["imr"]["lcl"], "lsl": h["lsl"], "usl": h["usl"]}
            for sid, h in hist.items()}


def out_of_spec_counts(day, sid, lsl, usl):
    return sum(1 for r in day[sid] if qc.out_of_spec(r["bikes"], lsl, usl))


def summary(baseline, policy_days, stations, hist):
    """Night plan, rush slots and the weekly p-charts (baseline limits, policy days judged)."""
    ids = sorted(stations)
    b_days = [baseline[d] for d in sorted(baseline)]
    p_days = [policy_days[d] for d in sorted(policy_days)]
    S = slots_of(b_days[0])
    plan = [{"station_id": sid, "name": stations[sid]["name"], "capacity": stations[sid]["capacity"],
             "lsl": hist[sid]["lsl"], "usl": hist[sid]["usl"],
             "swing": round(max(hist[sid]["C"]) - min(hist[sid]["C"]), 2),
             "lo": round(hist[sid]["plan"]["lo"], 2), "hi": round(hist[sid]["plan"]["hi"], 2),
             "start": hist[sid]["overnight_start"],
             "target_share": round(hist[sid]["overnight_share"], 4),
             "morning_net": round(hist[sid]["morning_net"], 2),
             "feasible": hist[sid]["plan"]["feasible"],
             "sigma": round(hist[sid]["imr"]["sigma"], 3)} for sid in ids]
    pcharts = []
    for sid in ids:
        lsl, usl = hist[sid]["lsl"], hist[sid]["usl"]
        res = qc.p_chart_phase([out_of_spec_counts(d, sid, lsl, usl) for d in b_days],
                               [out_of_spec_counts(d, sid, lsl, usl) for d in p_days], S)
        pcharts.append({"station_id": sid, "n": S, **res,
                        "phase1_dates": [str(d) for d in sorted(baseline)],
                        "phase2_dates": [str(d) for d in sorted(policy_days)]})
    # Rentals are not in the readings, so rush slots use the mean total |net flow| per slot.
    act = [0.0] * S
    for day in b_days:
        for sid in ids:
            f = net_flows(day, sid)
            for k in range(1, S):
                act[k] += abs(f[k]) / len(b_days)
    rush = [k + 1 for k in qc.rush_slots(act[1:])]
    oos = lambda days: sum(out_of_spec_counts(d, sid, hist[sid]["lsl"], hist[sid]["usl"]) for d in days for sid in ids)
    warnings = []
    if len(b_days) < MIN_BASELINE_DAYS:
        warnings.append(f"only {len(b_days)} baseline days: each slot's usual flow is an average of "
                        f"{len(b_days)} values, so limits and the plan are rough")
    return {"plan": plan, "rush_slots": rush, "rush_times": [b_days[0][ids[0]][k]["timestamp"].strftime("%H:%M") for k in rush],
            "pcharts": pcharts, "warnings": warnings,
            "kpis": {"out_of_spec_week1": oos(b_days), "out_of_spec_week2": oos(p_days),
                     "readings_per_day": S * len(ids), "baseline_days": len(b_days), "policy_days": len(p_days)}}


def clean(o):
    """JSON-safe: NaN and infinity become None."""
    if isinstance(o, float) and (math.isnan(o) or math.isinf(o)):
        return None
    if isinstance(o, dict):
        return {k: clean(v) for k, v in o.items()}
    if isinstance(o, list):
        return [clean(v) for v in o]
    return o
