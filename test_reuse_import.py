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
        with patch.object(worker,'data_rows',side_effect=[[(None,row)],[(None,result)]]),patch.object(worker,'progress'),patch.object(worker,'report') as report,patch.object(worker,'upload_excel') as upload:
            worker.process(page,dict(id='abc',lease='lease',payload=data,mode='create'),'abc')
        page.reload.assert_not_called();page.goto.assert_not_called();upload.assert_not_called()
        self.assertEqual([c.args[1] for c in report.call_args_list],['submitting','succeeded'])
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
