"""Trailing recovery voltages must not masquerade as high-voltage Go/No-Go failures."""
import unittest
from array import array
from pathlib import Path
from engine import Config, Test, Wafer, Phase, Identity, ChipData, vmin


def flow(voltages, name="Scan", offset=200):
    return [Test("Function", offset+i, "item"+str(i), voltage,
                 stop=name if i==len(voltages)-1 else "") for i,voltage in enumerate(voltages)]


def recovery_wafer(target="Scan"):
    tests=[Test("Function",110,"Hard",1.2,stop="Hard Fail")]
    for i,name in enumerate(("Scan","March","FutureFlow")):
        tests.extend(flow([1.035,.765,1.26],name,200+i*100))
    die=ChipData()
    for test in tests:
        count=10 if test.tno%100==1 else 100 if test.tno%100==2 else 0
        active=test.tno//100=={"Scan":2,"March":3,"FutureFlow":4}[target]
        die.fbc[test.tno]=array('Q',[count if active else 0]+[0]*255)
        die.masks[test.tno]=int(active and count>0)
    source=Identity(Path('recovery_WT1.asc'),'RECOV',1,1,'AA',1)
    return Wafer(Config(tuple(tests),'FBC90%'),(Phase(source,{(0,0):die}),))


class TestTerminalRecoveryVoltage(unittest.TestCase):
    def test_reported_example_retains_true_crossing(self):
        result=vmin(flow([.765,1.26]),[10,100],'FBC90%',hard_voltage=1.2)
        self.assertEqual((result.voltage,result.relation),(.765,''))
        self.assertEqual((result.tno,result.fbc,result.test_voltage),(201,100,1.26))
        self.assertEqual((result.voltage_tno,result.voltage_rule),(200,'terminal-recovery'))

    def test_repeated_and_multiple_recovery_items(self):
        scope=flow([1.035,.765,.765,1.2,1.26,1.26])
        result=vmin(scope,[0,1,1,2,3,100],'FBC90%',hard_voltage=1.2)
        self.assertEqual((result.voltage,result.voltage_tno,result.tno),(.765,202,205))
        result=vmin(scope,[0,0,0,100,100,100],'FBC90%',hard_voltage=1.2)
        self.assertEqual((result.voltage,result.tno),(.765,203))

    def test_thresholds_and_missing_data_preserved(self):
        scope=flow([1.035,.765,1.26])
        for mode in ('FBC0','FBC1','FBC10','FBC90%'):
            with self.subTest(mode=mode):
                self.assertEqual(vmin(scope,[0,0,100],mode,hard_voltage=1.2).voltage,.765)
        self.assertEqual(vmin(scope,[0,None,100],'FBC90%',hard_voltage=1.2).status,'No Data')
        self.assertEqual(vmin(scope,[0,0,0],'FBC90%',hard_voltage=1.2).status,'Pass')
        # The same threshold and raw peak are used: a 100-FBC terminal item does not lower the 90% threshold.
        self.assertEqual(vmin(scope,[0,89,100],'FBC90%',hard_voltage=1.2).tno,202)

    def test_real_first_highest_fail_still_reports_hard_bound(self):
        result=vmin(flow([1.035,.765,1.26]),[100,100,100],'FBC90%',hard_voltage=1.2)
        self.assertEqual((result.tno,result.voltage,result.relation),(200,1.2,'>='))

    def test_merge_does_not_backtrack_into_previous_flow(self):
        scope=flow([1.035,.765],'Scan')+flow([1.035,.9],'March',300)
        result=vmin(scope,[0,0,100,100],'FBC90%',hard_voltage=1.2)
        self.assertEqual((result.tno,result.voltage,result.relation),(300,1.2,'>='))
        self.assertEqual(result.voltage_rule,'')

    def test_all_stop_signs_and_merge_use_corrected_voltage(self):
        for name in ('Scan','March','FutureFlow'):
            with self.subTest(name=name):
                w=recovery_wafer(name)
                result=w.pattern_chip_vmin(0,(0,0),name)
                self.assertEqual((result['voltage'],result['relation']),(.765,''))
                self.assertEqual(result['voltage_rule'],'terminal-recovery')
                self.assertEqual(result['test_voltage'],1.26)
                self.assertEqual(w.chip_vmin(0,(0,0))['voltage'],.765)
                if name!='FutureFlow':
                    self.assertEqual(w.merged_chip_vmin(0,(0,0))['voltage'],.765)

    def test_tail_box_uses_corrected_exact_readings(self):
        w=recovery_wafer()
        die=w.die(0,(0,0))
        for tno,count in ((201,10),(202,100)):
            die.fbc[tno][:8]=array('Q',[count]*8)
            die.masks[tno]=255
        result=w.vmin_distribution(0,(0,0),'pattern:Scan')
        self.assertEqual(result['box']['count'],8)
        self.assertEqual(result['box']['median'],.765)
        self.assertEqual(result['summary']['tail'],[])
        self.assertEqual(result['summary']['before_tail']['voltage'],.765)


if __name__=='__main__':
    unittest.main()
