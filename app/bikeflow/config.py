"""Settings for BikeFlow. Every number the module assumes lives here, so a dispatcher (or another
branch) can change it without touching the statistics."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class Settings:
    capacity: int = 20              # docks per station, used when the data has no docks/capacity column
    fleet: int = 120                # bikes in the whole city: stations + depot/van + in use
    target_share: float = 0.5       # target bikes, as a share of the station's docks (10 of 20)
    band_low_share: float = 0.25    # target range as shares of the docks (5-15 of 20, inclusive);
    band_high_share: float = 0.75   # outside it a station is flagged. Yash's spec: 0.20 / 0.80
    open_time: str = "06:00"
    close_time: str = "22:00"
    interval_min: int = 15
    morning_rush: tuple = ("07:00", "10:00")    # [start, end), weekdays
    evening_rush: tuple = ("16:00", "19:00")
    horizon_slots: int = 4          # daytime projection horizon: 4 x 15 min = 1 hour
    min_history_days: int = 2       # comparable days needed before a projection counts as reliable
    recurring_share: float = 0.5    # empty/full on at least this share of comparable days = recurring
    morning_window: tuple = ("06:00", "10:00")  # overnight plan covers the opening through the morning rush
    buffer: int = 2                 # overnight plan keeps this many bikes and docks spare all morning
    depart_share: float = 0.8       # 10 PM plan: start of the station riders most depart from
    arrive_share: float = 0.2       # 10 PM plan: start of the station riders most arrive at
    weekends_differ: bool = True    # compare weekdays with weekdays, weekends with weekends
    depot_from_fleet: bool = False  # True when every undocked bike is in the depot (as in a simulation
                                    # where trips finish inside the 15 minutes): depot = fleet - docked
    phase1_through: Optional[str] = None  # last Phase I day (ISO date): Yash's van-free week 1
    limits_mode: str = "rolling"    # "rolling": each day is charted against the last `rolling_days`
                                    # days before it, cleaned of readings beyond 3 sigma (updates daily);
                                    # "week1": the fixed Phase I days (comparison mode)
    rolling_days: int = 7

    def validate(self) -> "Settings":
        if self.capacity < 1 or self.fleet < 0 or self.interval_min < 1:
            raise ValueError("capacity and interval must be at least 1, fleet at least 0")
        if not 0 <= self.band_low_share <= self.target_share <= self.band_high_share <= 1:
            raise ValueError(
                f"need 0 <= band_low_share ({self.band_low_share}) <= target_share ({self.target_share}) "
                f"<= band_high_share ({self.band_high_share}) <= 1")
        if hhmm(self.close_time) <= hhmm(self.open_time):
            raise ValueError("close_time must be after open_time")
        if not 0 <= self.arrive_share <= 0.5 <= self.depart_share <= 1:
            raise ValueError("need 0 <= arrive_share <= 0.5 <= depart_share <= 1")
        if self.limits_mode not in ("rolling", "week1"):
            raise ValueError("limits_mode must be 'rolling' or 'week1'")
        if self.horizon_slots < 1 or self.min_history_days < 1 or self.buffer < 0 or self.rolling_days < 2:
            raise ValueError("horizon_slots and min_history_days must be at least 1, buffer at least 0")
        return self

    @property
    def n_slots(self) -> int:
        """Readings per day: 06:00, 06:15, ..., 22:00 is 65."""
        return (hhmm(self.close_time) - hhmm(self.open_time)) // self.interval_min + 1

    def slot_of(self, t) -> int | None:
        """Index of the 15-minute slot a time falls in (0 = opening), or None outside operating hours."""
        minutes = t.hour * 60 + t.minute - hhmm(self.open_time)
        if minutes < 0 or minutes > hhmm(self.close_time) - hhmm(self.open_time):
            return None
        return minutes // self.interval_min

    def band(self, capacity: int) -> tuple:
        """(low, high) bikes of the target range for a station of this many docks, halves rounded up
        (as Yash's qc.spec_limits: 20 docks -> 4-16 at 20%/80%, 31 -> 6-25, 12 -> 2-10)."""
        return (math.floor(self.band_low_share * capacity + 0.5), math.floor(self.band_high_share * capacity + 0.5))

    def target_for(self, capacity: int) -> int:
        return math.floor(self.target_share * capacity + 0.5)

    def kind(self, d) -> str:
        """Which days count as comparable: weekday/weekend, or every day alike."""
        return day_type(d) if self.weekends_differ else "day"

    def slot_time(self, slot: int) -> str:
        m = hhmm(self.open_time) + slot * self.interval_min
        return f"{m // 60:02d}:{m % 60:02d}"


def hhmm(s: str) -> int:
    h, m = s.split(":")
    return int(h) * 60 + int(m)


def day_type(d) -> str:
    return "weekend" if d.weekday() >= 5 else "weekday"
