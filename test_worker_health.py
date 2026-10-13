import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from flask import Flask
from co_flow import Queue, install, BotUnavailable
from co_health import readiness


class HealthTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.path=str(Path(tmp.name)/'queue.db');self.q=Queue(self.path)
        self.p=dict(source='1',destination='2',product='0131491005414',quantity=1,note='')

    def pulse(self,state,age=0):
        self.q.heartbeat(True,{'state':state,'progress_age_seconds':age})

    def test_alive_but_not_ready_rejects_without_queueing(self):
        for state in ('loading','login','blocked','reconnecting','stopping','unverified'):
            self.pulse(state)
            with self.assertRaises(BotUnavailable):self.q.draft(state,'o','c',self.p,require_online=True)
            self.assertIn('Chưa bật được',self.q.admin('BOT ON'))
        with self.q.db() as db:self.assertEqual(db.execute('SELECT COUNT(*) AS n FROM jobs').fetchone()['n'],0)

    def test_heartbeat_cannot_hide_stalled_progress(self):
        self.pulse('processing',61)
        with self.q.db() as db:
            health=readiness(db)
        self.assertTrue(health['online']);self.assertFalse(health['accepting'])
        self.assertEqual(health['worker_state'],'blocked')
        self.assertIsNone(self.q.claim(require_online=True))

    def test_healthy_busy_worker_keeps_gathering_and_confirming(self):
        for n,state in enumerate(('ready','processing','awaiting_confirmation')):
            self.pulse(state)
            j=self.q.draft(str(n),'o','c',self.p,require_online=True)
            self.q.confirm(j['id'],'o','c',require_online=True)
        self.assertIsNotNone(self.q.claim(require_online=True))

    def test_prepared_confirmation_claim_and_cancel_release(self):
        j=self.q.draft('e','o','c',self.p,check_product=True)
        job=self.q.claim(preview_protocol=True)
        self.q.update(job['id'],job['lease'],'preview_ready','["iPhone"]')
        self.pulse('awaiting_confirmation')
        self.q.confirm(j['id'],'o','c',require_online=True)
        claimed=self.q.claim(preview_protocol=True,prepared_id=j['id'],require_online=True)
        self.assertEqual(claimed['mode'],'create')
        self.assertEqual(claimed['id'],j['id'])
        self.q.update(claimed['id'],claimed['lease'],'failed','before submit')
        self.pulse('blocked')
        self.assertEqual(self.q.claim(prepared_id=j['id'],require_online=True),{'release_preview':True})

    def test_unready_expiry_does_not_punish_requester(self):
        p=dict(self.p,confirmation_lock_version=1)
        j=self.q.draft('e','o','c',p)
        with self.q.db() as db:
            db.execute("UPDATE jobs SET result='MWG_PREVIEW',notified=1,created=created-61 WHERE id=?",(j['id'],))
        self.pulse('login');self.q.expire_confirmations()
        with self.q.db() as db:
            self.assertEqual(db.execute('SELECT state FROM jobs WHERE id=?',(j['id'],)).fetchone()['state'],'expired')
            self.assertIsNone(db.execute('SELECT * FROM co_confirmation_locks').fetchone())

    def test_authenticated_endpoint_requires_readiness_from_legacy_worker(self):
        env={'CO_ENABLED':'1','CO_DB_PATH':self.path,'CO_DATABASE_URL':'','CO_WORKER_TOKEN':'x'*40}
        with patch.dict(os.environ,env):
            app=Flask(__name__);install(app,lambda *a:None,lambda *a:None)
            client=app.test_client();headers={'Authorization':'Bearer '+'x'*40}
            self.assertEqual(client.post('/co/worker/heartbeat',json={'online':True}).status_code,401)
            client.post('/co/worker/heartbeat',json={'online':True},headers=headers)
            status=client.get('/co/worker/status',headers=headers).json
            self.assertTrue(status['online']);self.assertFalse(status['accepting'])
            for value in ({}, {'state':'ready','progress_age_seconds':-1}, {'state':'ready','progress_age_seconds':float('nan')}):
                self.assertEqual(client.post('/co/worker/heartbeat',json={'online':True,'health':value},headers=headers).status_code,400)
            client.post('/co/worker/heartbeat',json={'online':True,'health':{'state':'ready','progress_age_seconds':0}},headers=headers)
            self.assertTrue(client.get('/co/worker/status',headers=headers).json['accepting'])
            client.post('/co/worker/heartbeat',json={'online':False},headers=headers)
            self.assertFalse(client.get('/co/worker/status',headers=headers).json['accepting'])


if __name__=='__main__':unittest.main()
