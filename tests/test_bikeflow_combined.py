"""The combined server: Yash's console and API unchanged at /, BikeFlow beside it."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.bikeflow.api import reset
from app.bikeflow.combined import app
from app.bikeflow.server import load_default

client = TestClient(app)
DIST = Path(__file__).resolve().parent.parent / "app" / "frontend" / "dist"


@pytest.fixture(autouse=True)
def team_data():
    # other test files reset the shared dataset; start every test from the team data
    reset()
    load_default()
    yield


def test_his_api_and_bikeflow_share_one_server():
    frames = client.get("/frames/event").json()
    assert frames["date"] == "2026-10-19" and len(frames["frames"]) == 64
    assert client.get("/latest").status_code == 200
    s = client.get("/api/bikeflow/summary").json()
    assert s["stations"] == ["S01", "S02", "S03", "S04", "S05"] and s["readings"] == 4800
    his = {d["id"] for d in client.get("/datasets").json()}
    mine = {d["id"] for d in client.get("/api/bikeflow/datasets").json()["datasets"]}
    assert his == mine == {"collegetown", "downtown", "waterfront"}


def test_side_by_side_page_and_bikeflow_page():
    r = client.get("/side-by-side", follow_redirects=False)
    assert r.status_code in (302, 307) and r.headers["location"] == "bikeflow/?follow=console"
    page = client.get("/bikeflow/")
    assert page.status_code == 200 and 'id="console"' in page.text


@pytest.mark.parametrize("city,at", [("collegetown", "18:30"), ("downtown", "17:20"), ("waterfront", "16:30")])
def test_both_tools_read_the_same_readings(city, at):
    # his event-day frame and BikeFlow's inventory give the same bikes at every station
    frames = client.get("/frames/event", params={"dataset": city}).json()["frames"]
    frame = [f for f in frames if f["as_of"] == f"2026-10-19T{at}"][0]
    his = {st["station_id"]: st["bikes"] for st in frame["stations"]}
    inv = client.get("/api/bikeflow/inventory", params={"start": "2026-10-19", "end": "2026-10-19",
                                                        "dataset": city}).json()
    mine = {s["station_id"]: [p["bikes"] for p in s["series"] if p["t"] == f"2026-10-19T{at}"][0]
            for s in inv["stations"]}
    assert his == mine


def test_his_console_is_served_at_root_when_built():
    if not DIST.exists():
        return                                   # build it with: cd app/frontend && npm ci && npm run build
    r = client.get("/")
    assert r.status_code == 200 and '<div id="root">' in r.text
