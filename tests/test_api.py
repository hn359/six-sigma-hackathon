"""API and engine checks (H-04): frames follow the map contract and agree with the simulation."""

import csv
from pathlib import Path

from fastapi.testclient import TestClient

from app.app import app

client = TestClient(app)
DATA = Path(__file__).resolve().parent.parent / "data" / "collegetown"


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
    assert all(p["feasible"] for p in body["plan"])
    assert [p["start"] for p in body["plan"]] == [15, 4, 16, 8, 9]
    assert [p["target_share"] for p in body["plan"]] == [0.7667, 0.2, 0.8, 0.4045, 0.4318]
    assert body["kpis"]["out_of_spec_week2"] == 165
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


# ---- every dataset, and uploads the tool has never seen ----------------------------

import pytest  # noqa: E402

ROOT = DATA.parent
KEYS = [d["id"] for d in client.get("/datasets").json()]


def test_three_datasets_are_served():
    assert sorted(KEYS) == ["collegetown", "downtown", "waterfront"]


@pytest.mark.parametrize("key", KEYS)
def test_api_recomputes_every_event_van_stop_in_every_dataset(key):
    body = client.get(f"/frames/event?dataset={key}").json()
    frames = {f["as_of"]: f for f in body["frames"]}
    event_date = body["date"]
    with open(ROOT / key / "van_log.csv") as fh:
        stops = [r for r in csv.DictReader(fh) if r["timestamp"].startswith(event_date)]
    assert stops
    for v in stops:
        st = next(s for s in frames[v["timestamp"]]["stations"] if s["station_id"] == v["station_id"])
        assert st["trigger"] == v["trigger"]
        assert frames[v["timestamp"]]["van"]["bikes_moved"] == int(v["bikes_moved"])
    for f in body["frames"]:
        for s in f["stations"]:
            assert (s["trigger"] is None) == (s["bikes_to_move"] is None)
            assert s["lsl"] < s["usl"] <= s["capacity"]


@pytest.mark.parametrize("key", KEYS)
def test_summary_for_every_dataset(key):
    body = client.get(f"/summary?dataset={key}").json()
    expected = {"collegetown": (607, 165), "downtown": (838, 213), "waterfront": (186, 238)}
    assert (body["kpis"]["out_of_spec_week1"], body["kpis"]["out_of_spec_week2"]) == expected[key]
    assert all(p["feasible"] for p in body["plan"])
    assert body["rush_slots"] and len(body["rush_times"]) == len(body["rush_slots"])


def test_upload_of_an_unknown_network_learns_its_own_history():
    # Downtown's two weeks with every station renamed: the tool has no history for these ids.
    rename = lambda text: text.replace("D0", "X0")
    readings = rename((ROOT / "downtown" / "week1_baseline.csv").read_text()) + \
        "".join(rename((ROOT / "downtown" / "week2_policy.csv").read_text()).splitlines(keepends=True)[1:])
    files = {"readings": ("r.csv", readings.encode()),
             "stations": ("s.csv", rename((ROOT / "downtown" / "stations.csv").read_text()).encode())}
    r = client.post("/replay", files=files)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["history"] == "learned from 7 day(s) of the upload"     # the van-free week
    assert len(body["frames"]) == 7 * 96                                 # the policy week, 10-minute readings
    assert body["frames"][0]["as_of"].endswith("06:00") and body["frames"][1]["as_of"].endswith("06:10")
    # Same history as the built-in dataset, so the same signals and moves come out.
    built_in = client.get("/frames/week2?dataset=downtown&day=0").json()["frames"]
    for a, b in zip(built_in, body["frames"][:96]):
        assert [s["trigger"] for s in a["stations"]] == [s["trigger"] for s in b["stations"]]


def test_upload_off_grid_reading_is_rejected_clearly():
    text = (ROOT / "collegetown" / "event_day.csv").read_text().replace("2026-10-19T06:15", "2026-10-19T06:17", 1)
    files = {"readings": ("r.csv", text.encode()), "stations": ("s.csv", (ROOT / "collegetown" / "stations.csv").read_bytes())}
    r = client.post("/replay", files=files)
    assert r.status_code == 400 and "grid" in r.json()["detail"]


def test_chart_limits_are_rolling_by_default_with_week1_for_comparison_and_never_move_the_van():
    roll = client.get("/frames/event").json()
    week = client.get("/frames/event", params={"limits": "week1"}).json()
    assert roll["limits"] == "rolling" and week["limits"] == "week1"
    assert roll["chart"]["S01"]["basis_days"] == [f"2026-10-{d}" for d in range(12, 19)]
    assert roll["chart"]["S01"]["sigma"] != week["chart"]["S01"]["sigma"]
    # the van's decisions are identical in both modes; only the chart fields differ
    van = lambda r: [(s["station_id"], s["x"], s["severity"], s["trigger"], s["bikes_to_move"])
                     for f in r["frames"] for s in f["stations"]]
    assert van(roll) == van(week)
    assert all(s["chart_x"] == s["x"] for f in week["frames"] for s in f["stations"])
    assert any(s["chart_x"] != s["x"] for f in roll["frames"] for s in f["stations"] if s["x"] is not None)
    assert client.get("/frames/event", params={"limits": "monthly"}).status_code == 400
