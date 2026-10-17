"""Checks on the simulated datasets in data/ (H-02)."""

import csv
import importlib.util
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"
spec = importlib.util.spec_from_file_location("simulate", DATA / "simulate.py")
simulate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(simulate)
SIM = simulate.build()          # run_day asserts docks + reserve = 100 after every reading


def read(name):
    with open(DATA / name) as f:
        return list(csv.DictReader(f))


def out_of_spec(days):
    return sum(1 for rows, _, _ in days for r in rows if r["bikes"] < 4 or r["bikes"] > 16)


def test_files_have_the_documented_shape():
    for name, days in [("week1_baseline.csv", 7), ("week2_policy.csv", 7), ("event_day.csv", 1)]:
        rows = read(name)
        assert list(rows[0]) == ["station_id", "timestamp", "bikes", "capacity", "van_moved"]
        assert len(rows) == days * 64 * 5
        assert all(0 <= int(r["bikes"]) <= int(r["capacity"]) == 20 for r in rows)
    stations = read("stations.csv")
    assert [s["station_id"] for s in stations] == ["S01", "S02", "S03", "S04", "S05"]


def test_files_match_a_fresh_simulation():
    rows = read("week2_policy.csv")
    fresh = [r for rows_, _, _ in SIM["week2"] for r in rows_]
    assert [int(r["bikes"]) for r in rows] == [r["bikes"] for r in fresh]


def test_week_1_has_no_van_and_week_2_has_far_fewer_out_of_spec_readings():
    assert all(r["van_moved"] == "0" for r in read("week1_baseline.csv"))
    assert out_of_spec(SIM["week2"]) < out_of_spec(SIM["week1"]) / 4


def test_every_start_plan_is_feasible():
    assert all(p["feasible"] for p in SIM["plans"])


def test_event_day_problems_get_the_van():
    log = SIM["event"][1]
    drain = [v for v in log if v["station_id"] == "S03" and "10:15" <= v["timestamp"][11:] <= "13:00"]
    crowd = [v for v in log if v["station_id"] == "S02" and "18:15" <= v["timestamp"][11:] <= "19:15"]
    assert drain and drain[0]["bikes_moved"] > 0          # slow drain: bikes brought in
    assert crowd and crowd[0]["trigger"] == "rule 1" and crowd[0]["bikes_moved"] < 0   # crowd: taken away
