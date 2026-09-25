import os
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch
from co_flow import Queue,install,BotUnavailable,admin_command

class AdminTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=str(Path(self.tmp.name)/'q.db');self.q=Queue(self.path)
        self.p=dict(source='1',destination='2',product='003',quantity=1,note='')
        self.replies=[]
        env=patch.dict(os.environ,{'CO_ENABLED':'1','CO_DB_PATH':self.path,'CO_DATABASE_URL':'','CO_WORKER_TOKEN':'x'*32,'CO_ALLOWED_USER_IDS':'operator'})
        env.start();self.addCleanup(env.stop)
        app=types.SimpleNamespace(post=lambda route:lambda f:f,get=lambda route:lambda f:f,logger=types.SimpleNamespace(warning=lambda *a:None))
        with patch.dict('sys.modules',{'flask':types.SimpleNamespace(request=None,jsonify=None,abort=None)}):
            self.handle,_=install(app,lambda token,text:self.replies.append(text),lambda *a:True,['admin'])
    def event(self,text,owner='admin'):
        return types.SimpleNamespace(reply_token='reply',webhook_event_id='event',source=types.SimpleNamespace(user_id=owner),message=types.SimpleNamespace(id='msg',text=text))
    def test_offline_rejects_form_without_queueing(self):
        self.handle(self.event('Kho xuất: 1\nKho nhận: 2\nMSP: 003','operator'))
        self.assertIn('offline',self.replies[-1])
        with self.q.db() as db:self.assertEqual(db.execute('SELECT COUNT(*) AS n FROM jobs').fetchone()['n'],0)
    def test_heartbeat_expires_after_thirty_seconds(self):
        self.q.heartbeat()
        self.assertIn('Mac: online',self.q.admin('BOT STATUS'))
        with self.q.db() as db:db.execute('UPDATE co_control SET heartbeat=heartbeat-31')
        with self.assertRaises(BotUnavailable):self.q.draft('e','o','c',self.p,require_online=True)
    def test_off_persists_despite_heartbeat_and_stops_claim(self):
        self.q.heartbeat();j=self.q.draft('e','o','c',self.p)
        self.q.confirm(j['id'],'o','c')
        self.q.admin('BOT OFF');self.q.heartbeat()
        self.assertIsNone(self.q.claim(require_online=True))
        self.assertIn('ADM tạm dừng: có',self.q.admin('BOT STATUS'))
        self.q.admin('BOT ON');self.assertIsNotNone(self.q.claim(require_online=True))
    def test_offline_on_cannot_enable(self):
        self.q.admin('BOT OFF')
        self.assertIn('Chưa bật được',self.q.admin('BOT ON'))
    def test_shutdown_marks_offline(self):
        self.q.heartbeat();self.q.heartbeat(False)
        self.assertIn('Mac: offline',self.q.admin('BOT STATUS'))
    def test_nonadmin_cannot_use_any_admin_command(self):
        for text in ['!listadm','listadm','BOT OFF','!bot on','BOT STATUS','HUY CHO ALL']:
            self.handle(self.event(text,'operator'))
            self.assertIn('chỉ dành cho tài khoản ADM',self.replies[-1])
    def test_admin_help_without_co_allowlist_membership(self):
        self.handle(self.event('!listadm'))
        self.assertIn('!bot off',self.replies[-1]);self.assertIn('mọi chat',self.replies[-1])
    def test_global_cancel_preserves_inflight_unknown_and_success(self):
        states=['draft','queued','verified_queued','preview_queued','preview_running','running','submitting','unknown','succeeded']
        for state in states:
            j=self.q.draft(state,state,state,self.p)
            with self.q.db() as db:db.execute('UPDATE jobs SET state=? WHERE id=?',(state,j['id']))
        self.assertIn('4 yêu cầu',self.q.admin('HUY CHO ALL'))
        with self.q.db() as db:
            remaining=[row['state'] for row in db.execute("SELECT state FROM jobs WHERE state!='cancelled'")]
        self.assertCountEqual(remaining,states[4:])
    def test_expired_old_queue_is_not_replayed_on_reconnect(self):
        j=self.q.draft('e','o','c',self.p);self.q.confirm(j['id'],'o','c')
        with self.q.db() as db:db.execute('UPDATE jobs SET created=created-901')
        self.q.heartbeat();self.assertIsNone(self.q.claim(require_online=True))
    def test_normal_faq_commands_not_intercepted(self):
        for text in ['!say bot | hello','!list','!reload','!listadm unexpected']:
            self.assertIsNone(admin_command(text))
            self.assertFalse(self.handle(self.event(text)))

if __name__=='__main__':unittest.main()
