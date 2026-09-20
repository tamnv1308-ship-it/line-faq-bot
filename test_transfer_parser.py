import unittest
import unicodedata
from transfer_parser import parse_form, is_transfer_message

SAMPLE='''Điện thoại iPhone 18 Pro Max 1TB Glacier
Mã sản phẩm : 0131491005420
Kho xuất : 2533
Kho nhận : 315
QL cho hàng : Người A -
Nhờ anh @Người B 21028 DM/VH xác nhận để NH tạo lệnh về cho KH ạ
Khách đang đợi ạ - 16688
Nhờ a/c tạo lệnh giúp e ạ @Người C 25251 @Người D 31718 @Người E 282210'''

class ParserTests(unittest.TestCase):
    def test_user_sample_missing_quantity(self):
        self.assertTrue(is_transfer_message(SAMPLE))
        with self.assertRaisesRegex(ValueError,'Thiếu Số lượng'):
            parse_form(SAMPLE)
    def test_user_sample_complete_ignores_unlabelled_notes(self):
        p=parse_form(SAMPLE+'\nSL: 1 máy')
        self.assertEqual((p['source'],p['destination'],p['product'],p['quantity']),('2533','315','0131491005420',1))
        self.assertEqual(p['note'],'')
        p=parse_form(SAMPLE+'\nSL: 1 máy\nNote: chuyển gấp\nNhờ @Người F hỗ trợ\nGhi chú: khách đợi')
        self.assertEqual(p['note'],'chuyển gấp\nkhách đợi')
    def test_variants(self):
        for text in ['KHO XUẤT：2533; Kho nhập = 315 | MSP: 0131491005420; SL: 1',
                     '• kho xuat 2533\n- kho nhan 315\n* ma sp 0131491005420\nso luong 1 chiếc',
                     'Kho xuất: 2533 - Cửa hàng A\nKho nhận: 315 - Cửa hàng B\nSKU: 0131491005420\nSố lượng: 1']:
            for value in (text,unicodedata.normalize('NFD',text)):
                self.assertEqual(parse_form(value)['product'],'0131491005420')
    def test_ambiguous_and_multiple_orders_rejected(self):
        base='Kho xuất: 2533\nKho nhận: 315\nMSP: 0131491005420\nSL: 1'
        for value in [base+'\nKho xuất: 99',base+'\n'+base,base.replace('2533','2533/99'),base.replace('SL: 1','SL: 1 hoặc 2'),base.replace('SL: 1','SL: 1.5'),base.replace('SL: 1','SL: -1')]:
            with self.assertRaises(ValueError):parse_form(value)
    def test_no_guessing_from_mentions(self):
        self.assertFalse(is_transfer_message('Nhờ @Huy 21028 tạo lệnh giúp. Note: khách đợi'))
        self.assertFalse(is_transfer_message('!say bot | nội dung'))
        with self.assertRaises(ValueError):parse_form('iPhone 1TB @Huy 2533 @Tam 315')
    def test_note_not_silently_truncated(self):
        with self.assertRaisesRegex(ValueError,'500'):
            parse_form('Kho xuất: 1\nKho nhận: 2\nMSP: 0003\nSL: 1\nNote: '+'a'*501)

if __name__=='__main__':unittest.main()
