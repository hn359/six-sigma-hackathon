import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from simulator import BikeshareSimulator, SimulatorConfig


class SimulatorTests(unittest.TestCase):
    def make_sim(self, seed=7):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        cfg = SimulatorConfig(
            database_path=str(Path(temp.name) / "test.db"),
            start_time=datetime(2026, 10, 19, 0, 0),
        )
        sim = BikeshareSimulator(cfg, seed=seed)
        self.addCleanup(sim.close)
        return sim

    def test_monday_initial_state(self):
        sim = self.make_sim()
        station_names = set(sim.stations.keys())
        expected = {"Lansing", "North Campus", "Maplewood", "Central Campus", "Downtown"}
        self.assertEqual(station_names, expected)
        self.assertEqual([s.bikes for s in sim.stations.values()], [10] * 5)
        self.assertEqual(sim.reserve, 50)
        self.assertEqual(sim.snapshot()["fleet_accounted"], 100)
        self.assertEqual(sim.snapshot()["fleet_size"], 100)
        self.assertEqual(sim.snapshot()["ucl"], 18)
        self.assertEqual(sim.snapshot()["lcl"], 2)

    def test_conservation_and_bounds(self):
        sim = self.make_sim()
        for _ in range(7 * 96):
            state = sim.step()
            self.assertEqual(state["fleet_accounted"], 100)
            self.assertTrue(all(0 <= row["bikes"] <= 20 for row in state["stations"]))

    def test_seed_reproducibility(self):
        left, right = self.make_sim(99), self.make_sim(99)
        for _ in range(50):
            self.assertEqual(left.step()["stations"], right.step()["stations"])

    def test_dispatch_and_aliases(self):
        sim = self.make_sim()
        # Test dispatch with full station names
        result = sim.dispatch("RESERVE", "Lansing", 5)
        self.assertEqual(result["moved"], 5)
        self.assertEqual(sim.stations["Lansing"].bikes, 15)
        self.assertEqual(sim.reserve, 45)

        # Test dispatch with legacy aliases (A -> Lansing, B -> Maplewood)
        result2 = sim.dispatch("A", "B", 3)
        self.assertEqual(result2["moved"], 3)
        self.assertEqual(sim.stations["Lansing"].bikes, 12)
        self.assertEqual(sim.stations["Maplewood"].bikes, 13)
        self.assertEqual(sim.snapshot()["fleet_accounted"], 100)

    def test_special_cause_locking_and_remedy(self):
        sim = self.make_sim(seed=42)
        # Manually force Lansing into special cause deficit (<= 2 bikes)
        sim.stations["Lansing"].bikes = 1
        sim.stations["Lansing"].special_cause_active = True
        sim.stations["Lansing"].special_cause_type = "DEFICIT"
        sim.reserve = 59  # conserve fleet

        # Run several steps: normal arrivals cannot auto-correct it above LCL (2)
        for _ in range(8):
            sim.step()
            self.assertLessEqual(sim.stations["Lansing"].bikes, 2)
            self.assertTrue(sim.stations["Lansing"].special_cause_active)

        # Operator issues remedy: dispatch from RESERVE to Lansing
        sim.dispatch("RESERVE", "Lansing", 8)
        self.assertGreater(sim.stations["Lansing"].bikes, 2)
        # Special cause should be cleared by operator command!
        self.assertFalse(sim.stations["Lansing"].special_cause_active)
        self.assertEqual(sim.stations["Lansing"].special_cause_type, "NONE")

    def test_overnight_proportional_rebalance(self):
        sim = self.make_sim(seed=42)
        for _ in range(96):
            sim.step()

        state = sim.snapshot()
        self.assertEqual(state["tick"], 96)
        station_bikes = [s["bikes"] for s in state["stations"]]
        self.assertEqual(sum(station_bikes), 50)
        self.assertEqual(state["reserve"], 50)
        self.assertEqual(state["fleet_accounted"], 100)

    def test_imr_and_spc_metrics(self):
        sim = self.make_sim(seed=10)
        for _ in range(40):
            sim.step()

        spc_all = sim.spc_metrics()
        self.assertEqual(len(spc_all), 5)
        for sid, metrics in spc_all.items():
            self.assertEqual(metrics["ucl"], 18.0)
            self.assertEqual(metrics["lcl"], 2.0)
            self.assertIn("imr", metrics)
            self.assertIn("moving_range", metrics["imr"])
            self.assertIn("moving_average", metrics["imr"])
            self.assertEqual(len(metrics["imr"]["individual"]), 41)  # 40 steps + initial

    def test_reset(self):
        sim = self.make_sim()
        for _ in range(10):
            sim.step()
        self.assertEqual(sim.tick_number, 10)

        sim.reset()
        self.assertEqual(sim.tick_number, 0)
        self.assertEqual([s.bikes for s in sim.stations.values()], [10] * 5)
        self.assertEqual(sim.reserve, 50)
        self.assertEqual(sim.snapshot()["fleet_accounted"], 100)

    def test_p_chart_attribute_metrics(self):
        sim = self.make_sim(seed=10)
        for _ in range(30):
            sim.step()

        p_chart = sim.p_chart()
        self.assertIn("p_bar", p_chart)
        self.assertIn("ucl_p", p_chart)
        self.assertIn("lcl_p", p_chart)
        self.assertIn("p_values", p_chart)
        self.assertIn("np_values", p_chart)
        self.assertEqual(len(p_chart["p_values"]), 31)  # 30 steps + initial
        self.assertTrue(0.0 <= p_chart["p_bar"] <= 1.0)
        self.assertTrue(0.0 <= p_chart["ucl_p"] <= 1.0)

        # Also check DMAIC report contains p_chart_summary
        dmaic = sim.dmaic_report()
        self.assertIn("p_chart_summary", dmaic["measure"])
        self.assertIn("p_chart_control_limits", dmaic["control"])


if __name__ == "__main__":
    unittest.main()
