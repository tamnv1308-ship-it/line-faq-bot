import json
import os
import tempfile
import time
import types
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock, patch

from co_flow import Queue, RequesterLocked, PRIVATE_CO_OWNER, CANCEL_QUIPS, install
from co_results import line_text_messages


class ConfirmationLockTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.q=Queue(self.tmp.name+'/q.db')
        self.now=Mock(return_value=1000)
        clock=patch('co_flow.time',types.SimpleNamespace(time=self.now,monotonic=time.monotonic))
        clock.start();self.addCleanup(clock.stop)
        self.q.heartbeat()
        self.number=0

    def payload(self):
        return dict(source='9469',destination='7298',product='0131491005416',quantity=1,
                    status='Mới',note='',requester_name='Người thử nghiệm')

    def ready(self, owner='user', delivered=True, batch=False):
        self.number+=1;p=self.payload()
        if batch:p=dict(items=[p,dict(p,source='9470')],status='Mới',requester_name=p['requester_name'])
        j=self.q.draft('e'+str(self.number),owner,'group',p,check_product=True)
        work=self.q.claim(True,batch_protocol=True)
        self.q.update(j['id'],work['lease'],'preview_ready','["Phone 1","Phone 2"]' if batch else 'Phone')
        if delivered:self.q.mark_notified(j['id'],'draft')
        return j['id']

    def expire(self, jid, seconds=60, online=True):
        self.now.return_value+=seconds
        if online:self.q.heartbeat()
        self.q.expire_confirmations()
        with self.q.db() as db:return dict(db.execute('SELECT * FROM jobs WHERE id=?',(jid,)).fetchone())

    def lock(self, owner='user'):
        with self.q.db() as db:
            row=db.execute('SELECT * FROM co_confirmation_locks WHERE owner=?',(owner,)).fetchone()
        return dict(row) if row else None

    def test_three_levels_persist_and_block_only_new_intake(self):
        first=self.ready();self.expire(first)
        self.assertEqual((self.lock()['strikes'],self.lock()['locked_until']),(1,1120))
        with self.assertRaises(RequesterLocked):self.q.draft('blocked','user','another',self.payload())
        self.now.return_value=1120;self.q.heartbeat()
        second=self.ready();self.expire(second)
        self.assertEqual((self.lock()['strikes'],self.lock()['locked_until']),(2,1360))
        self.now.return_value=1360;self.q.heartbeat()
        third=self.ready();self.expire(third)
        self.assertEqual(self.lock()['strikes'],3)
        self.q=Queue(self.q.path)
        self.now.return_value=100000
        with self.assertRaisesRegex(RequesterLocked,'Tâm'):self.q.draft('forever','user','another',self.payload())

    def test_confirm_at_59_seconds_succeeds_at_60_expires(self):
        first=self.ready();self.now.return_value=1059;self.q.heartbeat()
        self.q.confirm(first,'user','group')
        self.now.return_value=1060
        self.assertEqual(self.q.claim(True,first,True)['mode'],'create')
        self.assertIsNone(self.lock())

    def test_late_confirm_is_not_created_and_counts_once(self):
        jid=self.ready();self.now.return_value=1060;self.q.heartbeat()
        self.assertIn('hết hạn',self.q.confirm(jid,'user','group'))
        self.q.confirm(jid,'user','group');self.q.confirm_all('user','group')
        self.q.notifications();self.q.expire_confirmations()
        self.assertEqual(self.lock()['strikes'],1)
        self.assertIsNone(self.q.claim(True))

    def test_batch_counts_once_and_releases_next_request(self):
        jid=self.ready(batch=True)
        nxt=self.q.draft('next','another','group',self.payload(),check_product=True)
        self.now.return_value=1059;self.q.heartbeat()
        self.assertIsNone(self.q.claim(True,jid,True))
        self.now.return_value=1000
        self.expire(jid)
        self.assertEqual(self.lock()['strikes'],1)
        self.assertEqual(self.q.claim(True,jid,True),{'release_preview':True})
        self.assertEqual(self.q.claim(True,batch_protocol=True)['id'],nxt['id'])

    def test_manual_cancel_never_penalizes(self):
        jid=self.ready();self.q.confirm(jid,'user','group',cancel=True)
        self.expire(jid)
        self.assertIsNone(self.lock())

    def test_undelivered_preview_and_bot_offline_never_penalize(self):
        jid=self.ready(delivered=False);self.expire(jid,301)
        self.assertIsNone(self.lock())
        jid=self.ready();self.expire(jid,online=False)
        self.assertIsNone(self.lock())
        self.q.heartbeat();jid=self.ready();self.q.admin('BOT OFF');self.expire(jid)
        self.assertIsNone(self.lock())

    def test_owner_and_pre_policy_confirmations_are_exempt(self):
        jid=self.ready(PRIVATE_CO_OWNER);self.expire(jid)
        self.assertIsNone(self.lock(PRIVATE_CO_OWNER))
        jid=self.ready()
        with self.q.db() as db:
            p=json.loads(db.execute('SELECT payload FROM jobs WHERE id=?',(jid,)).fetchone()['payload'])
            p.pop('confirmation_lock_version')
            db.execute('UPDATE jobs SET payload=? WHERE id=?',(json.dumps(p),jid))
        self.expire(jid)
        self.assertIsNone(self.lock())

    def test_concurrent_expiry_does_not_double_count(self):
        jid=self.ready();self.now.return_value=1060;self.q.heartbeat()
        with ThreadPoolExecutor(max_workers=4) as pool:list(pool.map(lambda _:self.q.expire_confirmations(),range(4)))
        self.assertEqual(self.lock()['strikes'],1)

    def test_owner_list_selection_and_event_redelivery_reset_counter(self):
        first=self.ready('first');self.expire(first)
        second=self.ready('second');self.expire(second)
        # Refresh the first lock so both people remain visible in the menu.
        with self.q.db() as db:db.execute('UPDATE co_confirmation_locks SET locked_until=9999')
        self.assertIn('1.',self.q.unlock_requester(PRIVATE_CO_OWNER,'private','list'))
        message=self.q.unlock_requester(PRIVATE_CO_OWNER,'private','open','2')
        self.assertIn('reset về 0',message)
        self.assertIsNotNone(self.lock('first'));self.assertIsNone(self.lock('second'))
        self.assertEqual(self.q.unlock_requester(PRIVATE_CO_OWNER,'private','open','2'),message)
        self.assertIn('Chỉ Tâm',self.q.unlock_requester('another-admin','group','bad'))

    def test_expired_or_changed_unlock_menu_is_rejected(self):
        jid=self.ready();self.expire(jid)
        self.q.unlock_requester(PRIVATE_CO_OWNER,'private','list')
        with self.q.db() as db:db.execute("UPDATE co_confirmation_locks SET last_job='newer-incident'")
        self.assertIn('thay đổi',self.q.unlock_requester(PRIVATE_CO_OWNER,'private','changed','1'))
        self.q.unlock_requester(PRIVATE_CO_OWNER,'private','list2')
        self.now.return_value+=300
        self.assertIn('hết hiệu lực',self.q.unlock_requester(PRIVATE_CO_OWNER,'private','old','1'))
        self.assertIsNotNone(self.lock())

    def test_compact_form_keeps_deadline_buttons_without_lock_warning(self):
        jid=self.ready()
        with self.q.db() as db:job=dict(db.execute('SELECT * FROM jobs WHERE id=?',(jid,)).fetchone())
        text=self.q.confirmation(job)
        self.assertNotIn('khóa',text)
        self.assertFalse(any(quip in text for quip in CANCEL_QUIPS))
        self.assertIn('Hiệu lực: 1 phút',text)
        self.assertEqual([x['action']['text'] for x in line_text_messages(text)[-1]['quickReply']['items']],
                         ['XACNHAN '+jid,'HUY '+jid])

    def test_huy_reply_only_jokes_after_safe_cancellation(self):
        messages=[]
        env={'CO_ENABLED':'1','CO_DB_PATH':self.q.path,'CO_DATABASE_URL':'','CO_WORKER_TOKEN':'x'*32,'CO_ALLOWED_USER_IDS':'user'}
        app=types.SimpleNamespace(post=lambda _:lambda f:f,get=lambda _:lambda f:f,
                                  logger=types.SimpleNamespace(warning=lambda *a:None))
        with patch.dict(os.environ,env),patch.dict('sys.modules',{'flask':types.SimpleNamespace(request=None,jsonify=None,abort=None)}):
            handle,_=install(app,lambda token,text:messages.append(text) or True,lambda *a:True)
            for state in ('draft','preview_queued','verified_queued','running','submitting','unknown','succeeded','expired','cancelled'):
                with self.subTest(state=state):
                    jid=self.ready()
                    with self.q.db() as db:db.execute('UPDATE jobs SET state=? WHERE id=?',(state,jid))
                    event=types.SimpleNamespace(reply_token='token',webhook_event_id='cancel-'+jid,source=types.SimpleNamespace(user_id='user',group_id='group'),message=types.SimpleNamespace(id=jid,text='HUY '+jid))
                    handle(event)
                    safe=state in {'draft','preview_queued','verified_queued','expired'}
                    self.assertEqual(sum(quip in messages[-1] for quip in CANCEL_QUIPS),int(safe))
                    with self.q.db() as db:
                        result=db.execute('SELECT state FROM jobs WHERE id=?',(jid,)).fetchone()['state']
                        self.assertEqual(result,'cancelled' if state in {'draft','preview_queued','verified_queued'} else state)
                        # Isolate fixtures so an intentional in-flight row cannot block the next preview.
                        db.execute('DELETE FROM jobs WHERE id=?',(jid,))

    def test_late_huy_preserves_lock_and_sua_has_no_joke(self):
        jid=self.ready();self.expire(jid)
        response=self.q.confirm(jid,'user','group',cancel=True,playful_cancel=True)
        self.assertIn('tự hủy',response)
        self.assertEqual(sum(quip in response for quip in CANCEL_QUIPS),1)
        self.assertEqual(self.lock()['strikes'],1)
        self.now.return_value=1120;self.q.heartbeat()
        jid=self.ready()
        response=self.q.confirm(jid,'user','group',cancel=True)
        self.assertFalse(any(quip in response for quip in CANCEL_QUIPS))

    def test_webhook_owner_gate_and_expiry_notice_delivery(self):
        messages=[];pushes=[]
        env={'CO_ENABLED':'1','CO_DB_PATH':self.q.path,'CO_DATABASE_URL':'','CO_WORKER_TOKEN':'x'*32}
        app=types.SimpleNamespace(post=lambda _:lambda f:f,get=lambda _:lambda f:f,
                                  logger=types.SimpleNamespace(warning=lambda *a:None))
        with patch.dict(os.environ,env),patch.dict('sys.modules',{'flask':types.SimpleNamespace(request=None,jsonify=None,abort=None)}):
            handle,notify=install(app,lambda token,text:messages.append(text) or True,
                                  lambda chat,text,key:pushes.append(text) or True,['another-admin'])
            event=types.SimpleNamespace(reply_token='token',webhook_event_id='u1',source=types.SimpleNamespace(user_id='another-admin',group_id='group'),message=types.SimpleNamespace(id='1',text='!mokhoa'))
            handle(event);self.assertIn('Chỉ Tâm',messages[-1])
            jid=self.ready();self.expire(jid);notify();notify()
            self.assertEqual(len(pushes),1)
            self.assertIn('Khóa nhận yêu cầu mới 1 phút',pushes[0])
            event.source.user_id=PRIVATE_CO_OWNER;event.webhook_event_id='u2'
            handle(event);self.assertIn('1.',messages[-1])
            event.message.text='!mokhoa 1';event.webhook_event_id='u3'
            handle(event);self.assertIn('Đã mở khóa',messages[-1])
            self.assertIsNone(self.lock())


if __name__=='__main__':unittest.main()
