"""FastAPI router for BikeFlow. No statistics here: it parses query parameters, calls analyze/plan
and returns their dicts.

Mount it in any FastAPI app:   app.include_router(router)      (routes live under /api/bikeflow)

Datasets are held in memory by name: Yash's simulated cities (server.load_default reads data/<city>/),
plus "uploaded" for a CSV posted to /dataset or named by $BIKEFLOW_DATA. Every route takes
?dataset=<name>; without it, the default (collegetown when present). No database, by design.
"""

from __future__ import annotations

import os
from datetime import date, datetime
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query, Request

from . import analyze, plan
from .config import Settings
from .data import Dataset, parse_csv

router = APIRouter(prefix="/api/bikeflow", tags=["bikeflow"])
# datasets: name -> {"dataset", "name", "names", "places", "events", "about", ...}
_state = {"datasets": {}, "default": None}
UPLOADED = "uploaded"


def register(key: str, entry: dict, default: bool = False) -> dict:
    _state["datasets"][key] = entry
    if default or _state["default"] not in _state["datasets"]:
        _state["default"] = key
    return entry


def reset():
    _state["datasets"].clear()
    _state["default"] = None


def settings_from(params: dict, base: Optional[Settings] = None) -> Settings:
    fields = Settings.__dataclass_fields__
    given = {k: v for k, v in params.items() if v is not None and k in fields}
    return Settings(**{**(base or Settings()).__dict__, **given}).validate()


def load_text(text: str, settings: Optional[Settings] = None, key: str = UPLOADED) -> Dataset:
    ds = parse_csv(text, settings or Settings())
    register(key, {"dataset": ds, "name": "Uploaded CSV", "names": {}, "places": {}, "events": []})
    return ds


def _entry(dataset: Optional[str]) -> dict:
    if not _state["datasets"]:
        path = os.environ.get("BIKEFLOW_DATA")
        if path and Path(path).exists():
            load_text(Path(path).read_text(encoding="utf-8-sig"))
    if not _state["datasets"]:
        raise HTTPException(404, "no dataset loaded: POST a snapshots CSV to /api/bikeflow/dataset "
                                 "or set BIKEFLOW_DATA")
    key = dataset or _state["default"]
    if key not in _state["datasets"]:
        raise HTTPException(404, f"unknown dataset {key!r}; use one of {list(_state['datasets'])}")
    return _state["datasets"][key]


def _ds(dataset: Optional[str] = None) -> Dataset:
    return _entry(dataset)["dataset"]


def _day(value: Optional[str], default: Optional[date] = None) -> Optional[date]:
    if not value:
        return default
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise HTTPException(400, f"{value!r} is not a date like 2026-10-05")


def _guard(fn, *a, **kw):
    try:
        return fn(*a, **kw)
    except ValueError as e:
        raise HTTPException(400, str(e))


def _stations(ds: Dataset, station: Optional[List[str]]) -> List[str]:
    chosen = [x for s in (station or []) for x in s.split(",") if x] or ds.stations()
    unknown = [s for s in chosen if s not in ds.stations()]
    if unknown:
        raise HTTPException(400, f"unknown station(s) {unknown}; known: {ds.stations()}")
    return chosen


def _summary(key: str) -> dict:
    e = _entry(key)
    return {**analyze.summary(e["dataset"]), "dataset": key, "dataset_name": e.get("name", key),
            "names": e.get("names", {}), "places": e.get("places", {}), "roles": e.get("roles", {}),
            "events": e.get("events", []), "phase1_days": e.get("phase1_days", []),
            "event_day": e.get("event_day")}


@router.get("/datasets")
async def datasets():
    out = []
    for key, e in _state["datasets"].items():
        ds, s = e["dataset"], e["dataset"].settings
        out.append({"id": key, "name": e.get("name", key), "interval_minutes": s.interval_min,
                    "first_reading": s.open_time, "last_reading": s.close_time, "fleet": s.fleet,
                    "stations": ds.stations(), "days": [d.isoformat() for d in ds.days()],
                    "default": key == _state["default"]})
    return {"datasets": out}


@router.post("/dataset")
async def upload(request: Request, fleet: Optional[int] = None, capacity: Optional[int] = None,
                 interval_min: Optional[int] = None, open_time: Optional[str] = None,
                 close_time: Optional[str] = None, target_share: Optional[float] = None,
                 band_low_share: Optional[float] = None, band_high_share: Optional[float] = None):
    """Body: the raw text of a station-snapshot CSV (see app/bikeflow/data.py for the columns).
    It is stored as the dataset "uploaded"."""
    text = (await request.body()).decode("utf-8-sig")
    s = _guard(settings_from, dict(fleet=fleet, capacity=capacity, interval_min=interval_min,
                                   open_time=open_time, close_time=close_time, target_share=target_share,
                                   band_low_share=band_low_share, band_high_share=band_high_share))
    _guard(load_text, text, s)
    return _summary(UPLOADED)


@router.get("/summary")
async def summary(dataset: Optional[str] = None):
    _entry(dataset)                            # loads $BIKEFLOW_DATA if nothing is loaded yet
    return _summary(dataset or _state["default"])


@router.get("/scorecard")
async def scorecard(dataset: Optional[str] = None, limits: Optional[str] = None):
    """Did the control chart catch each planted problem (about.json), and the false-alarm rate on
    the Phase II days without one."""
    e = _entry(dataset)
    return _guard(analyze.scorecard, e["dataset"], e.get("events", []), limits)


@router.get("/trips")
async def trips(start: str, end: str, dataset: Optional[str] = None):
    """From-to trip counts with a timestamp after `start` and up to `end` (ISO date-times), from the
    city's trips.csv. 404 when the dataset has no trip records."""
    e = _entry(dataset)
    if not e.get("trips"):
        raise HTTPException(404, "this dataset has no trip records (data/<city>/trips.csv)")
    for v in (start, end):
        try:
            datetime.fromisoformat(v)
        except ValueError:
            raise HTTPException(400, f"{v!r} is not a time like 2026-10-19T08:00")
    return analyze.trip_matrix(e["trips"], e["dataset"].stations(), start, end)


@router.get("/trips/events")
async def trip_events(start: str, end: str, dataset: Optional[str] = None):
    """Individual simulated rider trips during an ISO time window, for map animation."""
    e = _entry(dataset)
    if not e.get("trips"):
        raise HTTPException(404, "this dataset has no trip records (data/<city>/trips.csv)")
    try:
        first, last = datetime.fromisoformat(start), datetime.fromisoformat(end)
    except ValueError:
        raise HTTPException(400, "start and end must be ISO times such as 2026-10-19T06:00")
    if first > last:
        raise HTTPException(400, "start must be before or equal to end")
    return {"trips": [{"timestamp": t, "from_station": a, "to_station": b}
                      for t, a, b in e["trips"] if start <= t <= end]}


@router.get("/inventory")
async def inventory(station: Optional[List[str]] = Query(None), start: Optional[str] = None,
                    end: Optional[str] = None, dataset: Optional[str] = None):
    ds = _ds(dataset)
    return _guard(analyze.inventory_view, ds, _stations(ds, station), _day(start), _day(end))


@router.get("/flow")
async def flow(station: Optional[List[str]] = Query(None), start: Optional[str] = None,
               end: Optional[str] = None, period: Optional[str] = None, dataset: Optional[str] = None):
    ds = _ds(dataset)
    if period is not None and period not in analyze.PERIODS:
        raise HTTPException(400, f"period must be one of {analyze.PERIODS}")
    return _guard(analyze.flow_view, ds, _stations(ds, station), _day(start), _day(end), period)


@router.get("/spc")
async def spc(station: str, start: str, end: str, measure: str = "net_flow",
              day_type: Optional[str] = None, dataset: Optional[str] = None, limits: Optional[str] = None):
    """limits: rolling (default: the last 7 clean days before each day) or week1 (fixed)."""
    ds = _ds(dataset)
    if station not in ds.stations():
        raise HTTPException(400, f"unknown station {station!r}; known: {ds.stations()}")
    if day_type not in (None, "weekday", "weekend", "day"):
        raise HTTPException(400, "day_type must be weekday, weekend or day")
    return _guard(analyze.spc_view, ds, station, _day(start), _day(end), measure, day_type, limits)


@router.get("/plan")
async def plan_endpoint(at: str, depot_bikes: Optional[int] = None, dataset: Optional[str] = None):
    """The plan for a reading time, e.g. at=2026-10-05T08:15."""
    try:
        when = datetime.fromisoformat(at)
    except ValueError:
        raise HTTPException(400, f"{at!r} is not a time like 2026-10-05T08:15")
    return _guard(plan.plan_now, _ds(dataset), when, depot_bikes)


@router.get("/plan/overnight")
async def plan_overnight(day: str, depot_bikes: Optional[int] = None, dataset: Optional[str] = None):
    """The 10 PM plan for the next morning's opening."""
    return _guard(plan.plan_overnight, _ds(dataset), _day(day), depot_bikes)
