"""The data contract: turns any station-snapshot CSV into clean, validated readings.

Required columns (matched case-insensitively; the aliases below are accepted too):
  station_id       text
  timestamp        ISO 8601 local time, e.g. 2026-10-05T08:15
  bikes_available  count of bikes docked
Optional:
  docks_available  open docks; capacity = bikes + docks for that reading
  capacity         docks at the station (else Settings.capacity, 20)
  van_moved        bikes the van dropped (+) or took (-) just after that reading; when present, net flow
                   = change in bikes minus the PREVIOUS reading's van_moved, so it counts riders only
  arrivals, departures   rider counts in the 15 minutes ending at the reading; when both are
                         present, net flow = arrivals - departures instead of the change in bikes

Another branch with different names passes column_map={"bikes_available": "num_bikes"}.
A row that cannot be trusted is skipped and listed in Dataset.issues; it never becomes a 0.
"""

from __future__ import annotations

import csv
import io
import math
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Dict, Iterable, List, Optional, Tuple

from .config import Settings

ALIASES = {
    "station_id": ["station_id", "station", "station_code"],
    "timestamp": ["timestamp", "time", "datetime", "last_reported"],
    "bikes_available": ["bikes_available", "num_bikes_available", "bikes", "inventory"],
    "docks_available": ["docks_available", "num_docks_available", "docks"],
    "capacity": ["capacity"],
    "van_moved": ["van_moved", "van"],
    "arrivals": ["arrivals"],
    "departures": ["departures"],
}
REQUIRED = ("station_id", "timestamp", "bikes_available")


@dataclass(frozen=True)
class Reading:
    station_id: str
    ts: datetime
    slot: int
    bikes: int
    capacity: int
    arrivals: Optional[int] = None
    departures: Optional[int] = None
    van: Optional[int] = None       # bikes the van dropped (+) or took (-) just AFTER this reading

    @property
    def day(self) -> date:
        return self.ts.date()


@dataclass
class Dataset:
    settings: Settings
    readings: List[Reading]
    issues: List[str] = field(default_factory=list)
    has_flow_columns: bool = False
    has_van_column: bool = False

    def __post_init__(self):
        self._index: Dict[Tuple[str, date], Dict[int, Reading]] = {}
        for r in self.readings:
            self._index.setdefault((r.station_id, r.day), {})[r.slot] = r

    def stations(self) -> List[str]:
        return sorted({r.station_id for r in self.readings})

    def days(self, station: Optional[str] = None) -> List[date]:
        return sorted({d for (s, d) in self._index if station is None or s == station})

    def series(self, station: str, day: date) -> Dict[int, Reading]:
        """slot -> reading for one station on one day (missing slots are absent)."""
        return self._index.get((station, day), {})


def _int(value: str) -> Optional[int]:
    """'12' or '12.0' -> 12; blank -> None; '12.5' or 'abc' -> ValueError."""
    value = (value or "").strip()
    if value == "":
        return None
    f = float(value)
    if not math.isfinite(f) or f != int(f):
        raise ValueError(f"{value!r} is not a whole number")
    return int(f)


def _timestamp(value: str) -> datetime:
    value = value.strip().replace("Z", "")
    ts = datetime.fromisoformat(value)
    return ts.replace(tzinfo=None)


def _columns(header: Iterable[str], column_map: Optional[Dict[str, str]]) -> Dict[str, str]:
    lower = {h.strip().lower(): h for h in header if h is not None}
    found = {}
    for name, aliases in ALIASES.items():
        wanted = [column_map[name].lower()] if column_map and name in column_map else aliases
        for a in wanted:
            if a in lower:
                found[name] = lower[a]
                break
    missing = [c for c in REQUIRED if c not in found]
    if missing:
        raise ValueError(f"missing required column(s): {', '.join(missing)}; "
                         f"columns found: {', '.join(lower) or 'none'}")
    return found


def parse_rows(rows: Iterable[dict], settings: Settings = Settings(),
               column_map: Optional[Dict[str, str]] = None, header=None) -> Dataset:
    settings.validate()
    rows = list(rows)
    cols = _columns(header if header is not None else (rows[0].keys() if rows else []), column_map)
    has_flow = "arrivals" in cols and "departures" in cols
    has_van = "van_moved" in cols
    readings, issues, seen = [], [], set()
    for i, row in enumerate(rows, start=2):        # row 1 is the header
        get = lambda name: row.get(cols[name], "") if name in cols else ""
        try:
            sid = (get("station_id") or "").strip()
            raw_ts = (get("timestamp") or "").strip()
            bikes = _int(get("bikes_available"))
            if not sid or not raw_ts or bikes is None:
                issues.append(f"row {i}: missing station_id, timestamp or bikes_available; skipped")
                continue
            ts = _timestamp(raw_ts)
            docks = _int(get("docks_available"))
            cap = _int(get("capacity"))
            if cap is None:
                cap = bikes + docks if docks is not None else settings.capacity
            arr, dep = _int(get("arrivals")), _int(get("departures"))
            van = _int(get("van_moved"))
        except ValueError as e:
            issues.append(f"row {i}: {e}; skipped")
            continue
        if cap < 1 or bikes < 0 or bikes > cap or (docks is not None and docks < 0):
            issues.append(f"row {i}: capacity violation ({bikes} bikes, capacity {cap}) at {sid}; skipped")
            continue
        if (arr is not None and arr < 0) or (dep is not None and dep < 0):
            issues.append(f"row {i}: negative arrivals or departures; skipped")
            continue
        slot = settings.slot_of(ts)
        if slot is None:
            issues.append(f"row {i}: {raw_ts} is outside operating hours "
                          f"{settings.open_time}-{settings.close_time}; skipped")
            continue
        key = (sid, ts.date(), slot)
        if key in seen:
            issues.append(f"row {i}: second reading for {sid} in the {settings.slot_time(slot)} slot; skipped")
            continue
        seen.add(key)
        readings.append(Reading(sid, ts, slot, bikes, cap, arr, dep, van))

    readings.sort(key=lambda r: (r.station_id, r.ts))
    totals: Dict[Tuple[date, int], int] = {}
    for r in readings:
        totals[(r.day, r.slot)] = totals.get((r.day, r.slot), 0) + r.bikes
    for (d, s), total in sorted(totals.items()):
        if total > settings.fleet:
            issues.append(f"{d} {settings.slot_time(s)}: {total} bikes docked, more than the "
                          f"fleet of {settings.fleet}; check the feed or the fleet setting")
    if not readings:
        issues.append("no usable readings")
    return Dataset(settings, readings, issues, has_flow, has_van)


def parse_csv(text: str, settings: Settings = Settings(),
              column_map: Optional[Dict[str, str]] = None) -> Dataset:
    reader = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    if not reader.fieldnames:
        raise ValueError("the CSV is empty")
    return parse_rows(reader, settings, column_map, header=reader.fieldnames)
