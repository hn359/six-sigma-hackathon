"""
Bikeshare station quality control: the statistics, and nothing else.

No web framework here. app.py only calls these functions and shows the result.

Definitions (SPEC.md section 4):
- A reading is UNUSABLE when bikes_available == 0 (empty: nothing to rent) or
  docks_available == 0 (full: nowhere to return a bike).
- p-chart, one point (subgroup) per station:
    p_i = d_i / n_i,  pbar = sum(d) / sum(n),
    UCL_i = pbar + 3 * sqrt(pbar * (1 - pbar) / n_i),
    LCL_i = max(0, pbar - 3 * sqrt(pbar * (1 - pbar) / n_i)).
  A station with p_i > UCL_i is flagged: "send a van".
- Availability, per station: an outage episode is a run of back-to-back unusable
  readings inside one rush window. With t = reading length (minutes):
    downtime = unusable readings * t,  uptime = usable readings * t,
    MTTR = downtime / episodes,  MTBF = uptime / episodes,
    A = uptime / (uptime + downtime).
"""

import csv
import io
import math
from datetime import datetime
from statistics import median

# Weekday rush windows as [start hour, end hour): 07:00-09:59 and 16:00-18:59.
DEFAULT_WINDOWS = ((7, 10), (16, 19))


def p_chart(d, n, labels=None):
    """p-chart with variable subgroup size.

    d: unusable readings per station; n: rush-hour readings per station.
    Returns pbar, one row per station (p, ucl, lcl, flag) and warnings.
    """
    d, n = list(d), list(n)
    if len(d) != len(n):
        raise ValueError("d and n must have the same length")
    if len(n) < 2:
        raise ValueError("a p-chart needs at least 2 stations")
    if any(ni <= 0 for ni in n):
        raise ValueError("every station needs at least one reading (n_i > 0)")
    if any(di < 0 or di > ni for di, ni in zip(d, n)):
        raise ValueError("each d_i must be between 0 and n_i")
    labels = list(labels) if labels is not None else [str(i + 1) for i in range(len(n))]

    pbar = sum(d) / sum(n)
    warnings = []
    if pbar in (0.0, 1.0):
        what = "usable" if pbar == 0 else "unusable"
        warnings.append(f"every reading is {what}; there is no variation, "
                        "so the limits equal the centre line and nothing is flagged")
    rows = []
    for label, di, ni in zip(labels, d, n):
        sigma = math.sqrt(pbar * (1 - pbar) / ni)
        ucl = pbar + 3 * sigma
        lcl = max(0.0, pbar - 3 * sigma)
        p = di / ni
        if 0 < pbar < 1 and (ni * pbar < 5 or ni * (1 - pbar) < 5):
            warnings.append(
                f"station {label}: n*pbar = {ni * pbar:.1f} and n*(1-pbar) = "
                f"{ni * (1 - pbar):.1f}; below 5 the limits are rough"
            )
        rows.append({
            "station": label, "d": di, "n": ni, "p": p,
            "ucl": ucl, "lcl": lcl, "flag": p > ucl,
        })
    return {"pbar": pbar, "stations": rows, "warnings": warnings}


def availability(windows, t):
    """Availability, MTTR and MTBF for one station.

    windows: a list of rush windows, each a list of booleans in time order
             (True = unusable). An outage never continues across windows.
    t: minutes one reading stands for.
    """
    if t <= 0:
        raise ValueError("reading length t must be positive")
    readings = [x for w in windows for x in w]
    if not readings:
        raise ValueError("no readings")
    down_n = sum(1 for x in readings if x)
    up_n = len(readings) - down_n
    episodes = 0
    for w in windows:
        prev = False
        for x in w:
            if x and not prev:
                episodes += 1
            prev = x
    downtime, uptime = down_n * t, up_n * t
    if episodes == 0:
        return {"availability": 1.0, "mttr": None, "mtbf": None, "episodes": 0,
                "downtime": 0.0, "uptime": uptime, "note": "no outages"}
    return {
        "availability": uptime / (uptime + downtime),
        "mttr": downtime / episodes,
        "mtbf": uptime / episodes,
        "episodes": episodes,
        "downtime": downtime,
        "uptime": uptime,
        "note": "",
    }


def _in_window(ts, windows):
    for i, (start, end) in enumerate(windows):
        if start <= ts.hour < end:
            return i
    return None


def analyze_csv(text, windows=DEFAULT_WINDOWS):
    """Run both statistics on the text of a snapshots CSV.

    Columns: station_id, timestamp (ISO), bikes_available, docks_available.
    Keeps weekday readings inside the rush windows; drops rows with a blank
    count (and reports how many). A gap longer than 1.5 readings inside a
    window also ends an outage run, since we cannot see what happened.
    """
    reader = csv.DictReader(io.StringIO(text))
    need = {"station_id", "timestamp", "bikes_available", "docks_available"}
    if not reader.fieldnames or not need <= set(reader.fieldnames):
        raise ValueError(f"CSV needs the columns {sorted(need)}")

    by_station, dropped = {}, 0
    for row in reader:
        try:
            ts = datetime.fromisoformat(row["timestamp"].strip())
            bikes = int(row["bikes_available"])
            docks = int(row["docks_available"])
        except (ValueError, TypeError, AttributeError):
            dropped += 1
            continue
        w = _in_window(ts, windows)
        if ts.weekday() >= 5 or w is None:
            continue
        by_station.setdefault(row["station_id"].strip(), []).append((ts, w, bikes, docks))
    if len(by_station) < 2:
        raise ValueError("need rush-hour readings from at least 2 stations")

    # Reading length t: the median gap between back-to-back readings in a window.
    gaps = []
    for recs in by_station.values():
        recs.sort()
        for a, b in zip(recs, recs[1:]):
            if a[0].date() == b[0].date() and a[1] == b[1]:
                gaps.append((b[0] - a[0]).total_seconds() / 60)
    if not gaps:
        raise ValueError("cannot tell the reading interval: need 2+ readings in a window")
    t = median(gaps)

    labels, d, n, per_station = [], [], [], []
    for sid in sorted(by_station):
        recs = by_station[sid]
        runs, current, last = [], [], None
        empty = full = 0
        for ts, w, bikes, docks in recs:
            key = (ts.date(), w)
            if last is not None and (key != last[0] or
                                     (ts - last[1]).total_seconds() / 60 > 1.5 * t):
                runs.append(current)
                current = []
            unusable = bikes == 0 or docks == 0
            empty += bikes == 0
            full += docks == 0
            current.append(unusable)
            last = (key, ts)
        runs.append(current)
        labels.append(sid)
        d.append(sum(sum(r) for r in runs))
        n.append(len(recs))
        av = availability(runs, t)
        av.update({"station": sid, "empty": empty, "full": full})
        per_station.append(av)

    chart = p_chart(d, n, labels)
    for row, av in zip(chart["stations"], per_station):
        row.update({k: av[k] for k in ("empty", "full")})
        row["action"] = ("bring bikes" if av["empty"] >= av["full"] else "remove bikes") \
            if row["flag"] else ""
    send_first = sorted((r for r in chart["stations"] if r["flag"]),
                        key=lambda r: r["p"], reverse=True)
    return {
        "reading_minutes": t,
        "rows_dropped": dropped,
        "p_chart": chart,
        "send_first": [r["station"] for r in send_first],
        "availability": per_station,
    }
