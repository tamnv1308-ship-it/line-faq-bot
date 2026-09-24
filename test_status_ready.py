import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch
import mac_worker as w

class StatusReadyTests(unittest.TestCase):
    def test_blank_reloads_before_brand_and_status_selection(self):
        page=MagicMock();control=page.get_by_role.return_value
        control.input_value.side_effect=['']*7+['2 - Đã sử dụng']*3
        with patch.object(w,'progress'),patch.object(w,'select_brands') as brands,patch.object(w,'select_product_status') as select:
            w.prepare_import_controls(page,{'id':'a','payload':{'status':'Mới'}})
        page.reload.assert_called_once();brands.assert_called_once();select.assert_called_once_with(page,'Mới')
    def test_ready_status_does_not_reload(self):
        page=MagicMock();page.get_by_role.return_value.input_value.return_value='8 - Mới (Giảm giá)'
        with patch.object(w,'progress'),patch.object(w,'select_brands'),patch.object(w,'select_product_status'):
            w.prepare_import_controls(page,{'id':'a','payload':{}})
        page.reload.assert_not_called()
    def test_permanently_blank_never_uploads(self):
        page=MagicMock();page.url=w.URL;page.get_by_role.return_value.input_value.return_value=' '
        with tempfile.TemporaryDirectory() as tmp,patch.object(w,'ROOT',Path(tmp)),patch.object(w,'progress'),patch.object(w,'upload_excel') as upload,patch.object(w,'report') as report:
            w.process(page,{'id':'a','payload':{},'mode':'preview'})
        upload.assert_not_called();self.assertEqual(report.call_args.args[1],'failed')
        self.assertIn('trạng thái sản phẩm vẫn trống',report.call_args.args[2])
    def test_status_cleared_by_brands_requires_reload(self):
        page=MagicMock();page.get_by_role.return_value.input_value.side_effect=['1 - Mới','1 - Mới','','1 - Mới','1 - Mới','1 - Mới']
        with patch.object(w,'progress'),patch.object(w,'select_brands') as brands,patch.object(w,'select_product_status') as select:
            w.prepare_import_controls(page,{'id':'a','payload':{}})
        page.reload.assert_called_once();self.assertEqual(brands.call_count,2);select.assert_called_once()
if __name__=='__main__':unittest.main()
