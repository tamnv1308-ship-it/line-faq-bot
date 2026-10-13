import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from flask import Flask
from co_flow import install, Queue


class ReconciliationEndpointTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        path=str(Path(tmp.name)/'queue.db')
        env=patch.dict(os.environ,{'CO_ENABLED':'1','CO_DB_PATH':path,'CO_DATABASE_URL':'','CO_WORKER_TOKEN':'x'*40})
        env.start();self.addCleanup(env.stop)
        self.app=Flask(__name__);install(self.app,lambda *a:None,lambda *a:None)
        self.client=self.app.test_client();self.q=Queue(path)
        j=self.q.draft('test','owner','chat',dict(source='1',destination='2',product='0131491005414',quantity=1,note=''))
        self.q.confirm(j['id'],'owner','chat');self.job=self.q.claim()
        self.headers={'Authorization':'Bearer '+'x'*40}

    def test_read_only_state_and_lease_comparison(self):
        before=self.q.result_status(self.job['id'],self.job['lease'])
        for lease,expected in ((self.job['lease'],True),('old-lease',False)):
            response=self.client.post('/co/worker/result-status',json={'id':self.job['id'],'lease':lease},headers=self.headers)
            self.assertEqual(response.status_code,200)
            self.assertEqual(response.json,dict(found=True,state='running',result='',lease_matches=expected))
        self.assertEqual(self.q.result_status(self.job['id'],self.job['lease']),before)

    def test_auth_validation_and_missing(self):
        endpoint='/co/worker/result-status'
        self.assertEqual(self.client.post(endpoint,json=self.job).status_code,401)
        for body in ([],{},dict(id='../bad',lease='x'),dict(id=self.job['id'],lease='')):
            self.assertEqual(self.client.post(endpoint,json=body,headers=self.headers).status_code,400)
        self.assertEqual(self.client.post(endpoint,json=dict(id='0000000000',lease='x'),headers=self.headers).json,{'found':False})

    def test_status_shows_real_online_and_intake_flags(self):
        self.q.heartbeat();self.q.admin('BOT OFF')
        status=self.client.get('/co/worker/status',headers=self.headers).json
        self.assertFalse(status['enabled']);self.assertTrue(status['online'])
        self.assertEqual(status['result_recovery_version'],1)
        self.q.heartbeat(False)
        self.assertFalse(self.client.get('/co/worker/status',headers=self.headers).json['online'])


if __name__=='__main__':unittest.main()
