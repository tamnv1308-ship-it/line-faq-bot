import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch
import mac_worker as worker
from co_flow import Queue

class ReuseTests(unittest.TestCase):
    def test_confirm_reuses_import_without_navigation_or_upload(self):
        data=dict(source='123',destination='456',product='00123',quantity=1,note='',status='Mới',product_name='Phone')
        row=['1','123 - Source','456 - Dest','00123','Phone','1','0','','','','']
        result=row.copy();result[9]='00123CO2609001'
        page=MagicMock();page.url=worker.URL
        page.get_by_role.return_value.input_value.return_value='1 - Mới'
        page.locator.return_value.get_attribute.return_value='brands'
        page.locator.return_value.all_text_contents.return_value=['1 - thegioididong','2 - dienmayxanh','16 - TopZone']
        guard=worker.RecoveryGuard(page)
        page.get_by_role.return_value.click.side_effect=lambda:self.assertEqual(guard.uncertain_job,'abc')
        with patch.object(worker,'wait_matched_rows',return_value=[row]),patch.object(worker,'data_rows',return_value=[(None,result)]),patch.object(worker,'progress'),patch.object(worker,'report') as report,patch.object(worker,'upload_excel') as upload:
            worker.process(page,dict(id='abc',lease='lease',payload=data,mode='create'),'abc',guard=guard)
        page.reload.assert_not_called();page.goto.assert_not_called();upload.assert_not_called()
        self.assertEqual([c.args[1] for c in report.call_args_list],['submitting','succeeded'])
        self.assertIsNone(guard.uncertain_job)
    def test_submission_timeout_is_unknown_without_retry(self):
        data=dict(source='123',destination='456',product='00123',quantity=1,note='',status='Mới',product_name='Phone')
        row=['1','123 - Source','456 - Dest','00123','Phone','1','0','','','','']
        clock=[0.0]
        page=MagicMock();page.url=worker.URL
        page.wait_for_timeout.side_effect=lambda ms:clock.__setitem__(0,clock[0]+ms/1000)
        page.get_by_role.return_value.input_value.return_value='1 - Mới'
        page.locator.return_value.get_attribute.return_value='brands'
        page.locator.return_value.all_text_contents.return_value=['1 - thegioididong','2 - dienmayxanh','16 - TopZone']
        guard=worker.RecoveryGuard(page)
        with patch.object(worker,'wait_matched_rows',return_value=[row]),patch.object(worker.time,'monotonic',side_effect=lambda:clock[0]),patch.object(worker,'ROOT') as root,patch.object(worker,'data_rows',return_value=[(None,row)]),patch.object(worker,'progress'),patch.object(worker,'report') as report,patch.object(worker,'upload_excel') as upload:
            (root/'pending.json').exists.return_value=False
            worker.process(page,dict(id='abc',lease='lease',payload=data,mode='create'),'abc',guard=guard)
        page.reload.assert_not_called();page.goto.assert_not_called();upload.assert_not_called()
        self.assertEqual([c.args[1] for c in report.call_args_list],['submitting','unknown'])
        self.assertGreaterEqual(clock[0],15)
        self.assertLess(clock[0],worker.CREATE_RESULT_WAIT_SECONDS+0.4)
        page.get_by_role.return_value.click.assert_called_once()
        self.assertEqual(guard.uncertain_job,'abc')
    def test_new_request_reuses_current_page(self):
        page=MagicMock();page.url=worker.URL
        with tempfile.TemporaryDirectory() as tmp,patch.object(worker,'ROOT',Path(tmp)),patch.object(worker,'progress'),patch.object(worker,'prepare_import_controls',side_effect=RuntimeError('stop before import')),patch.object(worker,'report'):
            worker.process(page,dict(id='new',payload={},mode='preview'))
        page.reload.assert_not_called();page.goto.assert_not_called()

    def test_missing_prepared_page_fails_without_creating(self):
        page=MagicMock()
        with tempfile.TemporaryDirectory() as tmp,patch.object(worker,'ROOT',Path(tmp)),patch.object(worker,'progress'),patch.object(worker,'report') as report:
            worker.process(page,dict(id='abc',lease='lease',payload={'product_name':'Phone'},mode='create'))
        self.assertEqual(report.call_args.args[1],'failed');page.reload.assert_not_called()
    def test_queue_preserves_prepared_row_until_confirm_or_cancel(self):
        with tempfile.TemporaryDirectory() as tmp:
            q=Queue(str(Path(tmp)/'q.db'));p=dict(source='1',destination='2',product='003',quantity=1,note='')
            j=q.draft('a','o','c',p,True);w=q.claim(True);q.update(j['id'],w['lease'],'preview_ready','Phone')
            other=q.draft('b','o','c',p,True)
            self.assertIsNone(q.claim(True,j['id']))
            q.confirm(j['id'],'o','c')
            self.assertEqual(q.claim(True,j['id'])['id'],j['id'])
    def test_cancel_and_expiry_release_prepared_row(self):
        for expired in (False,True):
            with tempfile.TemporaryDirectory() as tmp:
                q=Queue(str(Path(tmp)/'q.db'));p=dict(source='1',destination='2',product='003',quantity=1,note='')
                j=q.draft('a','o','c',p,True);w=q.claim(True);q.update(j['id'],w['lease'],'preview_ready','Phone')
                if expired:
                    with q.db() as db:db.execute('UPDATE jobs SET created=? WHERE id=?',(time.time()-901,j['id']))
                else:q.confirm(j['id'],'o','c',True)
                self.assertEqual(q.claim(True,j['id']),{'release_preview':True})
if __name__=='__main__':unittest.main()
