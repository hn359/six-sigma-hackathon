"""Checks on the invented-data simulator (data/simulate.py)."""

import csv

import pytest

from data import simulate as sim


@pytest.fixture(scope="module")
def default_run():
    return sim.run()


def test_fleet_never_changes(default_run):
    assert {total for _, total in default_run["trace"]} == {sim.FLEET}


def test_same_seed_same_files_other_seed_differs(tmp_path):
    a = sim.main(tmp_path / "a", seed=11)
    b = sim.main(tmp_path / "b", seed=11)
    c = sim.main(tmp_path / "c", seed=12)
    for name in ("readings_baseline.csv", "readings_test.csv", "events.csv", "stations.csv"):
        assert (tmp_path / "a" / name).read_bytes() == (tmp_path / "b" / name).read_bytes()
    assert a["baseline"] == b["baseline"]
    assert a["baseline"] != c["baseline"]


def test_shape(default_run):
    assert len(default_run["baseline"]) == 20 * 65 * 5
    assert len(default_run["test"]) == 5 * 65 * 5
    times = sorted({r[1][11:] for r in default_run["baseline"]})
    assert times[0] == "06:00" and times[-1] == "22:00" and len(times) == 65


def test_bikes_within_docks(default_run):
    cap = {s[0]: s[4] for s in sim.STATIONS}
    for sid, stamp, bikes, docks in default_run["baseline"]:
        assert 0 <= bikes <= cap[sid] and bikes + docks == cap[sid]


def test_rush_hour_pattern(default_run):
    """North Campus empties in the morning; Main Campus fills."""
    def mean_at(sid, t):
        v = [r[2] for r in default_run["baseline"] if r[0] == sid and r[1].endswith(t)]
        return sum(v) / len(v)
    assert mean_at("S01", "T09:00") < mean_at("S01", "T06:00") - 3
    assert mean_at("S02", "T09:00") > mean_at("S02", "T06:00") + 3


def test_planted_events(default_run):
    test = default_run["test"]
    day = [d.isoformat() for d in default_run["test_days"]]
    main_campus_thu = {r[2] + r[3] for r in test if r[0] == "S02" and r[1].startswith(day[3])}
    assert main_campus_thu == {12}
    fri = [r for r in test if r[1].startswith(day[4])]
    assert sum(1 for r in fri if r[2] == "") == 3
    assert sum(1 for r in fri if r[0] == "S05" and r[2] == 0 and r[3] == 0) == 9
    assert [e[0] for e in default_run["events"]] == [day[0], day[1], day[2], day[3], day[4], day[4]]


def test_longer_baseline_moves_test_week():
    r = sim.run(seed=3, baseline_days=25)
    assert len(r["baseline"]) == 25 * 65 * 5
    assert r["test_days"][0].weekday() == 0
    assert r["test_days"][0] > sim.weekdays(sim.FIRST_DAY, 25)[-1]
    with pytest.raises(ValueError):
        sim.run(baseline_days=0)


def test_written_files_have_the_documented_columns(tmp_path):
    sim.main(tmp_path, seed=5)
    with open(tmp_path / "readings_test.csv") as f:
        assert next(csv.reader(f)) == ["station_id", "timestamp", "bikes_available", "docks_available"]
    with open(tmp_path / "stations.csv") as f:
        assert next(csv.reader(f)) == ["station_id", "name", "lat", "lon", "capacity"]
