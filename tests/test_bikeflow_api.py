"""End-to-end checks of the BikeFlow API with a tiny CSV built in the test (not the team dataset)."""

from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from app.bikeflow.api import reset
from app.bikeflow.api import load_text
from app.bikeflow.config import Settings
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


def test_overnight_plan_learns_from_the_previous_complete_week():
    load_default()
    summary = client.get("/api/bikeflow/summary").json()
    phase1_end = date.fromisoformat(summary["settings"]["phase1_through"])
    first_day = date.fromisoformat(summary["days"][0])
    next_week_day = next(date.fromisoformat(d) for d in summary["days"]
                         if date.fromisoformat(d) > phase1_end)
    week_three_day = phase1_end + timedelta(days=7)

    partial_week = client.get("/api/bikeflow/plan/overnight",
                              params={"day": first_day.isoformat()}).json()
    last_learning_night = client.get("/api/bikeflow/plan/overnight",
                                     params={"day": phase1_end.isoformat()}).json()
    later_night = client.get("/api/bikeflow/plan/overnight",
                             params={"day": next_week_day.isoformat()}).json()
    week_three = client.get("/api/bikeflow/plan/overnight",
                            params={"day": week_three_day.isoformat()}).json()

    assert later_night["baseline"] == {
        "source": "week 1 baseline", "from": summary["phase1_days"][0],
        "through": phase1_end.isoformat(), "window": "06:00-10:00",
        "complete_days": 7, "required_days": 7, "week_number": 1,
        "target_week": 2, "complete": True}
    assert week_three["baseline"]["source"] == "week 2 baseline"
    assert week_three["baseline"]["from"] == "2026-10-12"
    assert week_three["baseline"]["through"] == "2026-10-18"
    assert week_three["baseline"]["window"] == "06:00-10:00"
    assert week_three["baseline"]["complete_days"] == week_three["baseline"]["required_days"] == 7
    assert week_three["baseline"]["week_number"] == 2
    assert week_three["baseline"]["target_week"] == 3 and week_three["baseline"]["complete"] is True
    assert week_three["baseline"]["method"] == "previous-week projected availability"
    assert week_three["baseline"]["projected_out_of_spec"] is not None
    assert all(row["history_days"] >= 2 for row in later_night["rows"])
    assert any(a["morning_net"] != b["morning_net"]
               for a, b in zip(later_night["rows"], week_three["rows"]))
    assert partial_week["baseline"]["complete"] is False
    assert last_learning_night["baseline"]["complete"] is True
    assert {r["station_id"]: (r["morning_net"], r["target_share"])
            for r in later_night["rows"]} == {
        r["station_id"]: (r["morning_net"], r["target_share"])
        for r in last_learning_night["rows"]}
    assert later_night["at"].startswith(next_week_day.isoformat() + "T")
    assert later_night["redistribute_by"] == next_week_day.isoformat() + "T22:00"
    assert later_night["ready_at"] == (next_week_day + date.resolution).isoformat() + "T06:00"


def test_weekly_deviation_shows_complete_observed_weeks_and_does_not_claim_stability_early():
    load_default()

    r = client.get("/api/bikeflow/plan/weekly", params={
        "dataset": "collegetown", "through": "2026-10-19"})

    assert r.status_code == 200
    review = r.json()
    assert [(w["week"], w["defects"], w["readings"]) for w in review["weeks"]] == [
        (1, 607, 2240), (2, 165, 2240)]
    assert [w["status"] for w in review["weeks"]] == ["baseline", "improved"]
    assert review["best_week"] == 2
    assert review["stable_week"] is None


def test_weekly_deviation_marks_stable_after_two_weeks_inside_week_one_limits():
    # Three complete weeks repeat the same small daily variation. The readings are
    # test data: 4-6 of 325 station/slot opportunities are outside the dock limits.
    start = date(2026, 10, 5)
    daily_defects = [4, 5, 6, 5, 4, 6, 5]
    lines = ["station_id,timestamp,bikes_available,capacity"]
    for day_offset in range(21):
        day = start + timedelta(days=day_offset)
        bad_count = daily_defects[day_offset % 7]
        opportunity = 0
        for sid in "ABCDE":
            for slot in range(Settings().n_slots):
                minute = slot * Settings().interval_min
                hour, minute = divmod(6 * 60 + minute, 60)
                bikes = 0 if opportunity < bad_count else 10
                lines.append(f"{sid},{day.isoformat()}T{hour:02d}:{minute:02d},{bikes},20")
                opportunity += 1
    load_text("\n".join(lines), Settings(
        phase1_through=(start + timedelta(days=6)).isoformat(), weekends_differ=False))

    r = client.get("/api/bikeflow/plan/weekly", params={"through": "2026-10-25"})

    assert r.status_code == 200
    review = r.json()
    assert [w["status"] for w in review["weeks"]] == ["baseline", "stable", "stable"]
    assert review["best_week"] == 1
    assert review["stable_week"] == 3


def test_overnight_plan_is_withheld_until_all_week_one_station_mornings_are_complete():
    lines = ["station_id,timestamp,bikes_available,capacity"]
    days = [date(2026, 10, d) for d in range(5, 12)]
    for day in days:
        for sid in "ABCDE":
            for hour, minute in [(6, 0), (6, 15), (6, 30), (6, 45), (7, 0),
                                 (7, 15), (7, 30), (7, 45), (8, 0), (8, 15),
                                 (8, 30), (8, 45), (9, 0), (9, 15), (9, 30),
                                 (9, 45), (10, 0)]:
                if day == date(2026, 10, 8) and sid == "C" and (hour, minute) == (8, 0):
                    continue
                lines.append(f"{sid},{day.isoformat()}T{hour:02d}:{minute:02d},10,20")
            if day == days[-1]:
                lines.append(f"{sid},{day.isoformat()}T22:00,10,20")
    load_text("\n".join(lines), Settings(phase1_through=days[-1].isoformat(), weekends_differ=False))

    response = client.get("/api/bikeflow/plan/overnight", params={"day": days[-1].isoformat()})

    assert response.status_code == 200
    plan = response.json()
    assert plan["baseline"]["complete"] is False
    assert plan["baseline"]["complete_days"] == 6
    assert plan["baseline"]["required_days"] == 7
    assert plan["rows"] == [] and plan["transfers"] == []
    assert "no station targets or transfer plan is published" in plan["notes"][-1]


def test_trip_events_returns_individual_rides_for_the_simulation_map():
    load_default()
    r = client.get("/api/bikeflow/trips/events", params={
        "dataset": "collegetown", "start": "2026-10-19T18:15", "end": "2026-10-19T18:15"})
    assert r.status_code == 200
    assert r.json()["trips"]
    assert all(t["timestamp"] == "2026-10-19T18:15" for t in r.json()["trips"])
    assert all(t["from_station"] != t["to_station"] for t in r.json()["trips"])
    assert client.get("/api/bikeflow/trips/events", params={
        "dataset": "collegetown", "start": "2026-10-19T19:00", "end": "2026-10-19T18:00"}).status_code == 400


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
    downtown_days = next(d for d in client.get("/api/bikeflow/datasets").json()["datasets"]
                         if d["id"] == "downtown")["days"]
    assert client.get("/api/bikeflow/summary", params={"dataset": "downtown"}).json()["readings"] == len(downtown_days) * 96 * 6
    assert client.get("/api/bikeflow/summary", params={"dataset": "nowhere"}).status_code == 404
