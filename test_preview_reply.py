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
        self.env=patch.dict(os.environ,{'CO_ENABLED':'1','CO_DB_PATH':self.path,'CO_DATABASE_URL':'','CO_WORKER_TOKEN':'x'*32,'CO_ALLOWED_USER_IDS':'owner'})
        self.env.start();self.addCleanup(self.env.stop)
        app=types.SimpleNamespace(post=lambda route:lambda f:f,get=lambda route:lambda f:f,logger=types.SimpleNamespace(warning=lambda *args:None))
        flask=types.SimpleNamespace(request=None,jsonify=None,abort=None)
        with patch.dict('sys.modules',{'flask':flask}):
            self.handle,self.notify=install(app,self.reply,self.push)
        self.q=Queue(self.path)
    def reply(self,token,text):
        self.replies.append((token,text));return True
    def push(self,*args):
        self.pushes.append(args);return True
    def event(self):
        return types.SimpleNamespace(reply_token='test-token',webhook_event_id='evt',source=types.SimpleNamespace(user_id='owner'),message=types.SimpleNamespace(id='msg',text='Kho xuất: 123\nKho nhận: 456\nMã sản phẩm: 00123\nSố lượng: 1\nNote:'))
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
    def test_failed_reply_falls_back_to_push(self):
        self.handle(self.event());work=self.q.claim(True)
        self.q.update(work['id'],work['lease'],'preview_ready','MWG Product')
        # Stored reply is too old to use; send preview by push.
        with self.q.db() as db:db.execute('UPDATE preview_replies SET received=received-60')
        self.notify();self.assertEqual(self.replies,[]);self.assertEqual(len(self.pushes),1)

if __name__=='__main__':unittest.main()
