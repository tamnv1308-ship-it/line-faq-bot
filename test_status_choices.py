import unittest
from unittest.mock import Mock
from transfer_parser import parse_form, normalize_status
from mac_worker import select_product_status
BASE='Kho xuất: 1\nKho nhận: 2\nMSP: 0131491005418'
class StatusTests(unittest.TestCase):
 def test_all_labels_and_notes(self):
  for status in ['Mới','Đã sử dụng','Mới (giảm giá)','Trưng bày','Lỗi (mới)','Lỗi (ĐSD)']:
   for prefix in ['Trạng thái: ','Trạng thái ','Note: ','Note: trạng thái: ','']:
    self.assertEqual(parse_form(BASE+'\n'+prefix+status)['status'],normalize_status(status))
  self.assertEqual(parse_form(BASE)['status'],'Mới')
 def test_conflict(self):
  with self.assertRaises(ValueError):parse_form(BASE+'\nNote: Đã sử dụng\nTrạng thái: Mới')
 def test_option(self):
  page=Mock();control=Mock();option=Mock()
  control.input_value.side_effect=['1 - Mới','5 - Lỗi (ĐSD)','5 - Lỗi (ĐSD)']
  option.inner_text.return_value='5 - Lỗi (ĐSD)';option.is_visible.return_value=True
  page.get_by_role.side_effect=lambda role,**kw:control if role=='combobox' else Mock(all=lambda:[option])
  select_product_status(page,'Lỗi (ĐSD)');option.click.assert_called_once()
 def test_missing(self):
  page=Mock();control=Mock();control.input_value.return_value='1 - Mới'
  page.get_by_role.side_effect=lambda role,**kw:control if role=='combobox' else Mock(all=lambda:[])
  with self.assertRaises(RuntimeError):select_product_status(page,'Trưng bày')
