import json
import tempfile
import unittest
from pathlib import Path
from co_flow import Queue, preview_text

class PreviewTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.q=Queue(str(Path(self.tmp.name)/'q.db'))
        self.p=dict(source='123',destination='456',product='00123',quantity=1,note='',status='Mới')
    def draft(self):
        return self.q.draft('evt','owner','chat',self.p,check_product=True)
    def test_preview_cannot_create_before_confirmation(self):
        j=self.draft();self.assertIsNone(self.q.claim())
        self.q.confirm(j['id'],'owner','chat')
        work=self.q.claim(True);self.assertEqual(work['mode'],'preview')
        self.assertFalse(self.q.update(j['id'],work['lease'],'submitting'))
        self.assertTrue(self.q.update(j['id'],work['lease'],'preview_ready','Product MWG'))
        self.assertTrue(self.q.update(j['id'],work['lease'],'preview_ready','Product MWG'))
        self.assertIsNone(self.q.claim(True))
        notice=self.q.notifications()[0];self.assertIn('Product MWG',preview_text(notice))
        self.q.mark_notified(j['id'],'draft')
        self.q.confirm(j['id'],'other','chat');self.assertIsNone(self.q.claim(True))
        self.q.confirm(j['id'],'owner','chat');self.assertIsNone(self.q.claim())
        work=self.q.claim(True);self.assertEqual(work['mode'],'create')
        self.assertEqual(work['payload']['product_name'],'Product MWG')
        self.assertTrue(self.q.update(j['id'],work['lease'],'submitting'))
        self.assertTrue(self.q.update(j['id'],work['lease'],'failed','No stock'))
        self.assertEqual(len(self.q.notifications()),1)
    def test_cancel_and_invalid_lease(self):
        j=self.draft();self.q.cancel_waiting('owner','chat');self.assertIsNone(self.q.claim(True))
        self.assertFalse(self.q.update(j['id'],'wrong','preview_ready','x'))
    def test_all_confirms_verified_preview(self):
        j=self.draft();w=self.q.claim(True)
        self.q.update(j['id'],w['lease'],'preview_ready','MWG name')
        self.q.confirm_all('owner','chat');self.assertIsNone(self.q.claim())
        self.assertEqual(self.q.claim(True)['mode'],'create')
if __name__=='__main__':unittest.main()
