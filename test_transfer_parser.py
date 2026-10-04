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
    def test_source_and_product_aliases(self):
        for source in ['Kho chuyển','kho chuyen','Kho xuất']:
            for product in ['MSP','SP','mã sản phẩm','ma san pham']:
                p=parse_form(f'{source}: 2533\nKho nhận: 315\n{product}: 0131491005420\nSL: 1')
                self.assertEqual((p['source'],p['product']),('2533','0131491005420'))
    def test_sp_name_is_not_a_second_product_code(self):
        p=parse_form('SP: Điện thoại iPhone 18 Pro Max\nMSP: 0131491005420\nKho chuyển: 2533\nKho nhận: 315\nSL: 1')
        self.assertEqual(p['product'],'0131491005420')
        with self.assertRaisesRegex(ValueError,'Thiếu Mã sản phẩm'):
            parse_form('SP: iPhone 18\nKho chuyển: 2533\nKho nhận: 315\nSL: 1')

    def test_status_choices(self):
        base='Kho xuất: 1\nKho nhận: 2\nMSP: 0003\nSL: 1'
        self.assertEqual(parse_form(base)['status'],'Mới')
        for status in ['Mới','Đã sử dụng','Mới giảm giá']:
            parsed=parse_form(base+'\nTrạng thái: '+status)
            self.assertEqual(parsed['status'],status)
            self.assertEqual(parsed['note'],'')
        with self.assertRaises(ValueError):
            parse_form(base+'\nTrạng thái: hỏng')
        with self.assertRaises(ValueError):
            parse_form(base+'\nTrạng thái: Mới\nTrạng thái: Đã sử dụng')
    def test_user_sample_missing_quantity(self):
        self.assertTrue(is_transfer_message(SAMPLE))
        p=parse_form(SAMPLE)
        self.assertEqual(p['quantity'],1)
        self.assertTrue(p['quantity_defaulted'])
    def test_user_sample_complete_ignores_unlabelled_notes(self):
        p=parse_form(SAMPLE+'\nSL: 1 máy')
        self.assertEqual((p['source'],p['destination'],p['product'],p['quantity']),('2533','315','0131491005420',1))
        self.assertEqual(p['note'],'QL cho hàng : Người A -')
        p=parse_form(SAMPLE+'\nSL: 1 máy\nNote: chuyển gấp\nNhờ @Người F hỗ trợ\nGhi chú: khách đợi')
        self.assertEqual(p['note'],'QL cho hàng : Người A -\nchuyển gấp\nkhách đợi')
    def test_approval_notes_and_explicit_quantity(self):
        base='Kho xuất: 1\nKho nhận: 2\nMSP: 0003'
        p=parse_form(base+'\nQL cho hàng Hải 196767\nDM xác nhận: Hùng\nNhờ @A hỗ trợ\nSL: 3')
        self.assertEqual(p['note'],'QL cho hàng Hải 196767\nDM xác nhận: Hùng')
        self.assertEqual(p['quantity'],3)
        self.assertFalse(p.get('quantity_defaulted',False))
        self.assertEqual(parse_form(base)['note'],'')
        for invalid in ['', '0', '-1', 'abc']:
            with self.assertRaises(ValueError):
                parse_form(base+'\nSL: '+invalid)

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




class BlankLineRegressionTests(unittest.TestCase):
    def test_whitespace_inside_one_request(self):
        from transfer_parser import parse_request
        for blank in ('   ', '\t  ', '\u00a0   '):
            result = parse_request('MSP: 3641273000143\nImei: SLM4N14G356\n' + blank + '\nTrạng thái: đã sử dụng\nKho Xuất: 15078\nKho Nhận: 1537')
            self.assertEqual((result['source'], result['destination'], result['product'], result['quantity'], result['status']), ('15078', '1537', '3641273000143', 1, 'Đã sử dụng'))

    def test_real_separator_still_rejects_incomplete_record(self):
        from transfer_parser import parse_request
        with self.assertRaises(ValueError):
            parse_request('MSP: 3641273000143\n === \nKho xuất: 15078\nKho nhận: 1537')


class BareProductTests(unittest.TestCase):
    def test_two_returns_with_bare_codes(self):
        from transfer_parser import parse_request
        text = ('St trả cọc cho KH ạ\nMã đơn trả cọc:\n10336SO26090063520\n'
                'Điện thoại iPhone 18 Pro Max 256GB Slive\n0131491005413  \n'
                'Kho xuất: 114\nKho nhận: 10336\n\n'
                'Mã đơn trả cọc: YC xuất: 10336SO26090063420\n'
                'Điện thoại iPhone 18 Pro Max 256GB Burgundy\n0131491005411\n'
                'Kho xuất: 2184\nKho nhận: 10336')
        items = parse_request(text)['items']
        self.assertEqual([(i['product'], i['source'], i['destination'], i['quantity']) for i in items],
                         [('0131491005413', '114', '10336', 1), ('0131491005411', '2184', '10336', 1)])

    def test_only_standalone_exact_13_digits(self):
        from transfer_parser import parse_request
        for text in ('013149100541', '01314910054133', '10336SO26090063520',
                     'IMEI: 0131491005413', '@User 0131491005413', 'Note: 0131491005413'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                parse_request(text + '\nKho xuất: 114\nKho nhận: 10336')

    def test_ambiguous_partial_records_are_not_merged(self):
        from transfer_parser import parse_request
        with self.assertRaises(ValueError):
            parse_request('0131491005413\n0131491005411\nKho xuất: 114\nKho nhận: 10336')




class WarehouseNameTests(unittest.TestCase):
    def test_names_without_dash(self):
        from transfer_parser import parse_request
        result=parse_request('- Mã kho xuất: 10323 - AAR_CTH_NKI - Số 08 Hoà Bình\n- Mã kho nhận: 1759 ĐML Giồng Riềng\n- MSP:0131491004725\n- Trạng thái: mới\n- Số Lượng: 1')
        self.assertEqual((result['source'],result['destination']),('10323','1759'))
        result=parse_request('Kho xuất: 328 ĐMM_HNO_HDO - 746 Quang Trung\nKho nhận: 1759 ĐML Giồng Riềng\nMSP:0131491004725')
        self.assertEqual(result['source'],'328')

    def test_ambiguous_warehouse_numbers_rejected(self):
        from transfer_parser import parse_request
        for value in ('1759 1760', '1759/1760', '1759 hoặc 1760', '1759 và 1760'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_request('Kho xuất: 10323\nKho nhận: '+value+'\nMSP:0131491004725')




class InlineProductTests(unittest.TestCase):
    def test_stock_description_code(self):
        from transfer_parser import parse_request
        text='Nhờ anh/chị NH tạo lệnh giúp em\nĐiện thoại iPhone 18 Pro Max 256GB Black\nKD bình thường 0131491005414  \n\nkho xuât: 1093\nkho nhận: 7246\nSL: 1'
        result=parse_request(text)
        self.assertEqual((result['product'],result['source'],result['destination'],result['quantity']),('0131491005414','1093','7246',1))
        self.assertEqual(parse_request(text+'\n'+text.replace('1093','1094'))['items'][1]['source'],'1094')

    def test_inline_ambiguity_and_other_ids(self):
        from transfer_parser import parse_request
        for line in ('KD bình thường 0131491005414 0131491005413',
                     'KD bình thường IMEI 0131491005414',
                     'Điện thoại mã đơn 0131491005414',
                     'KD bình thường X0131491005414',
                     'KD bình thường 01314910054140'):
            with self.subTest(line=line), self.assertRaises(ValueError):
                parse_request(line+'\nKho xuất: 1093\nKho nhận: 7246')

if __name__=='__main__':unittest.main()
