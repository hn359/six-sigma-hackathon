"""Known-answer and degenerate tests for app/qc.py. Every number comes from SPEC.md section 4."""

import pytest

from app.qc import (
    spec_limits, dispatch_trigger, imr_limits, imr_limits_days, out_of_spec, p_chart_phase, run_rules,
    rush_slots, start_plan, van_move, van_priority,
)


# ---- I-MR limits -------------------------------------------------------------

def test_imr_known_answer():
    lim = imr_limits([2, 4, 3, 5, 6])
    assert lim["xbar"] == pytest.approx(4)
    assert lim["mrbar"] == pytest.approx(1.5)
    assert lim["sigma"] == pytest.approx(1.3298, abs=1e-4)
    assert lim["ucl"] == pytest.approx(7.99)
    assert lim["lcl"] == pytest.approx(0.01)
    assert lim["mr_ucl"] == pytest.approx(4.9005)


def test_imr_moving_ranges_do_not_cross_days():
    # Within days: MRs 1 and 1. A cross-day MR (2 -> 10) would be 8 and must not count.
    lim = imr_limits_days([[1, 2], [10, 11]])
    assert lim["mrbar"] == pytest.approx(1.0)


def test_imr_constant_data_has_zero_sigma_and_a_message():
    lim = imr_limits([5, 5, 5, 5])
    assert lim["sigma"] == 0 and "no variation" in lim["message"]
    assert lim["ucl"] is None and lim["lcl"] is None        # no zero-width band
    with pytest.raises(ValueError):
        run_rules([5, 5], lim["xbar"], lim["sigma"])     # no division by zero


def test_imr_too_few_or_missing_values_raise():
    with pytest.raises(ValueError):
        imr_limits([3])
    with pytest.raises(ValueError):
        imr_limits([1, None, 2])


# ---- Western Electric rules (x-bar 0, sigma 1) -------------------------------

@pytest.mark.parametrize("x, rule", [
    ([-0.5, -3.5], 1),
    ([-2.5, 0.5, -2.2], 2),
    ([-1.5, -1.2, 0.3, -1.1, -1.4], 3),
    ([-0.5] * 8, 4),
])
def test_run_rules_known_answers(x, rule):
    sig = run_rules(x, 0, 1)
    assert sig is not None and sig["rule"] == rule and sig["side"] == -1
    assert run_rules(x[:-1], 0, 1) is None          # fires on the planted point, not before


def test_run_rules_upper_side_and_no_signal():
    assert run_rules([0.2, 3.4], 0, 1)["side"] == 1
    assert run_rules([0.5, -0.5, 0.8, -0.2, 1.5, -1.2], 0, 1) is None
    assert run_rules([], 0, 1) is None
    with pytest.raises(ValueError):
        run_rules([0.1, float("nan")], 0, 1)


def test_rule_2_and_3_need_the_latest_point_beyond_the_zone():
    # Montgomery: the point that completes the pattern must itself be beyond the zone.
    assert run_rules([-2.5, -2.2, -0.5], 0, 1) is None          # 2 of 3 beyond 2 sigma, but latest is not
    assert run_rules([-1.5, -1.2, -1.1, -1.4, -0.3], 0, 1) is None


# ---- dispatch ------------------------------------------------------------------

def test_van_move_known_answers():
    assert van_move(8, 3, 20) == 5          # bring 5
    assert van_move(12, 17, 20) == -5       # take 5
    with pytest.raises(ValueError):
        van_move(9, 22, 20)                 # 22 bikes cannot fit in 20 docks


def test_van_move_limits():
    assert van_move(20, 0, 20) == 10        # at most 10 per stop
    assert van_move(-5, 2, 20) == -2        # cannot take more bikes than are there
    assert van_move(10.5, 10, 20) == 1      # rounds half up


def test_van_priority_furthest_first():
    assert van_priority([("S2", 8, 5), ("S4", 10, 5)]) == ["S4", "S2"]   # 5 off before 3 off


def test_dispatch_trigger_signal_or_out_of_spec():
    assert dispatch_trigger({"rule": 3, "side": -1}, 9) == "rule 3"
    assert dispatch_trigger(None, 3) == "out of spec"     # safety net: no signal, still sent
    assert dispatch_trigger(None, 17) == "out of spec"
    assert dispatch_trigger(None, 4) is None and dispatch_trigger(None, 16) is None
    assert out_of_spec(3) and not out_of_spec(10)


def test_spec_limits_scale_with_station_size():
    assert spec_limits(20) == (4, 16)          # the SPEC's 20-dock station
    assert spec_limits(12) == (2, 10)          # 2.4 -> 2, 9.6 -> 10
    assert spec_limits(31) == (6, 25)          # 6.2 -> 6, 24.8 -> 25
    assert spec_limits(25) == (5, 20)
    for bad in (0, -5, 12.5):
        with pytest.raises(ValueError):
            spec_limits(bad)


# ---- night plan and rush hours -------------------------------------------------

def test_start_plan_known_answer():
    plan = start_plan([0, -3, -6, -8, -5])
    assert (plan["lo"], plan["hi"], plan["start"]) == (12, 16, 14)
    assert plan["path"] == [14, 11, 8, 6, 9]


def test_start_plan_infeasible_is_flagged_not_forced():
    plan = start_plan([0, -7, -13])
    assert plan["feasible"] is False and plan["start"] is None
    assert "planned visit" in plan["message"]


def test_rush_slots_known_answer_and_flat_day():
    assert rush_slots([2, 2, 6, 6, 2, 2]) == [2, 3]       # slots 3 and 4, 0-based
    assert rush_slots([3, 3, 3]) == []
    assert rush_slots([0, 0, 0]) == []


# ---- weekly p-chart ------------------------------------------------------------

def test_p_chart_known_answer():
    res = p_chart_phase([16, 20, 12, 24, 18, 14, 8], [3, 28], 64)
    assert res["pbar"] == pytest.approx(0.25)
    assert res["sigma"] == pytest.approx(0.054127, abs=1e-6)
    assert res["ucl"] == pytest.approx(0.41238, abs=1e-5)
    assert res["lcl"] == pytest.approx(0.08762, abs=1e-5)
    assert all(day["status"] == "in control" for day in res["phase1"])
    assert [day["status"] for day in res["phase2"]] == ["improved", "worse"]


def test_p_chart_degenerate():
    flat = p_chart_phase([0, 0, 0], [0], 64)
    assert flat["pbar"] == 0 and flat["ucl"] == 0 and flat["lcl"] == 0
    assert flat["phase2"][0]["status"] == "no Phase I variation"
    assert "no variation" in flat["warnings"][0]
    with pytest.raises(ValueError):
        p_chart_phase([5], [1], 64)          # one Phase I day
    with pytest.raises(ValueError):
        p_chart_phase([70, 1], [1], 64)      # more out-of-spec readings than readings
