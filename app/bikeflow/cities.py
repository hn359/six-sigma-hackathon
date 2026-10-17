"""Load Yash's simulated cities from data/<city>/ (branch yash_work; rebuilt by data/simulate.py).

Each folder holds about.json (reading interval, first and last reading, fleet, the planted event-day
problems), stations.csv (id, name, lat, lon, capacity, role) and three readings files:
week1_baseline.csv (van-free, Phase I), week2_policy.csv and event_day.csv. Every city gets its own
Settings, so a 10-minute city or one that opens at 08:00 is read on its own grid.
"""

from __future__ import annotations

import csv
import json
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List

from .config import Settings
from .data import Dataset, parse_csv

READINGS = ["week1_baseline.csv", "week2_policy.csv", "event_day.csv"]
REQUIRED = ["about.json", "stations.csv", *READINGS]

# The team's network rules (Yash's SPEC): spec range 20%-80% of each station's docks, no weekend
# pattern in the simulation, and every bike that is not docked is in the reserve depot.
BASE = Settings(band_low_share=0.2, band_high_share=0.8, weekends_differ=False, depot_from_fleet=True)


def _plus(hhmm: str, minutes: int) -> str:
    t = datetime.strptime(hhmm, "%H:%M") + timedelta(minutes=minutes)
    return t.strftime("%H:%M")


def city_settings(about: dict, phase1_through: str) -> Settings:
    first = about["first_reading"]
    return replace(BASE, interval_min=int(about["interval_minutes"]), open_time=first,
                   close_time=about["last_reading"], fleet=int(about["fleet"]),
                   capacity=max(int(d) for d in about["docks"]),
                   morning_window=(first, _plus(first, 240)),      # the opening through the morning rush
                   phase1_through=phase1_through).validate()


def planted_events(about: dict, event_day: str) -> List[dict]:
    """The event-day problems from about.json, as {kind, station, day, from, to, what}."""
    out = []
    for kind, ev in (about.get("event") or {}).items():
        what = {"slow_drain": f"slow drain: {ev.get('extra_rentals_per_reading', '?')} extra rental(s) per reading",
                "crowd": f"crowd: {ev.get('riders_per_reading', '?')} extra riders per reading arriving"}.get(kind, kind)
        out.append({"kind": kind, "station": ev["station"], "day": event_day,
                    "from": ev["from"], "to": ev["to"], "what": what})
    return out


def load_city(folder: Path) -> dict:
    folder = Path(folder)
    about = json.loads((folder / "about.json").read_text(encoding="utf-8"))
    with open(folder / "stations.csv", encoding="utf-8") as f:
        stations = list(csv.DictReader(f))
    parts = [(folder / name).read_text(encoding="utf-8-sig").strip().splitlines() for name in READINGS]
    week1_days = sorted({line.split(",")[1][:10] for line in parts[0][1:] if line.strip()})
    event_days = sorted({line.split(",")[1][:10] for line in parts[2][1:] if line.strip()})
    settings = city_settings(about, week1_days[-1])
    text = "\n".join(parts[0] + [line for p in parts[1:] for line in p[1:]]) + "\n"
    ds: Dataset = parse_csv(text, settings)
    trips = []
    if (folder / "trips.csv").exists():          # one row per simulated rider trip (data/README.md)
        with open(folder / "trips.csv", encoding="utf-8") as f:
            trips = [(r["timestamp"], r["from_station"], r["to_station"]) for r in csv.DictReader(f)]
    return {"id": about.get("id", folder.name), "name": about.get("name", folder.name), "about": about,
            "trips": trips,
            "dataset": ds,
            "names": {r["station_id"]: r["name"] for r in stations},
            "places": {r["station_id"]: {"lat": float(r["lat"]), "lon": float(r["lon"])}
                       for r in stations if r.get("lat") and r.get("lon")},
            "roles": {r["station_id"]: r.get("role", "") for r in stations},
            "phase1_days": week1_days, "event_day": event_days[0] if event_days else None,
            "events": planted_events(about, event_days[0]) if event_days else []}


def load_all(data_dir: Path) -> Dict[str, dict]:
    """Every subfolder of data/ that holds a complete city, keyed by its id."""
    out = {}
    if not Path(data_dir).is_dir():
        return out
    for folder in sorted(p for p in Path(data_dir).iterdir() if p.is_dir()):
        if all((folder / f).exists() for f in REQUIRED):
            city = load_city(folder)
            out[city["id"]] = city
    return out
