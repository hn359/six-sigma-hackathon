"""H-12: frozen comparison weeks, phase-to-phase limits and the adaptive weekly plan."""

import csv
import hashlib
import importlib.util
import json
import math
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app import app as console
from app.bikeflow import cities
from app.bikeflow.analyze import spc_view
from app.bikeflow.combined import app as combined_app

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
client = TestClient(console.app)
combined = TestClient(combined_app)
spec = importlib.util.spec_from_file_location("simulate_h12", DATA / "simulate.py")
simulate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(simulate)

FROZEN_HASHES = {
    "collegetown/week1_baseline.csv": "d8d275b555e531c91e6d58d31d83de43db40cd925adbc5ae7d6ae8e747d34bd2",
    "collegetown/week2_policy.csv": "9e7193fde2fda38601b14205900b1e53f765e897a3224efd687b16fe3cd19ea2",
    "downtown/week1_baseline.csv": "c7772cd7fa74596c7b1a30e1a0cccc20cadf49a1fc1f20134b988b93ba7f7285",
    "downtown/week2_policy.csv": "0d987b63d4dd279d76a3cf88fb8e49593fb302915723251d4da220de58de9b2f",
    "waterfront/week1_baseline.csv": "6bd34d92e6fbadc6b0b8da5ecbe04d2757ec104a524374eead1f626ad2260568",
    "waterfront/week2_policy.csv": "f6276b5d6a350acf6679967899a3412a39c15a6006e7e52342518ad8e0a73d90",
}


def _read(path):
    with open(path, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _opening(rows):
    first_time = min(row["timestamp"] for row in rows)
    return {row["station_id"]: int(row["bikes"]) for row in rows if row["timestamp"] == first_time}


def test_week_one_and_week_two_csv_bytes_are_frozen():
    for relative, expected in FROZEN_HASHES.items():
        actual = hashlib.sha256((DATA / relative).read_bytes()).hexdigest()
        assert actual == expected, relative


def test_previous_week_plan_is_conserved_bounded_and_limits_change_only_at_week_boundaries():
    all_cities = cities.load_all(DATA)
    for key, entry in all_cities.items():
        city_dir = DATA / key
        about = json.loads((city_dir / "about.json").read_text(encoding="utf-8"))
        saved = json.loads((city_dir / "adaptive_plans.json").read_text(encoding="utf-8"))
        quality = saved["weeks"]
        assert len(quality) == about["project_weeks"]
        assert quality[0]["status"] == "baseline" and quality[0]["lcl"] is None
        assert quality[1]["baseline_week"] == 1

        stable_run = 0
        for index, week in enumerate(quality):
            if index == 0:
                continue
            previous = quality[index - 1]
            n = week["readings"]
            sigma = math.sqrt(previous["rate"] * (1 - previous["rate"]) / n)
            assert week["center"] == previous["rate"]
            assert week["lcl"] == max(0.0, previous["rate"] - 3 * sigma)
            assert week["ucl"] == min(1.0, previous["rate"] + 3 * sigma)
            expected_status = ("worse" if week["rate"] > week["ucl"] else
                               "improved" if week["rate"] < week["lcl"] else "stable")
            assert week["status"] == expected_status
            stable_run = stable_run + 1 if expected_status == "stable" else 0
            assert week["stable_run"] == stable_run

        stable_week = next((w["week"] for w in quality if w["stable_run"] >= 2), None)
        assert stable_week == about["stable_week"]
        assert stable_week is not None, f"{key}: no stable point before the training limit"
        assert min(w["rate"] for w in quality[2:]) < quality[0]["rate"]

        specs = {row["station_id"]: simulate.spec_limits(int(row["capacity"]))
                 for row in _read(city_dir / "stations.csv")}
        for number in range(3, about["project_weeks"] + 1):
            plan = saved["plans"][f"week{number}"]
            previous_rows = _read(city_dir / ("week1_baseline.csv" if number == 2 else
                                               "week2_policy.csv" if number == 3 else
                                               f"week{number - 1}_policy.csv"))
            current_rows = _read(city_dir / f"week{number}_policy.csv")
            old_start, actual_start = _opening(previous_rows), _opening(current_rows)
            assert plan["source_week"] == number - 1
            assert plan["targets"] == actual_start
            assert sum(actual_start.values()) == sum(old_start.values())
            for station, target in actual_start.items():
                assert specs[station][0] <= target <= specs[station][1]
                assert abs(target - old_start[station]) <= simulate.MAX_WEEKLY_SHIFT_PER_STATION

        next_name = saved["next_week_plan"]
        next_targets = saved["plans"][next_name]["targets"]
        event_start = _opening(_read(city_dir / "event_day.csv"))
        assert event_start == next_targets


def test_adaptive_start_known_answer_and_no_flow_case():
    city = SimpleNamespace(ids=["A", "B"], cap=[10, 10], lim=[(2, 8), (2, 8)], n=2)

    def week(delta_a, delta_b):
        days = []
        for _ in range(7):
            rows = []
            for station, start, delta in (("A", 5, delta_a), ("B", 5, delta_b)):
                rows.extend([
                    {"station_id": station, "bikes": start, "van_moved": 0},
                    {"station_id": station, "bikes": start + delta, "van_moved": 0},
                ])
            # The simulator stores readings time-major; reorder them as slot 0 A/B, slot 1 A/B.
            rows = [rows[0], rows[2], rows[1], rows[3]]
            days.append((rows, [], {}))
        return days

    starts, result = simulate.adaptive_start(city, week(-3, 3), [6, 4])
    assert starts == [6, 4]
    assert result["projected_out_of_spec"] == 0 and result["docked_bikes"] == 10
    assert result["max_change_per_station"] == 1

    no_flow, _ = simulate.adaptive_start(city, week(0, 0), [5, 5])
    assert no_flow == [5, 5]


def test_console_uses_previous_complete_week_for_both_dispatch_and_chart():
    scenarios = client.get("/scenarios").json()
    phase = client.get("/frames/week3").json()
    comparison = client.get("/frames/week3", params={"limits": "week1"}).json()
    assert phase["baseline_week"] == 2
    assert phase["chart"]["S01"]["basis_days"] == scenarios["week2"]
    assert comparison["chart"]["S01"]["basis_days"] is None
    assert "week 1" in comparison["chart"]["S01"]["basis"].lower()
    van_state = lambda body: [(s["station_id"], s["trigger"], s["bikes_to_move"], s["x"])
                              for frame in body["frames"] for s in frame["stations"]]
    assert van_state(phase) == van_state(comparison)
    assert any(s["chart_x"] != s["x"] for frame in comparison["frames"] for s in frame["stations"]
               if s["x"] is not None)

    summary = client.get("/summary").json()["weekly_deviation"]
    saved = json.loads((DATA / "collegetown" / "adaptive_plans.json").read_text(encoding="utf-8"))
    assert [(w["week"], w["rate"], w["ucl"], w["lcl"]) for w in summary["weeks"]] == [
        (w["week"], w["rate"], w["ucl"], w["lcl"]) for w in saved["weeks"]]
    assert summary["stable_week"] == saved["weeks"][-1]["week"]


def test_bikeflow_i_mr_baseline_is_frozen_inside_a_week_and_updates_for_the_next_week():
    dataset = cities.load_all(DATA)["collegetown"]["dataset"]
    week_three = spc_view(dataset, "S01", date(2026, 10, 19), date(2026, 10, 19), limits="phase")
    week_four_monday = spc_view(dataset, "S01", date(2026, 10, 26), date(2026, 10, 26), limits="phase")
    week_four_tuesday = spc_view(dataset, "S01", date(2026, 10, 27), date(2026, 10, 27), limits="phase")
    assert week_three["baseline_days"] == [f"2026-10-{d}" for d in range(12, 18)] + ["2026-10-18"]
    assert week_four_monday["baseline_days"] == week_four_tuesday["baseline_days"]
    assert week_four_monday["basis"] == "Week 3 baseline (2026-10-19 to 2026-10-25)"
    assert week_four_monday["limits"]["cl"] != week_three["limits"]["cl"]
