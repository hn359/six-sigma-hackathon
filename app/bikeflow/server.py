"""Standalone BikeFlow app: the router plus the dashboard page.

    python -m uvicorn app.bikeflow.server:app --port 8000      (from the repo root)

To fold BikeFlow into the team's main FastAPI app instead: `from app.bikeflow.api import router`
and `app.include_router(router)`; the page is dashboard/index.html in this folder.
"""

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from . import cities
from .api import _state, register, router

HERE = Path(__file__).resolve().parent

app = FastAPI(title="BikeFlow QC", version="0.1.0",
              description="Analyze and Improve: slot-adjusted I-MR, inventory, net flow, redistribution.")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.include_router(router)

# The team data: Yash's simulated cities in data/<city>/ (rebuilt exactly by `python data/simulate.py`).
DATA = HERE.parent.parent / "data"
DEFAULT_CITY = "collegetown"


def load_default():
    """Load every city in data/ (each with its own interval, hours and fleet from about.json);
    collegetown is the default. A CSV named by BIKEFLOW_DATA is loaded lazily by the API instead."""
    if _state["datasets"] or os.environ.get("BIKEFLOW_DATA"):
        return _state["datasets"]
    for key, city in cities.load_all(DATA).items():
        register(key, city, default=(key == DEFAULT_CITY))
    return _state["datasets"]


load_default()


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/")
async def page():
    return FileResponse(HERE / "dashboard" / "index.html")
