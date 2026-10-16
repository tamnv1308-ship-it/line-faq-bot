import json
import os
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch
from co_flow import install, Queue

class ReplyTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=str(Path(self.tmp.name)/'q.db')
        self.replies=[];self.pushes=[]
        self.env=patch.dict(os.environ,{'CO_ENABLED':'1','CO_ACK_RECEIPT':'0','CO_GATHER_SECONDS':'0','CO_DB_PATH':self.path,'CO_DATABASE_URL':'','CO_WORKER_TOKEN':'x'*32,'CO_ALLOWED_USER_IDS':'owner'})
        self.env.start();self.addCleanup(self.env.stop)
        app=types.SimpleNamespace(post=lambda route:lambda f:f,get=lambda route:lambda f:f,logger=types.SimpleNamespace(warning=lambda *args:None))
        flask=types.SimpleNamespace(request=None,jsonify=None,abort=None)
        with patch.dict('sys.modules',{'flask':flask}):
            self.handle,self.notify=install(app,self.reply,self.push,requester_name=lambda event:"Người gửi thử nghiệm")
        self.q=Queue(self.path)
        self.q.heartbeat()
    def reply(self,token,text):
        self.replies.append((token,text));return True
    def push(self,*args):
        self.pushes.append(args);return True
    def event(self):
        return types.SimpleNamespace(reply_token='test-token',webhook_event_id='evt',source=types.SimpleNamespace(user_id='owner',group_id='owner'),message=types.SimpleNamespace(id='msg',text='Kho xuất: 123\nKho nhận: 999999\nMã sản phẩm: 0000000000123\nSố lượng: 1\nNote:'))
    def test_immediate_receipt_then_preview_push_without_creation(self):
        with patch.dict(os.environ,{'CO_ACK_RECEIPT':'1'}):
            self.handle(self.event());self.handle(self.event())
        self.assertEqual(len(self.replies),1)
        self.assertIn('Đã nhận yêu cầu',self.replies[0][1])
        self.assertIn('Chưa tạo CO',self.replies[0][1])
        w=self.q.claim(True);self.assertEqual(w['mode'],'preview')
        self.q.update(w['id'],w['lease'],'preview_ready','MWG Product')
        self.notify();self.notify()
        self.assertEqual(len(self.replies),1);self.assertEqual(len(self.pushes),1)
        self.assertIn('MWG Product',self.pushes[0][1]);self.assertIn('XACNHAN',self.pushes[0][1])
        self.assertIsNone(self.q.claim(True,w['id']))

    def test_import_error_after_receipt_is_pushed(self):
        with patch.dict(os.environ,{'CO_ACK_RECEIPT':'1'}):self.handle(self.event())
        w=self.q.claim(True);self.q.update(w['id'],w['lease'],'failed','MWG lỗi nhập file')
        self.notify();self.assertIn('MWG lỗi nhập file',self.pushes[0][1])
        self.assertEqual(len(self.replies),1)

    def test_late_result_push_has_its_own_deduplication_key(self):
        job=self.q.draft('late','owner','chat',dict(source='1',destination='2',product='0131491005415',quantity=1,note=''))
        with self.q.db() as db:
            db.execute("UPDATE jobs SET state='submitting',lease='lease' WHERE id=?",(job['id'],))
        unknown=json.dumps([dict(co='',error='Waiting',state='unknown')])
        final=json.dumps([dict(co='1CO123',error='',state='succeeded')])
        self.assertTrue(self.q.update(job['id'],'lease','unknown',unknown))
        self.notify();self.assertEqual(len(self.pushes),1)
        self.assertTrue(self.q.update(job['id'],'lease','succeeded',final))
        self.notify();self.notify()
        self.assertEqual(len(self.pushes),2)
        self.assertNotEqual(self.pushes[0][2],self.pushes[1][2])
        self.assertIn('1CO123',self.pushes[1][1])

    def test_only_actual_preview_replied_and_no_creation(self):
        event=self.event();self.assertTrue(self.handle(event));self.assertEqual(self.replies,[])
        self.handle(event) # webhook redelivery must not consume reply/create duplicate
        work=self.q.claim(True);self.assertEqual(work['mode'],'preview')
        self.assertNotIn('token',json.dumps(work));self.assertIsNone(self.q.claim(True))
        self.q.update(work['id'],work['lease'],'preview_ready','MWG Product')
        self.notify();self.notify()
        self.assertEqual(len(self.replies),1);self.assertIn('MWG Product',self.replies[0][1])
        self.assertIn('XACNHAN',self.replies[0][1]);self.assertNotIn('XEM',self.replies[0][1]);self.assertEqual(self.pushes,[])
        self.assertIsNone(self.q.claim(True))
    def test_import_failure_uses_original_reply(self):
        self.handle(self.event());work=self.q.claim(True)
        self.q.update(work['id'],work['lease'],'failed','Upload failed')
        self.notify();self.assertIn('Upload failed',self.replies[0][1]);self.assertEqual(self.pushes,[])
    def test_slow_preview_not_silent_and_later_push(self):
        self.handle(self.event());work=self.q.claim(True)
        with self.q.db() as db:db.execute('UPDATE preview_replies SET received=received-46')
        self.notify();self.assertEqual(len(self.replies),1);self.assertIn('Chưa tạo CO',self.replies[0][1])
        self.q.update(work['id'],work['lease'],'preview_ready','MWG Product')
        self.notify();self.assertEqual(len(self.pushes),1)
    def test_old_push_backlog_does_not_block_preview_reply(self):
        for i in range(3):
            j=self.q.draft('old'+str(i),'owner','chat',dict(source='1',destination='2',product='003',quantity=1,note=''))
            self.q.confirm(j['id'],'owner','chat');w=self.q.claim()
            self.q.update(j['id'],w['lease'],'failed','old error')
        self.handle(self.event());w=self.q.claim(True)
        self.q.update(w['id'],w['lease'],'preview_ready','Current product')
        self.notify()
        self.assertEqual(len(self.replies),1);self.assertIn('Current product',self.replies[0][1])
        self.assertEqual(len(self.pushes),1)

    def test_confirmation_failure_is_replied_without_ack_message(self):
        self.handle(self.event());w=self.q.claim(True)
        self.q.update(w['id'],w['lease'],'preview_ready','MWG Product');self.notify()
        event=self.event();event.message.text='XACNHAN '+w['id'];event.reply_token='confirm-token'
        self.handle(event);self.assertEqual(len(self.replies),1)
        create=self.q.claim(True,w['id']);self.q.update(create['id'],create['lease'],'failed','Không đủ tồn kho')
        self.notify();self.assertEqual(self.replies[-1][0],'confirm-token')
        self.assertIn('Không đủ tồn kho',self.replies[-1][1]);self.assertEqual(self.pushes,[])

    def test_failed_reply_falls_back_to_push(self):
        self.handle(self.event());work=self.q.claim(True)
        self.q.update(work['id'],work['lease'],'preview_ready','MWG Product')
        # Stored reply is too old to use; send preview by push.
        with self.q.db() as db:db.execute('UPDATE preview_replies SET received=received-60')
        self.notify();self.assertEqual(self.replies,[]);self.assertEqual(len(self.pushes),1)

    def test_duplicate_batch_replies_with_warning_and_confirms_remaining_rows(self):
        from co_results import line_text_messages,items
        event=self.event();row=event.message.text
        event.message.text=row+'\n'+row+'\n'+row.replace('123\nKho nhận','124\nKho nhận')
        self.handle(event)
        work=self.q.claim(True,batch_protocol=True)
        self.assertEqual([r['source'] for r in items(work['payload'])],['123','124'])
        self.q.update(work['id'],work['lease'],'preview_ready','["Phone A","Phone B"]')
        self.notify()
        text=self.replies[0][1]
        self.assertIn('Đã bỏ qua 1 dòng trùng',text)
        self.assertIn('Chỉ xác nhận 2 dòng',text)
        self.assertEqual(len(line_text_messages(text)[-1]['quickReply']['items']),2)
        self.assertIsNone(self.q.claim(True,work['id'],True))
        event.message.text='XACNHAN '+work['id'];event.reply_token='confirm-token'
        self.handle(event)
        create=self.q.claim(True,work['id'],True)
        self.assertEqual(create['mode'],'create')
        self.assertEqual(len(items(create['payload'])),2)

    def test_all_existing_duplicates_reply_without_adding_job(self):
        first=self.event();self.handle(first)
        duplicate=self.event();duplicate.webhook_event_id='duplicate';duplicate.reply_token='duplicate-token'
        self.handle(duplicate)
        self.assertEqual(self.replies[-1][0],'duplicate-token')
        self.assertIn('Không còn dòng mới',self.replies[-1][1])
        with self.q.db() as db:self.assertEqual(db.execute('SELECT COUNT(*) AS n FROM jobs').fetchone()['n'],1)
        self.assertEqual(self.q.take_preview_reply(self.q.claim(True)['id'])['token'],'test-token')

if __name__=='__main__':unittest.main()
