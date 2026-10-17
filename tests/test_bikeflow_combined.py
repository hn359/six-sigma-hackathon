"""The combined server: the home page at /, Yash's console at /index.html and his API unchanged, BikeFlow beside it."""

from pathlib import Path
import re

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


@pytest.mark.parametrize("city", ["collegetown", "downtown", "waterfront"])
@pytest.mark.parametrize("scenario", ["week1", "week2", "event"])
def test_every_scenario_has_an_exact_matching_station_snapshot(city, scenario):
    frames = client.get(f"/frames/{scenario}", params={"dataset": city}).json()
    frame = frames["frames"][10]  # 08:30 on the scenario's first day
    day, at = frame["as_of"].split("T")
    expected = {st["station_id"]: (st["bikes"], st["capacity"]) for st in frame["stations"]}
    inventory = client.get("/api/bikeflow/inventory", params={
        "start": day, "end": day, "dataset": city,
    }).json()
    actual = {}
    for station in inventory["stations"]:
        reading = next(point for point in station["series"] if point["t"] == f"{day}T{at}")
        actual[station["station_id"]] = (reading["bikes"], reading["capacity"])
    assert frames["date"] == day
    assert actual == expected


def test_home_page_has_four_tabs_over_one_tool_page():
    r = client.get("/")
    assert r.status_code == 200
    for name in ("about", "map", "night", "spc"):
        assert f'id="tab-{name}"' in r.text
    assert '"bikeflow/?follow=console#"' in r.text      # tabs 2-4 share one tool page and one clock
    page = client.get("/bikeflow/").text
    views = re.findall(r'<section data-view="(\w+)">', page)
    assert views.count("map") == 2 and views.count("night") == 2 and views.count("spc") == 2
    assert views.count("none") == 1                    # Validation: on the full page only, in no tab
    assert client.get("/home/images/how-the-van-decides.png").status_code == 200
    assert client.get("/home/images/banner.png").status_code == 404     # only the docs' own images


def test_his_console_is_served_at_index_html_when_built():
    if not DIST.exists():
        return                                   # build it with: cd app/frontend && npm ci && npm run build
    r = client.get("/index.html")
    assert r.status_code == 200 and '<div id="root">' in r.text


def test_production_side_by_side_uses_versioned_state_and_exact_snapshot_checks():
    if not DIST.exists():
        return
    console = client.get("/index.html")
    scripts = re.findall(r'<script[^>]+src="([^"]+\.js)"', console.text)
    assert console.status_code == 200 and scripts
    asset = client.get("/" + scripts[0].removeprefix("./"))
    assert asset.status_code == 200 and "sixsigma.simulation-state" in asset.text
    dashboard = client.get("/bikeflow/")
    assert dashboard.status_code == 200
    assert "onSimulationMessage" in dashboard.text
    assert "scenario date verified" in dashboard.text.lower()
    assert "every station count" in dashboard.text.lower()
