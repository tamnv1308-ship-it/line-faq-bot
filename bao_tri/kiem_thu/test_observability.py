import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock
from flask import Flask

from co_flow import Queue, install, PRIVATE_CO_OWNER as OWNER, MEMBER_CO_GROUP as GROUP
import co_observability as obs
from worker_observability import Telemetry
from bao_tri.kiem_thu import test_tao_portal as portal_tests
MEMBER=portal_tests.MEMBER
ADMIN=portal_tests.ADMIN


class ObservabilityTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.root=Path(tmp.name);self.q=Queue(str(self.root/'q.db'))
        self.p=dict(source='3945',destination='447',product='0131491005415',quantity=1,note='',status='Mới')

    def draft(self):
        return self.q.draft('evt'+str(time.time_ns()),OWNER,GROUP,self.p,check_product=True)

    def rows(self,jid):
        with self.q.db() as db:
            return dict(db.execute('SELECT * FROM jobs WHERE id=?',(jid,)).fetchone()),obs.read_events(db,jid)

    def test_full_lifecycle_separates_confirmation_and_preserves_one_minute(self):
        base=time.time()
        with patch('time.time',return_value=base):job=self.draft()
        with patch('time.time',return_value=base+10):claim=self.q.claim(True,batch_protocol=True)
        with patch('time.time',return_value=base+14):
            self.assertTrue(self.q.update(job['id'],claim['lease'],'preview_ready',json.dumps({'rows':[{'product_name':'iPhone','source_name':'3945 - A','destination_name':'447 - B'}]})))
        with patch('time.time',return_value=base+15):self.q.mark_notified(job['id'],'draft')
        before,_=self.rows(job['id']);self.assertEqual(before['created'],base+15)
        with patch('time.time',return_value=base+35):self.q.confirm(job['id'],OWNER,GROUP)
        with patch('time.time',return_value=base+36):create=self.q.claim(True,prepared_id=job['id'],batch_protocol=True)
        with patch('time.time',return_value=base+37):self.q.update(job['id'],create['lease'],'submitting')
        with patch('time.time',return_value=base+41):self.q.update(job['id'],create['lease'],'succeeded','123CO456')
        with patch('time.time',return_value=base+42):self.q.mark_notified(job['id'],'succeeded')
        row,events=self.rows(job['id']);phases=obs.timeline(row,events,base+43)['phases']
        durations={p['key']:p['seconds'] for p in phases if p['complete']}
        self.assertEqual(durations,dict(queue=10,prepare=4,preview_delivery=1,confirmation=20,create_queue=1,pre_submit=1,create=4,result_delivery=1))
        self.assertEqual(row['result'],'123CO456')
        self.assertEqual(row['state'],'succeeded')

    def test_worker_idempotent_redelivery_no_token_in_saved_events(self):
        job=self.draft();claim=self.q.claim(True,batch_protocol=True)
        e=dict(event_id='a'*32,job_id=job['id'],lease=claim['lease'],stage='upload_excel',at=time.time(),duration_ms=1400,outcome='ok',error_code='')
        self.assertEqual(self.q.observe_worker([e]),['a'*32])
        self.assertEqual(self.q.observe_worker([e]),['a'*32])
        row,events=self.rows(job['id']);mac=[r for r in events if r['source']=='mac']
        self.assertEqual(len(mac),1);self.assertNotIn(claim['lease'],json.dumps(mac))
        self.assertEqual(row['state'],'preview_running')

    def test_reject_bad_lease_invalid_duration_and_forged_stage(self):
        job=self.draft();claim=self.q.claim(True,batch_protocol=True)
        base=dict(event_id='b'*32,job_id=job['id'],lease=claim['lease'],stage='upload_excel',at=time.time(),duration_ms=1000,outcome='ok',error_code='')
        for changed in ({'lease':'wrong'},{'duration_ms':float('nan')},{'duration_ms':-1},{'at':time.time()+400},{'stage':'confirmed'},{'error_code':'token=secret'}):
            self.q.observe_worker([dict(base,**changed)])
        _,events=self.rows(job['id']);self.assertFalse(any(r['source']=='mac' for r in events))

    def test_diagnostic_db_failure_does_not_rollback_business_update(self):
        job=self.draft()
        with self.q.db() as db:
            db.execute('DROP TABLE co_ops_events')
        claim=self.q.claim(True,batch_protocol=True)
        self.assertEqual(claim['id'],job['id'])
        with self.q.db() as db:self.assertEqual(db.execute('SELECT state FROM jobs').fetchone()['state'],'preview_running')

    def test_unknown_and_notification_failure_remain_separate_and_readonly(self):
        job=self.draft();claim=self.q.claim(True,batch_protocol=True)
        with self.q.db() as db:
            db.execute("UPDATE jobs SET state='unknown',result='MWG chưa trả kết quả',updated=?,notified=0 WHERE id=?",(time.time()-20,job['id']))
        row,_=self.rows(job['id']);self.q.notice_failed(row)
        result=obs.overview(self.q)
        kinds={x['kind'] for x in result['issues'] if x.get('job_id')==job['id']}
        self.assertEqual(kinds,{'unknown','delivery'})
        self.assertEqual(self.rows(job['id'])[0],row)

    def test_partial_success_still_shows_line_error_but_keeps_co(self):
        job=self.draft()
        p=dict(items=[self.p,dict(self.p,destination='448')])
        result=[dict(co='123CO456',error='',state='succeeded'),dict(co='',error='Mã sản phẩm không tồn tại',state='failed')]
        with self.q.db() as db:db.execute("UPDATE jobs SET state='succeeded',payload=?,result=?,notified=1 WHERE id=?",(json.dumps(p),json.dumps(result),job['id']))
        view=obs.overview(self.q);issue=next(x for x in view['issues'] if x.get('job_id')==job['id'])
        self.assertEqual(issue['reason'],'product');self.assertIn('123CO456',self.rows(job['id'])[0]['result'])

    def test_missing_historical_timestamps_never_fabricate_durations(self):
        job=self.draft()
        with self.q.db() as db:db.execute('DELETE FROM co_ops_events')
        view=obs.overview(self.q)
        self.assertEqual(view['timings'],[]);self.assertEqual(view['coverage']['instrumented'],0)
        self.assertFalse(obs.timeline(self.rows(job['id'])[0],[])['available'])

    def test_worker_spool_survives_restart_and_ack_only_received_ids(self):
        job=dict(id='a'*10,lease='test-lease');clock=[20.0]
        with patch('time.monotonic',side_effect=lambda:clock[0]):
            telemetry=Telemetry(self.root);telemetry.progress(job,'upload_excel')
            clock[0]+=1.4;telemetry.progress(job,'accept_import')
            clock[0]+=2;telemetry.finish(job,'TimeoutError')
        records=Telemetry(self.root).batch()
        done=[r for r in records if r['duration_ms'] is not None]
        self.assertEqual([r['duration_ms'] for r in done],[1400,2000])
        self.assertEqual(done[-1]['error_code'],'timeout')
        telemetry.acknowledge([records[0]['event_id']]);self.assertEqual(len(Telemetry(self.root).batch()),len(records)-1)

    def test_queue_backlog_and_intentional_stop_are_distinct(self):
        self.q.heartbeat(False,{'state':'stopped','progress_age_seconds':0})
        self.assertFalse(obs.overview(self.q)['issues'])
        job=self.draft()
        with self.q.db() as db:db.execute('UPDATE jobs SET updated=? WHERE id=?',(time.time()-61,job['id']))
        self.assertEqual(obs.overview(self.q)['issues'][0]['kind'],'waiting')

    def test_worker_endpoint_requires_auth_and_diagnostics_cannot_override_state(self):
        job=self.draft();claim=self.q.claim(True,batch_protocol=True)
        env={'CO_ENABLED':'1','CO_DB_PATH':self.q.path,'CO_DATABASE_URL':'','CO_WORKER_TOKEN':'x'*40}
        with patch.dict(os.environ,env):
            app=Flask(__name__);install(app,lambda *a:None,lambda *a:None)
            client=app.test_client();headers={'Authorization':'Bearer '+'x'*40}
            body={'online':True,'health':{'state':'ready','progress_age_seconds':0},'telemetry':[
                dict(event_id='c'*32,job_id=job['id'],lease=claim['lease'],stage='upload_excel',at=time.time(),duration_ms=1500,outcome='ok',error_code='')]}
            self.assertEqual(client.post('/co/worker/heartbeat',json=body).status_code,401)
            response=client.post('/co/worker/heartbeat',json=body,headers=headers)
            self.assertEqual(response.status_code,200);self.assertEqual(response.json['telemetry_ack'],['c'*32])
            body['telemetry']=[{'stage':'confirmed'}]
            self.assertEqual(client.post('/co/worker/heartbeat',json=body,headers=headers).status_code,200)
            self.assertEqual(self.rows(job['id'])[0]['state'],'preview_running')

    def test_broken_local_diagnostics_never_prevent_durable_result_delivery(self):
        import mac_worker as worker
        job=dict(id='a'*10,lease='lease')
        broken=MagicMock()
        for name in ('finish','progress','batch','acknowledge'):getattr(broken,name).side_effect=RuntimeError('diagnostics failure')
        with patch.object(worker,'ROOT',self.root),patch.object(worker,'TELEMETRY',broken),patch.object(worker,'RUNTIME',None),patch.object(worker,'api',return_value={'ok':True}) as api:
            worker.report(job,'succeeded','123CO456')
            self.assertEqual(api.call_count,1);self.assertEqual(api.call_args.args[1]['result'],'123CO456')
            self.assertFalse((self.root/'pending.json').exists())

    def test_expired_undelivered_preview_is_visible_without_penalizing_or_requeuing(self):
        job=self.draft()
        with self.q.db() as db:
            db.execute("UPDATE jobs SET state='expired',notified=1 WHERE id=?",(job['id'],))
            obs.record(db,job['id'],'notification_failed',outcome='error',error_code='line_delivery')
        issue=next(i for i in obs.overview(self.q)['issues'] if i.get('job_id')==job['id'])
        self.assertIn('hết hạn',issue['title']);self.assertEqual(self.rows(job['id'])[0]['state'],'expired')

    def test_excluded_import_row_is_visible_while_good_row_awaits_confirmation(self):
        job=self.draft();p=dict(self.p,skipped_errors=[dict(self.p,error='Mã sản phẩm không tồn tại')])
        with self.q.db() as db:db.execute("UPDATE jobs SET payload=?,state='draft',notified=1 WHERE id=?",(json.dumps(p),job['id']))
        view=obs.overview(self.q)
        self.assertTrue(any(i['reason']=='product' for i in view['issues'] if i.get('job_id')==job['id']))
        self.assertEqual(self.rows(job['id'])[0]['state'],'draft')


class OperationsPortalTests(unittest.TestCase):
    setUp=portal_tests.PortalTests.setUp
    call=portal_tests.PortalTests.call
    login=portal_tests.PortalTests.login
    job=portal_tests.PortalTests.job
    state=portal_tests.PortalTests.state
    def test_operations_owner_only_and_member_diagnostics_hidden(self):
        jid=self.job()
        self.assertEqual(self.call('admin/operations').status_code,401)
        for user in (MEMBER,ADMIN):
            self.login(user);self.assertEqual(self.call('admin/operations').status_code,403)
        self.login(MEMBER);self.assertNotIn('diagnostics',self.call('jobs/'+jid).json['job'])
        self.login(OWNER);self.assertEqual(self.call('admin/operations').status_code,200)
        self.assertIn('diagnostics',self.call('jobs/'+jid).json['job'])
        before=self.call('jobs/'+jid).json['job']['expires_at']
        self.call('admin/operations')
        self.assertEqual(before,self.call('jobs/'+jid).json['job']['expires_at'])

    def test_portal_ack_is_a_delivery_milestone_not_confirmation(self):
        payload=dict(self.payload,portal_requests={'portal:x':'fingerprint'})
        jid=self.job(notified=0,payload=payload);self.login(MEMBER)
        revision=self.call('jobs/'+jid).json['job']['preview_revision']
        self.assertEqual(self.call('jobs/'+jid+'/preview-seen','POST',dict(revision=revision)).status_code,200)
        self.assertEqual(self.state(jid),'draft')
        with self.q.db() as db:stages=[x['stage'] for x in obs.read_events(db,jid)]
        self.assertIn('confirmation_delivered',stages);self.assertNotIn('confirmed',stages)


if __name__=='__main__':unittest.main()
