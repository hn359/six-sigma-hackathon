"""
Ithaca bikeshare dispatch API: a thin FastAPI layer. No statistics here; app/engine.py organises
readings and app/qc.py does every calculation. Frames follow docs/map-contract.md.
"""

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
DATA = next((d for d in (HERE.parent / "data", HERE / "data") if (d / "stations.csv").exists()), None)
SCENARIOS = {"week1": "week1_baseline.csv", "week2": "week2_policy.csv", "event": "event_day.csv"}
LIVE_SECONDS_PER_READING = 5

app = FastAPI(
    title="Ithaca Bikeshare Dispatch",
    description="Every 15 minutes: an I-chart of slot-adjusted net flow with Western Electric rules, "
                "and a van move when a station signals or leaves 4-16 bikes. Frames follow docs/map-contract.md.",
    version="1.0.0",
)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


def _load():
    if DATA is None:
        raise RuntimeError("data/ not found: run python data/simulate.py")
    stations = engine.parse_stations((DATA / "stations.csv").read_text())
    days = {name: engine.parse_readings((DATA / f).read_text()) for name, f in SCENARIOS.items()}
    hist = engine.learn(days["week1"], sorted(stations))
    return stations, days, hist


STATIONS, DAYS, HIST = _load()


def _day(scenario, day):
    if scenario not in DAYS:
        raise HTTPException(404, f"unknown scenario; use one of {list(DAYS)}")
    dates = sorted(DAYS[scenario])
    if not 0 <= day < len(dates):
        raise HTTPException(404, f"{scenario} has days 0..{len(dates) - 1}")
    return dates[day], DAYS[scenario][dates[day]]


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/scenarios")
def scenarios():
    return {name: [str(d) for d in sorted(days)] for name, days in DAYS.items()}


@app.get("/frames/{scenario}")
def frames(scenario: str, day: int = Query(0, ge=0)):
    """All 64 frames of one day (06:00-21:45), oldest first, plus the chart limits per station."""
    date, data = _day(scenario, day)
    return engine.clean({"scenario": scenario, "date": str(date),
                         "frames": engine.day_frames(data, STATIONS, HIST, policy=scenario != "week1"),
                         "chart": engine.chart_meta(HIST)})


@app.get("/latest")
def latest(scenario: str = "event", day: int = 0):
    """Live mode: the frame 'now', replaying the day at one 15-minute reading every 5 seconds."""
    _, data = _day(scenario, day)
    k = int(time.time() // LIVE_SECONDS_PER_READING) % engine.SLOTS
    return engine.clean(engine.day_frames(data, STATIONS, HIST, policy=scenario != "week1")[k])


@app.post("/replay")
async def replay(readings: UploadFile = File(...), stations: UploadFile = File(...)):
    """Upload a readings CSV and a stations CSV; get frames for every day, judged against week 1's history."""
    try:
        st = engine.parse_stations((await stations.read()).decode("utf-8-sig"))
        days = engine.parse_readings((await readings.read()).decode("utf-8-sig"))
        missing = sorted(set(st) - set(HIST))
        if missing:
            raise ValueError(f"no history for stations {missing}; the history covers {sorted(HIST)}")
        out = []
        for date in sorted(days):
            out += engine.day_frames(days[date], st, HIST, policy=True)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if not out:
        raise HTTPException(400, "no readings between 06:00 and 21:45")
    return engine.clean({"frames": out, "chart": engine.chart_meta(HIST)})


@app.get("/summary")
def summary():
    """Night plan, rush slots, weekly p-charts (week 1 limits, week 2 judged) and before/after counts."""
    return engine.clean(engine.summary(DAYS["week1"], DAYS["week2"], STATIONS, HIST))


@app.get("/__docs__/")
def docs_redirect():
    return RedirectResponse(url="/docs")


# The built React app (app/frontend/dist), served at / when it exists.
DIST = HERE / "frontend" / "dist"
if DIST.exists():
    app.mount("/", StaticFiles(directory=DIST, html=True), name="frontend")
