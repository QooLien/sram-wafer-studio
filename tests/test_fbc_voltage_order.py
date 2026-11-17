"""Regression tests for Scan/March voltage order and repeated-voltage stations."""
import unittest

from engine import fbc_voltage_comparison


class TestFbcVoltageComparison(unittest.TestCase):
    def test_config_order_and_duplicate_voltages(self):
        sweep = [
            {"pattern": "Scan", "tno": 10, "func": "S_A", "v": 1.0, "fbc": 3},
            {"pattern": "Scan", "tno": 11, "func": "S_A", "v": 0.9, "fbc": 4},
            {"pattern": "March", "tno": 12, "func": "M_A", "v": 1.0, "fbc": 7},
            {"pattern": "March", "tno": 13, "func": "M_A", "v": 1.0, "fbc": 8},
            {"pattern": "March", "tno": 14, "func": "M_B", "v": 0.9, "fbc": 2},
        ]
        result = fbc_voltage_comparison(sweep, "Scan")
        self.assertTrue(result["combined"])
        self.assertEqual([group["tno"] for group in result["groups"]], [10, 11, 12, 13, 14])
        self.assertEqual([group["voltage"] for group in result["groups"]], [1.0, 0.9, 1.0, 1.0, 0.9])
        self.assertEqual([group["stations"][0]["fbc"] for group in result["groups"]], [3, 4, 7, 8, 2])
        self.assertTrue(all(len(group["stations"]) == 1 for group in result["groups"]))

    def test_single_pattern_order_and_missing_station(self):
        sweep = [
            {"pattern": "Scan", "tno": 1, "func": "A", "v": 1.0, "fbc": 2},
            {"pattern": "Scan", "tno": 2, "func": "A", "v": 1.0, "fbc": None},
            {"pattern": "Scan", "tno": 3, "func": "B", "v": 0.8, "fbc": 4},
        ]
        result = fbc_voltage_comparison(sweep, "Scan")
        self.assertFalse(result["combined"])
        self.assertTrue(result["incomplete"])
        self.assertEqual([group["tno"] for group in result["groups"]], [1, 3])


if __name__ == "__main__":
    unittest.main()
