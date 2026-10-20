"""Default intake must not call the API prepare callback that failed live."""
import os,unittest
from unittest.mock import MagicMock,patch
import mac_worker as w
import mwg_import_bridge as b

class DefaultNativeImportTests(unittest.TestCase):
 def setUp(self):
  self.page=MagicMock();self.page.get_by_text.return_value.is_visible.return_value=True
  self.job={'id':'a'*10,'mode':'preview','payload':{'status':'Mới'}}
  self.records=[{'source':'844','destination':'1652','product':'0131491005411','quantity':2,'note':''},
                {'source':'1574','destination':'374','product':'0131491005415','quantity':1,'note':''}]
 def test_two_row_default_uses_native_upload_once_without_api_or_reload(self):
  environment={k:v for k,v in os.environ.items() if k!='CO_IMPORT_TRANSPORT'}
  responses=[]
  with patch.dict(os.environ,environment,clear=True),patch.object(b,'import_preview',side_effect=RuntimeError('prepare/browser_error')) as bridge,patch.object(w,'upload_excel') as upload,patch.object(w,'progress'):
   popup=w.import_with_retry(self.page,self.job,'fixture.xlsx',[],responses=responses,records=self.records)
  bridge.assert_not_called();upload.assert_called_once_with(self.page,'fixture.xlsx')
  self.page.reload.assert_not_called();self.assertIs(popup,self.page.get_by_text.return_value)
 def test_native_failure_never_tries_api_as_an_implicit_fallback(self):
  environment={k:v for k,v in os.environ.items() if k!='CO_IMPORT_TRANSPORT'}
  with patch.dict(os.environ,environment,clear=True),patch.object(b,'import_preview') as bridge,patch.object(w,'upload_excel',side_effect=RuntimeError('upload rejected')) as upload,patch.object(w,'progress'):
   with self.assertRaisesRegex(RuntimeError,'upload rejected'):
    w.import_with_retry(self.page,self.job,'fixture.xlsx',[],responses=[],records=self.records)
  bridge.assert_not_called();upload.assert_called_once();self.page.reload.assert_not_called()
 def test_api_remains_explicitly_selectable_for_isolated_contract_tests(self):
  self.page.get_by_role.return_value.input_value.return_value='1 - Mới'
  with patch.dict(os.environ,{'CO_IMPORT_TRANSPORT':'api'}),patch.object(b,'import_preview',return_value=b.ImportResponse({})) as bridge,patch.object(w,'upload_excel') as upload,patch.object(w,'progress'):
   w.import_with_retry(self.page,self.job,'fixture.xlsx',[],responses=[],records=self.records)
  bridge.assert_called_once();upload.assert_not_called();self.page.reload.assert_not_called()
 def test_confirmation_stage_never_reimports_by_native_path(self):
  self.job['mode']='create'
  with patch.dict(os.environ,{'CO_IMPORT_TRANSPORT':'ui'}),patch.object(w,'upload_excel') as upload,patch.object(b,'import_preview') as bridge:
   with self.assertRaisesRegex(RuntimeError,'chỉ dùng trước'):
    w.import_with_retry(self.page,self.job,'fixture.xlsx',[],responses=[],records=self.records)
  upload.assert_not_called();bridge.assert_not_called();self.page.reload.assert_not_called()
