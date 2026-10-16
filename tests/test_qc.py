"""Known-answer and degenerate tests for app/qc.py (SPEC.md section 4)."""

from pathlib import Path

import pytest

from app.qc import analyze_csv, availability, p_chart

DATA = Path(__file__).resolve().parent.parent / "data"


# ---- p-chart -------------------------------------------------------------

def test_p_chart_known_answer():
    # Hand-worked in SPEC.md: pbar 0.20, sigma sqrt(0.008), UCL 0.46833, LCL 0.
    res = p_chart([2, 3, 2, 3, 10], [20] * 5)
    assert res["pbar"] == pytest.approx(0.20)
    for row in res["stations"]:
        assert row["ucl"] == pytest.approx(0.468328, abs=1e-6)
        assert row["lcl"] == 0.0
    assert [r["p"] for r in res["stations"]] == pytest.approx([0.10, 0.15, 0.10, 0.15, 0.50])
    assert [r["flag"] for r in res["stations"]] == [False, False, False, False, True]


def test_p_chart_variable_n_gives_wider_limits_for_smaller_n():
    res = p_chart([4, 8], [20, 40])
    small, big = res["stations"]
    assert small["ucl"] > big["ucl"]


def test_p_chart_all_usable_is_flat_with_message():
    res = p_chart([0, 0, 0], [20, 20, 20])
    assert res["pbar"] == 0.0
    assert all(r["ucl"] == 0.0 and r["lcl"] == 0.0 and not r["flag"] for r in res["stations"])
    assert any("no variation" in w for w in res["warnings"])


def test_p_chart_bad_input_raises():
    with pytest.raises(ValueError):
        p_chart([1], [10])           # one station
    with pytest.raises(ValueError):
        p_chart([1, 1], [10, 0])     # n_i = 0
    with pytest.raises(ValueError):
        p_chart([11, 1], [10, 10])   # d_i > n_i


def test_p_chart_small_n_warns():
    res = p_chart([1, 1], [5, 5])
    assert any("below 5" in w for w in res["warnings"])


# ---- availability ----------------------------------------------------------

def _states(s):
    return [c == "X" for c in s]


def test_availability_known_answer():
    # Hand-worked in SPEC.md: UUXXUUUXUUUU at 15 min.
    res = availability([_states("UUXXUUUXUUUU")], 15)
    assert res["downtime"] == 45 and res["uptime"] == 135
    assert res["episodes"] == 2
    assert res["mttr"] == pytest.approx(22.5)
    assert res["mtbf"] == pytest.approx(67.5)
    assert res["availability"] == pytest.approx(0.75)


def test_availability_no_outages_is_one_not_inf():
    res = availability([_states("UUUU")], 15)
    assert res["availability"] == 1.0
    assert res["mttr"] is None and res["mtbf"] is None
    assert res["note"] == "no outages"


def test_availability_always_down():
    res = availability([_states("XXXX")], 15)
    assert res["availability"] == 0.0 and res["mtbf"] == 0.0 and res["episodes"] == 1


def test_availability_window_edge_splits_episode():
    # Same readings, but cut into two rush windows: one run becomes two episodes.
    assert availability([_states("UUXX"), _states("XXUU")], 15)["episodes"] == 2


def test_availability_empty_raises():
    with pytest.raises(ValueError):
        availability([], 15)
    with pytest.raises(ValueError):
        availability([[True]], 0)


# ---- whole CSV, on the test datasets ----------------------------------------

def _run(name):
    return analyze_csv((DATA / name).read_text())


def test_normal_week_flags_nothing():
    res = _run("normal_week.csv")
    assert res["reading_minutes"] == 15
    assert all(r["n"] == 120 for r in res["p_chart"]["stations"])
    assert res["send_first"] == []


def test_hot_station_flags_only_the_planted_station():
    res = _run("hot_station.csv")
    assert res["send_first"] == ["S07"]
    s07 = next(r for r in res["p_chart"]["stations"] if r["station"] == "S07")
    assert s07["action"] == "bring bikes"


def test_edge_case_handles_blanks_and_zero_outages():
    res = _run("edge_case.csv")
    assert res["rows_dropped"] > 0
    quiet = next(a for a in res["availability"] if a["station"] == "E02")
    assert quiet["availability"] == 1.0 and quiet["mttr"] is None
    assert any("below 5" in w for w in res["p_chart"]["warnings"])


def test_csv_missing_column_raises():
    with pytest.raises(ValueError):
        analyze_csv("station_id,timestamp\nA,2026-10-05T08:00\n")
