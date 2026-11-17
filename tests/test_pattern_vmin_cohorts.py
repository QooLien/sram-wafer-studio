"""Chip-level Scan/March cohorts are classified from complete raw BLK FBC."""
import unittest
from test_vmin_hard_voltage_bound import make_wafer


def march_fail(w, blk=1):
    die = w.die(0, (0, 0))
    for tno in (310, 305):
        die.fbc[tno][blk] = 10
        die.masks[tno] |= 1 << blk


class TestPatternVminCohorts(unittest.TestCase):
    def test_scan_fail_blocks_march_for_entire_chip(self):
        w = make_wafer()
        march_fail(w)
        self.assertIsNotNone(w.pattern_chip_vmin(0, (0, 0), "Scan")["voltage"])
        result = w.pattern_chip_vmin(0, (0, 0), "March")
        self.assertEqual(result["status"], "Not Applicable")
        self.assertIsNone(result["voltage"])
        self.assertIsNone(result["blk"])
        self.assertFalse(any(hit["pattern"] == "March" for row in w.grid((0, 0)) for hit in row["worst_vmin"]))
        # Raw BLK diagnostics, overall Vmin, and Merge remain inspectable.
        self.assertEqual(w.detail(0, (0, 0), 1)["fbc90"]["March"]["status"], "Fail")
        self.assertEqual(w.chip_vmin(0, (0, 0))["status"], "Vmin")
        self.assertEqual(w.merged_chip_vmin(0, (0, 0))["status"], "Vmin")

    def test_scan_pass_march_fail_is_eligible(self):
        w = make_wafer(first=0, second=0)
        march_fail(w, 2)
        self.assertEqual(w.pattern_chip_vmin(0, (0, 0), "Scan")["status"], "Pass")
        result = w.pattern_chip_vmin(0, (0, 0), "March")
        self.assertEqual((result["status"], result["blk"]), ("Vmin", 2))
        self.assertTrue(w.grid((0, 0))[2]["worst_vmin"])

    def test_early_scan_fail_cannot_be_hidden_by_pass_endpoint(self):
        w = make_wafer(first=10, second=0)
        march_fail(w)
        self.assertEqual(w.pattern_fbc_summary(0, (0, 0), "Scan")["fail_blks"], 1)
        self.assertEqual(w.pattern_chip_vmin(0, (0, 0), "March")["status"], "Not Applicable")

    def test_missing_scan_cannot_prove_pass(self):
        w = make_wafer(first=None, second=0)
        march_fail(w)
        for pattern in ("Scan", "March"):
            self.assertEqual(w.pattern_chip_vmin(0, (0, 0), pattern)["status"], "No Data")

    def test_missing_march_does_not_produce_vmin(self):
        w = make_wafer(first=0, second=0)
        march_fail(w)
        del w.die(0, (0, 0)).fbc[310]
        self.assertEqual(w.pattern_chip_vmin(0, (0, 0), "March")["status"], "No Data")

    def test_full_pass_and_addresses_do_not_create_fail(self):
        w = make_wafer(first=0, second=0)
        w.die(0, (0, 0)).addresses = {0: {(0, 1, 1, 1): {210, 310}}}
        for pattern in ("Scan", "March"):
            self.assertEqual(w.pattern_chip_vmin(0, (0, 0), pattern)["status"], "Pass")
        self.assertFalse(any(row["worst_vmin"] for row in w.grid((0, 0))))

    def test_invalid_phase_and_short_vector_are_not_pass(self):
        w = make_wafer(first=0, second=0)
        w.phases[0].fbc_error = True
        self.assertEqual(w.pattern_vmin_eligibility(0, (0, 0), "March")[0], "No Data")
        w.phases[0].fbc_error = False
        w.die(0, (0, 0)).fbc[210].pop()
        self.assertEqual(w.pattern_fbc_summary(0, (0, 0), "Scan")["status"], "No Data")


if __name__ == "__main__":
    unittest.main()
