import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from co_flow import Queue, DuplicateRequest

class IsolatedQueueTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.q=Queue(str(Path(self.tmp.name)/'q.db'))
        self.p=dict(source='12',destination='20',product='0131491005414',quantity=1,note='')
        self.bad=self.q.draft('bad','owner','chat',self.p)
        with self.q.db() as db:
            db.execute('UPDATE jobs SET state=?,result=? WHERE id=?',('unknown','keep evidence',self.bad['id']))
    def add(self,event,**changes):
        j=self.q.draft(event,'owner','chat',dict(self.p,**changes))
        self.q.confirm(j['id'],'owner','chat');return j
    def claim(self,**kwargs):
        return self.q.claim(recovery_protocol=True,page_ready=True,**kwargs)
    def test_old_worker_and_busy_page_block(self):
        self.add('other',source='99')
        self.assertIsNone(self.q.claim())
        self.assertEqual(self.q.claim(recovery_protocol=True),{'recovery_required':True})
    def test_skip_related_head_allow_independent_and_keep_evidence(self):
        blocked=self.add('blocked',destination='30',quantity=2,source='0012')
        other=self.add('other',source='99')
        self.assertEqual(self.claim()['id'],other['id'])
        with self.q.db() as db:
            a=db.execute('SELECT state,result FROM jobs WHERE id=?',(self.bad['id'],)).fetchone()
            b=db.execute('SELECT state FROM jobs WHERE id=?',(blocked['id'],)).fetchone()
        self.assertEqual(tuple(a),('unknown','keep evidence'));self.assertEqual(b['state'],'queued')
    def test_new_related_request_rejected_early(self):
        with self.assertRaises(DuplicateRequest):
            self.q.draft('new','another','group',dict(self.p,destination='88',quantity=9),check_duplicates=True)
    def test_batch_with_one_conflict_stays_queued(self):
        j=self.q.draft('batch','owner','chat',{'items':[dict(self.p,source='99'),self.p]})
        self.q.confirm(j['id'],'owner','chat')
        self.assertIsNone(self.claim(batch_protocol=True))
    def test_second_unknown_also_protects_inventory(self):
        self.add('second',source='99')
        with self.q.db() as db: db.execute("UPDATE jobs SET state='unknown' WHERE event='second'")
        self.add('related',source='99',destination='88')
        other=self.add('third',source='77')
        self.assertEqual(self.claim()['id'],other['id'])
    def test_concurrent_workers_only_claim_one(self):
        self.add('one',source='98');self.add('two',source='99')
        with ThreadPoolExecutor(max_workers=2) as pool: claims=list(pool.map(lambda _:self.claim(),range(2)))
        self.assertEqual(sum(x is not None for x in claims),1)
    def test_confirmed_prepared_row_survives_quarantine(self):
        j=self.add('one',source='99')
        self.assertEqual(self.claim(prepared_id=j['id'])['id'],j['id'])

