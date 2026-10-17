"""End-to-end checks of the BikeFlow API with a tiny CSV built in the test (not the team dataset)."""

import pytest
from fastapi.testclient import TestClient

from app.bikeflow.api import reset
from app.bikeflow.server import app, load_default

client = TestClient(app)


def csv_text():
    lines = ["station_id,timestamp,bikes_available,docks_available"]
    hist = {"08:00": 12, "08:15": 10, "08:30": 6}
    for day in ("2026-10-05", "2026-10-06"):
        for sid in "ABCDE":
            for t, b in hist.items():
                lines.append(f"{sid},{day}T{t},{b},{20 - b}")
    for sid, b in zip("ABCDE", [0, 20, 10, 14, 10]):
        lines.append(f"{sid},2026-10-07T08:00,{b},{20 - b}")
        lines.append(f"{sid},2026-10-07T22:00,{b},{20 - b}")
    return "\n".join(lines)


@pytest.fixture(autouse=True)
def fresh():
    reset()
    yield
    reset()


def test_no_dataset_is_a_clear_404_and_health_works():
    assert client.get("/health").json() == {"status": "ok"}
    r = client.get("/api/bikeflow/inventory")
    assert r.status_code == 404 and "POST a snapshots CSV" in r.json()["detail"]
    assert client.get("/").status_code == 200


def test_upload_then_every_view_responds():
    r = client.post("/api/bikeflow/dataset", content=csv_text())
    assert r.status_code == 200 and r.json()["stations"] == list("ABCDE")
    inv = client.get("/api/bikeflow/inventory", params={"station": "A,B", "start": "2026-10-07"}).json()
    assert [s["station_id"] for s in inv["stations"]] == ["A", "B"]
    assert inv["stations"][0]["latest"]["status"] == "empty"
    flow = client.get("/api/bikeflow/flow", params={"station": "A", "period": "morning rush"}).json()
    assert {b["period"] for b in flow["stations"][0]["bars"]} == {"morning rush"}
    spc = client.get("/api/bikeflow/spc", params={"station": "A", "start": "2026-10-07",
                                                  "end": "2026-10-07", "measure": "inventory"}).json()
    assert spc["day_type"] == "weekday" and "note" in spc
    # 7 Oct has no back-to-back readings, so there is no 15-minute net flow to chart: a clear 400
    r = client.get("/api/bikeflow/spc", params={"station": "A", "start": "2026-10-07", "end": "2026-10-07"})
    assert r.status_code == 400 and "no readings to chart" in r.json()["detail"]
    p = client.get("/api/bikeflow/plan", params={"at": "2026-10-07T08:00"}).json()
    assert p["kind"] == "now" and p["feasible"]
    assert (p["fleet"]["docked_after"] + p["fleet"]["reserve_after"]
            == p["fleet"]["docked"] + p["fleet"]["reserve_before"])
    o = client.get("/api/bikeflow/plan/overnight", params={"day": "2026-10-07"}).json()
    assert o["kind"] == "overnight" and o["for"] == "2026-10-08T06:00"
    assert o["fleet"]["docked_after"] + o["fleet"]["reserve_after"] == 120


def test_plan_changes_with_the_time_filter():
    client.post("/api/bikeflow/dataset", content=csv_text())
    a = client.get("/api/bikeflow/plan", params={"at": "2026-10-07T08:00"}).json()
    b = client.get("/api/bikeflow/plan", params={"at": "2026-10-07T22:00"}).json()
    assert a["at"] != b["at"]


def test_bad_inputs_are_400_not_500():
    client.post("/api/bikeflow/dataset", content=csv_text())
    assert client.get("/api/bikeflow/inventory", params={"station": "Z"}).status_code == 400
    assert client.get("/api/bikeflow/inventory", params={"start": "yesterday"}).status_code == 400
    assert client.get("/api/bikeflow/plan", params={"at": "2026-10-07T23:00"}).status_code == 400
    assert client.get("/api/bikeflow/plan", params={"at": "noon"}).status_code == 400
    assert client.get("/api/bikeflow/flow", params={"period": "lunch"}).status_code == 400
    assert client.get("/api/bikeflow/spc", params={"station": "A", "start": "2026-10-07",
                                                   "end": "2026-10-07", "measure": "x"}).status_code == 400
    assert client.post("/api/bikeflow/dataset", content="a,b\n1,2").status_code == 400
    assert client.post("/api/bikeflow/dataset", params={"target_share": 2}, content=csv_text()).status_code == 400


def test_upload_sits_beside_the_cities_and_is_picked_by_name():
    load_default()
    assert client.get("/api/bikeflow/summary").json()["dataset"] == "collegetown"
    up = client.post("/api/bikeflow/dataset", content=csv_text()).json()
    assert up["dataset"] == "uploaded" and up["readings"] < 4800
    names = [d["id"] for d in client.get("/api/bikeflow/datasets").json()["datasets"]]
    assert set(names) == {"collegetown", "downtown", "waterfront", "uploaded"}
    assert client.get("/api/bikeflow/summary", params={"dataset": "downtown"}).json()["readings"] == 8640
    assert client.get("/api/bikeflow/summary", params={"dataset": "nowhere"}).status_code == 404
