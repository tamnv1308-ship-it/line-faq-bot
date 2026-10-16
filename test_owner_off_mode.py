import json
import os
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch
from flask import Flask
from co_flow import Queue, install, BotUnavailable, PRIVATE_CO_OWNER, MEMBER_CO_GROUP


class OwnerOffModeTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.path=str(Path(tmp.name)/'q.db')
        env=patch.dict(os.environ,{'CO_ENABLED':'1','CO_DB_PATH':self.path,'CO_DATABASE_URL':'',
            'CO_WORKER_TOKEN':'x'*40,'CO_ALLOWED_USER_IDS':'admin,member','CO_GATHER_SECONDS':'0'})
        env.start();self.addCleanup(env.stop)
        self.p=dict(source='1',destination='2',product='0131491005415',quantity=1,note='',status='Mới')
        self.replies=[];self.pushes=[]
        self.app=Flask(__name__)
        self.handle,self.notify=install(self.app,lambda token,text:self.replies.append(text) or True,
            lambda *args:self.pushes.append(args) or True,['admin'],requester_name=lambda event:'Tâm')
        self.q=Queue(self.path);self.q.heartbeat();self.q.admin('BOT OFF')
        self.headers={'Authorization':'Bearer '+'x'*40}

    def event(self,owner,chat=None):
        source=types.SimpleNamespace(user_id=owner,group_id=chat,room_id=None)
        return types.SimpleNamespace(reply_token='token-'+owner,webhook_event_id='event-'+owner,
            source=source,message=types.SimpleNamespace(id='message',text='Kho xuất: 1\nKho nhận: 2\nMSP: 0131491005415'))

    def preview(self,owner='member',event='preview'):
        j=self.q.draft(event,owner,'chat',self.p,check_product=True)
        work=self.q.claim(preview_protocol=True,require_online=True)
        self.assertEqual(work['id'],j['id'])
        self.assertTrue(self.q.update(j['id'],work['lease'],'preview_ready','iPhone'))
        return j,work

    def test_only_owner_can_send_in_private_or_allowed_group(self):
        for chat in (None,MEMBER_CO_GROUP):
            with self.q.db() as db:db.execute('DELETE FROM jobs')
            event=self.event(PRIVATE_CO_OWNER,chat);event.webhook_event_id+=str(chat)
            self.handle(event)
            with self.q.db() as db:
                rows=db.execute('SELECT owner,state FROM jobs').fetchall()
            self.assertEqual([(r['owner'],r['state']) for r in rows],[(PRIVATE_CO_OWNER,'preview_queued')])
        for owner in ('member','admin'):
            self.handle(self.event(owner,MEMBER_CO_GROUP))
            self.assertIn('Gói cước đã hết hạn.',self.replies[-1])
        with self.q.db() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) AS n FROM jobs WHERE owner!=?',(PRIVATE_CO_OWNER,)).fetchone()['n'],0)

    def test_owner_preview_confirmation_and_claim_work_while_off(self):
        j,work=self.preview(PRIVATE_CO_OWNER)
        self.q.confirm(j['id'],PRIVATE_CO_OWNER,'chat',require_online=True)
        claimed=self.q.claim(preview_protocol=True,prepared_id=j['id'],require_online=True)
        self.assertEqual(claimed['mode'],'create')
        self.assertTrue(self.q.update(j['id'],claimed['lease'],'submitting'))
        self.assertTrue(self.q.update(j['id'],claimed['lease'],'succeeded','1CO123'))

    def test_owner_still_requires_mwg_and_online_mac(self):
        for state in ('login','blocked','stopping','reconnecting'):
            self.q.heartbeat(True,{'state':state,'progress_age_seconds':0})
            with self.assertRaises(BotUnavailable):
                self.q.draft(state,PRIVATE_CO_OWNER,'chat',self.p,require_online=True)
            self.assertIsNone(self.q.claim(require_online=True))
        self.q.heartbeat(False)
        with self.assertRaises(BotUnavailable):
            self.q.draft('offline',PRIVATE_CO_OWNER,'chat',self.p,require_online=True)

    def test_worker_skips_other_queued_jobs_including_admin(self):
        for owner in ('member','admin',PRIVATE_CO_OWNER):
            self.q.draft(owner,owner,'chat',self.p,check_product=True)
        response=self.app.test_client().post('/co/worker/claim',json={'preview_protocol':1},headers=self.headers)
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json['id'],self.q.draft(PRIVATE_CO_OWNER,PRIVATE_CO_OWNER,'chat',self.p)['id'])
        with self.q.db() as db:
            self.assertTrue(all(r['state']=='preview_queued' for r in db.execute('SELECT state FROM jobs WHERE owner!=?',(PRIVATE_CO_OWNER,))))

    def test_prepared_other_job_is_suspended_and_needs_fresh_confirmation(self):
        self.q.admin('BOT ON');j,old=self.preview()
        self.q.mark_notified(j['id'],'draft')
        self.q.confirm(j['id'],'member','chat',require_online=True)
        self.q.admin('BOT OFF')
        self.assertEqual(self.q.claim(True,j['id'],require_online=True),{'release_preview':True})
        with self.q.db() as db:
            parked=db.execute('SELECT * FROM jobs WHERE id=?',(j['id'],)).fetchone()
        self.assertEqual(parked['state'],'preview_queued');self.assertIsNone(parked['lease'])
        self.assertEqual(json.loads(parked['payload'])['preview_generation'],1)
        self.assertFalse(self.q.update(j['id'],old['lease'],'submitting'))
        own=self.q.draft('owner',PRIVATE_CO_OWNER,'chat',dict(self.p,source='3'),check_product=True)
        claimed=self.q.claim(True,require_online=True)
        self.assertEqual(claimed['id'],own['id'])
        self.q.update(own['id'],claimed['lease'],'failed','Test import failure')
        self.assertIsNone(self.q.claim(True,require_online=True))
        self.q.admin('BOT ON')
        resumed=self.q.claim(True,require_online=True)
        self.assertEqual(resumed['id'],j['id']);self.assertEqual(resumed['mode'],'preview')
        self.q.update(j['id'],resumed['lease'],'preview_ready','iPhone')
        self.assertIsNone(self.q.claim(True,j['id'],require_online=True))

    def test_off_does_not_interrupt_a_creation_already_started(self):
        self.q.admin('BOT ON');j,work=self.preview()
        self.q.confirm(j['id'],'member','chat',require_online=True)
        running=self.q.claim(True,j['id'],require_online=True)
        self.q.update(j['id'],running['lease'],'submitting')
        self.q.admin('BOT OFF')
        self.q.draft('owner',PRIVATE_CO_OWNER,'chat',self.p,check_product=True)
        self.assertIsNone(self.q.claim(True,require_online=True))
        self.assertTrue(self.q.update(j['id'],running['lease'],'succeeded','1CO123'))
        self.assertEqual(self.q.claim(True,require_online=True)['mode'],'preview')

    def test_confirm_all_only_queues_owner_but_cancel_permissions_remain(self):
        other=self.q.draft('other','member','chat',self.p)
        own=self.q.draft('own',PRIVATE_CO_OWNER,'chat',self.p)
        with self.assertRaises(BotUnavailable):self.q.confirm(other['id'],'member','chat',require_online=True)
        self.assertIn('!bot on',self.q.confirm(other['id'],PRIVATE_CO_OWNER,'chat',require_online=True))
        self.q.confirm_all(PRIVATE_CO_OWNER,'chat',require_online=True)
        with self.q.db() as db:
            states={r['id']:r['state'] for r in db.execute('SELECT id,state FROM jobs')}
        self.assertEqual(states[own['id']],'queued');self.assertEqual(states[other['id']],'draft')
        self.assertIn('Đã hủy',self.q.confirm(other['id'],PRIVATE_CO_OWNER,'chat',cancel=True,require_online=True))

    def test_new_confirmation_is_not_suppressed_by_old_line_retry_key(self):
        self.q.admin('BOT ON');j,work=self.preview()
        self.notify();first_key=self.pushes[-1][2]
        self.q.admin('BOT OFF')
        self.q.claim(True,j['id'],require_online=True)
        self.q.admin('BOT ON');new=self.q.claim(True,require_online=True)
        self.q.update(j['id'],new['lease'],'preview_ready','iPhone')
        self.q.mark_notified(j['id'],'draft',expected_updated=j['updated'])
        self.notify()
        self.assertEqual(len(self.pushes),2)
        self.assertNotEqual(first_key,self.pushes[-1][2])

    def test_status_distinguishes_owner_mode_and_unready_worker(self):
        client=self.app.test_client()
        status=client.get('/co/worker/status',headers=self.headers).json
        self.assertEqual(status['intake_mode'],'owner_only')
        self.assertTrue(status['owner_accepting']);self.assertFalse(status['accepting'])
        self.assertIn('CHỈ TÂM 258330',self.q.admin('BOT STATUS'))
        self.q.heartbeat(False)
        self.assertFalse(client.get('/co/worker/status',headers=self.headers).json['owner_accepting'])


if __name__=='__main__':unittest.main()
