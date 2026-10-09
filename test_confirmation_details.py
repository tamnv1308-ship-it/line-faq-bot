import json
import unittest
from transfer_parser import parse_request
from co_results import preview_names,preview_details,line_text_messages

class ConfirmationDetailsTests(unittest.TestCase):
    def test_numbered_aliases(self):
        for label in ['1. Mã SP','1. Mã code','mã code','ma code']:
            self.assertEqual(parse_request(label+': 0131491005418\nKho xuất: 1\nKho nhận: 2')['product'],'0131491005418')
    def test_verified_store_names(self):
        payload=dict(source='1',destination='2')
        wire=json.dumps({'rows':[dict(product_name='Phone',source_name='1 - Kho A',destination_name='2 - Kho B')]})
        self.assertEqual(preview_names(payload,wire),['Phone'])
        self.assertEqual(preview_details(payload,wire)[0]['source_name'],'1 - Kho A')
        with self.assertRaises(ValueError):preview_details(dict(source='3',destination='2'),wire)
    def test_buttons_keep_job_ownership_commands(self):
        actions=line_text_messages('XÁC NHẬN TẠO CO — abc123def4\nThông tin')[0]['quickReply']['items']
        self.assertEqual([x['action']['text'] for x in actions],['XACNHAN abc123def4','HUY abc123def4'])
        self.assertNotIn('quickReply',line_text_messages('Thông báo thường')[0])
    def test_compact_preview_and_one_minute_expiry(self):
        import tempfile,time
        from co_flow import Queue,preview_text
        with tempfile.TemporaryDirectory() as d:
            q=Queue(d+'/q.db')
            p=dict(source='1',destination='2',product='0131491005418',quantity=1,note='',status='Mới',product_name='iPhone',source_name='1 - Kho A',destination_name='2 - Kho B')
            j=q.draft('event','owner','chat',p)
            text=preview_text(j)
            self.assertIn('Kho xuất: 1 - Kho A\nKho nhận: 2 - Kho B',text)
            self.assertIn('Hiệu lực: 1 phút',text)
            self.assertNotIn('Thương hiệu',text)
            with q.db() as db:db.execute('UPDATE jobs SET created=? WHERE id=?',(time.time()-61,j['id']))
            q.confirm(j['id'],'owner','chat')
            with q.db() as db:self.assertEqual(db.execute('SELECT state FROM jobs WHERE id=?',(j['id'],)).fetchone()['state'],'expired')
