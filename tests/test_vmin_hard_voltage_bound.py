"""Highest-voltage failures report a bound, retaining the threshold and exclusions."""
import unittest
from array import array
from pathlib import Path

from engine import Config, Test, ChipData, Phase, Identity, Wafer, MODES, vmin


def make_wafer(mode="FBC0", first=10, second=10, hard=0):
    tests = (Test("Function", 110, "H", 1.2, stop="Hard Fail"),
             Test("Function", 210, "S1", 1.035),
             Test("Function", 205, "S2", .99, stop="Scan"),
             Test("Function", 310, "M1", 1.035),
             Test("Function", 305, "M2", .9, stop="March"))
    die = ChipData()
    for test, count in zip(tests, (hard, first, second, 0, 0)):
        if count is not None:
            die.fbc[test.tno] = array("Q", [count] + [0] * 255)
            die.masks[test.tno] = int(count > 0)
    source = Identity(Path("bound_WT1.asc"), "BOUND", 1, 1, "AA", 1)
    return Wafer(Config(tests, mode), (Phase(source, {(0, 0): die}),))


class TestHardVoltageBound(unittest.TestCase):
    def test_example_across_modes(self):
        for mode in MODES:
            with self.subTest(mode=mode):
                w = make_wafer(mode)
                crossing = next(w.crossings(0, (0, 0), blk=0))[2]
                self.assertEqual((crossing.voltage, crossing.relation), (1.2, ">="))
                self.assertEqual((crossing.tno, crossing.test_voltage, crossing.fbc), (210, 1.035, 10))

    def test_lower_voltage_fail_still_uses_previous_voltage(self):
        crossing = next(make_wafer(first=0).crossings(0, (0, 0), blk=0))[2]
        self.assertEqual((crossing.voltage, crossing.relation, crossing.tno), (1.035, "", 205))

    def test_fbc90_threshold_not_replaced_by_first_positive_fbc(self):
        crossing = next(make_wafer("FBC90%", first=1, second=100).crossings(0, (0, 0), blk=0))[2]
        self.assertEqual((crossing.voltage, crossing.relation, crossing.tno), (.99, "", 205))

    def test_missing_data_not_promoted_to_bound(self):
        crossing = next(make_wafer("FBC90%", second=None).crossings(0, (0, 0), blk=0))[2]
        self.assertEqual(crossing.status, "No Data")
        self.assertIsNone(crossing.voltage)
        self.assertEqual(crossing.relation, "")

    def test_missing_config_does_not_invent_bound(self):
        scope = [Test("Function", 210, "S1", 1.035), Test("Function", 205, "S2", .99)]
        self.assertEqual(vmin(scope, [10, 10], "FBC0").status, "No Vmin")
        scope[1] = Test("Function", 205, "S2", None)
        self.assertEqual(vmin(scope, [10, 10], "FBC0", hard_voltage=1.2).relation, "")

    def test_chip_maps_and_grid_preserve_bound(self):
        w = make_wafer()
        for result in (w.chip_vmin(0, (0, 0)), w.pattern_chip_vmin(0, (0, 0), "Scan"),
                       w.merged_chip_vmin(0, (0, 0)), w.map(0, "Scan", "vmin")[0]):
            self.assertEqual((result["voltage"], result["relation"], result["blk"]), (1.2, ">=", 0))
        grid = w.grid((0, 0))[0]
        self.assertEqual(grid["trigger"]["relation"], ">=")
        self.assertEqual(grid["worst_vmin"][0]["relation"], ">=")

    def test_hard_and_prior_exclusions_unchanged(self):
        w = make_wafer(hard=1)
        self.assertEqual(next(w.crossings(0, (0, 0), blk=0))[2].status, "Hard Fail")
        self.assertEqual(w.merged_fbc90(0, (0, 0), 0).status, "Hard Fail")
        w = make_wafer()
        second = make_wafer().phases[0]
        second.source = Identity(Path("bound_WT2.asc"), "BOUND", 1, 2, "AA", 2)
        w.phases = (*w.phases, second)
        self.assertEqual(next(w.crossings(1, (0, 0), blk=0))[2].status, "Prior WT")

    def test_bound_uses_observed_voltage_in_box_statistics(self):
        w = make_wafer(first=1000, second=1000)
        die = w.die(0, (0, 0))
        die.fbc[205][1:5] = array("Q", [1] * 4)
        die.masks[205] = 31
        result = w.chip_vmin(0, (0, 0))
        self.assertNotIn(0, result["tail"])
        self.assertEqual((result["voltage"], result["relation"], result["blk"]), (1.2, ">=", 0))
        distribution = w.vmin_distribution(0, (0, 0))
        self.assertEqual(distribution["box"]["count"], 5)
        self.assertEqual(distribution["entries"][0]["fbc90_relation"], ">=")
        self.assertEqual(distribution["entries"][0]["tail_voltage"], 1.035)


if __name__ == "__main__":
    unittest.main()
