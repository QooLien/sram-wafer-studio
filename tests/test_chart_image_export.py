"""Native chart saves preserve bytes, cancellation and existing files on failure."""
import base64
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from app import DesktopAPI, chart_image_bytes

SVG = '<svg xmlns="http://www.w3.org/2000/svg" width="100" height="50"><text x="1" y="20">≥1.20 V</text></svg>'
PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aV1sAAAAASUVORK5CYII=')


class TestChartImageExport(unittest.TestCase):
    def test_bytes_preserve_svg_unicode_and_png(self):
        self.assertEqual(chart_image_bytes(dict(format='svg', content=SVG)), SVG.encode())
        self.assertEqual(chart_image_bytes(dict(format='png', content=base64.b64encode(PNG).decode())), PNG)

    def test_rejects_invalid_formats_and_payloads(self):
        for data in (dict(format='pdf',content=SVG),dict(format='svg',content='<html/>'),
                     dict(format='svg',content='<svg'),dict(format='png',content='!'),
                     dict(format='png',content=base64.b64encode(b'not png').decode()),
                     dict(format='svg',content='<!DOCTYPE svg>'+SVG)):
            with self.subTest(data=data), self.assertRaises(ValueError):
                chart_image_bytes(data)

    def test_native_save_dialog_and_extension_for_string_and_tuple(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict('sys.modules', webview=SimpleNamespace(FileDialog=SimpleNamespace(SAVE='save'))):
            for format, content, expected in (('svg',SVG,SVG.encode()),('png',base64.b64encode(PNG).decode(),PNG)):
                for tuple_result in (False, True):
                    api=DesktopAPI(); path=str(Path(folder)/'image.old')
                    api._window=Mock();api._window.create_file_dialog.return_value=(path,) if tuple_result else path
                    response=api.request('save-chart',dict(format=format,content=content,filename='a/b:chart.'+format))
                    self.assertFalse(response['cancelled'])
                    self.assertEqual(Path(response['path']).read_bytes(),expected)
                    self.assertEqual(Path(response['path']).suffix,'.'+format)
                    filename=api._window.create_file_dialog.call_args.kwargs['save_filename']
                    self.assertNotIn('/',filename);self.assertNotIn(':',filename)
            self.assertFalse(list(Path(folder).glob('.sram-chart-*')))

    def test_cancel_does_not_write(self):
        with patch.dict('sys.modules', webview=SimpleNamespace(FileDialog=SimpleNamespace(SAVE='save'))):
            api=DesktopAPI();api._window=Mock();api._window.create_file_dialog.return_value=None
            with patch('app.NamedTemporaryFile') as temporary:
                self.assertEqual(api.request('save-chart',dict(format='svg',content=SVG)),{'cancelled':True})
                temporary.assert_not_called()

    def test_write_failure_preserves_existing_file_and_cleans_temp(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict('sys.modules', webview=SimpleNamespace(FileDialog=SimpleNamespace(SAVE='save'))):
            path=Path(folder)/'image.svg';path.write_text('original')
            api=DesktopAPI();api._window=Mock();api._window.create_file_dialog.return_value=str(path)
            with patch('app.Path.replace',side_effect=OSError('disk error')):
                response=api.request('save-chart',dict(format='svg',content=SVG))
            self.assertIn('bridge_error',response)
            self.assertEqual(path.read_text(),'original')
            self.assertFalse(list(Path(folder).glob('.sram-chart-*')))


if __name__=='__main__':
    unittest.main()
