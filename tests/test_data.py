"""Checks on the simulated datasets in data/<dataset>/ (H-02). Every check runs on all three cities."""

import csv
import importlib.util
import json
from pathlib import Path

import pytest

from app.qc import spec_limits
from app.bikeflow.cities import load_city
from app.bikeflow.plan import plan_overnight

DATA = Path(__file__).resolve().parent.parent / "data"
spec = importlib.util.spec_from_file_location("simulate", DATA / "simulate.py")
simulate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(simulate)
KEYS = list(simulate.DATASETS)
SIMS = {k: simulate.build(k) for k in KEYS}   # run_day asserts docks + reserve = fleet after every reading


def read(key, name):
    with open(DATA / key / name) as f:
        return list(csv.DictReader(f))


def test_three_different_networks():
    about = {k: json.loads((DATA / k / "about.json").read_text()) for k in KEYS}
    assert len(KEYS) == 3
    assert len({a["interval_minutes"] for a in about.values()}) >= 2          # different reading intervals
    assert len({a["stations"] for a in about.values()}) >= 2                  # different network sizes
    assert any(len(set(a["docks"])) > 1 for a in about.values())             # mixed station sizes


@pytest.mark.parametrize("key", KEYS)
def test_files_have_the_documented_shape(key):
    city = SIMS[key]["city"]
    for name, days in [("week1_baseline.csv", 7), ("week2_policy.csv", 7), ("event_day.csv", 1)]:
        rows = read(key, name)
        assert list(rows[0]) == ["station_id", "timestamp", "bikes", "capacity", "van_moved"]
        assert len(rows) == days * city.slots * city.n
        assert all(0 <= int(r["bikes"]) <= int(r["capacity"]) for r in rows)
    assert [s["station_id"] for s in read(key, "stations.csv")] == city.ids


@pytest.mark.parametrize("key", KEYS)
def test_files_match_a_fresh_simulation(key):
    rows = read(key, "week2_policy.csv")
    fresh = [r for rows_, _, _ in SIMS[key]["week2"] for r in rows_]
    assert [int(r["bikes"]) for r in rows] == [r["bikes"] for r in fresh]


@pytest.mark.parametrize("key", KEYS)
def test_week2_policy_results_are_reported_for_the_80_20_strategy(key):
    sim = SIMS[key]
    assert all(r["van_moved"] == "0" for r in read(key, "week1_baseline.csv"))
    expected = {"collegetown": (607, 165), "downtown": (838, 213), "waterfront": (186, 238)}
    assert simulate.out_of_spec(sim, sim["week1"]) == expected[key][0]
    assert simulate.out_of_spec(sim, sim["week2"]) == expected[key][1]
    assert sum(d[2]["lost"] for d in sim["week2"]) == 0


@pytest.mark.parametrize("key", KEYS)
def test_every_start_plan_is_feasible_with_its_own_spec_limits(key):
    sim = SIMS[key]
    assert all(p["feasible"] for p in sim["plans"])
    assert sim["city"].lim == [spec_limits(c) for c in sim["city"].cap]


@pytest.mark.parametrize("key", KEYS)
def test_week2_starts_match_the_bikeflow_80_20_plan_from_week1(key):
    sim = SIMS[key]
    city = sim["city"]
    from datetime import timedelta
    last_week1_day = city.cfg["first_day"] + timedelta(days=6)
    recommendation = plan_overnight(load_city(DATA / key)["dataset"], last_week1_day)
    targets = {row["station_id"]: row["target"] for row in recommendation["rows"]}
    assert [targets[sid] for sid in city.ids] == sim["starts"]
    actual_open = [sim["week2"][0][0][i]["bikes"] for i in range(city.n)]
    assert actual_open == sim["starts"]


@pytest.mark.parametrize("key", KEYS)
def test_event_day_problems_get_the_van(key):
    ev = simulate.DATASETS[key]["event"]
    log = SIMS[key]["event"][1]
    st, frm, to, _ = ev["drain"]
    drain = [v for v in log if v["station_id"] == st and v["timestamp"][11:] <= to and v["bikes_moved"] > 0]
    st, frm, to = ev["crowd"][:3]
    crowd = [v for v in log if v["station_id"] == st and frm <= v["timestamp"][11:] <= to and v["bikes_moved"] < 0]
    assert drain, "the slow drain never got bikes brought in"
    assert crowd and crowd[0]["trigger"] == "rule 1", "the crowd was not caught by rule 1"
