"""API and engine checks (H-04): frames follow the map contract and agree with the simulation."""

import csv
from pathlib import Path

from fastapi.testclient import TestClient

from app.app import app

client = TestClient(app)
DATA = Path(__file__).resolve().parent.parent / "data"


def test_health_and_scenarios():
    assert client.get("/health").json() == {"status": "ok"}
    s = client.get("/scenarios").json()
    assert len(s["week1"]) == 7 and len(s["week2"]) == 7 and len(s["event"]) == 1


def test_frames_have_the_contract_fields_and_rules():
    body = client.get("/frames/event").json()
    assert len(body["frames"]) == 64
    for f in body["frames"]:
        for s in f["stations"]:
            assert abs(s["occupancy"] - s["bikes"] / s["capacity"]) <= 0.01            # rule 1
            assert (s["severity"] == 0) == (s["direction"] == "ok")                    # rule 2
            assert (s["trigger"] is None) == (s["bikes_to_move"] is None)              # rule 3 (v2)
            if s["bikes_to_move"]:
                assert (s["bikes_to_move"] > 0) == (s["direction"] == "empty")         # rule 4
                assert -s["bikes"] <= s["bikes_to_move"] <= s["capacity"] - s["bikes"]  # rule 5


def test_every_van_stop_in_the_data_matches_a_trigger_and_move_from_the_api():
    frames = {f["as_of"]: f for f in client.get("/frames/event").json()["frames"]}
    with open(DATA / "van_log.csv") as fh:
        stops = [r for r in csv.DictReader(fh) if r["timestamp"].startswith("2026-10-19")]
    assert stops
    for v in stops:
        st = next(s for s in frames[v["timestamp"]]["stations"] if s["station_id"] == v["station_id"])
        assert st["trigger"] == v["trigger"]
        assert frames[v["timestamp"]]["van"]["station_id"] == v["station_id"]
        assert frames[v["timestamp"]]["van"]["bikes_moved"] == int(v["bikes_moved"])


def test_event_day_crowd_is_rule_1_at_s02():
    f = next(f for f in client.get("/frames/event").json()["frames"] if f["as_of"].endswith("18:15"))
    s02 = next(s for s in f["stations"] if s["station_id"] == "S02")
    assert s02["trigger"] == "rule 1" and s02["direction"] == "full" and s02["severity"] == 3


def test_summary_pchart_and_plan():
    body = client.get("/summary").json()
    assert body["kpis"]["out_of_spec_week2"] < body["kpis"]["out_of_spec_week1"]
    assert all(p["feasible"] for p in body["plan"])
    assert [p["start"] for p in body["plan"]] == [11, 7, 11, 10, 10]
    for pc in body["pcharts"]:
        assert len(pc["phase1"]) == 7 and len(pc["phase2"]) == 7


def test_replay_upload_and_bad_input():
    files = {"readings": ("r.csv", (DATA / "event_day.csv").read_bytes()),
             "stations": ("s.csv", (DATA / "stations.csv").read_bytes())}
    body = client.post("/replay", files=files).json()
    assert len(body["frames"]) == 64
    bad = {"readings": ("r.csv", b"station_id,timestamp\nS01,2026-10-19T08:00\n"),
           "stations": ("s.csv", (DATA / "stations.csv").read_bytes())}
    r = client.post("/replay", files=bad)
    assert r.status_code == 400 and "columns" in r.json()["detail"]


def test_latest_and_unknown_scenario():
    assert len(client.get("/latest").json()["stations"]) == 5
    assert client.get("/frames/nope").status_code == 404
