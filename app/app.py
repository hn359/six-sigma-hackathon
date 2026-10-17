"""
Bikeshare dispatch API: a thin FastAPI layer. No statistics here; app/engine.py organises
readings and app/qc.py does every calculation. Frames follow docs/map-contract.md.

Datasets: every folder data/<id>/ holding stations.csv, a Week 1 baseline, policy weeks, an
event_day.csv and about.json is loaded at startup. Each policy week uses the preceding complete
week's learned flow and control limits; Week 1 and Week 2 remain the original comparison.
"""

import csv
import json
import re
import time
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

try:
    from app import engine
except ImportError:  # running from inside app/ (e.g. on Posit Connect)
    import engine

HERE = Path(__file__).resolve().parent
DATA = next((d for d in (HERE.parent / "data", HERE / "data") if d.is_dir()), None)
WEEK_FILE = re.compile(r"week(\d+)_policy\.csv$")
DEFAULT = "collegetown"
LIVE_SECONDS_PER_READING = 5

app = FastAPI(
    title="Bikeshare Dispatch",
    description="After every reading: an I-chart of slot-adjusted net flow with Western Electric rules, "
                "and a van move when a station signals or leaves its spec limits (20%-80% of its docks). "
                "Frames follow docs/map-contract.md.",
    version="2.0.0",
)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


def _load_all():
    if DATA is None:
        raise RuntimeError("data/ not found: run python data/simulate.py")
    out = {}
    for folder in sorted(p for p in DATA.iterdir() if (p / "stations.csv").exists()):
        stations = engine.parse_stations((folder / "stations.csv").read_text())
        week_files = {1: "week1_baseline.csv"}
        for candidate in folder.glob("week*_policy.csv"):
            match = WEEK_FILE.fullmatch(candidate.name)
            if match:
                week_files[int(match.group(1))] = candidate.name
        days = {f"week{number}": engine.parse_readings((folder / filename).read_text())
                for number, filename in sorted(week_files.items()) if (folder / filename).exists()}
        days["event"] = engine.parse_readings((folder / "event_day.csv").read_text())
        about = json.loads((folder / "about.json").read_text()) if (folder / "about.json").exists() else {"id": folder.name}
        adaptive = json.loads((folder / "adaptive_plans.json").read_text()) if (folder / "adaptive_plans.json").exists() else {}
        trips = {}
        if (folder / "trips.csv").exists():   # every simulated rider trip, for the map's cyclists
            with open(folder / "trips.csv") as fh:
                for r in csv.DictReader(fh):
                    trips.setdefault(r["timestamp"][:10], []).append(
                        {"timestamp": r["timestamp"], "from": r["from_station"], "to": r["to_station"]})
        out[folder.name] = {"stations": stations, "days": days, "about": about, "trips": trips,
                            "adaptive": adaptive,
                            "hist": engine.learn(days["week1"], sorted(stations))}
    if not out:
        raise RuntimeError("no datasets in data/: run python data/simulate.py")
    return out


DATASETS = _load_all()


def _ds(dataset):
    if dataset not in DATASETS:
        raise HTTPException(404, f"unknown dataset; use one of {list(DATASETS)}")
    return DATASETS[dataset]


def _day(ds, scenario, day):
    if scenario not in ds["days"]:
        raise HTTPException(404, f"unknown scenario; use one of {list(ds['days'])}")
    dates = sorted(ds["days"][scenario])
    if not 0 <= day < len(dates):
        raise HTTPException(404, f"{scenario} has days 0..{len(dates) - 1}")
    return dates[day], ds["days"][scenario][dates[day]]


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/datasets")
def datasets():
    """The simulated networks: their size, reading interval and days per scenario."""
    return [{**ds["about"], "id": key, "days": {s: [str(d) for d in sorted(v)] for s, v in ds["days"].items()}}
            for key, ds in DATASETS.items()]


@app.get("/scenarios")
def scenarios(dataset: str = DEFAULT):
    return {name: [str(d) for d in sorted(days)] for name, days in _ds(dataset)["days"].items()}


LIMITS = ("phase", "rolling", "week1")


def _phase_history(ds, scenario):
    """The frozen reference used to judge and dispatch the selected complete policy week."""
    week_numbers = sorted(int(name[4:]) for name in ds["days"] if name.startswith("week"))
    if scenario == "week1":
        reference_week = 1
    elif scenario == "event":
        reference_week = max(week_numbers)
    else:
        current_week = int(scenario[4:])
        reference_week = current_week - 1
    if reference_week == 1:
        result = {sid: {**h, "basis": "Week 1 baseline (7 days)",
                        "basis_days": [str(d) for d in sorted(ds["days"]["week1"])]}
                  for sid, h in ds["hist"].items()}
    else:
        result = engine.learn(ds["days"][f"week{reference_week}"], sorted(ds["stations"]))
        basis_days = [str(d) for d in sorted(ds["days"][f"week{reference_week}"])]
        for h in result.values():
            h["basis"] = f"Week {reference_week} baseline ({len(basis_days)} days)"
            h["basis_days"] = basis_days
    target_scenario = scenario if scenario != "event" else ds.get("adaptive", {}).get("next_week_plan")
    targets = (ds.get("adaptive", {}).get("plans", {}).get(target_scenario, {}).get("targets") or {})
    for sid, value in targets.items():
        if sid in result:
            result[sid]["overnight_start"] = int(value)
    return result, reference_week


def _chart_hist(ds, date, limits, phase_hist):
    """The chart history is phase-frozen by default, or can show rolling/week-1 diagnostics."""
    if limits not in LIMITS:
        raise HTTPException(400, f"limits must be one of {list(LIMITS)}")
    if limits == "phase":
        return phase_hist
    if limits == "week1":
        return ds["hist"]
    every = {d: v for name, days in ds["days"].items() if name != "event" for d, v in days.items()}
    return engine.rolling_history(every, date, sorted(ds["stations"]), ds["hist"])


@app.get("/frames/{scenario}")
def frames(scenario: str, day: int = Query(0, ge=0), dataset: str = DEFAULT, limits: str = "phase"):
    """Every reading of one day, oldest first, plus each station's chart centre, sigma and spec limits.
    limits=phase (default): the selected policy week and van use the previous complete week's limits;
    limits=rolling: chart-only rolling limits; limits=week1: fixed Week 1 chart comparison."""
    ds = _ds(dataset)
    date, data = _day(ds, scenario, day)
    phase_hist, baseline_week = _phase_history(ds, scenario)
    ch = _chart_hist(ds, date, limits, phase_hist)
    return engine.clean({"dataset": dataset, "scenario": scenario, "date": str(date), "limits": limits,
                         "baseline_week": baseline_week,
                         "frames": engine.day_frames(data, ds["stations"], phase_hist, policy=scenario != "week1",
                                                     chart_hist=ch),
                         "chart": engine.chart_meta(ch)})


@app.get("/latest")
def latest(scenario: str = "event", day: int = 0, dataset: str = DEFAULT, limits: str = "phase"):
    """Live mode: the frame 'now', replaying the day at one reading every 5 seconds."""
    ds = _ds(dataset)
    date, data = _day(ds, scenario, day)
    phase_hist, _ = _phase_history(ds, scenario)
    f = engine.day_frames(data, ds["stations"], phase_hist, policy=scenario != "week1",
                          chart_hist=_chart_hist(ds, date, limits, phase_hist))
    return engine.clean(f[int(time.time() // LIVE_SECONDS_PER_READING) % len(f)])


@app.post("/replay")
async def replay(readings: UploadFile = File(...), stations: UploadFile = File(...)):
    """Upload any readings CSV and stations CSV.

    If the stations belong to a known dataset, its history is used. Otherwise the history is learned
    from the upload itself (its days with no van moves, else its first half) and the other days are
    replayed; with a single-part upload every day is replayed against what was learned.
    """
    try:
        st = engine.parse_stations((await stations.read()).decode("utf-8-sig"))
        days = engine.parse_readings((await readings.read()).decode("utf-8-sig"))
        known = next((k for k, ds in DATASETS.items() if set(st) <= set(ds["hist"])), None)
        if known:
            hist, judged, source = DATASETS[known]["hist"], days, f"dataset {known}"
        else:
            base, rest = engine.split_baseline(days)
            hist = engine.learn(base, sorted(st))
            judged = rest or days
            source = f"learned from {len(base)} day(s) of the upload"
        out = []
        for date in sorted(judged):
            out += engine.day_frames(judged[date], st, hist, policy=True)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if not out:
        raise HTTPException(400, "no readings to replay")
    return engine.clean({"frames": out, "chart": engine.chart_meta(hist), "history": source})


@app.get("/trips/{scenario}")
def trips(scenario: str, day: int = Query(0, ge=0), dataset: str = DEFAULT):
    """Every rider trip of one day: the reading that ends its interval, where it started and ended.

    Display only (the map's cyclists): the statistics use the station readings, not the trips."""
    ds = _ds(dataset)
    date, _ = _day(ds, scenario, day)
    return {"dataset": dataset, "scenario": scenario, "date": str(date), "trips": ds["trips"].get(str(date), [])}


@app.get("/summary")
def summary(dataset: str = DEFAULT):
    """Night plan, rush slots, weekly p-charts (baseline limits, policy week judged) and before/after counts."""
    ds = _ds(dataset)
    weeks = ds.get("adaptive", {}).get("weeks", [])
    stable_week = next((w["week"] for w in weeks if w.get("stable_run", 0) >= 2), None)
    best = min(weeks, key=lambda w: (w.get("rate", 1), w.get("week", 0))) if weeks else None
    weekly_deviation = {
        "weeks": [{k: w.get(k) for k in ("week", "rate", "status", "baseline_week", "center", "lcl", "ucl",
                                           "defects", "readings", "signals", "stable_run")}
                  for w in weeks],
        "best_week": best.get("week") if best else None,
        "stable_week": stable_week,
        "stable": stable_week is not None,
        "measure": "share of station readings outside the 20%-80% dock range",
        "limits": "weekly p-chart limits learned from the immediately preceding complete week"
    }
    return engine.clean({"dataset": dataset, "about": ds["about"],
                         "weekly_deviation": weekly_deviation,
                         **engine.summary(ds["days"]["week1"], ds["days"]["week2"], ds["stations"], ds["hist"])})


@app.get("/__docs__/")
def docs_redirect():
    return RedirectResponse(url="/docs")


# The built React app (app/frontend/dist), served at / when it exists.
DIST = HERE / "frontend" / "dist"
if DIST.exists():
    app.mount("/", StaticFiles(directory=DIST, html=True), name="frontend")
