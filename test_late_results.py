import json
import tempfile
import unittest
from pathlib import Path
from co_flow import Queue


class LateResultTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.q=Queue(str(Path(tmp.name)/'q.db'))
        records=[dict(source=str(n),destination='447',product='0131491005415',quantity=1,product_name='iPhone') for n in (1,2)]
        self.job=self.q.draft('event','owner','chat',dict(items=records,requester_name='Tâm'))
        with self.q.db() as db:
            db.execute("UPDATE jobs SET state='submitting',lease='lease' WHERE id=?",(self.job['id'],))
        self.previous=[dict(co='1CO123',error='',state='succeeded'),dict(co='',error='Waiting',state='unknown')]
        self.final=[self.previous[0],dict(co='2CO123',error='',state='succeeded')]
        self.assertTrue(self.update('unknown',self.previous))

    def update(self,state,rows,lease='lease'):
        return self.q.update(self.job['id'],lease,state,json.dumps(rows))

    def test_late_success_preserves_evidence_and_only_notifies_new_co(self):
        messages=[]
        def send(text):messages.append(text);return True
        self.q.reply_notes('first',send)
        self.assertIn('1CO123',messages[-1])
        self.assertTrue(self.update('succeeded',self.final))
        self.assertTrue(self.update('succeeded',self.final))
        with self.q.db() as db:
            job=db.execute('SELECT * FROM jobs WHERE id=?',(self.job['id'],)).fetchone()
            self.assertEqual(job['state'],'succeeded');self.assertEqual(job['notified'],0)
            self.assertEqual(json.loads(json.loads(job['payload'])['late_reconciliation']['previous_result']),self.previous)
        self.q.reply_notes('second',send)
        self.assertIn('2CO123',messages[-1]);self.assertNotIn('1CO123',messages[-1])
        self.q.reply_notes('third',send)
        self.assertIn('Chưa có CO',messages[-1])

    def test_wrong_lease_changed_co_and_incomplete_evidence_are_rejected(self):
        self.assertFalse(self.update('succeeded',self.final,lease='wrong'))
        self.assertFalse(self.update('succeeded',[dict(self.final[0],co='9CO123'),self.final[1]]))
        self.assertFalse(self.update('succeeded',self.previous))
        self.assertFalse(self.update('failed',[dict(co='',error='Failed',state='failed')]*2))
        self.assertEqual(self.q.result_status(self.job['id'],'lease')['state'],'unknown')

    def test_cancelled_jobs_are_not_revived(self):
        with self.q.db() as db:
            db.execute("UPDATE jobs SET state='cancelled' WHERE id=?",(self.job['id'],))
        self.assertFalse(self.update('succeeded',self.final))

    def test_verified_failures_release_unknown_without_claiming_a_co(self):
        previous=[dict(co='',error='Waiting',state='unknown')]*2
        with self.q.db() as db:
            db.execute('UPDATE jobs SET result=? WHERE id=?',(json.dumps(previous),self.job['id']))
        self.assertTrue(self.update('failed',[dict(co='',error='Không đủ tồn',state='failed')]*2))
        self.assertEqual(self.q.result_status(self.job['id'],'lease')['state'],'failed')


if __name__=='__main__':unittest.main()
