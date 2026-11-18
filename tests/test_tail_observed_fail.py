"""Observed highest-voltage failures participate without becoming exact Vmin."""
import unittest
from array import array
from pathlib import Path

from engine import (Config, Test, ChipData, Phase, Identity, Wafer, Crossing,
                    tail_sample_voltage, voltage_distribution)


def tail_wafer():
    voltages = (1.035, .99, .90, .81, .765)
    tests = (Test('Function', 100, 'Hard', 1.2, stop='Hard Fail'),) + tuple(
        Test('Function', 200+i, 'S'+str(i), voltage, stop='Scan' if i == 4 else '')
        for i, voltage in enumerate(voltages)) + (Test('Function', 300, 'M', .765, stop='March'),)
    die = ChipData()
    for test in tests:
        counts = [0]*256
        if 200 <= test.tno < 300:
            for blk, first in enumerate((1.035, .90, .765, .765, .765, .765)):
                counts[blk] = 100 if test.voltage <= first else 0
        die.fbc[test.tno] = array('Q', counts)
        die.masks[test.tno] = sum(1 << b for b, count in enumerate(counts) if count)
    source = Identity(Path('tail_WT1.asc'), 'TAIL', 1, 1, 'AA', 1)
    return Wafer(Config(tests, 'FBC90%'), (Phase(source, {(0, 0): die}),))


class TestObservedFailTail(unittest.TestCase):
    def test_bound_can_restore_old_tail_and_become_tail_itself(self):
        w = tail_wafer()
        for scope in ('chip', 'Scan', 'merge'):
            with self.subTest(scope=scope):
                result = w.vmin_distribution(0, (0, 0), scope)
                box, summary = result['box'], result['summary']
                self.assertEqual((box['exact_count'], box['bound_count'], box['count']), (5, 1, 6))
                self.assertEqual(box['exact_only_tail'], [1])
                self.assertEqual(box['returned_from_tail'], [1])
                self.assertEqual(box['exact_only_upper_fence'], .765)
                self.assertEqual(box['upper_fence'], 1.018125)
                self.assertEqual(summary['tail'], [0])
                self.assertEqual((summary['blk'], summary['voltage'], summary['relation']), (1, .90, ''))
                self.assertEqual(summary['before_tail']['relation'], '>=')
                self.assertEqual(summary['before_tail']['voltage'], 1.2)
                bound = result['entries'][0]
                self.assertEqual((bound['tail_voltage'], bound['fbc90_voltage'], bound['fbc90_relation']),
                                 (1.035, 1.2, '>='))
        self.assertEqual(w.map(0, 'Scan', 'vmin')[0]['blk'], 1)
        self.assertEqual(w.grid((0, 0))[1]['trigger']['voltage'], .90)

    def test_no_observed_voltage_does_not_substitute_hard_voltage(self):
        bound = Crossing(1, 1.2, 'S', 10, 'Fail', '>=')
        self.assertIsNone(tail_sample_voltage(bound))
        box, _, tail = voltage_distribution({0: ('Scan', bound)}, {'Scan': [1.035, .9]})
        self.assertEqual(box['count'], 0)
        self.assertEqual(tail, [])

    def test_recovery_uses_corrected_voltage_not_raw_recovery_voltage(self):
        corrected = Crossing(5, .765, 'Recovery', 100, 'Fail', '', 1.26, 4, 'terminal-recovery')
        self.assertEqual(tail_sample_voltage(corrected), .765)

    def test_many_bounds_can_leave_bound_as_judge_candidate(self):
        readings = {i: ('Scan', Crossing(1, 1.2, 'S', 100, 'Fail', '>=', 1.035)) for i in range(4)}
        readings[4] = ('Scan', Crossing(2, .9, 'S2', 100, 'Fail'))
        box, _, tail = voltage_distribution(readings, {'Scan': [1.035, .99, .9, .81, .765]})
        self.assertEqual(box['high'], 1.035)
        self.assertEqual(tail, [])


if __name__ == '__main__':
    unittest.main()
