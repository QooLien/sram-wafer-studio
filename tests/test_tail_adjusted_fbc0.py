"""Per-BLK early-FBC detection is opt-in and preserves legacy Vmin rules."""
import copy
import json
import tempfile
import unittest
from array import array
from dataclasses import asdict
from pathlib import Path

from engine import Config, Test, Crossing, ChipData, Identity, Phase, Wafer, TailBitSettings, TAIL_MODE, vmin
from exports import save_report
from workbook_settings import workbook_config
from app import view


def sweep(counts, voltages=(1.035, .99, .945, .90, .855), function='Scan0'):
    tests = [Test('Function', 200+i, function, voltage, stop='Scan' if i == len(voltages)-1 else '')
             for i, voltage in enumerate(voltages)]
    return tests, list(counts)


def adaptive_wafer():
    tests, _ = sweep([0]*5)
    tests = [Test('Function', 100, 'Hard', 1.2, stop='Hard Fail'), *tests,
             Test('Function', 300, 'March0', .855, stop='March')]
    die = ChipData()
    curves = ([0, 1, 2, 80, 500], [0, 5, 10, 400, 2500])
    for test in tests:
        counts = [0]*256
        if 200 <= test.tno < 205:
            for blk, curve in enumerate(curves):
                counts[blk] = curve[test.tno-200]
        die.fbc[test.tno] = array('Q', counts)
        die.masks[test.tno] = sum(1 << b for b, count in enumerate(counts) if count)
    source = Identity(Path('adaptive_WT1.asc'), 'ADAPT', 1, 1, 'AA', 1)
    return Wafer(Config(tuple(tests), TAIL_MODE), (Phase(source, {(0, 0): die}),))


class TestTailAdjustedFBC0(unittest.TestCase):
    def test_example_and_independent_blk_baselines(self):
        w = adaptive_wafer()
        results = [next(w.crossings(0, (0, 0), blk=b))[2] for b in (0, 1)]
        self.assertEqual([c.voltage for c in results], [.945, .945])
        self.assertEqual([c.adjustment['baseline'] for c in results], [2, 10])
        self.assertEqual([c.adjustment['evidence'][0]['effective_fbc_threshold'] for c in results], [3, 11])
        for c in results:
            self.assertEqual(c.adjustment['raw_voltage'], 1.035)
            self.assertEqual(c.adjustment['ignored_tnos'], [201, 202])
            self.assertEqual(c.tno, 203)
        # Raw FBC vectors and original 90% outputs are untouched.
        self.assertEqual(w.die(0, (0, 0)).fbc[201][0], 1)
        self.assertEqual(next(w.crossings(0, (0, 0), blk=0, mode='FBC90%'))[2].voltage, .855)
        legacy = copy.deepcopy(w); legacy.config.mode = 'FBC0'
        self.assertEqual(next(legacy.crossings(0, (0, 0), blk=0))[2].voltage, 1.035)
        self.assertEqual(w.merged_fbc90(0, (0, 0), 0), legacy.merged_fbc90(0, (0, 0), 0))

    def test_maps_matrix_detail_and_api_agree(self):
        w = adaptive_wafer()
        for scope in ('chip', 'pattern:Scan'):
            result = w.vmin_distribution(0, (0, 0), scope)
            self.assertEqual(result['mode'], TAIL_MODE)
            self.assertEqual(result['summary']['voltage'], .945)
            self.assertEqual(result['entries'][0]['voltage'], .945)
            self.assertEqual(result['entries'][0]['fbc90_voltage'], .855)
            self.assertEqual(result['entries'][0]['adjustment']['baseline'], 2)
        self.assertEqual(w.map(0, 'Scan', 'vmin')[0]['voltage'], .945)
        self.assertEqual(w.grid((0, 0))[0]['trigger']['voltage'], .945)
        self.assertEqual(w.detail(0, (0, 0), 0)['crossings'][0]['adjustment']['baseline'], 2)
        response = view(w, dict(view='vmin_distribution', wt=1, x=0, y=0, scope='pattern:Scan'))
        self.assertEqual(response['summary']['raw_voltage'], 1.035)
        self.assertEqual(w.vmin_distribution(0, (0, 0), 'merge')['mode'], 'FBC90%')

    def test_each_safety_gate_can_prevent_adjustment(self):
        tests, counts = sweep([0, 1, 2, 80, 500])
        for settings in (TailBitSettings(max_tail_bits=1), TailBitSettings(max_tail_fraction=.01),
                         TailBitSettings(jump_ratio=100), TailBitSettings(slope_ratio=100),
                         TailBitSettings(min_gap_steps=3), TailBitSettings(confirmation_points=3)):
            result = vmin(tests, counts, TAIL_MODE, hard_voltage=1.2, tail_bits=settings)
            self.assertFalse(result.adjustment['applied'], settings)
            self.assertEqual(result.voltage, 1.035)

    def test_gradual_single_spike_and_insufficient_data_keep_raw(self):
        for counts in ([0, 1, 2, 3, 4], [0, 1, 2, 80, 2], [0, 1, 2, 3, 500], [0, 1, None, 80, 500]):
            tests, values = sweep(counts)
            raw = vmin(tests, values, 'FBC0', hard_voltage=1.2)
            result = vmin(tests, values, TAIL_MODE, hard_voltage=1.2)
            self.assertFalse(result.adjustment['applied'])
            self.assertEqual((result.voltage, result.relation, result.tno), (raw.voltage, raw.relation, raw.tno))

    def test_slope_is_normalized_by_voltage_interval(self):
        tests, counts = sweep([0, 1, 2, 80, 500], (1.035, .99, .989, .689, .389))
        result = vmin(tests, counts, TAIL_MODE, hard_voltage=1.2)
        self.assertFalse(result.adjustment['applied'])

    def test_repeated_voltages_and_functions_are_not_summed(self):
        tests = []; values = []
        for i, (voltage, count) in enumerate(zip((1.035, .99, .945, .90, .855), (0, 1, 2, 80, 500))):
            tests.extend((Test('Function', 200+3*i, 'A', voltage),
                          Test('Function', 201+3*i, 'A', voltage),
                          Test('Function', 202+3*i, 'B', voltage, stop='Scan' if i == 4 else '')))
            values.extend((count, count, 0))
        result = vmin(tests, values, TAIL_MODE, hard_voltage=1.2)
        self.assertEqual(result.voltage, .945)
        self.assertEqual(result.adjustment['baseline'], 2)
        self.assertEqual(result.adjustment['ignored_tnos'], [203, 204, 206, 207])
        self.assertEqual(len(result.adjustment['evidence']), 1)
        # A real weak B function must remain; A evidence cannot suppress B failures.
        values[5] = values[8] = values[11] = values[14] = 1
        result = vmin(tests, values, TAIL_MODE, hard_voltage=1.2)
        self.assertEqual(result.voltage, 1.035)
        self.assertNotIn(205, result.adjustment['ignored_tnos'])

    def test_changed_function_coverage_and_internal_rise_fall_back(self):
        tests, counts = sweep([0, 1, 2, 80, 500]); tests[2] = Test('Function', 202, 'Different', .945)
        self.assertIn('coverage', vmin(tests, counts, TAIL_MODE).adjustment['reason'])
        tests, counts = sweep([0, 1, 2, 80, 500], (1.035, .945, .99, .90, .855))
        self.assertIn('Non-descending', vmin(tests, counts, TAIL_MODE).adjustment['reason'])

    def test_recovery_does_not_supply_confirmation_and_hard_bound_is_preserved(self):
        tests, counts = sweep([0, 1, 2, 80, 500], (1.035, .99, .945, .90, 1.26))
        result = vmin(tests, counts, TAIL_MODE, hard_voltage=1.2)
        self.assertFalse(result.adjustment['applied'])
        tests, counts = sweep([100, 100, 100, 100, 100])
        result = vmin(tests, counts, TAIL_MODE, hard_voltage=1.2)
        self.assertEqual((result.voltage, result.relation), (1.2, '>='))
        tests, counts = sweep([0, 0, 0, 0, 100], (1.035, .99, .945, .90, 1.26))
        self.assertEqual(vmin(tests, counts, TAIL_MODE, hard_voltage=1.2).voltage, .90)

    def test_hard_prior_pattern_and_wt_exclusions_are_preserved(self):
        w = adaptive_wafer(); die = w.die(0, (0, 0))
        die.fbc[100][0] = 1; die.masks[100] = 1
        self.assertEqual(next(w.crossings(0, (0, 0), blk=0))[2].status, 'Hard Fail')
        w = adaptive_wafer()
        self.assertEqual(list(w.crossings(0, (0, 0), blk=0))[1][2].status, 'Prior Pattern')
        second = copy.deepcopy(w.phases[0]); second.source = Identity(Path('adaptive_WT2.asc'), 'ADAPT', 1, 2, 'AA', 2)
        w.phases = (*w.phases, second)
        self.assertEqual(next(w.crossings(1, (0, 0), blk=0))[2].status, 'Prior WT')

    def test_settings_validation_and_legacy_defaults(self):
        self.assertEqual(TailBitSettings.create(), TailBitSettings())
        for values in ({'unknown': 1}, {'max_tail_bits': -1}, {'max_tail_bits': 1.5}, {'jump_ratio': float('nan')},
                       {'max_tail_fraction': 1}, {'confirmation_points': 1}, {'slope_ratio': True}):
            with self.subTest(values=values), self.assertRaises(ValueError):
                TailBitSettings.create(values)
        rows = [dict(group='Function', tno=200, name='A', voltage=1, stop='Scan')]
        self.assertEqual(Config.create(rows).mode, 'FBC0')
        cfg = Config.create(rows, TAIL_MODE, tail_bits={'max_tail_bits': '20'})
        self.assertEqual(cfg.json()['tail_bits']['max_tail_bits'], 20)
        self.assertEqual(Config.create(**{k:v for k,v in cfg.json().items()}).json(), cfg.json())

    def test_highest_voltage_small_fail_can_be_adjusted_with_evidence(self):
        tests, counts = sweep([1, 2, 80, 500, 1000])
        result = vmin(tests, counts, TAIL_MODE, hard_voltage=1.2)
        self.assertEqual((result.adjustment['raw_voltage'], result.adjustment['raw_relation']), (1.2, '>='))
        self.assertEqual((result.voltage, result.relation), (.99, ''))

    def test_stop_sign_name_does_not_limit_new_mode(self):
        from dataclasses import replace
        w = adaptive_wafer()
        w.config = Config(tuple(replace(t, stop='FutureFlow') if t.stop == 'Scan' else t for t in w.config.tests), TAIL_MODE)
        self.assertEqual(w.pattern_chip_vmin(0, (0, 0), 'FutureFlow')['voltage'], .945)

    def test_bridge_persists_thresholds_and_rejects_invalid_settings(self):
        from unittest.mock import patch
        from app import DesktopAPI
        cfg = adaptive_wafer().config.json()
        with tempfile.TemporaryDirectory() as folder, patch('app.PROFILES', Path(folder)/'settings.json'):
            api = DesktopAPI()
            response = api.request('save-settings', dict(profile='full', **cfg))
            self.assertEqual(response['mode'], TAIL_MODE)
            self.assertEqual(api.request('settings', {})['settings']['full']['tail_bits'], cfg['tail_bits'])
            cfg['tail_bits']['max_tail_bits'] = -1
            self.assertIn('bridge_error', api.request('save-settings', dict(profile='full', **cfg)))
            self.assertEqual(api.request('settings', {})['settings']['full']['tail_bits']['max_tail_bits'], 10)

    def test_excel_audit_and_config_round_trip(self):
        from openpyxl import load_workbook
        w = adaptive_wafer()
        w.config.tail_bits = TailBitSettings(max_tail_bits=12)
        with tempfile.TemporaryDirectory() as folder:
            for kind in ('full', 'fbc'):
                path = save_report(w, Path(folder), kind)
                settings = workbook_config(path)
                self.assertEqual(settings['mode'], TAIL_MODE)
                self.assertEqual(settings['tail_bits']['max_tail_bits'], 12)
                book = load_workbook(path, read_only=True, data_only=True)
                rows = list(book['Tail FBC0 Audit'].values)
                row = dict(zip(rows[0], rows[1]))
                self.assertEqual(row['Original FBC0 Vmin (V)'], 1.035)
                self.assertEqual(row['Selected Vmin (V)'], .945)
                self.assertEqual(row['Max excluded early FBC'], 2)
                self.assertEqual(json.loads(row['Evidence'])[0]['effective_fbc_threshold'], 3)
                book.close()


if __name__ == '__main__':
    unittest.main()
