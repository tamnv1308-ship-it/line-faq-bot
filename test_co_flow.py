import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from co_flow import Queue, parse_form

FORM='Kho xuất: 645\nKho nhận: 10341\nMã sản phẩm: 0131491005424\nSố lượng: 1\nNote: chuyển gấp'

class QueueTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.q=Queue(self.tmp.name+'/queue.db')
        self.p=parse_form(FORM)
    def tearDown(self):
        self.tmp.cleanup()
    def draft(self):
        return self.q.draft('event','owner','group',self.p)
    def test_all_scoped_and_repeat_safe(self):
        first=self.q.draft('one','owner','group',self.p)
        second=self.q.draft('two','owner','group',self.p)
        self.q.draft('three','other','group',self.p)
        self.q.draft('four','owner','elsewhere',self.p)
        self.assertIn('2 yêu cầu',self.q.confirm_all('owner','group'))
        self.assertIn('Không có',self.q.confirm_all('owner','group'))
        with self.q.db() as db:
            states={r['id']:r['state'] for r in db.execute('SELECT * FROM jobs')}
        self.assertEqual(states[first['id']],'queued')
        self.assertEqual(states[second['id']],'queued')
        self.assertEqual(list(states.values()).count('draft'),2)
    def test_cancel_all_keeps_confirmed_and_expires_old(self):
        old=self.q.draft('old','owner','group',self.p)
        with self.q.db() as db:
            db.execute('UPDATE jobs SET created=created-901 WHERE id=?',(old['id'],))
        ready=self.q.draft('ready','owner','group',self.p)
        self.q.confirm(ready['id'],'owner','group')
        waiting=self.q.draft('waiting','owner','group',self.p)
        self.assertIn('Đã hủy 1',self.q.confirm_all('owner','group',True))
        with self.q.db() as db:
            states={r['id']:r['state'] for r in db.execute('SELECT * FROM jobs')}
        self.assertEqual(states[old['id']],'expired')
        self.assertEqual(states[ready['id']],'queued')
        self.assertEqual(states[waiting['id']],'cancelled')

    def test_parser(self):
        self.assertEqual(self.p['product'],'0131491005424')
        for bad in [FORM.replace('Số lượng: 1','Số lượng: 0'),FORM+'\nKho xuất: 1',FORM.replace('Kho nhận: 10341','Kho nhận: 645')]:
            with self.assertRaises(ValueError): parse_form(bad)
    def test_duplicate_and_wrong_owner(self):
        j=self.draft(); self.assertEqual(j['id'],self.draft()['id'])
        self.q.confirm(j['id'],'other','group')
        self.q.confirm(j['id'],'owner','other-group')
        self.assertIsNone(self.q.claim())
    def test_concurrent_claim(self):
        j=self.draft(); self.q.confirm(j['id'],'owner','group')
        with ThreadPoolExecutor(max_workers=4) as pool:
            claimed=list(pool.map(lambda _:self.q.claim(),range(4)))
        self.assertEqual(sum(x is not None for x in claimed),1)
    def test_expiry(self):
        j=self.draft()
        with patch('co_flow.time.time',return_value=j['created']+901):
            self.q.confirm(j['id'],'owner','group')
        self.assertIsNone(self.q.claim())
    def test_stale_is_not_replayed(self):
        j=self.draft(); self.q.confirm(j['id'],'owner','group'); job=self.q.claim()
        with patch('co_flow.time.time',return_value=j['created']+1000):
            self.assertIsNone(self.q.claim())
        self.assertEqual(self.q.notifications()[0]['state'],'unknown')
    def test_result_and_reopen(self):
        j=self.draft(); self.q.confirm(j['id'],'owner','group'); job=self.q.claim()
        self.assertFalse(self.q.update(job['id'],job['lease'],'succeeded','00645CO26094531061'))
        self.assertFalse(self.q.update(job['id'],'wrong','submitting'))
        self.assertTrue(self.q.update(job['id'],job['lease'],'submitting'))
        self.assertTrue(self.q.update(job['id'],job['lease'],'succeeded','00645CO26094531061'))
        reopened=Queue(self.q.path)
        self.assertEqual(reopened.notifications()[0]['result'],'00645CO26094531061')
        reopened.mark_notified(j['id']); self.assertEqual(reopened.notifications(),[])

if __name__=='__main__': unittest.main()
