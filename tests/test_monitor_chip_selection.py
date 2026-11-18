"""Selected Chip correlation must recalculate totals/r and preserve empty selections."""
import unittest
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from statistics import correlation
from openpyxl import load_workbook
from app import view
from exports import write_monitor_report
from test_vmin_distribution_and_monitor import monitor_wafer


def selection_wafer():
    w = monitor_wafer()
    partial = deepcopy(w.phases[0].chips[0, 0])
    partial.addresses = {0: dict(list(partial.addresses[0].items())[:2])}
    w.phases[0].chips[1, 0] = partial
    zero = deepcopy(partial)
    zero.addresses = {}
    w.phases[0].chips[2, 0] = zero
    return w


class TestMonitorChipSelection(unittest.TestCase):
    def test_subset_totals_and_pearson(self):
        w = selection_wafer()
        all_rows = w.monitor_correlation(0, "merge")["rows"]
        result = w.monitor_correlation(0, "merge", chips=[(0, 0), (2, 0)])
        self.assertEqual(result["rows"], [all_rows[0], all_rows[2]])
        self.assertEqual(result["counts"], [sum(row["counts"][i] for row in result["rows"]) for i in range(4)])
        self.assertEqual(result["relationships"]["write"]["chips"], 2)
        self.assertAlmostEqual(result["relationships"]["write"]["r"], correlation([3, 0], [5, 0]))

    def test_empty_is_not_all_and_single_has_no_r(self):
        w = selection_wafer()
        empty = w.monitor_correlation(0, "merge", chips=[])
        self.assertEqual(empty["rows"], [])
        self.assertEqual(empty["counts"], [0] * 4)
        self.assertIsNone(empty["relationships"]["read"]["r"])
        self.assertEqual(w.monitor_correlation(0, "merge", chips=[(1, 0)])["relationships"]["write"], {"r": None, "chips": 1})

    def test_api_selection_validates_coordinates(self):
        w = selection_wafer()
        query = dict(view="monitor_correlation", wt=1, scope="merge")
        self.assertEqual(len(view(w, query | {"chips": "[[1,0],[1,0]]"})["rows"]), 1)
        for raw in ('[[999,0]]', '[1,0]', '[[true,0]]', '[[1.5,0]]', '{}'):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                view(w, query | {"chips": raw})

    def test_incomplete_selected_chip_is_not_plotted(self):
        w = selection_wafer()
        del w.phases[0].chips[1, 0].fbc[305]
        result = w.monitor_correlation(0, "merge", chips=[(1, 0)])
        self.assertFalse(result["rows"][0]["complete"])
        self.assertEqual(result["relationships"]["write"]["chips"], 0)

    def test_export_filters_chip_rows(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "selected.xlsx"
            write_monitor_report(selection_wafer(), path, chips=[(1, 0)])
            book = load_workbook(path, data_only=True)
            rows = list(book["Chip Breakdown"].values)[1:]
            self.assertEqual(len(rows), 3)
            self.assertTrue(all(row[2:4] == (1, 0) for row in rows))
            book.close()


if __name__ == "__main__":
    unittest.main()
