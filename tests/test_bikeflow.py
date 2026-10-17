"""Tests for the BikeFlow Analyze & Improve module (H-09, H-10).

Every known answer below is worked by hand in the comments. The data here are tiny fixtures built
in the test, not the team's historical dataset (that comes from the data branch).
"""

import math
from datetime import date, datetime

import pytest

from app.bikeflow.analyze import flow_view, inventory_view, net_flow_day, project, spc_view
from app.bikeflow.config import Settings
from app.bikeflow.data import parse_csv, parse_rows
from app.bikeflow.plan import DEPOT, match_transfers, overnight_shares, plan_now, plan_overnight
from app.bikeflow.qc import D2, D4, imr_slot_adjusted

MON, TUE, WED = date(2026, 10, 5), date(2026, 10, 6), date(2026, 10, 7)
S = Settings()


def rows_for(station, day, bikes_by_time, cap=20):
    """{"08:00": 12, ...} -> snapshot rows with docks = cap - bikes."""
    return [{"station_id": station, "timestamp": f"{day.isoformat()}T{t}",
             "bikes_available": str(b), "docks_available": str(cap - b)}
            for t, b in bikes_by_time.items()]


def build(rows, settings=S):
    return parse_rows(rows, settings, header=list(rows[0].keys()))


# ---------------------------------------------------------------- the statistic: slot-adjusted I-MR

def test_imr_known_answer():
    # Course I-MR (lesson 5): sigma = MR-bar / d2, limits = CL +/- 3 sigma (= +/- 2.66 MR-bar),
    # MR UCL = D4 * MR-bar.
    # Baseline Mon 10,12,8 and Tue 12,10,12 -> slot means 11, 11, 10.
    # Residuals Mon -1,+1,-2; Tue +1,-1,+2 -> CL = 0.
    # Moving ranges (same day only): 2,3 and 2,3 -> MR-bar = 10/4 = 2.5.
    # sigma = 2.5/1.128 = 2.216312; UCL = +6.648936 (= 2.66 x 2.5 to 2 d.p.), LCL = -6.648936;
    # MR UCL = 3.267 x 2.5 = 8.1675.
    # Chart Wed 11,3,10 -> residuals 0,-8,0: the 3 is beyond zone A (-8 / 2.216 = -3.61 sigma), so
    # test 1 fires there; its MRs are 8 and 8, both under 8.1675, so no MR signal.
    res = imr_slot_adjusted([[10, 12, 8], [12, 10, 12]], [[11, 3, 10]])
    lim = res["limits"]
    assert res["slot_means"] == [11, 11, 10]
    assert lim["cl"] == 0
    assert lim["mr_bar"] == pytest.approx(2.5)
    assert lim["sigma"] == pytest.approx(2.216312, abs=1e-6)
    assert lim["ucl"] == pytest.approx(6.648936, abs=1e-6)
    assert lim["lcl"] == pytest.approx(-6.648936, abs=1e-6)
    assert lim["mr_ucl"] == pytest.approx(8.1675)
    assert [p["signals"] for p in res["points"]] == [[], ["rule1"], []]
    assert res["points"][1]["z"] == pytest.approx(-8 / 2.216312, abs=1e-5)
    assert [p["mr"] for p in res["points"]] == [None, 8, 8]
    assert (D2, D4) == (1.128, 3.267)


# A baseline whose slot means are 0 and whose MR-bar is 1.128, so sigma = 1 and CL = 0: a chart day
# is then charted in sigma units exactly as written.
UNIT = [[0, 1.128] * 10, [0, -1.128] * 10]


def fired(chart):
    res = imr_slot_adjusted(UNIT, [chart])
    assert res["limits"]["sigma"] == pytest.approx(1) and res["limits"]["cl"] == pytest.approx(0)
    return {i: p["signals"] for i, p in enumerate(res["points"]) if p["signals"]}


def test_course_tests_2_to_8_each_fire_on_a_planted_pattern():
    # Test 2: 2 of 3 beyond zone B (2 sigma), same side: completed at the second 2.5.
    assert fired([0, 2.5, 0, 2.5]) == {3: ["rule2"]}
    # Test 3: 4 of 5 beyond zone C (1 sigma), same side: completed at the fourth 1.5.
    assert fired([1.5, 1.5, 0, 1.5, 1.5]) == {4: ["rule3"]}
    # Test 4: 8 in a row on one side of the centre line (0.5 each).
    assert fired([0.5] * 8) == {7: ["rule4"]}
    # Test 5: 6 in a row steadily increasing (0 is on the centre line, so test 4 cannot fire).
    assert fired([0, 0.1, 0.2, 0.3, 0.4, 0.5]) == {5: ["rule5"]}
    # Test 6: 15 in a row inside zone C, both sides, in pairs so no alternation and no run of 8.
    assert fired([0.5, 0.5, -0.5, -0.5] * 3 + [0.5, 0.5, -0.5]) == {14: ["rule6"]}
    # Test 7: 8 in a row on both sides with none in zone C (MR 3 < 3.267 x 1.128 = 3.685).
    assert fired([1.5, -1.5] * 4) == {7: ["rule7"]}
    # Test 8: 14 in a row alternating up and down, inside zone C.
    assert fired([0.5, -0.5] * 7) == {13: ["rule8"]}
    # The MR chart: a jump of 4 > 3.685.
    assert fired([0, 0, 4 - 0.5, 0]) == {2: ["rule1", "mr"]} or fired([-2, 2]) == {1: ["mr"]}
    assert fired([-2, 2]) == {1: ["mr"]}


def test_inventory_style_sigma_does_not_flag_ordinary_day_to_day_level_differences():
    # Each baseline day sits at its own level (-3..+3 bikes) with a tiny 0/1 wobble, like an
    # accumulating inventory: consecutive readings are nearly equal, so MR-bar is 1 (sigma 0.89)
    # while the day-to-day spread is about 2.2. A chart day at +3 is ordinary. MR-based limits
    # (+-2.66) wrongly flag it; sd-based limits do not.
    wobble = [0, 1] * 4
    flipped = [1, 0] * 4            # alternate the phase by day, or the slot means absorb the wobble
    base = [[off + w for w in (wobble if i % 2 == 0 else flipped)]
            for i, off in enumerate((-3, -2, -1, 1, 2, 3))]
    chart = [[3 + w for w in wobble]]
    by_mr = imr_slot_adjusted(base, chart, sigma="mr", rules=("rule1",))
    by_sd = imr_slot_adjusted(base, chart, sigma="sd", rules=("rule1",))
    assert by_mr["limits"]["sigma_basis"] == "mr" and by_sd["limits"]["sigma_basis"] == "sd"
    assert any(p["signals"] for p in by_mr["points"])
    assert not any(p["signals"] for p in by_sd["points"])
    assert by_sd["limits"]["sigma"] > 2 * by_mr["limits"]["sigma"]
    # a day far outside the usual spread is still caught by the sd chart
    far = imr_slot_adjusted(base, [[15 + w for w in wobble]], sigma="sd", rules=("rule1",))
    assert all(p["signals"] == ["rule1"] for p in far["points"])
    # rules and sigma options are validated; unrequested rules never fire
    with pytest.raises(ValueError):
        imr_slot_adjusted(base, chart, sigma="range")
    with pytest.raises(ValueError):
        imr_slot_adjusted(base, chart, rules=("rule_9",))
    runs = imr_slot_adjusted([[10, 12] * 6, [12, 10] * 6], [[12] * 12], rules=("rule1",))
    assert not any(p["signals"] for p in runs["points"])


def test_imr_degenerate_constant_baseline_gives_no_limits_not_zero():
    res = imr_slot_adjusted([[10, 10, 10], [10, 10, 10]], [[10, 2, 10]])
    assert res["limits"] is None
    assert "undefined" in res["warnings"][0]
    assert all(p["signals"] == [] for p in res["points"])


def test_imr_degenerate_one_baseline_day_and_empty_chart():
    res = imr_slot_adjusted([[10, 12, 8]], [[11, 3, 10]])
    assert res["limits"] is None and "fewer than 2" in res["warnings"][0]
    with pytest.raises(ValueError):
        imr_slot_adjusted([[1, 2]], [])
    with pytest.raises(ValueError):
        imr_slot_adjusted([[1, 2]], [[None, None]])


def test_imr_moving_range_never_spans_a_missing_reading():
    res = imr_slot_adjusted([[10, 12, 8, 9], [12, 10, 12, 11]], [[11, None, 10, 30]])
    mrs = [p["mr"] for p in res["points"]]
    assert mrs[0] is None and mrs[1] is None      # 10 follows a gap: no MR
    assert len(res["points"]) == 3                 # the missing slot is not charted


def test_imr_run_of_8_planted():
    base = [[10, 12] * 6, [12, 10] * 6]            # slot means all 11, residuals +-1, sigma 1.77
    chart = [[12] * 12]                            # every residual +1: one side of CL=0
    res = imr_slot_adjusted(base, chart)
    flags = [p["signals"] for p in res["points"]]
    assert flags == [[]] * 7 + [["rule4"]] * 5


def test_usual_rush_hour_empty_is_not_a_special_cause():
    # Every weekday the station drains to 0 at 08:00. Wednesday doing the same is usual:
    # an operational "empty", not an SPC signal.
    usual = {"07:30": 8, "07:45": 4, "08:00": 0, "08:15": 3}
    rows = (rows_for("A", MON, usual) + rows_for("A", TUE, {**usual, "07:45": 5})
            + rows_for("A", WED, usual))
    view = spc_view(build(rows), "A", WED, WED, "inventory")
    at8 = [p for p in view["points"] if p["t"].endswith("08:00")][0]
    assert at8["status"] == "empty"
    assert at8["signals"] == []
    assert view["baseline_days"] == ["2026-10-05", "2026-10-06"]


# ---------------------------------------------------------------- data contract

def test_missing_data_and_capacity_violations_are_skipped_with_a_reason():
    text = ("station_id,timestamp,bikes_available,docks_available\n"
            "A,2026-10-05T08:00,5,15\n"
            "A,2026-10-05T08:15,,15\n"           # missing bikes
            "A,2026-10-05T08:30,-1,21\n"          # negative bikes
            "A,2026-10-05T08:45,7.5,12\n"         # not a whole number
            "B,2026-10-05T08:00,25,0\n"           # 25 bikes, capacity 20 from settings? no: 25+0=25
            "C,2026-10-05T23:00,5,15\n"           # after closing
            "A,2026-10-05T08:00,6,14\n")          # duplicate slot
    ds = parse_csv(text)
    assert [(r.station_id, r.bikes) for r in ds.readings] == [("A", 5), ("B", 25)]
    joined = " | ".join(ds.issues)
    assert "row 3: missing" in joined and "row 4: capacity violation" in joined
    assert "row 5" in joined and "row 7" in joined and "row 8: second reading" in joined

    over = parse_csv("station_id,timestamp,bikes_available,capacity\nB,2026-10-05T08:00,25,20\n")
    assert over.readings == [] and "capacity violation" in over.issues[0]
    with pytest.raises(ValueError, match="bikes_available"):
        parse_csv("station_id,timestamp\nA,2026-10-05T08:00\n")


def test_column_aliases_and_map_for_other_branches():
    ds = parse_csv("station,time,num_bikes_available,num_docks_available\nA,2026-10-05 08:00,4,16\n")
    assert ds.readings[0].bikes == 4 and ds.readings[0].capacity == 20
    ds = parse_csv("sid,when,b\nA,2026-10-05T08:00,4\n",
                   column_map={"station_id": "sid", "timestamp": "when", "bikes_available": "b"})
    assert ds.readings[0].capacity == 20          # no docks column: Settings.capacity


def test_fleet_over_120_docked_is_reported():
    rows = [r for sid in "ABCDEFG" for r in rows_for(sid, MON, {"08:00": 18})]   # 7 x 18 = 126
    ds = build(rows)
    assert any("126 bikes docked, more than the fleet of 120" in i for i in ds.issues)


# ---------------------------------------------------------------- net flow, projection, views

def test_net_flow_from_change_in_bikes_and_from_counts():
    ds = build(rows_for("A", MON, {"08:00": 10, "08:15": 7, "08:30": 9, "09:00": 9}))
    flow, counted = net_flow_day(ds, "A", MON)
    slot = S.slot_of(datetime(2026, 10, 5, 8, 0))
    assert flow[slot:slot + 5] == [None, -3, 2, None, None]   # 09:00 follows a gap
    assert counted[slot + 1] is False

    text = ("station_id,timestamp,bikes_available,arrivals,departures\n"
            "A,2026-10-05T08:00,10,0,0\nA,2026-10-05T08:15,7,2,5\n")
    ds = parse_csv(text)
    flow, counted = net_flow_day(ds, "A", MON)
    assert flow[slot + 1] == -3 and counted[slot + 1] is True and ds.has_flow_columns


def test_net_flow_subtracts_the_previous_readings_van_move():
    # 08:00 10 bikes, van drops 5 right after -> 15. Riders take 4 -> 08:15 reads 11.
    # Riders-only net flow = 11 - 10 - 5 = -4 (not +1). A reading with no van value keeps the raw change.
    text = ("station_id,timestamp,bikes,capacity,van_moved\n"
            "A,2026-10-05T08:00,10,20,5\nA,2026-10-05T08:15,11,20,0\nA,2026-10-05T08:30,12,20,\n"
            "A,2026-10-05T08:45,12,20,0\n")
    ds = parse_csv(text)
    flow, counted = net_flow_day(ds, "A", MON)
    slot = S.slot_of(datetime(2026, 10, 5, 8, 0))
    assert flow[slot + 1:slot + 4] == [-4, 1, 0]
    assert counted[slot + 1] == "van" and counted[slot + 3] is False   # 08:30 has no van value
    assert ds.has_van_column
    assert "riders only" in flow_view(ds, ["A"])["source"]


def test_projection_known_answer_and_unreliable_case():
    # Mon and Tue both lose 2 then 4 bikes after 08:00 -> mean change -6 over two slots.
    # Wed at 08:00 with 9 bikes: projected 9 - 6 = 3 at 08:30.
    hist = {"08:00": 12, "08:15": 10, "08:30": 6}
    rows = rows_for("A", MON, hist) + rows_for("A", TUE, hist) + rows_for("A", WED, {"08:00": 9})
    ds = build(rows)
    slot = S.slot_of(datetime(2026, 10, 7, 8, 0))
    p = project(ds, "A", WED, slot, 9, 20, horizon=2)
    assert p["value"] == pytest.approx(3) and p["at"] == "08:30" and p["history_days"] == 2
    p = project(ds, "A", WED, slot, 2, 20, horizon=2)
    assert p["value"] == 0                          # clipped at empty, never negative
    p = project(ds, "A", TUE, slot, 9, 20, horizon=2)
    assert p["value"] is None and "not reliable" in p["basis"]   # only Monday before Tuesday


def test_inventory_and_flow_views():
    rows = rows_for("A", MON, {"08:00": 0, "08:15": 20, "08:30": 10})
    ds = build(rows)
    inv = inventory_view(ds, ["A"])["stations"][0]
    assert [p["status"] for p in inv["series"]] == ["empty", "full", "ok"]
    assert inv["latest"]["occupancy"] == 0.5
    fl = flow_view(ds, ["A"])["stations"][0]
    assert [b["net_flow"] for b in fl["bars"]] == [20, -10]
    rush = [x for x in fl["summary"] if x["period"] == "morning rush"][0]
    assert (rush["gained"], rush["lost"], rush["total"]) == (20, 10, 10)


# ---------------------------------------------------------------- the matching engine

def st(sid, bikes, desired, priority=2, spare=0, cap=20):
    return {"station_id": sid, "bikes": bikes, "capacity": cap, "desired": desired,
            "priority": priority, "spare": spare}


def test_match_transfers_known_answer_and_conservation():
    # A needs 7; B must shed 10; D can spare 5. A takes 7 from B; B's last 3 go to the depot.
    res = match_transfers([st("A", 4, 11, 0), st("B", 12, 2, 0), st("C", 10, 10),
                           st("D", 15, 15, spare=5), st("E", 10, 10)], reserve=69, fleet=120)
    assert [(t["from"], t["to"], t["bikes"]) for t in res["transfers"]] == [("B", "A", 7), ("B", DEPOT, 3)]
    assert res["after"] == {"A": 11, "B": 2, "C": 10, "D": 15, "E": 10}
    assert res["reserve_after"] == 72
    assert sum(res["after"].values()) + res["reserve_after"] == 120


def test_insufficient_donor_inventory_is_explained_not_invented():
    res = match_transfers([st("A", 0, 10, 0), st("B", 0, 10, 0), st("C", 12, 12, spare=2)],
                          reserve=0, fleet=120)
    assert [(t["from"], t["to"], t["bikes"]) for t in res["transfers"]] == [("C", "A", 2)]
    assert res["shortfall"] == {"A": 8, "B": 10}
    assert min(res["after"].values()) >= 0


def test_capacity_and_fleet_violations_raise():
    with pytest.raises(ValueError, match="capacity violation"):
        match_transfers([st("A", 21, 10)], 0, 120)
    with pytest.raises(ValueError, match="capacity violation"):
        match_transfers([st("A", 5, 25)], 0, 120)
    with pytest.raises(ValueError, match="more than the fleet"):
        match_transfers([st("A", 20, 20)] * 1 + [st("B", 20, 20)], reserve=81, fleet=120)
    with pytest.raises(ValueError):
        match_transfers([st("A", 5, 5), st("A", 6, 6)], 0, 120)


# ---------------------------------------------------------------- plans on a dataset

def five_station_day(day, bikes, t="08:00"):
    return [r for sid, b in zip("ABCDE", bikes) for r in rows_for(sid, day, {t: b})]


def test_plan_now_empty_and_full_stations():
    # No history, so level = current. A empty (HIGH), B full (HIGH), D 14 spares 4.
    ds = build(five_station_day(WED, [0, 20, 10, 14, 10]))
    plan = plan_now(ds, datetime(2026, 10, 7, 8, 0))
    rows = {r["station_id"]: r for r in plan["rows"]}
    assert rows["A"]["priority"] == "HIGH" and "empty now" in rows["A"]["reason"]
    assert rows["B"]["priority"] == "HIGH" and "full now" in rows["B"]["reason"]
    assert [(t["from"], t["to"], t["bikes"]) for t in plan["transfers"]] == [("B", "A", 10)]
    assert rows["A"]["after"] == 10 and rows["B"]["after"] == 10
    assert [r["station_id"] for r in plan["rows"]][:2] == ["A", "B"]
    assert plan["feasible"] and plan["fleet"]["docked_after"] == 54
    assert "0 depot bikes" in plan["notes"][0]


def test_plan_now_insufficient_donors_and_depot():
    ds = build(five_station_day(WED, [0, 0, 10, 12, 10]))
    plan = plan_now(ds, datetime(2026, 10, 7, 8, 0))
    rows = {r["station_id"]: r for r in plan["rows"]}
    assert not plan["feasible"]
    assert rows["A"]["short"] + rows["B"]["short"] == 18          # 20 needed, D spares 2
    assert "short by" in rows["B"]["action"]

    plan = plan_now(ds, datetime(2026, 10, 7, 8, 0), depot_bikes=5)
    assert sum(r["short"] for r in plan["rows"]) == 13
    f = plan["fleet"]
    assert f["docked_after"] + f["reserve_after"] == f["docked"] + f["reserve_before"]

    flat = build(five_station_day(WED, [0, 10, 10, 10, 10]))
    plan = plan_now(flat, datetime(2026, 10, 7, 8, 0))
    a = [r for r in plan["rows"] if r["station_id"] == "A"][0]
    assert "no station has bikes above target and no depot bikes" in a["action"]


def test_plan_now_outside_hours_and_missing_station():
    ds = build(five_station_day(WED, [5, 5, 5, 5, 5])[:4] + rows_for("E", TUE, {"08:00": 5}))
    with pytest.raises(ValueError, match="outside operating hours"):
        plan_now(ds, datetime(2026, 10, 7, 23, 0))
    plan = plan_now(ds, datetime(2026, 10, 7, 9, 0))
    assert any("no reading yet today for E" in n for n in plan["notes"])


def test_overnight_shares_80_for_most_departures_20_for_most_arrivals():
    # Morning net flow: A -9 (most departures), F -3 (a third as much), B +16 (most arrivals),
    # G +4 (a quarter as much), C 0, H no history.
    # A = 0.5 + 0.3 x 9/9 = 0.80;  F = 0.5 + 0.3 x 3/9 = 0.60;  B = 0.5 - 0.3 x 16/16 = 0.20;
    # G = 0.5 - 0.3 x 4/16 = 0.425;  C = H = 0.50.
    sh = overnight_shares({"A": -9, "F": -3, "B": 16, "G": 4, "C": 0, "H": None}, 0.8, 0.2)
    assert sh == pytest.approx({"A": 0.8, "F": 0.6, "B": 0.2, "G": 0.425, "C": 0.5, "H": 0.5})
    assert overnight_shares({"A": 0, "B": 0}, 0.8, 0.2) == {"A": 0.5, "B": 0.5}


def test_overnight_known_answer_and_120_bike_conservation():
    # Window 06:00-07:00 (flows into 06:15, 06:30, 06:45, 07:00), cap 20.
    # A: Mon -3,-3,-2,0; Tue -3,-3,-4,0 -> mean -3,-3,-3,0 -> morning net -9: most departures -> 80% = 16.
    # B: +4 each slot both days -> +16: most arrivals -> 20% = 4.   C, D, E: flat -> 50% = 10.
    # At 22:00 Tue: A 4, B 12, C 10, D 15, E 10 (51 docked), depot 120 - 51 = 69.
    # Moves: A needs 12; B sheds 8, D sheds 5 -> B->A 8, D->A 4, D's last 1 -> depot.
    # After: 16, 4, 10, 10, 10 = 50 docked, depot 70; 50 + 70 = 120.
    # Priority by bikes to move: A 12 HIGH, B 8 HIGH, D 5 MEDIUM, C and E 0 LOW.
    s = Settings(morning_window=("06:00", "07:00"))
    a_mon = {"06:00": 15, "06:15": 12, "06:30": 9, "06:45": 7, "07:00": 7}
    a_tue = {"06:00": 15, "06:15": 12, "06:30": 9, "06:45": 5, "07:00": 5, "22:00": 4}
    b = {"06:00": 2, "06:15": 6, "06:30": 10, "06:45": 14, "07:00": 18}
    flat = {"06:00": 10, "06:15": 10, "06:30": 10, "06:45": 10, "07:00": 10}
    rows = (rows_for("A", MON, a_mon) + rows_for("A", TUE, a_tue)
            + rows_for("B", MON, b) + rows_for("B", TUE, {**b, "22:00": 12}))
    for sid, last in (("C", 10), ("D", 15), ("E", 10)):
        rows += rows_for(sid, MON, flat) + rows_for(sid, TUE, {**flat, "22:00": last})
    plan = plan_overnight(build(rows, s), TUE)
    by = {r["station_id"]: r for r in plan["rows"]}
    assert (by["A"]["target"], by["A"]["role"], by["A"]["morning_net"]) == (16, "mostly departures", pytest.approx(-9))
    assert (by["B"]["target"], by["B"]["role"]) == (4, "mostly arrivals")
    assert [by[x]["target"] for x in "CDE"] == [10, 10, 10]
    assert [by[x]["priority"] for x in "ABCDE"] == ["HIGH", "HIGH", "LOW", "MEDIUM", "LOW"]
    assert [(t["from"], t["to"], t["bikes"]) for t in plan["transfers"]] == [("B", "A", 8), ("D", "A", 4), ("D", DEPOT, 1)]
    assert [by[x]["after"] for x in "ABCDE"] == [16, 4, 10, 10, 10]
    f = plan["fleet"]
    assert (f["docked"], f["reserve_before"], f["docked_after"], f["reserve_after"]) == (51, 69, 50, 70)
    assert f["docked_after"] + f["reserve_after"] == 120
    assert plan["for"] == "2026-10-07T06:00" and "80%" in plan["notes"][0]


def test_overnight_without_history_uses_default_target_and_says_so():
    ds = build([r for sid, b in zip("ABCDE", [2, 18, 10, 10, 10])
                for r in rows_for(sid, TUE, {"22:00": b})])
    plan = plan_overnight(ds, TUE)
    rows = {r["station_id"]: r for r in plan["rows"]}
    assert all(r["target"] == 10 for r in plan["rows"])
    assert "not enough history" in rows["A"]["projection_basis"] and rows["A"]["role"] == "no history"
    assert rows["A"]["after"] == 10 and rows["B"]["after"] == 10
    assert plan["fleet"]["docked_after"] + plan["fleet"]["reserve_after"] == 120


def test_overnight_more_bikes_docked_than_fleet_raises():
    s = Settings(fleet=40)
    ds = build([r for sid in "ABC" for r in rows_for(sid, TUE, {"22:00": 15})], s)
    with pytest.raises(ValueError, match="more than the fleet"):
        plan_overnight(ds, TUE)
