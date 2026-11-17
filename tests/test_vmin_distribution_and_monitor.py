"""Check that Tail values remain visible, and address matching shares the Map scope."""
from array import array
from copy import deepcopy
from pathlib import Path
import unittest

from engine import ChipData, Config, Crossing, Identity, Phase, Test, Wafer, voltage_distribution
from test_vmin_hard_voltage_bound import make_wafer


def voltage_tail_wafer():
    tests = (Test("Function", 110, "Hard", 1.26, stop="Hard Fail"),
             Test("Function", 210, "Scan", 1.20),
             Test("Function", 209, "Scan", 1.035),
             Test("Function", 208, "Scan", .99),
             Test("Function", 207, "Scan", .90, stop="Scan"),
             Test("Function", 310, "March", .90, stop="March"))
    positive = {209: [0], 208: [0, 9], 207: list(range(10))}
    die = ChipData()
    for test in tests:
        blks = positive.get(test.tno, ())
        die.fbc[test.tno] = array("Q", [int(b in blks) for b in range(256)])
        die.masks[test.tno] = sum(1 << b for b in blks)
    source = Identity(Path("tail_WT1.asc"), "TAIL", 1, 1, "AA", 1)
    return Wafer(Config(tests, "FBC0"), (Phase(source, {(0, 0): die}),))


class TestVminDistribution(unittest.TestCase):
    def test_higher_tail_value_never_becomes_judge(self):
        wafer = voltage_tail_wafer()
        for scope, judge in (("chip", wafer.chip_vmin), ("pattern:Scan", wafer.pattern_chip_vmin),
                             ("merge", wafer.merged_chip_vmin)):
            with self.subTest(scope=scope):
                result = wafer.vmin_distribution(0, (0, 0), scope)
                summary = result["summary"]
                expected = judge(0, (0, 0), "Scan") if scope.startswith("pattern:") else judge(0, (0, 0))
                self.assertEqual(summary, expected)
                blocks = result["entries"]
                self.assertEqual([row["blk"] for row in blocks], list(range(256)))
                self.assertEqual(result["box"]["count"], 10)
                self.assertEqual(result["box"]["median"], .90)
                self.assertEqual(result["box"]["upper_fence"], .90)
                self.assertTrue(blocks[0]["tail"])
                self.assertEqual((blocks[0]["fbc90_voltage"], blocks[0]["peak_fbc"],
                                  blocks[0]["steps_above_median"]), (1.035, 1, 2))
                self.assertFalse(blocks[9]["tail"])
                self.assertEqual(blocks[9]["steps_above_median"], 1)
                self.assertEqual([row["blk"] for row in blocks if row["judge"]], [9])
                self.assertEqual(summary["before_tail"]["blk"], 0)
                self.assertLess(summary["voltage"], summary["before_tail"]["voltage"])

    def test_voltage_from_another_pattern_is_not_counted_as_a_step(self):
        readings = {blk: ("Scan", Crossing(207, .9, "Scan", 1, "Fail")) for blk in range(8)}
        readings[8] = "Scan", Crossing(209, 1.035, "Scan", 1, "Fail")
        stats, outliers, tail = voltage_distribution(readings, {"Scan": (.90, 1.035), "March": (.99,)})
        self.assertEqual(stats["median"], .9)
        self.assertEqual(outliers, {8: 1})
        self.assertEqual(tail, [])

    def test_insufficient_exact_values_leave_tail_unclassified(self):
        result = make_wafer(first=0, second=1).vmin_distribution(0, (0, 0), "pattern:Scan")
        self.assertEqual(result["box"]["count"], 1)
        self.assertNotIn("upper_fence", result["box"])
        self.assertFalse(result["summary"]["tail"])

    def test_march_cohort_can_show_observed_values_without_judge(self):
        wafer = make_wafer()
        die = wafer.die(0, (0, 0))
        die.fbc[305][255] = 3
        die.masks[305] = 1 << 255
        distribution = wafer.vmin_distribution(0, (0, 0), "pattern:March")
        self.assertEqual(distribution["summary"]["status"], "Not Applicable")
        self.assertFalse(any(row["judge"] for row in distribution["entries"]))
        self.assertEqual(distribution["entries"][255]["voltage"], .9)


def monitor_wafer():
    wafer = make_wafer()
    monitors = (Test("Monitor", 350, "W-Low pBL", 1.2),
                Test("Monitor", 351, "W-Low pBL", 1.035),
                Test("Monitor", 370, "R-Low pBL", 1.2))
    wafer.config = Config(monitors + wafer.config.tests, "FBC0")
    die = wafer.die(0, (0, 0))
    for test in monitors:
        die.fbc[test.tno] = array("Q", [0] * 256)
    die.fbc[305][255] = 3
    die.masks[305] = 1 << 255
    die.addresses = {
        0: {(0, 0, 0, 0): {210, 205, 305, 350, 351},
            (0, 1, 0, 0): {210, 370},
            (0, 2, 0, 0): {205, 350, 370},
            (0, 3, 0, 0): {205},
            (0, 4, 0, 0): {350}},
        255: {(255, 0, 0, 0): {210, 305, 370}},
    }
    return wafer


class TestMonitorCorrelation(unittest.TestCase):
    def test_combined_deduplicates_and_matrix_matches_summary(self):
        wafer = monitor_wafer()
        expected = {"pattern:Scan": [1, 1, 1, 1], "pattern:March": [1, 0, 0, 0],
                    "merge": [2, 1, 1, 1]}
        for scope, counts in expected.items():
            with self.subTest(scope=scope):
                report = wafer.monitor_correlation(0, scope)
                self.assertEqual(report["counts"], counts)
                self.assertEqual(report["rows"][0]["write"], 3)
                self.assertEqual(report["rows"][0]["read"], 3)
                self.assertIsNone(report["relationships"]["write"]["r"])
                rows = wafer.vmin_distribution(0, (0, 0), scope, with_matches=True)["entries"]
                self.assertEqual([sum(row["matches"][i] for row in rows) for i in range(4)], counts)
        self.assertNotIn("matches", wafer.vmin_distribution(0, (0, 0))["entries"][0])

    def test_pearson_uses_only_complete_function_and_observed_monitor_data(self):
        wafer = monitor_wafer()
        phase = wafer.phases[0]
        zero = deepcopy(phase.chips[0, 0])
        zero.addresses = {}
        phase.chips[1, 0] = zero
        partial = deepcopy(phase.chips[0, 0])
        del partial.fbc[305], partial.masks[305]
        phase.chips[2, 0] = partial
        result = wafer.monitor_correlation(0, "merge")
        self.assertEqual([row["complete"] for row in result["rows"]], [True, True, False])
        for side in ("write", "read"):
            self.assertEqual(result["relationships"][side]["chips"], 2)
            self.assertAlmostEqual(result["relationships"][side]["r"], 1.0)


if __name__ == "__main__":
    unittest.main()
