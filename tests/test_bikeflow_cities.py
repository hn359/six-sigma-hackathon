"""Yash's three simulated cities (data/<city>/, branch yash_work): loading, Phase I limits, and a
regression check that the course I-MR with the eight tests catches every planted problem."""

from datetime import date
from pathlib import Path

import pytest

from app.bikeflow import cities
from app.bikeflow.analyze import net_flow_day, scorecard, spc_view
from app.bikeflow.config import Settings
from app.bikeflow.qc import imr_slot_adjusted

DATA = Path(__file__).resolve().parent.parent / "data"
CITIES = cities.load_all(DATA)


@pytest.mark.parametrize("key,rows,interval,first,last,fleet,stations", [
    ("collegetown", 4800, 15, "06:00", "21:45", 100, 5),     # 15 days x 64 readings x 5
    ("downtown", 8640, 10, "06:00", "21:50", 127, 6),        # 15 days x 96 readings x 6
    ("waterfront", 3600, 15, "08:00", "22:45", 90, 4),       # 15 days x 60 readings x 4
])
def test_each_city_loads_on_its_own_grid(key, rows, interval, first, last, fleet, stations):
    c = CITIES[key]
    ds, s = c["dataset"], c["dataset"].settings
    assert (len(ds.readings), ds.issues) == (rows, [])
    assert (s.interval_min, s.open_time, s.close_time, s.fleet) == (interval, first, last, fleet)
    assert len(ds.stations()) == stations and len(c["names"]) == stations
    assert c["phase1_days"][0] == "2026-10-05" and len(c["phase1_days"]) == 7
    assert s.phase1_through == "2026-10-11" and c["event_day"] == "2026-10-19"
    assert s.morning_window[0] == first                   # the 10 PM plan's window starts at opening
    assert {e["kind"] for e in c["events"]} == {"slow_drain", "crowd"}


def test_spec_range_is_20_to_80_percent_of_each_stations_docks():
    s = CITIES["downtown"]["dataset"].settings
    # as Yash's qc.spec_limits: round half up
    assert [s.band(cap) for cap in (20, 31, 12, 15, 27)] == [(4, 16), (6, 25), (2, 10), (3, 12), (5, 22)]
    assert Settings().band(20) == (5, 15) and Settings().target_for(20) == 10


def test_event_day_limits_come_from_week_1_only():
    # Phase I/II: the limits on the event day equal the limits computed from the 7 van-free days
    c = CITIES["collegetown"]
    ds = c["dataset"]
    w1 = [date.fromisoformat(d) for d in c["phase1_days"]]
    ev = date(2026, 10, 19)
    v = spc_view(ds, "S03", ev, ev)
    direct = imr_slot_adjusted([net_flow_day(ds, "S03", d)[0] for d in w1], [net_flow_day(ds, "S03", ev)[0]])
    assert v["baseline_days"] == c["phase1_days"] and v["phase"] == "Phase II"
    assert v["limits"]["sigma"] == pytest.approx(direct["limits"]["sigma"])
    assert v["limits"]["cl"] == pytest.approx(direct["limits"]["cl"])
    # a week-1 day is a Phase I chart on the same 7 days
    assert spc_view(ds, "S03", w1[2], w1[2])["phase"] == "Phase I"


@pytest.mark.parametrize("key,drain_first,crowd_first", [
    ("collegetown", "11:15", "18:15"),
    ("downtown", "11:20", "17:00"),
    ("waterfront", "09:00", "16:00"),
])
def test_every_planted_problem_is_caught_inside_its_window(key, drain_first, crowd_first):
    c = CITIES[key]
    sc = scorecard(c["dataset"], c["events"])
    by = {e["kind"]: e for e in sc["events"]}
    assert by["slow_drain"]["first_flag"] == drain_first
    assert by["crowd"]["first_flag"] == crowd_first
    for e in sc["events"]:
        assert e["from"] <= e["first_flag"] <= e["to"] and e["flagged_in_window"] >= 1
    assert 0 < sc["false_alarm_rate_tests_only"] <= sc["false_alarm_rate"] < 0.15
    assert sc["quiet_days"][0] == "2026-10-12" and len(sc["quiet_days"]) == 7


def test_trip_matrix_counts_known_answer():
    from app.bikeflow.analyze import trip_matrix
    trips = [("2026-10-19T08:15", "A", "B"), ("2026-10-19T08:15", "A", "B"), ("2026-10-19T08:30", "B", "C"),
             ("2026-10-19T09:00", "C", "A"), ("2026-10-19T08:00", "A", "C")]      # the last is outside the window
    m = trip_matrix(trips, ["A", "B", "C"], "2026-10-19T08:00", "2026-10-19T09:00")
    assert m["matrix"] == [[0, 2, 0], [0, 0, 1], [1, 0, 0]]
    assert (m["total"], m["left"], m["arrived"]) == (4, [2, 1, 1], [1, 2, 1])
    assert m["top"][0] == {"from": "A", "to": "B", "trips": 2}


@pytest.mark.parametrize("key", ["collegetown", "downtown", "waterfront"])
def test_trips_agree_with_the_readings_at_every_station_and_reading(key):
    # trips in minus trips out at each reading = rider net flow from the bike counts (minus van moves)
    c = CITIES[key]
    ds, trips = c["dataset"], c["trips"]
    assert len(trips) > 1000
    net = {}
    for t, a, b in trips:
        net[(t, a)] = net.get((t, a), 0) - 1
        net[(t, b)] = net.get((t, b), 0) + 1
    checked = 0
    for d in ds.days():
        for sid in ds.stations():
            flow = net_flow_day(ds, sid, d)[0]
            for slot, f in enumerate(flow):
                if f is None:
                    continue
                assert f == net.get((f"{d.isoformat()}T{ds.settings.slot_time(slot)}", sid), 0)
                checked += 1
    assert checked > 3000
