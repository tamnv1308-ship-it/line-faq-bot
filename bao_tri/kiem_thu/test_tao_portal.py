import json
import os
import tempfile
import time
import types
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch, MagicMock

from flask import Flask
import tao_portal as portal
from co_flow import Queue, PRIVATE_CO_OWNER as OWNER, MEMBER_CO_GROUP as GROUP, DISABLED_CO_GROUP
from co_summary import period

MEMBER = 'U'+'1'*32
OTHER = 'U'+'2'*32
ADMIN = 'U'+'3'*32
BASE = 'https://test.example'


class PortalTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.path = str(Path(tmp.name)/'queue.db')
        env = patch.dict(os.environ, {'CO_ENABLED':'1','CO_DB_PATH':self.path,'CO_DATABASE_URL':'',
            'CO_WORKER_TOKEN':'test-worker-token','CO_ALLOWED_USER_IDS':ADMIN,
            'CHANNEL_SECRET':'test-secret-never-production'*2,'CHANNEL_ACCESS_TOKEN':'test-token',
            'TAO_LIFF_ID':'123456-test','TAO_LINE_LOGIN_CHANNEL_ID':'123456',
            'TAO_PUBLIC_LAUNCH':'1',
            'REPORT_PUBLIC_BASE_URL':BASE,'CO_GATHER_SECONDS':'0'})
        env.start();self.addCleanup(env.stop)
        for name, value in [('load_conditions',{}),('stores',{}),('verify_chat_member',None)]:
            mock=patch.object(portal,name,return_value=value);mock.start();self.addCleanup(mock.stop)
        self.app=Flask(__name__);self.app.testing=True;self.replies=[]
        self.handle=portal.install(self.app,lambda token,text:self.replies.append(text),[ADMIN])
        self.client=self.app.test_client();self.q=Queue(self.path);self.q.heartbeat()
        self.payload=dict(source='3945',destination='447',product='0131491005415',product_name='Điện thoại iPhone 18 Pro Max 512GB Glacier',quantity=1,status='Mới',note='QL cho hàng: Tư · Mọi thắc mắc liên hệ Tâm 258330 Apple.',requester_name='Thành viên')
        self.csrf=''

    def call(self,path,method='GET',data=None,headers=None):
        return self.client.open('/tao/api/'+path,method=method,json=data,base_url=BASE,
            headers={'Origin':BASE,'X-Tao-CSRF':self.csrf,**(headers or {})})

    def login(self,user=MEMBER):
        with patch.object(portal,'verify_id_token',return_value={'sub':user,'name':'Tên LINE đã xác thực','exp':time.time()+3600}):
            response=self.call('auth','POST',{'id_token':'x'*150,'user_id':OWNER})
        self.assertEqual(response.status_code,200)
        me=self.call('me');self.assertEqual(me.status_code,200)
        self.csrf=me.json['csrf'];return me.json

    def job(self,owner=MEMBER,chat=GROUP,state='draft',notified=1,age=0,payload=None):
        job=self.q.draft('test-'+str(time.time_ns()),owner,chat,payload or self.payload)
        with self.q.db() as db:
            db.execute('UPDATE jobs SET state=?,notified=?,created=?,result=? WHERE id=?',
                (state,notified,time.time()-age,'MWG_PREVIEW' if state=='draft' else '',job['id']))
        return job['id']

    def state(self,jid):
        with self.q.db() as db:return db.execute('SELECT state FROM jobs WHERE id=?',(jid,)).fetchone()['state']

    def test_reset_owner_only_preserves_unknown_and_waiting(self):
        self.login(MEMBER)
        self.assertEqual(self.call('admin/reset-worker','POST',{}).status_code,403)
        self.login(OWNER)
        jid=self.job(state='unknown')
        self.assertEqual(self.call('admin/reset-worker','POST',{}).status_code,200)
        self.assertEqual(self.state(jid),'unknown')
        result=self.q.claim(reset_protocol=True)
        self.assertTrue(result['reset_workspace'])
        self.assertEqual(self.state(jid),'unknown')
        with self.q.db() as db:
            self.assertIsNotNone(db.execute('SELECT consumed FROM co_worker_resets').fetchone()['consumed'])

    def test_reset_rejected_during_confirmation_and_creation(self):
        self.login(OWNER)
        jid=self.job(state='draft')
        for state in ('draft','running','submitting','preview_running','verified_queued'):
            with self.q.db() as db:db.execute('UPDATE jobs SET state=? WHERE id=?',(state,jid))
            self.assertEqual(self.call('admin/reset-worker','POST',{}).status_code,409)
            self.assertEqual(self.state(jid),state)

    def test_public_assets_and_login_required(self):
        for path in ('/tao/','/tao/privacy','/tao/assets/app.js','/tao/assets/app.css'):
            with self.client.get(path) as response:self.assertEqual(response.status_code,200)
        self.assertEqual(self.call('config').status_code,200)
        for path in ('me','jobs','summary','conditions?code=0131491005415','lookup?code=1CO123','admin/locks','admin/queue'):
            self.assertEqual(self.call(path).status_code,401,path)
        self.assertEqual(self.client.get('/tao/assets/tao_portal.py').status_code,404)

    def test_verified_identity_ignores_client_uid_and_cookie_secure(self):
        me=self.login();self.assertFalse(me['owner']);self.assertFalse(me['admin'])
        self.assertEqual(me['name'],'Tên LINE đã xác thực')
        cookie=self.client.get_cookie(portal.COOKIE,domain='test.example')
        self.assertTrue(cookie.secure);self.assertTrue(cookie.http_only);self.assertEqual(cookie.same_site,'Lax')
        self.client.set_cookie(portal.COOKIE,cookie.value+'bad',domain='test.example')
        self.assertEqual(self.call('me').status_code,401)

    def test_csrf_origin_and_auth_payload(self):
        self.login(OWNER)
        for headers in ({'X-Tao-CSRF':''},{'Origin':'https://evil.example'}):
            self.assertEqual(self.call('admin/intake','POST',{'enabled':False},headers).status_code,403)
        self.assertEqual(self.call('auth','POST',{'id_token':'x'*150},{'Origin':'https://evil.example'}).status_code,403)
        self.assertEqual(self.call('auth','POST',{'id_token':'x'*17000}).status_code,413)
        self.assertEqual(self.call('admin/intake','POST',{'enabled':'true'}).status_code,400)

    def test_own_jobs_only_even_for_admin(self):
        own=self.job();other=self.job(OTHER)
        self.login();self.assertEqual([j['id'] for j in self.call('jobs').json['jobs']],[own])
        self.assertEqual(self.call('jobs/'+other).status_code,404)
        self.assertEqual(self.call('lookup?code='+other).status_code,404)
        self.login(ADMIN)
        self.assertEqual(self.call('jobs/'+own+'/confirm','POST',{}).status_code,404)
        self.assertEqual(self.call('summary?period=30').status_code,403)
        self.assertEqual(self.call('admin/locks').status_code,403)
        self.login(OWNER);self.assertEqual(len(self.call('jobs').json['jobs']),2)
        self.assertEqual(self.call('jobs/'+other).status_code,200)

    def test_confirm_once_uses_existing_queue(self):
        jid=self.job();self.login()
        result=self.call('jobs/'+jid+'/confirm','POST',{})
        self.assertEqual(result.status_code,200,result.json)
        self.assertEqual(self.state(jid),'verified_queued')
        self.assertEqual(self.call('jobs/'+jid+'/confirm','POST',{}).status_code,409)
        with self.q.db() as db:self.assertEqual(db.execute('SELECT COUNT(*) AS n FROM jobs').fetchone()['n'],1)

    def test_preview_undelivered_and_expired_cannot_confirm(self):
        self.login()
        for state,notified,age in [('preview_running',0,0),('draft',0,0),('draft',1,61)]:
            jid=self.job(state=state,notified=notified,age=age)
            self.call('jobs/'+jid+'/confirm','POST',{})
            self.assertNotIn(self.state(jid),('queued','verified_queued'))
        self.assertEqual(self.state(jid),'expired')

    def test_refresh_does_not_extend_minute(self):
        jid=self.job(age=12);self.login()
        first=self.call('jobs/'+jid).json['job'];second=self.call('jobs/'+jid).json['job']
        self.assertEqual(first['expires_at'],second['expires_at'])
        self.assertLess(first['expires_at']-time.time(),49)
        self.assertIn('Mọi thắc mắc',first['rows'][0]['note'])

    def test_membership_and_disabled_group_checks(self):
        jid=self.job();self.login()
        with patch.object(portal,'verify_chat_member',side_effect=portal.PortalError('not member',403)):
            self.assertEqual(self.call('jobs/'+jid+'/confirm','POST',{}).status_code,403)
        self.assertEqual(self.state(jid),'draft')
        for chat in (DISABLED_CO_GROUP,'C'+'a'*32,MEMBER):
            jid=self.job(chat=chat)
            self.assertEqual(self.call('jobs/'+jid+'/confirm','POST',{}).status_code,403)

    def test_off_mode_preserves_owner_exception(self):
        other=self.job();own=self.job(OWNER,OWNER);self.q.admin('BOT OFF');self.login()
        self.assertEqual(self.call('jobs/'+other+'/confirm','POST',{}).status_code,409)
        self.login(OWNER);self.call('jobs/'+other+'/confirm','POST',{})
        self.assertEqual(self.state(other),'draft')
        self.assertEqual(self.call('jobs/'+own+'/confirm','POST',{}).status_code,200)
        self.assertEqual(self.state(own),'verified_queued')

    def test_owner_requires_healthy_worker(self):
        jid=self.job(OWNER);self.login(OWNER);self.q.heartbeat(False)
        self.assertEqual(self.call('jobs/'+jid+'/confirm','POST',{}).status_code,409)
        self.assertEqual(self.state(jid),'draft')

    def test_unknown_or_running_never_cancelled(self):
        self.login(OWNER)
        for state in ('unknown','running','submitting','succeeded'):
            jid=self.job(state=state)
            result=self.call('jobs/'+jid+'/cancel','POST',{})
            self.assertEqual(result.status_code,200,result.json);self.assertEqual(self.state(jid),state)
        jid=self.job(state='queued');self.call('jobs/'+jid+'/cancel','POST',{})
        self.assertEqual(self.state(jid),'cancelled')

    def unknown_job(self,result='MWG chưa trả kết quả.',payload=None):
        jid=self.job(state='unknown',payload=payload)
        with self.q.db() as db:
            db.execute('UPDATE jobs SET result=?,lease=? WHERE id=?',(result,'unknown-lease',jid))
        return jid

    def unknown_review(self,jid):
        return {'revision':self.call('jobs/'+jid).json['job']['unknown_resolution']['revision'],
                'checked_mwg_no_co':True}

    def test_unknown_cancel_only_owner_not_member_or_admin(self):
        jid=self.unknown_job();path='admin/jobs/'+jid+'/cancel-unknown'
        self.assertEqual(self.call(path,'POST',{}).status_code,401)
        for user in (MEMBER,ADMIN):
            self.login(user)
            self.assertEqual(self.call(path,'POST',{'checked_mwg_no_co':True,'revision':'0'*64}).status_code,403)
        self.login(MEMBER)
        self.assertNotIn('unknown_resolution',self.call('jobs/'+jid).json['job'])
        self.login(OWNER)
        self.assertTrue(self.call('jobs/'+jid).json['job']['unknown_resolution']['can_cancel'])
        self.assertEqual(self.state(jid),'unknown')

    def test_unknown_cancel_requires_explicit_attestation_and_csrf(self):
        jid=self.unknown_job();self.login(OWNER);data=self.unknown_review(jid)
        path='admin/jobs/'+jid+'/cancel-unknown'
        for value in (None,False,'true',1):
            self.assertEqual(self.call(path,'POST',dict(data,checked_mwg_no_co=value)).status_code,400)
        for value in (None,3,'bad'):
            self.assertEqual(self.call(path,'POST',dict(data,revision=value)).status_code,400)
        for headers in ({'Origin':'https://evil.example'},{'X-Tao-CSRF':''}):
            self.assertEqual(self.call(path,'POST',data,headers).status_code,403)
        self.assertEqual(self.state(jid),'unknown')

    def test_unknown_cancel_preserves_evidence_and_releases_queue(self):
        jid=self.unknown_job();next_id=self.job(state='preview_queued');self.login(OWNER)
        data=self.unknown_review(jid)
        with self.q.db() as db:before=dict(db.execute('SELECT * FROM jobs WHERE id=?',(jid,)).fetchone())
        response=self.call('admin/jobs/'+jid+'/cancel-unknown','POST',data)
        self.assertEqual(response.status_code,200,response.json)
        self.assertEqual(response.json['job']['state'],'cancelled')
        self.assertIn('owner_cancelled_at',response.json['job'])
        with self.q.db() as db:
            after=dict(db.execute('SELECT * FROM jobs WHERE id=?',(jid,)).fetchone())
            for field in ('result','created','owner','chat','lease'):self.assertEqual(after[field],before[field])
            payload=json.loads(after['payload']);audit=payload.pop('owner_no_co_cancellation')
            self.assertEqual(payload,json.loads(before['payload']))
            self.assertEqual(audit['actor'],OWNER);self.assertIs(audit['checked_mwg_no_co'],True)
            self.assertEqual(audit['previous_result'],before['result']);self.assertEqual(audit['revision'],data['revision'])
            self.assertEqual(after['notified'],1)
        self.assertEqual(self.call('admin/jobs/'+jid+'/cancel-unknown','POST',data).status_code,409)
        self.assertEqual(self.q.claim(preview_protocol=True,batch_protocol=True)['id'],next_id)
        self.assertEqual(self.state(jid),'cancelled')

    def test_unknown_cancel_refuses_stale_result_payload_or_lease(self):
        self.login(OWNER)
        changes=(('state','succeeded'),('result','Late MWG response'),('lease','new-lease'),
                 ('updated',time.time()+10),('payload',json.dumps(dict(self.payload,quantity=2))))
        for key,value in changes:
            jid=self.unknown_job();data=self.unknown_review(jid)
            with self.q.db() as db:db.execute('UPDATE jobs SET '+key+'=? WHERE id=?',(value,jid))
            response=self.call('admin/jobs/'+jid+'/cancel-unknown','POST',data)
            self.assertEqual(response.status_code,409,(key,response.json))
            self.assertNotEqual(self.state(jid),'cancelled')

    def test_unknown_cancel_rejects_other_states_even_with_valid_revision(self):
        self.login(OWNER)
        for state in ('draft','queued','preview_running','running','submitting','succeeded','failed','cancelled','expired'):
            jid=self.job(state=state)
            with self.q.db() as db:job=dict(db.execute('SELECT * FROM jobs WHERE id=?',(jid,)).fetchone())
            data={'revision':portal.unknown_revision(job),'checked_mwg_no_co':True}
            self.assertEqual(self.call('admin/jobs/'+jid+'/cancel-unknown','POST',data).status_code,409)
            self.assertEqual(self.state(jid),state)

    def test_unknown_cancel_rejects_partial_co_legacy_co_and_bad_evidence(self):
        self.login(OWNER)
        batch=dict(items=[self.payload,dict(self.payload,source='789')])
        cases=[('Đã có 123CO456 nhưng MWG trả lỗi',None),('[broken',None),
               (json.dumps([dict(co='1CO123',error='',state='succeeded'),dict(co='',error='Waiting',state='unknown')]),batch)]
        for result,payload in cases:
            jid=self.unknown_job(result,payload);job=self.call('jobs/'+jid).json['job']
            self.assertFalse(job['unknown_resolution']['can_cancel'])
            data={'revision':job['unknown_resolution']['revision'],'checked_mwg_no_co':True}
            self.assertEqual(self.call('admin/jobs/'+jid+'/cancel-unknown','POST',data).status_code,409)
            self.assertEqual(self.state(jid),'unknown')

    def test_unknown_cancel_checks_saved_co_note_evidence(self):
        jid=self.unknown_job();self.login(OWNER);data=self.unknown_review(jid)
        with self.q.db() as db:
            db.execute('INSERT INTO co_note_outbox(job_id,destination,message) VALUES(?,?,?)',(jid,GROUP,'1CO123'))
        self.assertEqual(self.call('admin/jobs/'+jid+'/cancel-unknown','POST',data).status_code,409)
        self.assertEqual(self.state(jid),'unknown')

    def test_unknown_cancel_acknowledges_exact_retry_and_verified_failure(self):
        result=json.dumps([dict(co='',error='Waiting',state='unknown')])
        jid=self.unknown_job(result);self.login(OWNER)
        self.call('admin/jobs/'+jid+'/cancel-unknown','POST',self.unknown_review(jid))
        self.assertTrue(self.q.update(jid,'unknown-lease','unknown',result))
        failed=json.dumps([dict(co='',error='Không đủ tồn',state='failed')])
        self.assertTrue(self.q.update(jid,'unknown-lease','failed',failed))
        self.assertTrue(self.q.update(jid,'unknown-lease','failed',failed))
        self.assertEqual(self.state(jid),'cancelled')
        self.assertEqual(self.q.result_status(jid,'unknown-lease')['result'],result)
        with self.q.db() as db:
            payload=json.loads(db.execute('SELECT payload FROM jobs WHERE id=?',(jid,)).fetchone()['payload'])
            self.assertEqual(payload['owner_no_co_cancellation']['verified_failure'],failed)

    def test_unknown_cancel_does_not_hide_late_success(self):
        jid=self.unknown_job();self.login(OWNER)
        self.call('admin/jobs/'+jid+'/cancel-unknown','POST',self.unknown_review(jid))
        final=json.dumps([dict(co='1CO987654',error='',state='succeeded')])
        self.assertTrue(self.q.update(jid,'unknown-lease','succeeded',final))
        self.assertTrue(self.q.update(jid,'unknown-lease','succeeded',final))
        with self.q.db() as db:
            job=dict(db.execute('SELECT * FROM jobs WHERE id=?',(jid,)).fetchone())
            self.assertEqual(job['state'],'succeeded');self.assertEqual(job['result'],final);self.assertEqual(job['notified'],0)
            self.assertIn('owner_no_co_cancellation',json.loads(job['payload']))
            self.assertIn('1CO987654',db.execute('SELECT message FROM co_note_outbox WHERE job_id=?',(jid,)).fetchone()['message'])

    def test_unknown_cancel_never_acknowledges_submit_or_wrong_lease(self):
        jid=self.unknown_job();self.login(OWNER)
        self.call('admin/jobs/'+jid+'/cancel-unknown','POST',self.unknown_review(jid))
        self.assertFalse(self.q.update(jid,'unknown-lease','submitting',''))
        self.assertFalse(self.q.update(jid,'wrong-lease','unknown','MWG chưa trả kết quả.'))
        self.assertFalse(self.q.update(jid,'unknown-lease','preview_ready','Product'))
        self.assertFalse(self.q.update(jid,'unknown-lease','succeeded',json.dumps([dict(co='1CO123',error='')])) )
        self.assertEqual(self.state(jid),'cancelled')

    def test_unknown_cancel_late_result_preserves_already_failed_rows(self):
        payload=dict(items=[self.payload,dict(self.payload,source='789')])
        failed=dict(co='',error='Không đủ tồn',state='failed')
        original=json.dumps([failed,dict(co='',error='Waiting',state='unknown')])
        jid=self.unknown_job(original,payload);self.login(OWNER)
        response=self.call('admin/jobs/'+jid+'/cancel-unknown','POST',self.unknown_review(jid))
        self.assertEqual(response.status_code,200,response.json)
        co=dict(co='1CO123',error='',state='succeeded')
        self.assertFalse(self.q.update(jid,'unknown-lease','succeeded',json.dumps([co,co])))
        self.assertTrue(self.q.update(jid,'unknown-lease','succeeded',json.dumps([failed,co])))
        self.assertEqual(self.state(jid),'succeeded')

    def test_bulk_cancel_only_owner_even_for_other_admins(self):
        jid=self.job(state='queued')
        self.assertEqual(self.call('admin/cancel-waiting','POST',{}).status_code,401)
        for user in (MEMBER,ADMIN):
            self.login(user)
            self.assertEqual(self.call('admin/queue').status_code,403)
            self.assertEqual(self.call('admin/cancel-waiting','POST',{'revision':'0'*64}).status_code,403)
        self.assertEqual(self.state(jid),'queued')

    def test_bulk_cancel_requires_origin_csrf_and_revision(self):
        jid=self.job(state='queued');self.login(OWNER)
        revision=self.call('admin/queue').json['revision']
        for headers in ({'Origin':'https://evil.example'},{'X-Tao-CSRF':'bad'}):
            self.assertEqual(self.call('admin/cancel-waiting','POST',{'revision':revision},headers).status_code,403)
        for value in (None,1,{},'bad'):
            self.assertEqual(self.call('admin/cancel-waiting','POST',{'revision':value}).status_code,400)
        self.assertEqual(self.state(jid),'queued')

    def test_bulk_cancel_all_chats_preserves_processing_history_and_intake(self):
        waiting=[self.job(owner=user,chat=chat,state=state) for state,user,chat in (
            ('draft',MEMBER,GROUP),('preview_queued',OTHER,'C'+'4'*32),
            ('queued',OWNER,OWNER),('verified_queued',ADMIN,GROUP))]
        protected={self.job(state=state):state for state in
                   ('preview_running','running','submitting','unknown','succeeded','failed','expired','cancelled')}
        before={}
        with self.q.db() as db:
            for jid in waiting+list(protected):
                db.execute('UPDATE jobs SET lease=?,result=? WHERE id=?',('original-lease','original-evidence',jid))
                db.execute('INSERT INTO preview_replies(job_id,token,received) VALUES(?,?,?)',(jid,'reply-'+jid,time.time()))
                before[jid]=dict(db.execute('SELECT * FROM jobs WHERE id=?',(jid,)).fetchone())
        self.q.admin('BOT OFF');self.q.heartbeat(False);self.login(OWNER)
        overview=self.call('admin/queue').json
        self.assertEqual((overview['waiting'],overview['processing'],overview['unknown']),(4,3,1))
        response=self.call('admin/cancel-waiting','POST',{'revision':overview['revision']})
        self.assertEqual(response.status_code,200,response.json);self.assertEqual(response.json['cancelled'],4)
        with self.q.db() as db:
            self.assertEqual(db.execute('SELECT enabled FROM co_control WHERE id=1').fetchone()['enabled'],0)
            for jid in waiting:
                row=dict(db.execute('SELECT * FROM jobs WHERE id=?',(jid,)).fetchone())
                self.assertEqual(row['state'],'cancelled');self.assertIsNone(row['lease']);self.assertEqual(row['notified'],1)
                for field in ('payload','result','owner','chat','created'):self.assertEqual(row[field],before[jid][field])
                self.assertIsNone(db.execute('SELECT job_id FROM preview_replies WHERE job_id=?',(jid,)).fetchone())
            for jid in protected:
                self.assertEqual(dict(db.execute('SELECT * FROM jobs WHERE id=?',(jid,)).fetchone()),before[jid])
        self.assertEqual(self.call('admin/queue').json['waiting'],0)

    def test_bulk_cancel_does_not_cancel_new_arrivals_without_new_review(self):
        first=self.job(state='queued');self.login(OWNER)
        revision=self.call('admin/queue').json['revision']
        second=self.job(owner=OTHER,state='queued')
        response=self.call('admin/cancel-waiting','POST',{'revision':revision})
        self.assertEqual(response.status_code,409)
        self.assertEqual(self.state(first),'queued');self.assertEqual(self.state(second),'queued')

    def test_bulk_cancel_refuses_after_worker_claim(self):
        jid=self.job(state='preview_queued');self.login(OWNER)
        revision=self.call('admin/queue').json['revision']
        claimed=self.q.claim(preview_protocol=True,batch_protocol=True)
        self.assertEqual(claimed['id'],jid)
        response=self.call('admin/cancel-waiting','POST',{'revision':revision})
        self.assertEqual(response.status_code,409);self.assertEqual(self.state(jid),'preview_running')

    def test_bulk_cancel_release_prepared_page_and_reject_stale_report(self):
        jid=self.job(state='draft');self.login(OWNER)
        with self.q.db() as db:db.execute('UPDATE jobs SET lease=? WHERE id=?',('lease-before-cancel',jid))
        data={'revision':self.call('admin/queue').json['revision']}
        self.assertEqual(self.call('admin/cancel-waiting','POST',data).json['cancelled'],1)
        self.assertEqual(self.call('admin/cancel-waiting','POST',data).status_code,409)
        self.assertEqual(self.q.claim(preview_protocol=True,prepared_id=jid),{'release_preview':True})
        self.assertFalse(self.q.update(jid,'lease-before-cancel','preview_ready','Late response'))
        self.assertEqual(self.state(jid),'cancelled')

    def test_waiting_and_attention_filters_keep_user_scope(self):
        waiting=self.job(state='queued');unknown=self.job(state='unknown')
        other=self.job(owner=OTHER,state='unknown');self.job(state='succeeded')
        self.login(MEMBER)
        self.assertEqual([j['id'] for j in self.call('jobs?filter=waiting').json['jobs']],[waiting])
        self.assertEqual([j['id'] for j in self.call('jobs?filter=attention').json['jobs']],[unknown])
        self.login(OWNER)
        self.assertEqual({j['id'] for j in self.call('jobs?filter=attention').json['jobs']},{unknown,other})

    def test_conditions_exact_sku_and_unknown_not_permission(self):
        self.login()
        self.assertEqual(self.call('conditions?code=131491005415').status_code,400)
        self.assertFalse(self.call('conditions?code=0131491005415').json['found'])
        with patch.object(portal,'load_conditions',return_value={'0131491005415':['MỞ','KHÓA','']}):
            data=self.call('conditions?code=0131491005415').json
        self.assertEqual([r['state'] for r in data['conditions']],['yes','no','unknown'])

    def test_only_owner_unlock_and_stale_revision(self):
        now=time.time()
        with self.q.db() as db:db.execute('INSERT INTO co_confirmation_locks VALUES(?,?,?,?,?,?)',(MEMBER,'Thành viên',3,0,'1234567890',now))
        data={'owner':MEMBER,'last_job':'1234567890','updated':now}
        self.login(ADMIN);self.assertEqual(self.call('admin/unlock','POST',data).status_code,403)
        self.login(OWNER)
        self.assertEqual(self.call('admin/unlock','POST',dict(data,updated=now-1)).status_code,409)
        self.assertEqual(self.call('admin/unlock','POST',data).status_code,200)
        self.assertEqual(self.call('admin/locks').json['locks'],[])

    def test_report_30_days_distinct_co_and_five_recent_rows(self):
        self.login(OWNER)
        for i in range(7):
            jid=self.job(payload=dict(self.payload,source=str(i+1)))
            with self.q.db() as db:db.execute("UPDATE jobs SET state='succeeded',result='1CO123' WHERE id=?",(jid,))
        old=self.job();start,_=period('30ngay')
        with self.q.db() as db:db.execute("UPDATE jobs SET state='succeeded',result='2CO123',created=? WHERE id=?",((start-timedelta(days=1)).timestamp(),old))
        result=self.call('summary?period=30').json
        self.assertEqual(result['stats']['co'],1)
        self.assertEqual(result['top']['people'][0]['count'],1)
        self.assertEqual(len(result['recent']),5)
        self.assertEqual(len(result['top']['source']),5)

    def test_intake_admin_allowed_member_denied(self):
        self.login();self.assertEqual(self.call('admin/intake','POST',{'enabled':False}).status_code,403)
        self.login(ADMIN);self.assertEqual(self.call('admin/intake','POST',{'enabled':False}).status_code,200)
        self.assertFalse(self.call('me').json['enabled'])

    def test_command_link_without_worker_mutation(self):
        event=types.SimpleNamespace(reply_token='test',message=types.SimpleNamespace(text='!công cụ'))
        self.assertTrue(self.handle(event));self.assertIn('https://liff.line.me/123456-test',self.replies[-1])
        event.message.text='!other';self.assertFalse(self.handle(event))

    def test_unpublished_app_does_not_distribute_link(self):
        event=types.SimpleNamespace(reply_token='test',message=types.SimpleNamespace(text='!congcu'))
        with patch.dict(os.environ,{'TAO_PUBLIC_LAUNCH':'0'}):self.assertTrue(self.handle(event))
        self.assertNotIn('https://',self.replies[-1])


class LineVerificationTests(unittest.TestCase):
    def test_rejects_wrong_channel_issuer_expiry_or_user(self):
        good={'iss':'https://access.line.me','aud':'123456','sub':MEMBER,'exp':time.time()+60}
        for change in ({'aud':'999'},{'iss':'https://evil.example'},{'exp':0},{'sub':'owner'}):
            response=MagicMock();response.__enter__.return_value.read.return_value=json.dumps(dict(good,**change)).encode()
            with patch.object(portal,'urlopen',return_value=response),self.assertRaises(portal.PortalError):
                portal.verify_id_token('token','123456')
        response.__enter__.return_value.read.return_value=json.dumps(good).encode()
        with patch.object(portal,'urlopen',return_value=response) as request:
            self.assertEqual(portal.verify_id_token('token','123456')['sub'],MEMBER)
            self.assertEqual(request.call_args.kwargs['timeout'],6)

    def test_member_api_identity_checked(self):
        response=MagicMock();response.__enter__.return_value.read.return_value=json.dumps({'userId':OTHER}).encode()
        with patch.object(portal,'urlopen',return_value=response),self.assertRaises(portal.PortalError):
            portal.verify_chat_member(GROUP,MEMBER,'test-token')


if __name__=='__main__':unittest.main()
