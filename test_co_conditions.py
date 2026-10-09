import json
import tempfile
import unittest
from unittest.mock import patch, Mock
from co_conditions import parse_rows, condition_text
from co_flow import Queue, preview_text
from co_results import line_text_messages
from transfer_parser import parse_request


class ConditionsTests(unittest.TestCase):
    def test_exact_sku_and_three_fields(self):
        rows = [['1', '0131491005393', 'Điện thoại iPhone 18 Pro 256GB', 'MỞ', 'KHÓA', 'Mở khi QL duyệt', 'MỞ', 'MỞ']]
        policies = parse_rows(rows)
        item = dict(product='0131491005393', product_name=rows[0][2])
        text = condition_text(item, policies)
        self.assertIn('✅ Bán thường', text)
        self.assertIn('❌ Chiến giá', text)
        self.assertIn('Chuyển kho: Mở khi QL duyệt', text)
        self.assertNotIn('Lostsale', text)
        self.assertNotIn('ƯĐNV', text)
        item['product'] = '0131491005394'
        self.assertEqual(condition_text(item, policies).count('Chưa rõ'), 3)
        self.assertNotIn('❌', condition_text(item, policies))
        item['product_name'] = 'iPhone 17 Pro'
        self.assertEqual(condition_text(item, policies), '')

    def test_duplicate_conflicts_unknown(self):
        row = ['1','0131491005393','iPhone 18 Pro','MỞ','MỞ','MỞ']
        other = row[:];other[3] = 'KHÓA'
        self.assertTrue(all('Chưa rõ' in value for value in parse_rows([row,other])[row[1]]))

    def test_network_failure_clears_old_permissions(self):
        import co_conditions as c
        with patch.object(c,'_until',0), patch.object(c,'_cache',{'old':['MỞ']*3}), patch.dict('sys.modules',{'sheets':Mock(get_client=Mock(side_effect=RuntimeError()))}):
            self.assertEqual(c.load_conditions(),{})

    def test_aliases_and_compact_buttons(self):
        for label in ('Mã kho xuất', 'Mã kho cho', 'Mã kho chuyển', 'ma kho cho'):
            p = parse_request(label+': 1\nMã kho nhận: 2\nMSP: 0131491005393')
            self.assertEqual((p['source'],p['destination']),('1','2'))
        p.update(product_name='iPhone 18 Pro',note='QL cho hàng: A. Mọi thắc mắc liên hệ Tâm')
        text = preview_text(dict(id='0123456789',payload=json.dumps(p)))
        self.assertNotIn('Quá hạn',text)
        self.assertIn('Hiệu lực: 1 phút',text)
        self.assertEqual([x['action']['label'] for x in line_text_messages(text)[-1]['quickReply']['items']],['Xác nhận','Hủy'])


class ConfirmationExpiryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.q=Queue(self.tmp.name+'/q.db')
        self.p=dict(source='1',destination='2',product='0131491005393',quantity=1,note='')

    def ready(self):
        j=self.q.draft('a','o','c',self.p,check_product=True)
        work=self.q.claim(True)
        self.q.update(j['id'],work['lease'],'preview_ready','iPhone 18 Pro')
        return j['id']

    def test_minute_starts_after_delivery_then_releases_next(self):
        with patch('co_flow.time.time',return_value=1000):jid=self.ready()
        with patch('co_flow.time.time',return_value=1080):
            self.assertIsNone(self.q.claim(True,prepared_id=jid))
            self.q.mark_notified(jid,'draft')
            next_job=self.q.draft('b','o','c',self.p,check_product=True)
        with patch('co_flow.time.time',return_value=1139):
            self.assertIsNone(self.q.claim(True,prepared_id=jid))
        with patch('co_flow.time.time',return_value=1140):
            self.assertEqual(self.q.claim(True,prepared_id=jid),{'release_preview':True})
            self.assertEqual(self.q.claim(True)['id'],next_job['id'])
            self.assertIn('đã được xử lý',self.q.confirm(jid,'o','c'))

    def test_confirmed_job_survives_confirmation_deadline(self):
        with patch('co_flow.time.time',return_value=1000):
            jid=self.ready();self.q.mark_notified(jid,'draft')
        with patch('co_flow.time.time',return_value=1059):self.q.confirm(jid,'o','c')
        with patch('co_flow.time.time',return_value=1070):
            self.assertEqual(self.q.claim(True,prepared_id=jid)['mode'],'create')

    def test_confirm_at_exact_deadline_rejected(self):
        with patch('co_flow.time.time',return_value=1000):
            jid=self.ready();self.q.mark_notified(jid,'draft')
        with patch('co_flow.time.time',return_value=1060):
            self.assertIn('hết hạn',self.q.confirm(jid,'o','c'))

    def test_repeat_notification_does_not_extend_deadline(self):
        with patch('co_flow.time.time',return_value=1000):
            jid=self.ready();self.q.mark_notified(jid,'draft')
        with patch('co_flow.time.time',return_value=1050):self.q.mark_notified(jid,'draft')
        with patch('co_flow.time.time',return_value=1061):
            self.assertIn('hết hạn',self.q.confirm(jid,'o','c'))
