"""Analyze views over a Dataset: station inventory, net flow, the SPC chart and projections.
Every function returns plain JSON-ready dicts; the statistic itself is qc.imr_slot_adjusted.

Net flow for the 15 minutes ending at a reading:
  arrivals - departures                 when the data has both columns, else
  bikes_t - bikes_(t-15 min)            the observed change, which also includes van moves
Positive = the station gained bikes.

Projection (only when reliable):
  projected = clip(current + sum over the next h slots of the mean net flow at that slot on
                   comparable earlier days, 0, capacity)
  reliable  = every one of those slots has at least Settings.min_history_days days of history.
"""

from __future__ import annotations

from datetime import date, timedelta
from statistics import mean
from typing import Dict, List, Optional, Sequence, Tuple

from .data import Dataset
from .qc import RULE_TEXT, clean_baseline, imr_slot_adjusted

FLOW_SOURCE = {True: "arrivals - departures",
               "van": "change in bikes since the last reading minus the van move after it (riders only)",
               False: "change in bikes since the last reading (includes van moves)"}


def flow_source(ds: Dataset) -> str:
    return FLOW_SOURCE[True if ds.has_flow_columns else "van" if ds.has_van_column else False]


def status(bikes: int, capacity: int, s) -> str:
    """Operational state of one reading (not a statistical signal)."""
    if bikes == 0:
        return "empty"
    if bikes >= capacity:
        return "full"
    lo, hi = s.band(capacity)
    if bikes < lo:
        return "low"
    if bikes > hi:
        return "high"
    return "ok"


def net_flow_day(ds: Dataset, station: str, day: date) -> Tuple[List[Optional[int]], List[Optional[bool]]]:
    """Net flow per slot, plus whether each value came from arrival/departure counts."""
    ser, n = ds.series(station, day), ds.settings.n_slots
    flow, counted = [None] * n, [None] * n
    for slot, r in ser.items():
        if r.arrivals is not None and r.departures is not None:
            flow[slot], counted[slot] = r.arrivals - r.departures, True
        elif slot - 1 in ser:
            prev = ser[slot - 1]
            if prev.van is not None:
                flow[slot], counted[slot] = r.bikes - prev.bikes - prev.van, "van"
            else:
                flow[slot], counted[slot] = r.bikes - prev.bikes, False
    return flow, counted


def inventory_day(ds: Dataset, station: str, day: date) -> List[Optional[int]]:
    ser = ds.series(station, day)
    return [ser[s].bikes if s in ser else None for s in range(ds.settings.n_slots)]


def comparable_days(ds: Dataset, station: str, like: date, before: Optional[date] = None,
                    through: Optional[date] = None) -> List[date]:
    """Days with readings for this station and the same day type (weekday/weekend) as `like`."""
    return [d for d in ds.days(station) if ds.settings.kind(d) == ds.settings.kind(like)
            and (before is None or d < before) and (through is None or d <= through)]


def flow_profile(ds: Dataset, station: str, days: Sequence[date]) -> List[Tuple[Optional[float], int]]:
    """(mean net flow, number of days) for every slot over the given days."""
    per_day = [net_flow_day(ds, station, d)[0] for d in days]
    out = []
    for s in range(ds.settings.n_slots):
        vals = [f[s] for f in per_day if f[s] is not None]
        out.append((mean(vals) if vals else None, len(vals)))
    return out


def project(ds: Dataset, station: str, day: date, slot: int, bikes: int, capacity: int,
            horizon: Optional[int] = None) -> dict:
    """Projected bikes `horizon` slots after `slot`, from comparable days before `day`."""
    s = ds.settings
    h = s.horizon_slots if horizon is None else horizon
    end = min(slot + h, s.n_slots - 1)
    hist = comparable_days(ds, station, day, before=day)
    out = {"at": s.slot_time(end), "value": None, "history_days": len(hist), "basis": ""}
    if end == slot:
        out["basis"] = "closing time: nothing left to project"
        return out
    prof = flow_profile(ds, station, hist)[slot + 1:end + 1]
    thin = [s.slot_time(slot + 1 + i) for i, (m, n) in enumerate(prof) if n < s.min_history_days]
    if thin:
        out["basis"] = (f"not reliable: fewer than {s.min_history_days} comparable "
                        f"{s.kind(day)}s of history for {', '.join(thin[:3])}"
                        f"{'...' if len(thin) > 3 else ''}")
        return out
    change = sum(m for m, _ in prof)
    out["value"] = min(max(bikes + change, 0), capacity)
    out["change"] = change
    out["basis"] = (f"historical average of {len(hist)} comparable {s.kind(day)}s: "
                    f"{change:+.1f} bikes by {out['at']}")
    return out


def _period(day: date, slot: int, s) -> str:
    if s.kind(day) == "weekend":
        return "weekend"
    t = s.slot_time(slot)
    if s.morning_rush[0] <= t < s.morning_rush[1]:
        return "morning rush"
    if s.evening_rush[0] <= t < s.evening_rush[1]:
        return "evening rush"
    return "other hours"


PERIODS = ["morning rush", "evening rush", "other hours", "weekend"]


def _days_in(ds: Dataset, start: Optional[date], end: Optional[date], station: Optional[str] = None):
    return [d for d in ds.days(station) if (start is None or d >= start) and (end is None or d <= end)]


def inventory_view(ds: Dataset, stations: Sequence[str], start=None, end=None) -> dict:
    s = ds.settings
    out = []
    for sid in stations:
        series = []
        for d in _days_in(ds, start, end, sid):
            for slot, r in sorted(ds.series(sid, d).items()):
                series.append({"t": r.ts.isoformat(timespec="minutes"), "bikes": r.bikes,
                               "capacity": r.capacity, "occupancy": r.bikes / r.capacity,
                               "status": status(r.bikes, r.capacity, s), "van": r.van})
        latest = None
        if series:
            last_day = _days_in(ds, start, end, sid)[-1]
            r = ds.series(sid, last_day)[max(ds.series(sid, last_day))]
            latest = {"t": series[-1]["t"], "bikes": r.bikes, "capacity": r.capacity,
                      "occupancy": r.bikes / r.capacity, "status": status(r.bikes, r.capacity, s),
                      "projection": project(ds, sid, last_day, r.slot, r.bikes, r.capacity)}
        cap = series[-1]["capacity"] if series else s.capacity
        out.append({"station_id": sid, "series": series, "latest": latest, "capacity": cap,
                    "band": list(s.band(cap)), "target": s.target_for(cap)})
    return {"stations": out, "target_share": s.target_share,
            "band_share": [s.band_low_share, s.band_high_share]}


def flow_view(ds: Dataset, stations: Sequence[str], start=None, end=None, period: Optional[str] = None) -> dict:
    s = ds.settings
    out = []
    for sid in stations:
        bars, by_period = [], {p: [] for p in PERIODS}
        for d in _days_in(ds, start, end, sid):
            flow, counted = net_flow_day(ds, sid, d)
            for slot, f in enumerate(flow):
                if f is None:
                    continue
                p = _period(d, slot, s)
                by_period[p].append(f)
                if period is None or p == period:
                    bars.append({"t": f"{d.isoformat()}T{s.slot_time(slot)}", "net_flow": f,
                                 "period": p, "source": FLOW_SOURCE[counted[slot]]})
        summary = [{"period": p, "intervals": len(v), "total": sum(v),
                    "mean_per_interval": mean(v) if v else None,
                    "gained": sum(x for x in v if x > 0), "lost": -sum(x for x in v if x < 0)}
                   for p, v in by_period.items()]
        out.append({"station_id": sid, "bars": bars, "summary": summary})
    return {"stations": out, "source": flow_source(ds),
            "note": "station-level counts only: rider routes between stations are not inferred"}


def chart_baseline(ds: Dataset, station: str, day: date, kind: str, limits: str) -> tuple:
    """The days a chart of `day` is judged against, and how they were chosen.
    phase: the previous complete project week (same day type); rolling: last rolling_days comparable
    days; week1: fixed Phase I. Incomplete previous weeks do not become new reference limits."""
    s = ds.settings
    cut = date.fromisoformat(s.phase1_through) if s.phase1_through else None
    phase1 = [d for d in ds.days(station) if cut and d <= cut and s.kind(d) == kind]
    if limits == "rolling":
        base = [d for d in ds.days(station) if d < day and s.kind(d) == kind][-s.rolling_days:]
        if len(base) >= 2:
            return base, f"last {len(base)} days before {day}, cleaned", None
    elif limits == "phase" and cut:
        project_start = cut - timedelta(days=6)
        week_index = (day - project_start).days // 7
        if week_index > 0:
            start = project_start + timedelta(days=(week_index - 1) * 7)
            end = start + timedelta(days=6)
            week_days = [start + timedelta(days=i) for i in range(7)]
            complete = [d for d in week_days if all(slot in ds.series(station, d)
                                                     for slot in range(s.n_slots))]
            base = [d for d in complete if s.kind(d) == kind]
            needed = 7 if not s.weekends_differ else (5 if kind == "weekday" else 2)
            if len(complete) == 7 and len(base) == needed:
                return base, f"Week {week_index} baseline ({start} to {end})", None
    elif limits == "phase" and not cut:
        # Uploaded datasets may not declare project-week boundaries. Use only prior
        # comparable days as the phase reference instead of estimating limits from
        # the day currently being judged.
        base = comparable_days(ds, station, day, before=day)
        if len(base) >= 2:
            return base, f"{len(base)} earlier comparable days (no project week declared)", None
    elif phase1:
        return phase1, f"week 1 ({len(phase1)} days, fixed)", None
    if limits not in ("phase", "week1"):
        base = comparable_days(ds, station, day, before=day)
        if len(base) >= 2:
            return base, f"{len(base)} earlier days", None
    if len(phase1) >= 2:
        return phase1, f"week 1 ({len(phase1)} days): fewer than 2 earlier days", None
    return [day], "the day itself", (f"fewer than 2 {kind}s before {day}: limits are estimated from the "
                                     f"charted day itself, so a lasting change may be partly absorbed")


def spc_view(ds: Dataset, station: str, start: date, end: date, measure: str = "net_flow",
             kind: Optional[str] = None, limits: Optional[str] = None) -> dict:
    """Slot-adjusted I-MR chart for one station over [start, end], one day type at a time, with the
    course's eight tests (qc.py). In phase mode, every complete project week uses the preceding
    complete week's same-day-type baseline, frozen for that week. limits="rolling" is a diagnostic
    that updates daily; limits="week1" keeps the original Phase I days fixed. Inventory is offered
    with sigma from the residual spread and test 1 only, because inventory accumulates."""
    if measure not in ("inventory", "net_flow"):
        raise ValueError("measure must be 'inventory' or 'net_flow'")
    s = ds.settings
    limits = limits or s.limits_mode
    if limits not in ("phase", "rolling", "week1"):
        raise ValueError("limits must be 'phase', 'rolling' or 'week1'")
    kind = kind or s.kind(end)
    chart_days = [d for d in _days_in(ds, start, end, station) if s.kind(d) == kind]
    if not chart_days:
        raise ValueError(f"no {kind} readings for {station} between {start} and {end}")
    pick = (lambda d: inventory_day(ds, station, d)) if measure == "inventory" \
        else (lambda d: net_flow_day(ds, station, d)[0])
    first = ds.series(station, chart_days[0])
    cap0 = first[min(first)].capacity if first else s.capacity
    warnings, points, lim, basis, base_days, removed_total = [], [], None, "", [], 0
    for d in chart_days:
        base, basis, warn = chart_baseline(ds, station, d, kind, limits)
        if warn:
            warnings.append(warn)
        series = [pick(b) for b in base]
        removed = 0
        if limits == "rolling" and basis.startswith("last") and measure == "net_flow":
            series, removed = clean_baseline(series)
        removed_total += removed
        if measure == "inventory":
            res = imr_slot_adjusted(series, [pick(d)], sigma="sd", rules=("rule1",))
        else:
            res = imr_slot_adjusted(series, [pick(d)])
        warnings += [w for w in res["warnings"] if w not in warnings]
        lim, base_days = res["limits"], base
        for p in res["points"]:
            cap = ds.series(station, d).get(p["slot"])
            cap = cap.capacity if cap else s.capacity
            lo = hi = None
            if lim and p["expected"] is not None:
                m = res["slot_means"][p["slot"]]
                lo, hi = m + lim["lcl"], m + lim["ucl"]
            reasons = []
            for code in p["signals"]:
                if code == "rule1":
                    reasons.append(f"{RULE_TEXT[code]}: {p['x']} vs usual {p['expected']:.1f} at "
                                   f"{s.slot_time(p['slot'])} ({p['z']:+.1f} sigma)")
                elif code == "mr":
                    reasons.append(f"{RULE_TEXT[code]}: moved {p['mr']:.1f} vs MR limit {lim['mr_ucl']:.1f}")
                else:
                    reasons.append(RULE_TEXT[code])
            state = status(int(p["x"]), cap, s) if measure == "inventory" else None
            points.append({"t": f"{d.isoformat()}T{s.slot_time(p['slot'])}", "x": p["x"],
                           "expected": p["expected"], "lcl": lo, "ucl": hi, "residual": p["residual"],
                           "chart_cl": lim["cl"] if lim else None,
                           "chart_ucl": lim["ucl"] if lim else None,
                           "chart_lcl": lim["lcl"] if lim else None,
                           "chart_sigma": lim["sigma"] if lim else None,
                           "chart_mr_ucl": lim["mr_ucl"] if lim else None,
                           "chart_mr_bar": lim["mr_bar"] if lim else None,
                           "baseline": basis,
                           "z": p["z"], "mr": p["mr"], "signals": p["signals"], "reasons": reasons,
                           "status": state})
    if lim is not None:
        lim = {**lim, "basis": basis, "removed": removed_total}
    return {"station_id": station, "measure": measure, "day_type": kind, "limits_mode": limits,
            "baseline_days": [d.isoformat() for d in base_days], "basis": basis, "limits": lim,
            "points": points, "warnings": warnings, "rules": RULE_TEXT,
            "phase": ("Phase I" if s.phase1_through and chart_days[-1] <= date.fromisoformat(s.phase1_through)
                      else "Phase II" if s.phase1_through else None),
            "target_band": list(s.band(cap0)) if measure == "inventory" else None,
            "method": ("sigma = standard deviation of the baseline residuals; test 1 only, because "
                       "inventory accumulates and runs are normal"
                       if measure == "inventory" else
                       "course I-MR: sigma = MR-bar / 1.128, limits = centre +/- 3 sigma, "
                       "MR UCL = 3.267 x MR-bar; the eight tests with zones C (1 sigma), B (2), A (3). "
                       + ("Limits: the last 7 days before each charted day, with readings beyond 3 sigma "
                          "removed and recomputed (they update every day)" if limits == "rolling"
                          else "Limits: previous complete project week, frozen within this week"
                          if limits == "phase" else "Limits: week 1, fixed (comparison mode)")),
            "note": "the chart plots each reading minus what is usual for that time slot on the "
                    "baseline days, so the normal rush-hour swing is not a signal."}


def scorecard(ds: Dataset, events: Sequence[dict], limits: Optional[str] = None) -> dict:
    """Did the control chart catch each planted problem? For each event (station, day, from, to):
    the first flagged reading at or after its start, the tests that fired there, and how many
    readings inside the window were flagged. Also each station's false-alarm rate over the
    Phase II days that have no planted event (the share of readings that fired any test)."""
    s = ds.settings
    rows = []
    for ev in events:
        day = date.fromisoformat(ev["day"])
        try:
            v = spc_view(ds, ev["station"], day, day, "net_flow", limits=limits)
        except ValueError as e:
            rows.append({**ev, "first_flag": None, "tests": [], "flagged_in_window": 0, "error": str(e)})
            continue
        pts = [p for p in v["points"] if p["t"][11:] >= ev["from"]]
        first = next((p for p in pts if p["signals"]), None)
        inside = [p for p in pts if p["t"][11:] <= ev["to"]]
        rows.append({**ev, "first_flag": first["t"][11:] if first else None,
                     "tests": first["signals"] if first else [],
                     "minutes_after_start": (None if not first else
                                             (int(first["t"][11:13]) * 60 + int(first["t"][14:16]))
                                             - (int(ev["from"][:2]) * 60 + int(ev["from"][3:]))),
                     "flagged_in_window": sum(1 for p in inside if p["signals"]), "readings_in_window": len(inside)})
    event_days = {ev["day"] for ev in events}
    cut = date.fromisoformat(s.phase1_through) if s.phase1_through else None
    quiet = [d for d in ds.days() if (cut is None or d > cut) and d.isoformat() not in event_days]
    rates = {}
    for sid in ds.stations():
        n = a = t = 0
        for d in quiet:
            try:
                pts = spc_view(ds, sid, d, d, "net_flow", limits=limits)["points"]
            except ValueError:
                continue
            n += len(pts)
            a += sum(1 for p in pts if p["signals"])
            t += sum(1 for p in pts if any(x != "mr" for x in p["signals"]))
        rates[sid] = {"readings": n, "flagged": a, "rate": a / n if n else None,
                      "flagged_by_tests": t, "rate_tests_only": t / n if n else None}
    n = sum(r["readings"] for r in rates.values())
    a = sum(r["flagged"] for r in rates.values())
    t = sum(r["flagged_by_tests"] for r in rates.values())
    return {"events": rows, "false_alarms": rates, "false_alarm_rate": a / n if n else None,
            "false_alarm_rate_tests_only": t / n if n else None,
            "quiet_days": [d.isoformat() for d in quiet]}


def trip_matrix(trips: Sequence[tuple], stations: Sequence[str], after: str, through: str) -> dict:
    """Origin-destination counts: how many trips went from each station to each other station
    with a timestamp in (after, through] (ISO strings, compared as text). A count, not a statistic.
    matrix[i][j] = trips from stations[i] to stations[j]; the diagonal is always 0."""
    idx = {sid: k for k, sid in enumerate(stations)}
    m = [[0] * len(stations) for _ in stations]
    for t, a, b in trips:
        if after < t <= through and a in idx and b in idx:
            m[idx[a]][idx[b]] += 1
    top = sorted(({"from": stations[i], "to": stations[j], "trips": m[i][j]}
                  for i in range(len(stations)) for j in range(len(stations)) if m[i][j]),
                 key=lambda r: -r["trips"])
    return {"stations": list(stations), "matrix": m, "total": sum(map(sum, m)),
            "left": [sum(r) for r in m], "arrived": [sum(c) for c in zip(*m)] if m else [],
            "top": top[:8], "after": after, "through": through}


def summary(ds: Dataset) -> dict:
    days = ds.days()
    return {"stations": ds.stations(), "days": [d.isoformat() for d in days],
            "readings": len(ds.readings), "issues": ds.issues[:50], "issue_count": len(ds.issues),
            "flow_source": flow_source(ds),
            "settings": {k: getattr(ds.settings, k) for k in ds.settings.__dataclass_fields__}}
