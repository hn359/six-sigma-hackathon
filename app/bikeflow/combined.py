"""Yash's dispatch console and the BikeFlow charts from one server, so they share one clock.

    python -m uvicorn app.bikeflow.combined:app --port 8000      (from the repo root)

  /                  home page: a Documentation tab and a Tool tab (the side-by-side page)
  /index.html        his console (app/frontend/dist); his API routes are unchanged
  /side-by-side      his console on top; the BikeFlow charts below follow its day and time
  /bikeflow/         the BikeFlow charts on their own
  /api/bikeflow/...  the BikeFlow API

His console must be built once first: cd app/frontend && npm ci && npm run build.
"""

from typing import Optional
from urllib.parse import quote

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, RedirectResponse

from app.app import app as console          # his API and the built React console

from .api import router
from .server import HERE, load_default

app = FastAPI(title="Ithaca bikeshare: dispatch console + BikeFlow charts", version="0.1.0")
app.include_router(router)
load_default()

IMAGES = HERE.parent.parent / "docs" / "images"
HOME_IMAGES = {"how-the-van-decides.png", "redistribution-flowchart.png"}   # the two the docs tab shows


@app.get("/")
async def home():
    """The front door: Documentation and Tool tabs. His console itself is at /index.html."""
    return FileResponse(HERE / "home.html")


@app.get("/home/images/{name}")
async def home_image(name: str):
    if name not in HOME_IMAGES:
        raise HTTPException(404, "not a documentation image")
    return FileResponse(IMAGES / name)


@app.get("/side-by-side")
async def side_by_side(dataset: Optional[str] = None):
    """?dataset=downtown opens his console on that city; the charts follow it either way."""
    return RedirectResponse(url="bikeflow/?follow=console" + (f"&dataset={quote(dataset)}" if dataset else ""))


@app.get("/bikeflow/")
async def bikeflow_page():
    return FileResponse(HERE / "dashboard" / "index.html")


app.mount("/", console)                       # last: everything else is his app
