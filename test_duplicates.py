import tempfile
import json
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from co_flow import Queue,DuplicateRequest,transfer_key
from co_results import items
from transfer_parser import parse_request

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
            self.assertEqual(self.add('b-'+state,dict(self.p,note='different'))['state'],'skipped')
        with self.q.db() as db:self.assertEqual(db.execute('SELECT COUNT(*) AS n FROM jobs').fetchone()['n'],1)
    def test_different_quantity_allowed(self):
        self.add('a');self.add('b',dict(self.p,quantity=2))
    def test_pasted_copies_keep_first_note_and_do_not_add_quantities(self):
        row='Kho xuất: 1\nKho nhận: 2\nMSP: 0131491005418\nNote: QL A\n'
        p=parse_request(row+row.replace('QL A','QL B')+row.replace('Kho xuất: 1','Kho xuất: 3'))
        self.assertEqual([(r['source'],r['quantity'],r['note']) for r in items(p)],[('1',1,'QL A'),('3',1,'QL A')])
        self.assertEqual(len(p['skipped_duplicates']),1)
    def test_copies_only_in_same_message_still_keep_one_new_request(self):
        row='Kho xuất: 1\nKho nhận: 2\nMSP: 0131491005418\n'
        p=parse_request(row*3)
        self.assertEqual(len(items(p)),1)
        job=self.add('copies',p)
        self.assertEqual(job['state'],'draft')
        self.assertEqual(len(json.loads(job['payload'])['skipped_duplicates']),2)
    def test_redelivery_is_idempotent(self):
        self.assertEqual(self.add('a')['id'],self.add('a')['id'])
    def test_completed_cancelled_failed_and_expired_allow_new(self):
        self.add('a')
        for n,state in enumerate(['succeeded','cancelled','failed','expired']):
            with self.q.db() as db:db.execute('UPDATE jobs SET state=?',(state,))
            self.add(str(n))
    def test_batch_overlap_keeps_only_new_rows(self):
        self.add('a')
        job=self.add('b',{'items':[dict(self.p,source='8'),self.p,dict(self.p,source='9')]})
        payload=json.loads(job['payload'])
        self.assertEqual([r['source'] for r in items(payload)],['8','9'])
        self.assertEqual(len(payload['skipped_duplicates']),1)
        with self.q.db() as db:self.assertEqual(db.execute('SELECT COUNT(*) AS n FROM jobs').fetchone()['n'],2)
    def test_concurrent_duplicates_only_insert_once(self):
        def submit(n):
            try:return self.add(str(n))['state']!='skipped'
            except DuplicateRequest:return False
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(sum(pool.map(submit,range(2))),1)
    def test_old_waiting_expires_but_unknown_still_blocks(self):
        self.add('a')
        with self.q.db() as db:db.execute('UPDATE jobs SET created=created-901')
        self.add('b')
        with self.q.db() as db:db.execute("UPDATE jobs SET state='unknown',created=created-901")
        self.assertEqual(self.add('c')['state'],'skipped')

    def test_skipped_event_cannot_reappear_after_original_finishes(self):
        self.add('a');self.assertEqual(self.add('b')['state'],'skipped')
        with self.q.db() as db:db.execute("UPDATE jobs SET state='succeeded'")
        with self.assertRaises(DuplicateRequest):self.add('b')
        self.assertEqual(self.add('fresh')['state'],'draft')

    def test_partial_redelivery_does_not_readd_previously_skipped_row(self):
        self.add('a')
        p={'items':[self.p,dict(self.p,source='8')]}
        first=self.add('b',p)
        with self.q.db() as db:db.execute("UPDATE jobs SET state='succeeded' WHERE event='a'")
        again=self.add('b',p)
        self.assertEqual(first['id'],again['id'])
        self.assertEqual([r['source'] for r in items(json.loads(again['payload']))],['8'])

    def test_concurrent_overlapping_batches_keep_three_unique_rows(self):
        batches=[{'items':[self.p,dict(self.p,source=source)]} for source in ('8','9')]
        with ThreadPoolExecutor(max_workers=2) as pool:
            jobs=list(pool.map(lambda n:self.add(str(n),batches[n]),range(2)))
        keys=[transfer_key(row) for job in jobs for row in items(json.loads(job['payload']))]
        self.assertEqual(len(keys),3);self.assertEqual(len(set(keys)),3)

    def test_unknown_exact_copy_skipped_without_cancelling_original(self):
        original=self.add('a')
        with self.q.db() as db:db.execute("UPDATE jobs SET state='unknown',result='evidence'")
        job=self.add('b',{'items':[self.p,dict(self.p,source='8')]})
        self.assertEqual([r['source'] for r in items(json.loads(job['payload']))],['8'])
        with self.q.db() as db:
            saved=db.execute('SELECT state,result FROM jobs WHERE id=?',(original['id'],)).fetchone()
        self.assertEqual(tuple(saved),('unknown','evidence'))

if __name__=='__main__':unittest.main()
