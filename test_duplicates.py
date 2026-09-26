import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from co_flow import Queue,DuplicateRequest

class DuplicateTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.q=Queue(str(Path(self.tmp.name)/'q.db'))
        self.p=dict(source='1',destination='2',product='003',quantity=1,note='')
    def add(self,event,p=None):
        return self.q.draft(event,event,event,p or self.p,check_duplicates=True)
    def test_all_active_states_block_across_users_chats_notes(self):
        job=self.add('a')
        for state in ['draft','queued','verified_queued','preview_queued','preview_running','running','submitting','unknown']:
            with self.q.db() as db:db.execute('UPDATE jobs SET state=?',(state,))
            with self.assertRaises(DuplicateRequest):self.add('b',dict(self.p,note='different'))
    def test_different_quantity_allowed(self):
        self.add('a');self.add('b',dict(self.p,quantity=2))
    def test_redelivery_is_idempotent(self):
        self.assertEqual(self.add('a')['id'],self.add('a')['id'])
    def test_completed_cancelled_failed_and_expired_allow_new(self):
        self.add('a')
        for n,state in enumerate(['succeeded','cancelled','failed','expired']):
            with self.q.db() as db:db.execute('UPDATE jobs SET state=?',(state,))
            self.add(str(n))
    def test_batch_overlap_rejects_whole_message(self):
        self.add('a')
        with self.assertRaises(DuplicateRequest):
            self.add('b',{'items':[dict(self.p,source='8'),self.p]})
        with self.q.db() as db:self.assertEqual(db.execute('SELECT COUNT(*) AS n FROM jobs').fetchone()['n'],1)
    def test_concurrent_duplicates_only_insert_once(self):
        def submit(n):
            try:self.add(str(n));return True
            except DuplicateRequest:return False
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(sum(pool.map(submit,range(2))),1)
    def test_old_waiting_expires_but_unknown_still_blocks(self):
        self.add('a')
        with self.q.db() as db:db.execute('UPDATE jobs SET created=created-901')
        self.add('b')
        with self.q.db() as db:db.execute("UPDATE jobs SET state='unknown',created=created-901")
        with self.assertRaises(DuplicateRequest):self.add('c')

if __name__=='__main__':unittest.main()
