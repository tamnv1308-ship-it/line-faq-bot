import json
import os
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

    def test_numeric_sheet_code_restores_one_leading_zero(self):
        row = ['1',131491005393,'Điện thoại iPhone 18 Pro 256GB','MỞ','KHÓA','MỞ']
        self.assertEqual(parse_rows([row]),{'0131491005393':['MỞ','KHÓA','MỞ']})
        row[1]='131491005393'
        full=row[:];full[1]='0131491005393';full[3]='KHÓA'
        self.assertTrue(all('Chưa rõ' in value for value in parse_rows([row,full])['0131491005393']))
        for bad in ('13149100539','00131491005393','131491005393.0','1.31491005393E11','13149100539x'):
            row[1]=bad
            self.assertEqual(parse_rows([row]),{})

    def test_forced_reload_replaces_fresh_cache_and_next_read_uses_it(self):
        import co_conditions as c
        response=Mock();response.json.return_value={'values':[['1','131491005393','iPhone 18 Pro','KHÓA','MỞ','KHÓA']]}
        client=Mock();client.http_client.session.get.return_value=response
        with patch.object(c,'_until',float('inf')),patch.object(c,'_cache',{'0131491005393':['MỞ']*3}),patch.dict('sys.modules',{'sheets':Mock(get_client=Mock(return_value=client))}):
            fresh=c.load_conditions(force=True)
            self.assertEqual(fresh,{'0131491005393':['KHÓA','MỞ','KHÓA']})
            self.assertEqual(c.load_conditions(),fresh)
            client.http_client.session.get.assert_called_once()

    def test_network_failure_clears_old_permissions(self):
        import co_conditions as c
        with patch.object(c,'_until',0), patch.object(c,'_cache',{'old':['MỞ']*3}), patch.dict('sys.modules',{'sheets':Mock(get_client=Mock(side_effect=RuntimeError()))}):
            self.assertEqual(c.load_conditions(),{})
            with self.assertRaises(RuntimeError):c.load_conditions(force=True)
            self.assertEqual(c._cache,{})

    def test_aliases_and_compact_buttons(self):
        for label in ('Mã kho xuất', 'Mã kho cho', 'Mã kho chuyển', 'ma kho cho'):
            p = parse_request(label+': 1\nMã kho nhận: 2\nMSP: 0131491005393')
            self.assertEqual((p['source'],p['destination']),('1','2'))
        p.update(product_name='iPhone 18 Pro',note='QL cho hàng: A. Mọi thắc mắc liên hệ Tâm')
        text = preview_text(dict(id='0123456789',payload=json.dumps(p)))
        self.assertNotIn('Quá hạn',text)
        self.assertIn('Hiệu lực: 1 phút',text)
        self.assertEqual([x['action']['label'] for x in line_text_messages(text)[-1]['quickReply']['items']],['Xác nhận','Hủy'])


class ConditionsReloadTests(unittest.TestCase):
    def test_authenticated_reload_and_failure_leave_jobs_untouched(self):
        from flask import Flask
        from co_flow import install
        with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,{'CO_ENABLED':'1','CO_DB_PATH':tmp+'/q.db','CO_DATABASE_URL':'','CO_WORKER_TOKEN':'x'*40}):
            app=Flask(__name__);install(app,lambda *a:None,lambda *a:None)
            client=app.test_client();q=Queue(tmp+'/q.db')
            job=q.draft('event','owner','chat',dict(source='1',destination='2',product='0131491005393',quantity=1,note=''))
            endpoint='/co/worker/conditions/reload';headers={'Authorization':'Bearer '+'x'*40}
            policies={'0131491005393':['MỞ','KHÓA','MỞ']}
            with patch('co_flow.load_conditions',return_value=policies) as load:
                self.assertEqual(client.post(endpoint).status_code,401)
                load.assert_not_called()
                response=client.post(endpoint,json={},headers=headers)
                self.assertEqual(response.status_code,200)
                self.assertEqual(response.json,dict(ok=True,count=1,conditions=policies))
                load.assert_called_once_with(force=True)
            with patch('co_flow.load_conditions',side_effect=RuntimeError('private upstream error')):
                response=client.post(endpoint,json={},headers=headers)
                self.assertEqual(response.status_code,502)
                self.assertFalse(response.json['ok'])
                self.assertNotIn('private',response.get_data(as_text=True))
            with q.db() as db:self.assertEqual(dict(db.execute('SELECT * FROM jobs WHERE id=?',(job['id'],)).fetchone()),job)


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
            self.assertIn('hết hạn',self.q.confirm(jid,'o','c'))

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
