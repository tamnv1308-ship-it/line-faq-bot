import unittest
from transfer_parser import parse_request, is_transfer_message

FORM='''- \ufeff\ufeffMã kho xuất: 9469

- \ufeff\ufeffMã kho nhận: 7298

- \ufeff\ufeffMSP: 0131491005416

- \ufeff\ufeffTên sp: Điện thoại iPhone 18 Pro Max 512GB Glacier
(Barcode: 195951411699)

- Số Lượng : 1'''

class CopiedFormTests(unittest.TestCase):
    def test_exact_pasted_form_is_recognized(self):
        self.assertTrue(is_transfer_message(FORM))
        p=parse_request(FORM)
        self.assertEqual((p['source'],p['destination'],p['product'],p['quantity'],p['status']),
                         ('9469','7298','0131491005416',1,'Mới'))
        self.assertEqual(p['note'],'')

    def test_formatting_markers_and_nonbreaking_spaces(self):
        for marker in ('\ufeff','\u200b','\u2060','\u200e','\u200f'):
            text=FORM.replace('\ufeff',marker).replace('Mã kho','Mã\u202fkho').replace('Số Lượng','Số\u00a0Lượng')
            with self.subTest(marker=repr(marker)):
                self.assertEqual(parse_request(text)['product'],'0131491005416')

    def test_notes_and_explicit_status_are_preserved(self):
        note='QL cho hàng: @Tâm 👨\u200d💻 Nguyễn Văn'
        p=parse_request(FORM+'\n- \ufeffTrạng thái: Đã sử dụng\n'+note)
        self.assertEqual(p['status'],'Đã sử dụng')
        self.assertEqual(p['note'],note)

    def test_multiple_copied_forms_keep_separate_rows(self):
        text=FORM+'\n\ufeff===\n'+FORM.replace('9469','9470').replace('7298','7299')
        p=parse_request(text)
        self.assertEqual([(r['source'],r['destination']) for r in p['items']],
                         [('9469','7298'),('9470','7299')])

    def test_incomplete_and_ambiguous_forms_still_fail(self):
        for text in (FORM.replace('- \ufeff\ufeffMSP: 0131491005416',''),
                     FORM.replace('7298','7298/7299'),
                     '- \ufeffMSP: 0131491005416\n\ufeff===\n- \ufeffKho xuất: 9469\nKho nhận: 7298'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                parse_request(text)

    def test_barcode_or_note_alone_is_not_a_transfer(self):
        self.assertFalse(is_transfer_message('\ufeff(Barcode: 195951411699)'))
        self.assertFalse(is_transfer_message('\ufeffNote: nhờ @Tâm 258330 hỗ trợ'))

if __name__=='__main__':
    unittest.main()
