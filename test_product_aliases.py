import unittest
from transfer_parser import parse_request

class ProductAliasesTests(unittest.TestCase):
    def test_aliases_preserve_leading_zero(self):
        for label in ['code','CODE','msp','ma san pham','san pham','Sản phẩm','Mã sản phẩm']:
            with self.subTest(label=label):
                p=parse_request(f'{label}: 0131491005418\nKho xuất: 204\nKho nhận: 985')
                self.assertEqual(p['product'],'0131491005418')
    def test_product_name_is_not_a_second_code(self):
        p=parse_request('Sản phẩm: iPhone\ncode 0131491005418\nKho xuất: 204\nKho nhận: 985')
        self.assertEqual(p['product'],'0131491005418')
    def test_mixed_batch_aliases(self):
        p=parse_request('code 00123\nKho xuất: 1\nKho nhận: 2\n===\nsan pham 00456\nKho xuất: 3\nKho nhận: 4')
        self.assertEqual([x['product'] for x in p['items']],['00123','00456'])
