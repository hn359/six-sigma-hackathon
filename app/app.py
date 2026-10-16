"""
Bikeshare dock QC: a thin FastAPI layer over app/qc.py. No statistics here.
"""

from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

try:
    from app.qc import analyze_csv
except ImportError:  # run from inside app/ (e.g. on Posit Connect)
    from qc import analyze_csv

HERE = Path(__file__).resolve().parent
# Test datasets: data/ at the repo root locally, or app/data/ in a deployed bundle.
DATA_DIRS = [HERE.parent / "data", HERE / "data"]
SAMPLES = ["normal_week.csv", "hot_station.csv", "edge_case.csv"]

app = FastAPI(
    title="Bikeshare Dock QC",
    description="p-chart of rush-hour empty/full readings per station, plus availability, MTTR and MTBF.",
    version="0.1.0",
)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


def _run(text):
    try:
        return analyze_csv(text)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/")
async def page():
    """The dispatcher's page."""
    return FileResponse(HERE / "static" / "index.html")


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/analyze")
async def analyze(request: Request):
    """Send the raw text of a snapshots CSV as the request body."""
    body = await request.body()
    return _run(body.decode("utf-8-sig"))


@app.get("/samples")
async def samples():
    return {"samples": SAMPLES}


@app.get("/samples/{name}")
async def analyze_sample(name: str):
    """Run the analysis on one of the bundled test datasets."""
    if name not in SAMPLES:
        raise HTTPException(status_code=404, detail=f"unknown sample; try one of {SAMPLES}")
    for d in DATA_DIRS:
        if (d / name).exists():
            return _run((d / name).read_text())
    raise HTTPException(status_code=404, detail="sample file not found on the server")
