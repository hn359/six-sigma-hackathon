"""
Bikeshare dispatch API: a thin FastAPI layer. No statistics here; app/engine.py organises
readings and app/qc.py does every calculation. Frames follow docs/map-contract.md.

Datasets: every folder data/<id>/ holding stations.csv, week1_baseline.csv (no van: Phase I),
week2_policy.csv and event_day.csv (with van moves) and about.json is loaded at startup.
"""

import json
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
FILES = {"week1": "week1_baseline.csv", "week2": "week2_policy.csv", "event": "event_day.csv"}
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
        days = {name: engine.parse_readings((folder / f).read_text()) for name, f in FILES.items()}
        about = json.loads((folder / "about.json").read_text()) if (folder / "about.json").exists() else {"id": folder.name}
        out[folder.name] = {"stations": stations, "days": days, "about": about,
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


@app.get("/frames/{scenario}")
def frames(scenario: str, day: int = Query(0, ge=0), dataset: str = DEFAULT):
    """Every reading of one day, oldest first, plus each station's chart centre, sigma and spec limits."""
    ds = _ds(dataset)
    date, data = _day(ds, scenario, day)
    return engine.clean({"dataset": dataset, "scenario": scenario, "date": str(date),
                         "frames": engine.day_frames(data, ds["stations"], ds["hist"], policy=scenario != "week1"),
                         "chart": engine.chart_meta(ds["hist"])})


@app.get("/latest")
def latest(scenario: str = "event", day: int = 0, dataset: str = DEFAULT):
    """Live mode: the frame 'now', replaying the day at one reading every 5 seconds."""
    ds = _ds(dataset)
    _, data = _day(ds, scenario, day)
    f = engine.day_frames(data, ds["stations"], ds["hist"], policy=scenario != "week1")
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


@app.get("/summary")
def summary(dataset: str = DEFAULT):
    """Night plan, rush slots, weekly p-charts (baseline limits, policy week judged) and before/after counts."""
    ds = _ds(dataset)
    return engine.clean({"dataset": dataset, "about": ds["about"],
                         **engine.summary(ds["days"]["week1"], ds["days"]["week2"], ds["stations"], ds["hist"])})


@app.get("/__docs__/")
def docs_redirect():
    return RedirectResponse(url="/docs")


# The built React app (app/frontend/dist), served at / when it exists.
DIST = HERE / "frontend" / "dist"
if DIST.exists():
    app.mount("/", StaticFiles(directory=DIST, html=True), name="frontend")
