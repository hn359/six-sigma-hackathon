"""Stateful Monte Carlo simulator for the Ithaca bikeshare network.

Designed for municipal transport engineers and Six Sigma / DMAIC process control:
- 5 stations: Lansing, North Campus, Maplewood, Central Campus, Downtown.
- 20-dock maximum capacity each.
- Initial Monday fleet: 10 bikes per station (50 total) + 50 in reserve = 100 total fleet.
- Residential stations (Lansing, Maplewood) exhibit morning outflow (6-10 AM).
- Working district stations (Central Campus, North Campus) exhibit evening return outflow (4-7:30 PM).
- Downtown Commons exhibits steady transfer and midday demand.
- After 10 PM, night-time quiescence keeps fluctuations minimal until morning.
- Daily overnight rebalance redistributes the 50 station bikes proportionally
  based on the previous day's time-averaged occupancy.
- Statistical Process Control limits: UCL = 18, LCL = 2.
- Common Cause vs. Special Cause variation:
  * Common cause fluctuations self-correct naturally.
  * Special cause crises (bikes <= 2 or bikes >= 18) lock the station and worsen
    over time until an operator issues a maintenance van dispatch command.
- Real-time continuous background execution (1 tick every 10 wall-clock seconds by default).
- Full I-MR (Individual & Moving Range) and DMAIC metrics.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import random
import secrets
import sqlite3
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Iterable

from .spc_analytics import calculate_p_chart, calculate_station_spc, generate_dmaic_report

# Station layout for Ithaca bikeshare network:
# Lansing: North residential suburb
# Maplewood: East residential / graduate student community
# Downtown: Central Commons transfer & mixed business hub
# Central Campus: Core academic & employment working district
# North Campus: Student residential & campus working district
STATION_META: dict[str, dict[str, Any]] = {
    "Lansing": {"name": "Lansing Residential", "zone": "residential", "lat": 42.4820, "lon": -76.4850, "alias": "A"},
    "Maplewood": {"name": "Maplewood Residential", "zone": "residential", "lat": 42.4350, "lon": -76.4680, "alias": "B"},
    "Downtown": {"name": "Downtown Commons", "zone": "mixed", "lat": 42.4396, "lon": -76.4968, "alias": "C"},
    "Central Campus": {"name": "Central Campus", "zone": "employment", "lat": 42.4473, "lon": -76.4823, "alias": "D"},
    "North Campus": {"name": "North Campus", "zone": "employment", "lat": 42.4550, "lon": -76.4780, "alias": "E"},
}

ALIAS_TO_STATION: dict[str, str] = {
    "A": "Lansing",
    "B": "Maplewood",
    "C": "Downtown",
    "D": "Central Campus",
    "E": "North Campus",
}


def resolve_station_name(sid: str) -> str:
    """Resolve station identifier or legacy letter alias (A-E) to full station name."""
    if sid in STATION_META:
        return sid
    if sid.upper() in ALIAS_TO_STATION:
        return ALIAS_TO_STATION[sid.upper()]
    if sid == "RESERVE":
        return "RESERVE"
    raise ValueError(f"Unknown station: '{sid}'. Valid stations: {list(STATION_META.keys())} or A-E")


try:
    from pydantic import BaseModel, Field

    class DispatchRequest(BaseModel):
        source: str = Field(description="Origin: station name/alias or 'RESERVE'")
        destination: str = Field(description="Destination: station name/alias or 'RESERVE'")
        quantity: int = Field(gt=0, le=20, description="Number of bikes to move")
        reason: str = Field(default="operator", description="Dispatch reason")
except ImportError:
    class DispatchRequest:  # type: ignore
        pass


@dataclass(frozen=True)
class SimulatorConfig:
    capacity: int = 20
    initial_bikes_per_station: int = 10
    initial_reserve: int = 50
    simulation_minutes_per_tick: int = 15
    wall_seconds_per_tick: float = 10.0  # 10s default gives user enough time to react
    ucl: int = 18  # Upper Control Limit
    lcl: int = 2   # Lower Control Limit
    low_threshold: int = 5
    high_threshold: int = 15
    base_trip_rate: float = 1.35
    overnight_rebalance_total: int = 50
    database_path: str = "bikeshare.db"
    start_time: datetime = datetime(2026, 10, 19, 0, 0)  # Monday start of operation


@dataclass
class TripBatch:
    destination: str
    bikes: int
    arrival_time: datetime


@dataclass
class StationState:
    station_id: str
    bikes: int
    capacity: int
    rentals: int = 0
    returns: int = 0
    failed_rentals: int = 0
    failed_returns: int = 0
    special_cause_active: bool = False
    special_cause_type: str = "NONE"  # "DEFICIT", "SURPLUS", "NONE"

    @property
    def docks(self) -> int:
        return self.capacity - self.bikes

    @property
    def status(self) -> str:
        if self.bikes == 0:
            return "EMPTY"
        if self.bikes <= 2:
            return "DEFICIT"
        if self.bikes < 5:
            return "LOW"
        if self.bikes == self.capacity:
            return "FULL"
        if self.bikes >= 18:
            return "SURPLUS"
        if self.bikes > 15:
            return "HIGH"
        return "OK"

    @property
    def is_unusable(self) -> bool:
        return self.bikes == 0 or self.bikes >= self.capacity

    @property
    def unusable_reason(self) -> str:
        if self.bikes == 0:
            return "EMPTY"
        if self.bikes >= self.capacity:
            return "FULL"
        return "NONE"


class BikeshareSimulator:
    """Thread-safe Monte Carlo simulation engine with SQLite persistence,

    I-MR process control, Special Cause persistence, and van dispatch mechanics.
    """

    def __init__(
        self,
        config: SimulatorConfig | None = None,
        seed: int | None = None,
        persist: bool = True,
    ) -> None:
        self.config = config or SimulatorConfig()
        self.seed = seed if seed is not None else secrets.randbits(63)
        self.rng = random.Random(self.seed)
        self.current_time = self.config.start_time
        self.stations = {
            sid: StationState(sid, self.config.initial_bikes_per_station, self.config.capacity)
            for sid in STATION_META
        }
        self.reserve = self.config.initial_reserve
        self.in_transit: list[TripBatch] = []
        self.tick_number = 0
        self.running = False
        self._thread: threading.Thread | None = None
        self._lock = threading.RLock()
        self._subscribers: list[Callable[[dict], None]] = []
        self._daily_occupancy: dict[str, list[int]] = {sid: [] for sid in STATION_META}

        # Multi-scale stochastic drift parameters
        self._weather_drift = 1.0
        self._station_day_drift = self._new_day_drift()
        self._walk_drift = {sid: 1.0 for sid in STATION_META}

        self._persist = persist
        self._conn: sqlite3.Connection | None = None
        if persist:
            self._open_database()
        self._record_snapshot("INITIAL")
        self._assert_invariants()

    @property
    def fleet_size(self) -> int:
        return len(STATION_META) * self.config.initial_bikes_per_station + self.config.initial_reserve

    def _open_database(self) -> None:
        path = Path(self.config.database_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript("""
        CREATE TABLE IF NOT EXISTS snapshots (
            id INTEGER PRIMARY KEY, simulation_id TEXT, seed INTEGER, tick INTEGER,
            timestamp TEXT, station_id TEXT, zone TEXT, bikes INTEGER, docks INTEGER,
            capacity INTEGER, status TEXT, reserve INTEGER, in_transit INTEGER,
            rentals INTEGER, returns INTEGER, failed_rentals INTEGER,
            failed_returns INTEGER, special_cause_active INTEGER, special_cause_type TEXT,
            event TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_snapshot_time ON snapshots(timestamp);
        CREATE INDEX IF NOT EXISTS idx_snapshot_station_tick ON snapshots(station_id, tick);
        CREATE TABLE IF NOT EXISTS dispatches (
            id INTEGER PRIMARY KEY, timestamp TEXT, source TEXT, destination TEXT,
            requested INTEGER, moved INTEGER, reason TEXT
        );
        """)
        # Migrate existing tables if missing columns
        cursor = self._conn.execute("PRAGMA table_info(snapshots)")
        existing_cols = {row[1] for row in cursor.fetchall()}
        if "special_cause_active" not in existing_cols:
            self._conn.execute("ALTER TABLE snapshots ADD COLUMN special_cause_active INTEGER DEFAULT 0")
        if "special_cause_type" not in existing_cols:
            self._conn.execute("ALTER TABLE snapshots ADD COLUMN special_cause_type TEXT DEFAULT 'NONE'")
        self._conn.commit()

    def _new_day_drift(self) -> dict[str, float]:
        self._weather_drift = max(0.70, min(1.30, self.rng.gauss(1.0, 0.12)))
        return {sid: self.rng.lognormvariate(0.0, 0.10) for sid in STATION_META}

    def _update_walk_drift(self) -> None:
        for sid in STATION_META:
            step = self.rng.gauss(0.0, 0.015)
            self._walk_drift[sid] = max(0.75, min(1.35, self._walk_drift[sid] + step))

    @staticmethod
    def _poisson(rng: random.Random, lam: float) -> int:
        if lam <= 0:
            return 0
        if lam > 30:
            return max(0, round(rng.gauss(lam, math.sqrt(lam))))
        limit, product, k = math.exp(-lam), 1.0, 0
        while product > limit:
            k += 1
            product *= rng.random()
        return k - 1

    def _activity_multiplier(self, hour: float) -> float:
        morning = math.exp(-0.5 * ((hour - 8.0) / 1.25) ** 2)
        evening = math.exp(-0.5 * ((hour - 17.5) / 1.45) ** 2)
        midday = math.exp(-0.5 * ((hour - 13.0) / 3.2) ** 2)

        # After 10 PM (22:00) until 05:30 AM: minimal fluctuations
        late = 0.04 if (hour >= 22.0 or hour < 5.5) else 1.0
        weekend = 0.70 if self.current_time.weekday() >= 5 else 1.0

        return late * weekend * (0.20 + 2.05 * morning + 1.85 * evening + 0.45 * midday)

    def _origin_weight(self, sid: str, hour: float) -> float:
        zone = STATION_META[sid]["zone"]
        morning = math.exp(-0.5 * ((hour - 8.0) / 1.2) ** 2)
        evening = math.exp(-0.5 * ((hour - 17.5) / 1.3) ** 2)
        if zone == "residential":
            return 0.65 + 3.2 * morning + 0.35 * evening
        if zone == "employment":
            return 0.65 + 0.35 * morning + 3.2 * evening
        # Downtown Mixed
        return 1.10 + 0.70 * morning + 0.70 * evening

    def _destination_weights(self, origin: str, hour: float) -> dict[str, float]:
        origin_zone = STATION_META[origin]["zone"]
        weights: dict[str, float] = {}
        morning = 6.0 <= hour < 10.0
        evening = 15.5 <= hour < 20.0

        for sid, meta in STATION_META.items():
            if sid == origin:
                continue
            w = 1.0
            dest_zone = meta["zone"]
            if morning and origin_zone == "residential" and dest_zone == "employment":
                w = 5.5
            elif evening and origin_zone == "employment" and dest_zone == "residential":
                w = 5.5
            elif dest_zone == "mixed":
                w = 1.8
            drift_factor = self._station_day_drift[sid] * self._walk_drift[sid]
            weights[sid] = w * drift_factor
        return weights

    def _weighted_choice(self, weights: dict[str, float]) -> str:
        total = sum(weights.values())
        if total <= 0:
            return self.rng.choice(list(weights.keys()))
        point = self.rng.random() * total
        cumulative = 0.0
        for key, value in weights.items():
            cumulative += value
            if point <= cumulative:
                return key
        return next(reversed(weights))

    def _travel_minutes(self, origin: str, destination: str) -> int:
        ids = list(STATION_META)
        separation = abs(ids.index(origin) - ids.index(destination))
        raw = self.rng.gauss(11 + 3 * separation, 3.0)
        step = self.config.simulation_minutes_per_tick
        return max(step, math.ceil(max(4, raw) / step) * step)

    def _process_arrivals(self) -> None:
        waiting: list[TripBatch] = []
        for trip in self.in_transit:
            if trip.arrival_time > self.current_time:
                waiting.append(trip)
                continue
            destination = self.stations[trip.destination]

            # SPECIAL CAUSE CHECK:
            # If destination is locked in DEFICIT (special cause), arriving bikes cannot
            # auto-correct it above LCL (2). Docks may be blocked or arrivals diverted.
            if destination.special_cause_active and destination.special_cause_type == "DEFICIT":
                # Arriving bikes cannot raise station above 2 bikes
                allowed_space = max(0, self.config.lcl - destination.bikes)
                accepted = min(trip.bikes, allowed_space)
            else:
                accepted = min(trip.bikes, destination.docks)

            destination.bikes += accepted
            destination.returns += accepted
            overflow = trip.bikes - accepted

            # Check if arrival pushes station into SURPLUS special cause (>= 18)
            if destination.bikes >= self.config.ucl:
                destination.special_cause_active = True
                destination.special_cause_type = "SURPLUS"

            if overflow > 0:
                destination.failed_returns += overflow
                # Divert overflow to station with most free docks; reserve is fallback
                alternatives = sorted(
                    [s for s in self.stations.values() if not (s.special_cause_active and s.special_cause_type == "DEFICIT")],
                    key=lambda s: s.docks,
                    reverse=True,
                )
                remaining = overflow
                for alt in alternatives:
                    if alt.station_id == destination.station_id or remaining == 0:
                        continue
                    moved = min(remaining, alt.docks)
                    alt.bikes += moved
                    alt.returns += moved
                    remaining -= moved
                self.reserve += remaining

        self.in_transit = waiting

    def _generate_departures(self) -> None:
        hour = self.current_time.hour + self.current_time.minute / 60.0
        activity = self._activity_multiplier(hour)
        duration_scale = self.config.simulation_minutes_per_tick / 15.0

        # Occasional special cause shock (1.5% chance during rush hour)
        is_rush = (6.0 <= hour <= 10.0) or (16.0 <= hour <= 19.5)
        shock_station = (
            self.rng.choice(list(STATION_META))
            if is_rush and self.rng.random() < 0.015
            else None
        )

        for sid in list(STATION_META):
            station = self.stations[sid]

            # SPECIAL CAUSE CHECK:
            # If station is locked in SURPLUS (special cause), normal departures cannot
            # auto-correct it below UCL (18). Docks are locked/jammed until operator command.
            if station.special_cause_active and station.special_cause_type == "SURPLUS":
                allowed_drain = max(0, station.bikes - self.config.ucl)
            else:
                allowed_drain = station.bikes

            drift_factor = (
                self._weather_drift
                * self._station_day_drift[sid]
                * self._walk_drift[sid]
            )
            shock_mult = 2.4 if sid == shock_station else 1.0

            lam = (
                self.config.base_trip_rate
                * activity
                * self._origin_weight(sid, hour)
                * drift_factor
                * shock_mult
                * duration_scale
            )
            requested = self._poisson(self.rng, lam)
            completed = min(requested, allowed_drain)
            station.bikes -= completed
            station.rentals += completed
            station.failed_rentals += requested - completed

            # Check if departures push station into DEFICIT special cause (<= 2)
            if station.bikes <= self.config.lcl or sid == shock_station:
                if station.bikes <= self.config.lcl:
                    station.special_cause_active = True
                    station.special_cause_type = "DEFICIT"

            # Route completed trips to other stations
            grouped: dict[tuple[str, datetime], int] = {}
            for _ in range(completed):
                dest = self._weighted_choice(self._destination_weights(sid, hour))
                arrival = self.current_time + timedelta(
                    minutes=self._travel_minutes(sid, dest)
                )
                grouped[(dest, arrival)] = grouped.get((dest, arrival), 0) + 1
            self.in_transit.extend(
                TripBatch(dest, count, arrival)
                for (dest, arrival), count in grouped.items()
            )

    def _overnight_rebalance(self) -> None:
        """Proportional rebalance after Monday based on the previous day's time-averaged occupancy.

        Distributes the 50 station bikes across stations proportionally to their
        average daily bike levels, bounded by dock capacity [0, 20]. The remaining
        50 bikes remain in reserve.
        """
        total = min(self.config.overnight_rebalance_total, self.fleet_size)
        means = {
            sid: (sum(values) / len(values) if values else float(self.config.initial_bikes_per_station))
            for sid, values in self._daily_occupancy.items()
        }
        mean_sum = sum(means.values())
        if mean_sum > 0:
            raw = {sid: total * (means[sid] / mean_sum) for sid in STATION_META}
        else:
            raw = {sid: total / len(STATION_META) for sid in STATION_META}

        target = {sid: min(self.config.capacity, int(raw[sid])) for sid in STATION_META}
        remaining = total - sum(target.values())
        for sid in sorted(STATION_META, key=lambda x: raw[x] - int(raw[x]), reverse=True):
            if remaining == 0:
                break
            if target[sid] < self.config.capacity:
                target[sid] += 1
                remaining -= 1

        self.reserve += sum(s.bikes for s in self.stations.values()) + sum(t.bikes for t in self.in_transit)
        self.in_transit = []
        for station in self.stations.values():
            station.bikes = 0
            station.special_cause_active = False
            station.special_cause_type = "NONE"
        for sid, desired in target.items():
            moved = min(desired, self.reserve)
            self.stations[sid].bikes = moved
            self.reserve -= moved

        self._daily_occupancy = {sid: [] for sid in STATION_META}
        self._station_day_drift = self._new_day_drift()

    def step(self) -> dict[str, Any]:
        """Advance the simulation by one 15-minute tick."""
        with self._lock:
            old_date = self.current_time.date()
            self.current_time += timedelta(minutes=self.config.simulation_minutes_per_tick)
            self.tick_number += 1
            self._update_walk_drift()
            self._process_arrivals()
            self._generate_departures()
            for sid, station in self.stations.items():
                self._daily_occupancy[sid].append(station.bikes)
            event = "TICK"
            if self.current_time.date() != old_date:
                self._overnight_rebalance()
                event = "OVERNIGHT_REBALANCE"
            self._assert_invariants()
            snapshot = self.snapshot()
            self._record_snapshot(event)

        for callback in tuple(self._subscribers):
            try:
                callback(snapshot)
            except Exception:
                pass
        return snapshot

    def snapshot(self) -> dict[str, Any]:
        """Return full structured state snapshot of the network."""
        with self._lock:
            transit = sum(t.bikes for t in self.in_transit)
            station_rows = []
            active_special_causes = []
            for sid, state in self.stations.items():
                row = asdict(state)
                row.update(STATION_META[sid])
                row["docks"] = state.docks
                row["status"] = state.status
                row["occupancy_pct"] = round(100.0 * state.bikes / state.capacity, 1)
                row["is_unusable"] = state.is_unusable
                row["unusable_reason"] = state.unusable_reason
                row["special_cause_active"] = state.special_cause_active
                row["special_cause_type"] = state.special_cause_type
                row["alert"] = (
                    state.bikes <= self.config.lcl
                    or state.bikes >= self.config.ucl
                    or state.special_cause_active
                )
                if state.special_cause_active or state.bikes <= self.config.lcl or state.bikes >= self.config.ucl:
                    active_special_causes.append(sid)
                station_rows.append(row)

            unusable = sum(row["is_unusable"] for row in station_rows)
            return {
                "simulation_id": f"ithaca-{self.seed}",
                "seed": self.seed,
                "timestamp": self.current_time.isoformat(),
                "tick": self.tick_number,
                "stations": station_rows,
                "reserve": self.reserve,
                "in_transit": transit,
                "fleet_size": self.fleet_size,
                "fleet_accounted": (
                    sum(s.bikes for s in self.stations.values()) + self.reserve + transit
                ),
                "unusable_station_fraction": unusable / len(station_rows),
                "ucl": self.config.ucl,
                "lcl": self.config.lcl,
                "active_special_causes": active_special_causes,
                "requires_operator_remedy": len(active_special_causes) > 0,
                "running": self.running,
            }

    def dispatch(
        self, source: str, destination: str, quantity: int, reason: str = "operator"
    ) -> dict[str, Any]:
        """Dispatch maintenance van to move bikes.

        Crucially: issuing an operator dispatch to a station suffering from Special Cause
        clears and resolves the special cause condition!
        """
        if quantity <= 0:
            raise ValueError("quantity must be positive")

        source_clean = resolve_station_name(source)
        dest_clean = resolve_station_name(destination)

        with self._lock:
            if dest_clean == "RESERVE":
                if source_clean not in self.stations:
                    raise ValueError(f"source must be a station when moving to RESERVE: {list(STATION_META.keys())}")
                src = self.stations[source_clean]
                moved = min(quantity, src.bikes)
                src.bikes -= moved
                self.reserve += moved
                # If source was locked in SURPLUS special cause and moved below UCL, clear it!
                if src.special_cause_active and src.bikes < self.config.ucl:
                    src.special_cause_active = False
                    src.special_cause_type = "NONE"
            elif dest_clean in self.stations:
                dest = self.stations[dest_clean]
                if source_clean == "RESERVE":
                    available = self.reserve
                elif source_clean in self.stations and source_clean != dest_clean:
                    available = self.stations[source_clean].bikes
                else:
                    raise ValueError(
                        f"source must be RESERVE or a station different from destination"
                    )
                moved = min(quantity, available, dest.docks)
                if source_clean == "RESERVE":
                    self.reserve -= moved
                else:
                    src = self.stations[source_clean]
                    src.bikes -= moved
                    if src.special_cause_active and src.bikes < self.config.ucl:
                        src.special_cause_active = False
                        src.special_cause_type = "NONE"
                dest.bikes += moved

                # If destination was locked in DEFICIT special cause and moved above LCL, clear it!
                if dest.special_cause_active and dest.bikes > self.config.lcl:
                    dest.special_cause_active = False
                    dest.special_cause_type = "NONE"
            else:
                raise ValueError(f"destination must be RESERVE or a station: {list(STATION_META.keys())}")

            if self._conn:
                self._conn.execute(
                    "INSERT INTO dispatches(timestamp,source,destination,requested,moved,reason) VALUES(?,?,?,?,?,?)",
                    (
                        self.current_time.isoformat(),
                        source_clean,
                        dest_clean,
                        quantity,
                        moved,
                        reason,
                    ),
                )
                self._conn.commit()
            self._assert_invariants()
            self._record_snapshot("DISPATCH")
            return {
                "source": source_clean,
                "destination": dest_clean,
                "requested": quantity,
                "moved": moved,
                "state": self.snapshot(),
            }

    def recommendations(self) -> list[dict[str, Any]]:
        """Generate proactive and reactive van rebalancing recommendations.

        Prioritizes stations locked in Special Cause where operator intervention is mandatory.
        """
        with self._lock:
            actions = []
            for sid, s in self.stations.items():
                if s.special_cause_active or s.bikes <= self.config.lcl:
                    need = min(self.config.initial_bikes_per_station - s.bikes, s.docks)
                    if need > 0:
                        actions.append({
                            "source": "RESERVE",
                            "destination": sid,
                            "quantity": max(5, need),
                            "priority": "critical",
                            "special_cause": True,
                            "reason": f"SPECIAL CAUSE REMEDY REQUIRED: Station {sid} depleted ({s.bikes} bikes <= LCL {self.config.lcl}). Cannot self-correct.",
                        })
                elif s.special_cause_active or s.bikes >= self.config.ucl:
                    excess = s.bikes - self.config.initial_bikes_per_station
                    if excess > 0:
                        actions.append({
                            "source": sid,
                            "destination": "RESERVE",
                            "quantity": max(5, excess),
                            "priority": "critical",
                            "special_cause": True,
                            "reason": f"SPECIAL CAUSE REMEDY REQUIRED: Station {sid} overflow ({s.bikes} bikes >= UCL {self.config.ucl}). Cannot self-correct.",
                        })
                elif s.bikes < self.config.low_threshold:
                    need = self.config.initial_bikes_per_station - s.bikes
                    actions.append({
                        "source": "RESERVE",
                        "destination": sid,
                        "quantity": min(need, s.docks),
                        "priority": "warning",
                        "special_cause": False,
                        "reason": f"Common cause warning buffer at {sid} ({s.bikes} bikes).",
                    })
                elif s.bikes > self.config.high_threshold:
                    excess = s.bikes - self.config.initial_bikes_per_station
                    actions.append({
                        "source": sid,
                        "destination": "RESERVE",
                        "quantity": excess,
                        "priority": "warning",
                        "special_cause": False,
                        "reason": f"Common cause warning buffer at {sid} ({s.bikes} bikes).",
                    })
            return actions

    def query_history(
        self,
        station_id: str | None = None,
        limit: int = 1000,
        start_tick: int = 0,
        end_tick: int | None = None,
    ) -> list[dict[str, Any]]:
        """Query historical snapshots from SQLite persistence."""
        if not self._conn:
            return []
        sid_clean = resolve_station_name(station_id) if station_id else None
        with self._lock:
            query = "SELECT * FROM snapshots WHERE tick >= ?"
            params: list[Any] = [start_tick]
            if end_tick is not None:
                query += " AND tick <= ?"
                params.append(end_tick)
            if sid_clean:
                query += " AND station_id = ?"
                params.append(sid_clean)
            query += " ORDER BY id DESC LIMIT ?"
            params.append(limit)

            cursor = self._conn.execute(query, params)
            columns = [c[0] for c in cursor.description]
            rows = [dict(zip(columns, r)) for r in cursor.fetchall()]
            rows.reverse()
            return rows

    def spc_metrics(self, station_id: str | None = None) -> dict[str, Any]:
        """Compute live Six Sigma and I-MR Process Control metrics from historical telemetry."""
        with self._lock:
            if station_id:
                sid_clean = resolve_station_name(station_id)
                history = self.query_history(station_id=sid_clean, limit=2000)
                return calculate_station_spc(
                    history,
                    capacity=self.config.capacity,
                    target=float(self.config.initial_bikes_per_station),
                    ucl_spec=float(self.config.ucl),
                    lcl_spec=float(self.config.lcl),
                    low_warning=float(self.config.low_threshold),
                    high_warning=float(self.config.high_threshold),
                )
            all_spc = {}
            for sid in STATION_META:
                history = self.query_history(station_id=sid, limit=2000)
                all_spc[sid] = calculate_station_spc(
                    history,
                    capacity=self.config.capacity,
                    target=float(self.config.initial_bikes_per_station),
                    ucl_spec=float(self.config.ucl),
                    lcl_spec=float(self.config.lcl),
                    low_warning=float(self.config.low_threshold),
                    high_warning=float(self.config.high_threshold),
                )
            return all_spc

    def p_chart(self, limit: int = 5000) -> dict[str, Any]:
        """Compute Attribute Control Chart (p-chart & np-chart) across entire network."""
        with self._lock:
            all_history = self.query_history(limit=limit)
            return calculate_p_chart(
                all_history,
                n_stations=len(STATION_META),
                ucl_spec=float(self.config.ucl),
                lcl_spec=float(self.config.lcl),
            )

    def dmaic_report(self) -> dict[str, Any]:
        """Generate complete structured DMAIC analysis report for transport engineers."""
        with self._lock:
            station_histories = {
                sid: self.query_history(station_id=sid, limit=2000)
                for sid in STATION_META
            }
            return generate_dmaic_report(
                station_histories,
                STATION_META,
                reserve_inventory=self.reserve,
                fleet_size=self.fleet_size,
            )

    def subscribe(self, callback: Callable[[dict], None]) -> None:
        self._subscribers.append(callback)

    def start(self) -> None:
        with self._lock:
            if self.running:
                return
            self.running = True
            self._thread = threading.Thread(
                target=self._run_loop, name="bikeshare-simulator", daemon=True
            )
            self._thread.start()

    def _run_loop(self) -> None:
        deadline = time.monotonic()
        while self.running:
            deadline += self.config.wall_seconds_per_tick
            self.step()
            sleep_duration = max(0.0, deadline - time.monotonic())
            time.sleep(sleep_duration)

    def stop(self) -> None:
        self.running = False
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=self.config.wall_seconds_per_tick + 1.0)

    def reset(self) -> None:
        with self._lock:
            self.current_time = self.config.start_time
            self.tick_number = 0
            self.stations = {
                sid: StationState(
                    sid,
                    self.config.initial_bikes_per_station,
                    self.config.capacity,
                )
                for sid in STATION_META
            }
            self.reserve = self.config.initial_reserve
            self.in_transit = []
            self._daily_occupancy = {sid: [] for sid in STATION_META}
            self._station_day_drift = self._new_day_drift()
            self._walk_drift = {sid: 1.0 for sid in STATION_META}
            self._record_snapshot("RESET")
            self._assert_invariants()

    def _record_snapshot(self, event: str) -> None:
        if not self._conn:
            return
        transit = sum(t.bikes for t in self.in_transit)
        rows = []
        for sid, s in self.stations.items():
            rows.append((
                f"ithaca-{self.seed}",
                self.seed,
                self.tick_number,
                self.current_time.isoformat(),
                sid,
                STATION_META[sid]["zone"],
                s.bikes,
                s.docks,
                s.capacity,
                s.status,
                self.reserve,
                transit,
                s.rentals,
                s.returns,
                s.failed_rentals,
                s.failed_returns,
                1 if s.special_cause_active else 0,
                s.special_cause_type,
                event,
            ))
        self._conn.executemany(
            """INSERT INTO snapshots(simulation_id,seed,tick,timestamp,station_id,zone,bikes,docks,capacity,status,reserve,in_transit,rentals,returns,failed_rentals,failed_returns,special_cause_active,special_cause_type,event)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            rows,
        )
        self._conn.commit()

    def export_csv(self, output: str | Path) -> Path:
        if not self._conn:
            raise RuntimeError("CSV export requires persistence")
        output = Path(output)
        cursor = self._conn.execute("SELECT * FROM snapshots ORDER BY id")
        with output.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow([column[0] for column in cursor.description])
            writer.writerows(cursor)
        return output

    def _assert_invariants(self) -> None:
        for state in self.stations.values():
            if not 0 <= state.bikes <= state.capacity:
                raise AssertionError(
                    f"invalid occupancy at {state.station_id}: {state.bikes}"
                )
        accounted = (
            sum(s.bikes for s in self.stations.values())
            + self.reserve
            + sum(t.bikes for t in self.in_transit)
        )
        if accounted != self.fleet_size:
            raise AssertionError(
                f"fleet conservation failed: {accounted} != {self.fleet_size}"
            )

    def close(self) -> None:
        self.stop()
        if self._conn:
            self._conn.close()
            self._conn = None


def create_fastapi_app(simulator: BikeshareSimulator | None = None):
    """Factory creating FastAPI REST & SSE service for dashboard & backend integration."""
    try:
        import asyncio
        from fastapi import FastAPI, HTTPException, Query
        from fastapi.middleware.cors import CORSMiddleware
        from fastapi.responses import FileResponse, StreamingResponse
        from pydantic import BaseModel, Field
    except ImportError as exc:
        raise RuntimeError("Install API dependencies: pip install fastapi uvicorn") from exc

    sim = simulator or BikeshareSimulator()
    app = FastAPI(
        title="Ithaca Bikeshare Fleet Simulator & SPC API",
        version="2.1.0",
        description="Real-time telemetry, Six Sigma I-MR process control, and DMAIC analytics engine.",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.on_event("startup")
    def startup() -> None:
        pass

    @app.on_event("shutdown")
    def shutdown() -> None:
        sim.close()

    static_file = Path(__file__).parent / "static" / "index.html"

    @app.get("/", tags=["UI"])
    @app.get("/dashboard", tags=["UI"])
    def dashboard():
        if static_file.exists():
            return FileResponse(static_file, media_type="text/html")
        return {"message": "Bikeshare Simulator API Running. Visit /docs for Swagger."}

    @app.get("/health", tags=["System"])
    def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "running": sim.running,
            "tick": sim.tick_number,
            "current_time": sim.current_time.isoformat(),
            "fleet_size": sim.fleet_size,
        }

    @app.get("/api/v1/stations", tags=["Topology"])
    def get_stations() -> dict[str, Any]:
        """Return station metadata, coordinates, and zone classifications."""
        return STATION_META

    @app.get("/api/v1/state", tags=["Telemetry"])
    def state() -> dict[str, Any]:
        """Return current snapshot of all stations, inventory, and unusable metrics."""
        return sim.snapshot()

    @app.get("/api/v1/history", tags=["Telemetry"])
    def history(
        station_id: str | None = Query(None, description="Filter by station name or alias"),
        limit: int = Query(200, ge=1, le=5000, description="Max records to return"),
        start_tick: int = Query(0, ge=0),
        end_tick: int | None = Query(None),
    ) -> list[dict[str, Any]]:
        """Query time-series snapshot history for dashboards and trend analysis."""
        return sim.query_history(
            station_id=station_id, limit=limit, start_tick=start_tick, end_tick=end_tick
        )

    @app.get("/api/v1/spc", tags=["Six Sigma / SPC"])
    def spc_metrics(
        station_id: str | None = Query(None, description="Station name/alias, 'p_chart', or omit for all"),
    ) -> dict[str, Any]:
        """Compute real-time I-MR chart metrics, Cp, Cpk, Sigma Level, DPMO, UCL=18, LCL=2."""
        if station_id and station_id.lower() in ("p_chart", "pchart", "p-chart", "attribute"):
            return sim.p_chart()
        return sim.spc_metrics(station_id=station_id)

    @app.get("/api/v1/spc/p-chart", tags=["Six Sigma / SPC"])
    def p_chart_metrics(
        limit: int = Query(2000, ge=10, le=5000, description="Max history snapshots to analyze"),
    ) -> dict[str, Any]:
        """Compute Attribute Control Chart (p-chart & np-chart) based on SYSEN 5300 Lesson 5."""
        return sim.p_chart(limit=limit)

    @app.get("/api/v1/dmaic", tags=["Six Sigma / SPC"])
    def dmaic_report() -> dict[str, Any]:
        """Return full 5-phase DMAIC report for transport engineers."""
        return sim.dmaic_report()

    @app.get("/api/v1/recommendations", tags=["Rebalancing"])
    def recommendations() -> list[dict[str, Any]]:
        """Get automated maintenance van rebalancing recommendations prioritizing Special Cause."""
        return sim.recommendations()

    @app.post("/api/v1/dispatch", tags=["Rebalancing"])
    def dispatch(request: DispatchRequest) -> dict[str, Any]:
        """Execute maintenance van rebalance dispatch and resolve Special Cause."""
        try:
            return sim.dispatch(
                source=request.source,
                destination=request.destination,
                quantity=request.quantity,
                reason=request.reason,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/v1/step", tags=["Control"])
    def step() -> dict[str, Any]:
        """Manually advance the simulation by one 15-minute tick."""
        return sim.step()

    @app.post("/api/v1/start", tags=["Control"])
    def start_simulator() -> dict[str, Any]:
        """Start the continuous 10s real-time simulation thread."""
        sim.start()
        return {"running": True, "message": "Simulation started in real time"}

    @app.post("/api/v1/stop", tags=["Control"])
    def stop_simulator() -> dict[str, Any]:
        """Stop the background simulation thread."""
        sim.stop()
        return {"running": False, "message": "Simulation paused"}

    @app.post("/api/v1/reset", tags=["Control"])
    def reset_simulator() -> dict[str, Any]:
        """Reset the simulation back to Monday 00:00:00 initial state."""
        sim.reset()
        return {"running": sim.running, "message": "Simulation reset to Monday start"}

    @app.get("/api/v1/stream", tags=["Telemetry"])
    async def stream_telemetry():
        """Server-Sent Events (SSE) streaming live telemetry ticks as they occur."""
        queue: asyncio.Queue = asyncio.Queue(maxsize=50)
        loop = asyncio.get_event_loop()

        def listener(data: dict):
            try:
                loop.call_soon_threadsafe(queue.put_nowait, data)
            except Exception:
                pass

        sim.subscribe(listener)

        async def event_generator():
            try:
                initial = sim.snapshot()
                yield f"data: {json.dumps(initial)}\n\n"
                while True:
                    data = await queue.get()
                    yield f"data: {json.dumps(data)}\n\n"
            except asyncio.CancelledError:
                pass

        return StreamingResponse(event_generator(), media_type="text/event-stream")

    @app.get("/api/v1/export/csv", tags=["Export"])
    def export_csv() -> FileResponse:
        path = Path("bikeshare_export.csv")
        sim.export_csv(path)
        return FileResponse(
            path, media_type="text/csv", filename="bikeshare_snapshots.csv"
        )

    app.state.simulator = sim
    return app


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Ithaca Bikeshare Stateful Monte Carlo Simulator & DMAIC Generator"
    )
    parser.add_argument(
        "--seed", type=int, default=None, help="fixed seed for reproducible DMAIC validation"
    )
    parser.add_argument(
        "--ticks", type=int, default=96, help="number of 15-minute ticks (96=1 day, 672=7 days)"
    )
    parser.add_argument(
        "--wall-seconds",
        type=float,
        default=10.0,
        help="wall seconds per 15-minute tick (default 10.0s for operator intervention window)",
    )
    parser.add_argument("--db", default="bikeshare.db", help="SQLite database path")
    parser.add_argument("--csv", default="bikeshare_output.csv", help="output CSV path")
    parser.add_argument(
        "--realtime",
        action="store_true",
        help="run continuously in real time, advancing every wall tick",
    )
    parser.add_argument(
        "--api", action="store_true", help="launch FastAPI REST & SSE web server"
    )
    parser.add_argument("--host", default="0.0.0.0", help="API host (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8000, help="API port (default: 8000)")

    args = parser.parse_args()

    config = SimulatorConfig(
        database_path=args.db,
        wall_seconds_per_tick=args.wall_seconds,
    )
    sim = BikeshareSimulator(config, seed=args.seed)

    if args.api:
        try:
            import uvicorn
        except ImportError:
            print("uvicorn is required to run the API: pip install uvicorn")
            return
        app = create_fastapi_app(sim)
        sim.start()
        print(f"Starting Bikeshare API on http://{args.host}:{args.port}")
        uvicorn.run(app, host=args.host, port=args.port)
        return

    try:
        if args.realtime:
            sim.start()
            print(f"Simulator running in real time (1 tick every {args.wall_seconds}s). Press Ctrl+C to stop.")
            print(json.dumps(sim.snapshot(), indent=2))
            while True:
                time.sleep(args.wall_seconds)
                print(json.dumps(sim.snapshot()))
        else:
            print(f"Running simulation for {args.ticks} ticks (15 min each)...")
            for _ in range(args.ticks):
                sim.step()
            sim.export_csv(args.csv)
            print("\nFinal State Snapshot:")
            print(json.dumps(sim.snapshot(), indent=2))
            print(f"\nExported telemetry to {args.csv}")

            report = sim.dmaic_report()
            print("\n--- DMAIC / Process Capability Summary ---")
            print(f"System Mean Cpk: {report['measure']['system_mean_cpk']}")
            print(f"System DPMO:     {report['measure']['system_dpmo']}")
            print(f"Availability:    {report['measure']['system_availability_pct']}%")
            print("\nPareto Defect Ranking:")
            for p in report["analyze"]["pareto_defect_ranking"]:
                print(
                    f"  Station {p['station_id']} ({p['name']}): "
                    f"Defects={p['defects']} (Stockouts={p['stockouts']}, Overflows={p['overflows']}), "
                    f"Cpk={p['cpk']}, Status={p['status']}"
                )
    except KeyboardInterrupt:
        print("\nStopping simulation...")
    finally:
        sim.close()


if __name__ == "__main__":
    main()
