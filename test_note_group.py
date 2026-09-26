import json
import tempfile
import unittest
from pathlib import Path
from co_flow import Queue, NOTE_GROUP
from co_results import note_group_text

class NoteGroupTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.q=Queue(str(Path(self.tmp.name)/'q.db'))
        self.item=dict(source='1',destination='2',product='003',product_name='iPhone',quantity=2,note='')
    def test_partial_success_only_and_requester(self):
        job=dict(id='a',owner='uid',state='unknown',payload=json.dumps(dict(items=[self.item,self.item],requester_name='Tâm')),
                 result=json.dumps([dict(co='123CO456',error=''),dict(co='',error='Không tồn')]))
        text=note_group_text(job)
        self.assertIn('Người yêu cầu: Tâm',text);self.assertIn('Tên sản phẩm: iPhone',text)
        self.assertIn('Số lượng: 2',text);self.assertEqual(text.count('CO: 123CO456'),1)
        self.assertNotIn('Không tồn',text)
    def test_failure_has_no_notice(self):
        self.assertEqual(note_group_text(dict(id='a',owner='uid',state='failed',payload=json.dumps(self.item),result='error')),'')
    def test_outbox_persists_and_no_backfill(self):
        job=self.q.draft('e','uid','chat',dict(self.item,requester_name='Tâm'))
        with self.q.db() as db:db.execute("UPDATE jobs SET state='submitting',lease='l' WHERE id=?",(job['id'],))
        self.assertTrue(self.q.update(job['id'],'l','succeeded','123CO456'))
        q=Queue(self.q.path)
        with q.db() as db:
            rows=db.execute('SELECT * FROM co_note_outbox').fetchall()
            self.assertEqual(len(rows),1);self.assertEqual(rows[0]['destination'],NOTE_GROUP)
            self.assertEqual(rows[0]['delivered'],0)
            db.execute('DELETE FROM co_note_outbox')
        Queue(self.q.path)
        with q.db() as db:self.assertEqual(len(db.execute('SELECT * FROM co_note_outbox').fetchall()),0)
