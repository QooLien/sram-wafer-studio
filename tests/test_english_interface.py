"""Guard English-owned UI text; source data and user names are not translated."""
from pathlib import Path
import re
import unittest
from engine import Config
from app import view
from test_vmin_distribution_and_monitor import monitor_wafer

ROOT=Path(__file__).resolve().parents[1]


class TestEnglishInterface(unittest.TestCase):
    def test_owned_runtime_text_contains_no_chinese(self):
        for name in ('web/index.html','web/app.js','app.py','engine.py','exports.py',
                     'pattern_reports.py','workbook_results.py','workbook_settings.py'):
            with self.subTest(name=name):
                self.assertIsNone(re.search(r'[\u3400-\u9fff]',(ROOT/name).read_text()))
        self.assertIn('lang="en"',(ROOT/'web/index.html').read_text())

    def test_user_stop_sign_names_remain_unchanged(self):
        cfg=Config.create([dict(group='Function',tno=200,name='原始測試',voltage=1.0,stop='自訂流程')])
        self.assertEqual(list(cfg.patterns),['自訂流程'])
        self.assertEqual(cfg.functions[0].name,'原始測試')

    def test_errors_are_readable_english(self):
        with self.assertRaisesRegex(ValueError,'Select FBC0'):
            Config.create([],mode='invalid')
        with self.assertRaisesRegex(ValueError,'Chip coordinates'):
            view(monitor_wafer(),dict(view='grid',wt=1,x=999,y=999))


if __name__=='__main__':
    unittest.main()
