"""Improve: which bikes to move, from where, to where. Two plans share one matching engine.

match_transfers (the engine, plain numbers):
  Each station has its current bikes, capacity, a desired level and optional spare bikes.
  Recipients (desired > bikes) are served in priority order, from
    1. stations that must shed bikes (desired < bikes), largest surplus first,
    2. spare bikes at stations that are fine where they are (only down to their target),
    3. the depot/van reserve.
  Bikes a shedding station still holds afterwards go to the depot. Every bike moves at most
  once; no station ends below 0 or above capacity; stations + reserve is conserved and never
  exceeds the fleet. No distances, van capacity or labor limits are assumed (none are given).

plan_now (daytime, any 15-minute reading):
  level  = projected bikes in Settings.horizon_slots (historical average) if reliable, else current
  gap    = level - target  (positive = surplus, negative = shortage)
  HIGH   = empty or full now, or projected to empty or fill
  MEDIUM = level outside the target band, or an SPC signal at the latest reading
           (a recurring empty/full problem at this hour raises MEDIUM to HIGH)
  A flagged station's desired level is the one that puts its projection on target: bikes - gap.
  Depot bikes are 0 unless given: off-station bikes may be out with riders.

plan_overnight (at 22:00, for the 06:00 opening):
  Each station's average rider net flow over the morning window (06:00-10:00) on earlier days says
  whether riders mostly depart from it (net < 0) or arrive at it (net > 0). The station with the
  biggest net loss starts at Settings.depart_share (80%) of its docks, the biggest net gain at
  Settings.arrive_share (20%), the others in proportion in between, and 50% with no history.
  Every station is moved to its start at 22:00; HIGH = 6 or more bikes to move, MEDIUM = 3-5.
  Depot bikes = fleet - bikes docked at 22:00 unless given (assumes off-station bikes are back).
"""

from __future__ import annotations

import math
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Sequence

from .analyze import comparable_days, flow_profile, project, spc_view
from .data import Dataset

DEPOT = "DEPOT"
PRIORITY = ["HIGH", "MEDIUM", "LOW"]


def match_transfers(stations: Sequence[dict], reserve: int, fleet: int) -> dict:
    """stations: dicts with station_id, bikes, capacity, desired, and optionally spare, priority
    (0 = most urgent), reason. Returns {"transfers", "after", "shortfall", "reserve_after"}."""
    ids = [st["station_id"] for st in stations]
    if len(set(ids)) != len(ids):
        raise ValueError("a station appears twice")
    for st in stations:
        if not 0 <= st["bikes"] <= st["capacity"]:
            raise ValueError(f"capacity violation: {st['station_id']} has {st['bikes']} bikes "
                             f"for {st['capacity']} docks")
        if not 0 <= st["desired"] <= st["capacity"]:
            raise ValueError(f"capacity violation: {st['station_id']} cannot hold {st['desired']} bikes")
    if reserve < 0:
        raise ValueError("depot reserve cannot be negative")
    docked = sum(st["bikes"] for st in stations)
    if docked + reserve > fleet:
        raise ValueError(f"{docked} bikes at stations + {reserve} in reserve = {docked + reserve}, "
                         f"more than the fleet of {fleet}")

    by_id = {st["station_id"]: st for st in stations}
    shed = {i: st["bikes"] - st["desired"] for i, st in by_id.items() if st["desired"] < st["bikes"]}
    spare = {i: min(st.get("spare", 0), st["bikes"]) for i, st in by_id.items()
             if st["desired"] == st["bikes"] and st.get("spare", 0) > 0}
    depot = reserve
    transfers, shortfall = [], {}

    def move(src, dst, n, why):
        transfers.append({"from": src, "to": dst, "bikes": n, "reason": why,
                          "priority": by_id[dst if dst != DEPOT else src].get("priority", 2)})

    recipients = sorted((st for st in stations if st["desired"] > st["bikes"]),
                        key=lambda st: (st.get("priority", 2), st["bikes"] - st["desired"], st["station_id"]))
    for r in recipients:
        need = r["desired"] - r["bikes"]
        for pool in (shed, spare):
            for sid in sorted(pool, key=lambda k: (-pool[k], k)):
                k = min(need, pool[sid])
                if k > 0:
                    move(sid, r["station_id"], k, r.get("reason", ""))
                    pool[sid] -= k
                    need -= k
        if need and depot:
            k = min(need, depot)
            move(DEPOT, r["station_id"], k, r.get("reason", ""))
            depot -= k
            need -= k
        if need:
            shortfall[r["station_id"]] = need
    for sid, k in sorted(shed.items()):
        if k > 0:
            move(sid, DEPOT, k, by_id[sid].get("reason", ""))
            depot += k

    after = {i: st["bikes"] for i, st in by_id.items()}
    for t in transfers:
        if t["from"] != DEPOT:
            after[t["from"]] -= t["bikes"]
        if t["to"] != DEPOT:
            after[t["to"]] += t["bikes"]
    assert all(0 <= after[i] <= by_id[i]["capacity"] for i in after), "capacity broken"
    assert sum(after.values()) + depot == docked + reserve, "bikes not conserved"
    return {"transfers": transfers, "after": after, "shortfall": shortfall, "reserve_after": depot}


def _why_short(sid: str, short: int, reserve: int, any_donor: bool) -> str:
    if not any_donor and reserve == 0:
        return (f"short by {short}: no station has bikes above target and no depot bikes are "
                f"recorded (enter the depot count if the van has bikes)")
    return f"short by {short}: every donor station and the depot gave all they could"


def _rows(stations: List[dict], result: dict, reserve: int) -> List[dict]:
    any_donor = any(st["desired"] < st["bikes"] or st.get("spare", 0) > 0 for st in stations)
    rows = []
    for st in stations:
        sid = st["station_id"]
        ins = [t for t in result["transfers"] if t["to"] == sid]
        outs = [t for t in result["transfers"] if t["from"] == sid]
        parts = []
        if ins:
            parts.append("receive " + ", ".join(f"{t['bikes']} from {t['from']}" for t in ins))
        if outs:
            parts.append("send " + ", ".join(f"{t['bikes']} to {t['to']}" for t in outs))
        short = result["shortfall"].get(sid)
        if short:
            parts.append(_why_short(sid, short, reserve, any_donor))
        if not parts:
            parts.append("no action" if PRIORITY[st["priority"]] == "LOW" else "no move needed")
        rows.append({**{k: v for k, v in st.items() if k not in ("priority",)},
                     "priority": PRIORITY[st["priority"]],
                     "action": "; ".join(parts),
                     "bikes_in": sum(t["bikes"] for t in ins), "bikes_out": sum(t["bikes"] for t in outs),
                     "partners": sorted({t["from"] for t in ins} | {t["to"] for t in outs}),
                     "after": result["after"][sid], "short": short or 0})
    order = {sid: i for i, sid in enumerate(r["station_id"] for r in sorted(
        rows, key=lambda r: (PRIORITY.index(r["priority"]), -abs(r.get("gap") or 0), r["station_id"])))}
    rows.sort(key=lambda r: order[r["station_id"]])
    return rows


def _latest(ds: Dataset, sid: str, day: date, slot: int):
    ser = ds.series(sid, day)
    slots = [s for s in ser if s <= slot]
    return ser[max(slots)] if slots else None


def _recurring(ds: Dataset, sid: str, day: date, slots: range) -> tuple:
    hist = comparable_days(ds, sid, day, before=day)
    hits = 0
    for d in hist:
        ser = ds.series(sid, d)
        if any(s in ser and (ser[s].bikes == 0 or ser[s].bikes >= ser[s].capacity) for s in slots):
            hits += 1
    return hits, len(hist)


def _plan(ds: Dataset, stations: List[dict], reserve: int, extra: dict) -> dict:
    result = match_transfers(stations, reserve, ds.settings.fleet)
    rows = _rows(stations, result, reserve)
    docked = sum(st["bikes"] for st in stations)
    ranked = sorted(result["transfers"], key=lambda t: (t["priority"], -t["bikes"]))
    for t in ranked:
        t["priority"] = PRIORITY[t["priority"]]
    return {**extra, "rows": rows, "transfers": ranked,
            "fleet": {"fleet": ds.settings.fleet, "docked": docked, "reserve_before": reserve,
                      "reserve_after": result["reserve_after"],
                      "docked_after": sum(result["after"].values()),
                      "elsewhere": ds.settings.fleet - docked - reserve},
            "feasible": not result["shortfall"]}


def plan_now(ds: Dataset, at: datetime, depot_bikes: Optional[int] = None) -> dict:
    s = ds.settings
    slot = s.slot_of(at)
    if slot is None:
        raise ValueError(f"{at:%H:%M} is outside operating hours {s.open_time}-{s.close_time}")
    day = at.date()
    stations, missing = [], []
    for sid in ds.stations():
        r = _latest(ds, sid, day, slot)
        if r is None:
            missing.append(sid)
            continue
        b, cap = r.bikes, r.capacity
        proj = project(ds, sid, day, r.slot, b, cap)
        level = proj["value"] if proj["value"] is not None else b
        target = s.target_for(cap)
        lo_b, hi_b = s.band(cap)
        gap = level - target
        reasons, pr = [], 2
        if b == 0 or b >= cap:
            pr, reasons = 0, [f"{'empty' if b == 0 else 'full'} now ({b} of {cap} docks)"]
        if proj["value"] is not None and (proj["value"] <= 0 or proj["value"] >= cap):
            pr = 0
            reasons.append(f"projected to be {'empty' if proj['value'] <= 0 else 'full'} by {proj['at']}")
        if pr > 1 and not lo_b <= level <= hi_b:
            pr = 1
            reasons.append(f"{'projected ' if proj['value'] is not None else ''}{level:.1f} bikes, "
                           f"outside the target range {lo_b}-{hi_b}")
        try:
            spc = spc_view(ds, sid, day, day, "net_flow")
            last = [p for p in spc["points"] if p["t"].endswith(s.slot_time(r.slot)) and p["signals"]]
            if last:
                pr = min(pr, 1)
                reasons.append("SPC signal: " + last[-1]["reasons"][0])
        except ValueError:
            pass
        hits, n = _recurring(ds, sid, day, range(r.slot, min(r.slot + s.horizon_slots, s.n_slots - 1) + 1))
        if n and hits / n >= s.recurring_share:
            reasons.append(f"recurring: empty or full in this hour on {hits} of {n} comparable days")
            if pr == 1:
                pr = 0
        flagged = pr < 2
        desired = min(max(math.floor(b - gap + 0.5), 0), cap) if flagged else b
        spare = 0 if flagged else max(0, min(b, math.floor(level - target)))
        stations.append({"station_id": sid, "reading": r.ts.isoformat(timespec="minutes"),
                         "bikes": b, "capacity": cap, "occupancy": b / cap, "target": target,
                         "band": [lo_b, hi_b],
                         "projected": proj["value"], "projection_basis": proj["basis"],
                         "gap": gap, "desired": desired, "spare": spare, "priority": pr,
                         "reason": "; ".join(reasons) or "within the target range"})
    if not stations:
        raise ValueError(f"no readings on {day} at or before {at:%H:%M}")
    notes = []
    docked = sum(st["bikes"] for st in stations)
    if depot_bikes is not None:
        reserve = depot_bikes
    elif s.depot_from_fleet:
        reserve = s.fleet - docked
        if reserve < 0:
            raise ValueError(f"{docked} bikes docked, more than the fleet of {s.fleet}")
        notes.append(f"depot = fleet {s.fleet} - {docked} docked = {reserve} bikes (in this data every "
                     f"bike that is not docked is in the depot)")
    else:
        reserve = 0
        notes.append("no depot count given: the plan uses 0 depot bikes, because off-station bikes "
                     "may be out with riders")
    if missing:
        notes.append(f"no reading yet today for {', '.join(missing)}: left out of the plan")
    return _plan(ds, stations, reserve, {"kind": "now", "at": at.isoformat(timespec="minutes"),
                                         "notes": notes})


def overnight_shares(morning_net: Dict[str, Optional[float]], depart_share: float, arrive_share: float) -> Dict[str, float]:
    """Each station's start, as a share of its docks, from its average morning net flow.

    Net flow < 0 (more departures than arrivals): from 50% up to depart_share, the station with the
    biggest net loss getting depart_share. Net flow > 0 (more arrivals): from 50% down to
    arrive_share, the biggest net gain getting arrive_share. 0, or no history: 50%.
    """
    max_dep = max([-m for m in morning_net.values() if m is not None and m < 0], default=0)
    max_arr = max([m for m in morning_net.values() if m is not None and m > 0], default=0)
    out = {}
    for sid, m in morning_net.items():
        if m is None or m == 0:
            out[sid] = 0.5
        elif m < 0:
            out[sid] = 0.5 + (depart_share - 0.5) * (-m / max_dep)
        else:
            out[sid] = 0.5 - (0.5 - arrive_share) * (m / max_arr)
    return out


def plan_overnight(ds: Dataset, day: date, depot_bikes: Optional[int] = None) -> dict:
    s = ds.settings
    nxt = day + timedelta(days=1)
    # The team's city datasets mark the end of the van-free Phase I week. Once it
    # has been observed, keep using that week as the 80/20 baseline each night;
    # week-two policy results must not quietly change the rule they are testing.
    phase1_end = date.fromisoformat(s.phase1_through) if s.phase1_through else day
    history_through = min(day, phase1_end)
    first, last = s.slot_of(datetime.strptime(s.morning_window[0], "%H:%M")),         s.slot_of(datetime.strptime(s.morning_window[1], "%H:%M"))
    window = range(first + 1, last + 1)     # flows into 06:15 ... 10:00
    latest, morning_net, hist_days, missing = {}, {}, {}, []
    baseline_start = min((d for d in ds.days() if not s.phase1_through or
                          d <= date.fromisoformat(s.phase1_through)), default=None)
    phase1_dates = ([d for d in ds.days() if baseline_start and d >= baseline_start and
                     (not s.phase1_through or d <= phase1_end)] if s.phase1_through else [])
    required_days = ((phase1_end - baseline_start).days + 1
                     if s.phase1_through and baseline_start else 0)
    complete_phase1_days = []
    if phase1_dates:
        for d in phase1_dates:
            if all(all(slot in ds.series(sid, d) for slot in range(first, last + 1))
                   for sid in ds.stations()):
                complete_phase1_days.append(d)
    for sid in ds.stations():
        r = _latest(ds, sid, day, s.n_slots - 1)
        if r is None:
            missing.append(sid)
            continue
        latest[sid] = r
        hist = comparable_days(ds, sid, nxt, through=history_through)
        # A day informs the morning pattern only when every reading needed to calculate
        # each 15-minute net flow in the window is present. This avoids mixing partial days.
        hist = [d for d in hist if all(slot - 1 in ds.series(sid, d) and slot in ds.series(sid, d)
                                       for slot in window)]
        prof = [flow_profile(ds, sid, hist)[i] for i in window]
        reliable = bool(prof) and all(n >= s.min_history_days for _, n in prof)
        morning_net[sid] = sum(m for m, _ in prof) if reliable else None
        hist_days[sid] = len(hist)
    if not latest:
        raise ValueError(f"no readings on {day} to plan from")
    shares = overnight_shares(morning_net, s.depart_share, s.arrive_share)
    win = f"{s.morning_window[0]}-{s.morning_window[1]}"
    stations = []
    for sid, r in latest.items():
        b, cap, m = r.bikes, r.capacity, morning_net[sid]
        start = min(max(math.floor(shares[sid] * cap + 0.5), 0), cap)
        if m is None:
            role = "no history"
            basis = (f"not enough history (fewer than {s.min_history_days} days for {win}): starts at 50%")
        else:
            role = "mostly departures" if m < 0 else "mostly arrivals" if m > 0 else "balanced"
            basis = (f"{win} on average ({hist_days[sid]} days): riders "
                     f"{'take' if m < 0 else 'bring'} {abs(m):.1f} more bikes than they "
                     f"{'return' if m < 0 else 'take'}" if m else f"{win}: as many bikes arrive as leave")
        move = start - b
        pr = 0 if abs(move) >= 6 else 1 if abs(move) >= 3 else 2
        stations.append({"station_id": sid, "reading": r.ts.isoformat(timespec="minutes"),
                         "bikes": b, "capacity": cap, "occupancy": b / cap, "target": start,
                         "target_share": shares[sid], "role": role, "morning_net": m,
                         "history_days": hist_days[sid], "history_day_type": s.kind(nxt),
                         "projected": None, "projection_basis": basis,
                         "gap": b - start, "desired": start, "spare": 0, "priority": pr,
                         "reason": (f"{role}: start at {shares[sid]:.0%} = {start} of {cap} docks"
                                    + ("" if move == 0 else f", so {'bring' if move > 0 else 'take'} {abs(move)}"))})
    docked = sum(st["bikes"] for st in stations)
    notes = [f"for {nxt} {'(' + s.kind(nxt) + ') ' if s.weekends_differ else ''}opening at {s.open_time}: "
             f"stations where riders mostly depart in {win} start at up to {s.depart_share:.0%}, where "
             f"they mostly arrive at down to {s.arrive_share:.0%} (historical averages, not a forecast)"]
    if depot_bikes is None:
        reserve = s.fleet - docked
        if reserve < 0:
            raise ValueError(f"{docked} bikes docked at 22:00, more than the fleet of {s.fleet}")
        notes.append(f"no depot count given: assumes the {reserve} bikes not docked "
                     f"(fleet {s.fleet} - {docked} docked) are at the depot overnight")
    else:
        reserve = depot_bikes
    if missing:
        notes.append(f"no reading on {day} for {', '.join(missing)}: left out of the plan")
    calendar_complete = day >= phase1_end
    observed_complete = (not s.phase1_through or
                         (required_days > 0 and len(complete_phase1_days) == required_days))
    baseline_complete = calendar_complete and observed_complete
    baseline = {"source": "week 1 baseline" if s.phase1_through else "earlier readings",
                "from": baseline_start.isoformat() if baseline_start else None,
                "through": history_through.isoformat(),
                "window": win,
                "complete_days": len(complete_phase1_days) if s.phase1_through else max(hist_days.values(), default=0),
                "required_days": required_days or s.min_history_days,
                "complete": baseline_complete}
    if not baseline_complete:
        # Return readiness metadata only. Do not expose targets or transfer actions before
        # the required, fully observed Week 1 baseline is available.
        return {"kind": "overnight", "at": f"{day.isoformat()}T{s.close_time}",
                "redistribute_by": f"{day.isoformat()}T22:00",
                "for": f"{nxt.isoformat()}T{s.open_time}",
                "ready_at": f"{nxt.isoformat()}T{s.open_time}",
                "baseline": baseline, "rows": [], "transfers": [], "feasible": False,
                "notes": notes + [f"Learning Week 1: {baseline['complete_days']} of "
                                  f"{baseline['required_days']} complete morning days are available; "
                                  "no station targets or transfer plan is published yet."]}
    return _plan(ds, stations, reserve, {"kind": "overnight", "at": f"{day.isoformat()}T{s.close_time}",
                                         "redistribute_by": f"{day.isoformat()}T22:00",
                                         "for": f"{nxt.isoformat()}T{s.open_time}",
                                         "ready_at": f"{nxt.isoformat()}T{s.open_time}",
                                         "baseline": baseline, "notes": notes})
