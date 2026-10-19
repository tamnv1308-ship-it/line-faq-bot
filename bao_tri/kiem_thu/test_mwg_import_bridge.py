import base64,json,tempfile,unittest
from pathlib import Path
from unittest.mock import MagicMock,patch
import mac_worker as w
import mwg_import_bridge as b

def record():return dict(source='3945',destination='447',product='0131491005415',quantity=1,note='QL cho hàng')
def body():return {'Success':True,'Data':{'Data':json.dumps([dict(FROMSTOREID=3945,TOSTOREID=447,PRODUCTID='0131491005415',QUANTITY=1,NOTE='QL cho hàng',INVENTORYSTATUSID=1,STORECHANGEORDERTYPEID=0,ISURGENT=0,PRODUCTNAME='Mô phỏng',ISERROR=False,ERRORNOTE='')]),'strFileName':'fixture.xlsx','strFilePath':'test-only'}}
def params():return {'data':dict(INVENTORYSTATUSID=1,STORECHANGETYPEID=1,STORECHANGEORDERTYPEID=0,BRANDID='1,2,16',CONTENT=''),'headers':{'X-XSRF-TOKEN':'fixture-token'}}

class BridgeTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  self.file=Path(self.tmp.name)/'fixture.xlsx';self.file.write_bytes(b'offline')
  self.page=MagicMock();self.page.url=b.ORIGIN+'/storechangeordermanually'
  self.page.evaluate.side_effect=[{'url':b.IMPORT_URL},params(),{'status':200,'body':body()},True]
 def run_import(self):return b.import_preview(self.page,self.file,[record()],'1')
 def test_one_import_no_create_reload_or_button(self):
  self.assertEqual(self.run_import().json(),body())
  sends=[c for c in self.page.evaluate.call_args_list if c.args[0]==b.SEND]
  self.assertEqual(len(sends),1);kw=sends[0].args[1]
  self.assertEqual(kw['url'],b.IMPORT_URL);self.assertEqual(kw['timeout'],15000)
  self.assertEqual(base64.b64decode(kw['file']),b'offline')
  self.page.context.request.post.assert_not_called()
  self.page.reload.assert_not_called();self.page.get_by_role.assert_not_called()
 def test_unsupported_component_sends_nothing(self):
  self.page.evaluate.side_effect=[None]
  with self.assertRaises(b.BridgeUnavailable):self.run_import()
  self.page.context.request.post.assert_not_called();self.assertEqual(self.page.evaluate.call_count,1)
 def test_foreign_endpoint_not_used(self):
  self.page.evaluate.side_effect=[{'url':'https://example.com/import'}]
  with self.assertRaises(b.BridgeUnavailable):self.run_import()
  self.page.context.request.post.assert_not_called()
 def test_wrong_page_not_used(self):
  self.page.url='https://example.com'
  with self.assertRaises(b.BridgeUnavailable):self.run_import()
  self.page.evaluate.assert_not_called()
 def test_wrong_form_parameters_rejected(self):
  for field,value in [('INVENTORYSTATUSID',2),('BRANDID','1'),('STORECHANGETYPEID',3),('STORECHANGEORDERTYPEID',155),('CONTENT','other')]:
   with self.subTest(field=field):
    p=params();p['data'][field]=value
    with self.assertRaises(ValueError):b.parameters(p,'1')
  for value in ('',None,'bad\r\nheader'):
   p=params();p['headers']['X-XSRF-TOKEN']=value
   with self.assertRaises(ValueError):b.parameters(p,'1')
 def test_timeout_not_retried_or_leaked(self):
  self.page.evaluate.side_effect=[{'url':b.IMPORT_URL},params(),TimeoutError('secret headers'),None]
  with self.assertRaises(RuntimeError) as cm:self.run_import()
  self.assertNotIn('secret',str(cm.exception));self.page.context.request.post.assert_not_called()
  self.assertEqual(sum(c.args[0]==b.SEND for c in self.page.evaluate.call_args_list),1)
  self.assertEqual(self.page.evaluate.call_args.args[0],b.ABORT)
 def test_http_error_not_applied(self):
  self.page.evaluate.side_effect=[{'url':b.IMPORT_URL},params(),{'status':401},None]
  with self.assertRaisesRegex(ValueError,'401'):self.run_import()
  self.assertNotIn(b.FINISH,[c.args[0] for c in self.page.evaluate.call_args_list])
 def test_malformed_json_not_leaked(self):
  self.page.evaluate.side_effect=[{'url':b.IMPORT_URL},params(),{'error':'invalid_json'},None]
  with self.assertRaises(ValueError) as cm:self.run_import()
  self.assertNotIn('private',str(cm.exception))
 def test_browser_timeout_network_page_change_never_retried(self):
  for code in ('timeout','network','page_changed'):
   with self.subTest(code=code):
    self.page.reset_mock();self.page.evaluate.side_effect=[{'url':b.IMPORT_URL},params(),{'error':code},None]
    with self.assertRaises(ValueError):self.run_import()
    self.assertEqual(sum(c.args[0]==b.SEND for c in self.page.evaluate.call_args_list),1)
    self.assertNotIn(b.FINISH,[c.args[0] for c in self.page.evaluate.call_args_list])
    self.page.reload.assert_not_called();self.page.context.request.post.assert_not_called()
 def test_diagnostics_do_not_expose_raw_exception(self):
  for text,code in [('SSL certificate secret_cookie','certificate'),('net::ERR_CONNECTION_RESET private_token','network'),('Target page has been closed secret','browser_closed'),('private headers body','browser_error')]:
   self.assertEqual(b.error_code(RuntimeError(text)),code)
 def test_mismatched_rows_rejected(self):
  for field,value in [('FROMSTOREID',42),('PRODUCTID','0131491005416'),('QUANTITY',3),('INVENTORYSTATUSID',2),('NOTE','other'),('STORECHANGEORDERTYPEID',155),('ISURGENT',1)]:
   with self.subTest(field=field):
    data=body();rows=json.loads(data['Data']['Data']);rows[0][field]=value;data['Data']['Data']=json.dumps(rows)
    with self.assertRaises(ValueError):b.validate_rows(data,[record()],'1')
 def test_business_error_preserved_for_worker_filter(self):
  data=body();rows=json.loads(data['Data']['Data']);rows[0].update(ISERROR=True,ERRORNOTE='Không có hàng',INVENTORYSTATUSID=None);data['Data']['Data']=json.dumps(rows)
  self.assertEqual(b.validate_rows(data,[record()],'1'),data)
  from mwg_import_api import import_row_errors
  self.assertEqual(import_row_errors(data,[record()]),['Không có hàng'])
 def test_reordered_five_rows_and_mixed_errors_keep_identity(self):
  expected=[dict(record(),source=str(100+n)) for n in range(5)]
  rows=[]
  for n,r in enumerate(expected):
   row=json.loads(body()['Data']['Data'])[0];row['FROMSTOREID']=int(r['source'])
   if n==2:row.update(ISERROR=True,ERRORNOTE='Dòng lỗi riêng')
   rows.append(row)
  data=body();data['Data']['Data']=json.dumps(list(reversed(rows)))
  out=b.validate_rows(data,expected,'1')
  from mwg_import_api import import_row_errors
  self.assertEqual(import_row_errors(out,expected),['','','Dòng lỗi riêng','',''])
 def test_duplicate_response_rows_rejected(self):
  data=body();row=json.loads(data['Data']['Data'])[0];data['Data']['Data']=json.dumps([row,row])
  with self.assertRaises(ValueError):b.validate_rows(data,[record(),dict(record(),source='200')],'1')
 def test_array_normalized_for_web_callback(self):
  data=body();data['Data']['Data']=json.loads(data['Data']['Data'])
  self.assertIsInstance(b.validate_rows(data,[record()],'1')['Data']['Data'],str)
 def test_bridge_changed_after_upload_not_resubmitted(self):
  self.page.evaluate.side_effect=[{'url':b.IMPORT_URL},params(),{'status':200,'body':body()},RuntimeError('changed'),None]
  with self.assertRaises(RuntimeError):self.run_import()
  self.page.context.request.post.assert_not_called()
  self.assertEqual(sum(c.args[0]==b.SEND for c in self.page.evaluate.call_args_list),1)

class WorkerChoiceTests(unittest.TestCase):
 def setUp(self):
  self.page=MagicMock();self.page.get_by_role.return_value.input_value.return_value='1 - Mới'
  self.page.get_by_text.return_value.is_visible.return_value=True
  self.job={'id':'a'*10,'mode':'preview','payload':dict(record(),status='Mới')}
 def run_import(self):return w.import_with_retry(self.page,self.job,'file',[],responses=[],records=[record()])
 def test_api_skips_chooser_and_reload(self):
  with patch.dict(w.os.environ,{'CO_IMPORT_TRANSPORT':'auto'}),patch.object(b,'import_preview',return_value=b.ImportResponse(body())) as api,patch.object(w,'upload_excel') as ui:
   self.run_import()
  api.assert_called_once();ui.assert_not_called();self.page.reload.assert_not_called()
 def test_unsupported_before_request_uses_ui(self):
  with patch.dict(w.os.environ,{'CO_IMPORT_TRANSPORT':'auto'}),patch.object(b,'import_preview',side_effect=b.BridgeUnavailable),patch.object(w,'upload_excel') as ui,patch.object(w,'progress'):
   self.run_import()
  ui.assert_called_once();self.page.reload.assert_not_called()
 def test_api_error_never_falls_back(self):
  with patch.dict(w.os.environ,{'CO_IMPORT_TRANSPORT':'auto'}),patch.object(b,'import_preview',side_effect=RuntimeError('failure')),patch.object(w,'upload_excel') as ui:
   with self.assertRaises(RuntimeError):self.run_import()
  ui.assert_not_called();self.page.reload.assert_not_called()
 def test_create_cannot_upload_again(self):
  self.job['mode']='create'
  with patch.object(b,'import_preview') as api:
   with self.assertRaisesRegex(RuntimeError,'chỉ dùng trước'):self.run_import()
  api.assert_not_called()
 def test_ui_override_skips_api(self):
  with patch.dict(w.os.environ,{'CO_IMPORT_TRANSPORT':'ui'}),patch.object(b,'import_preview') as api,patch.object(w,'upload_excel') as ui,patch.object(w,'progress'):
   self.run_import()
  api.assert_not_called();ui.assert_called_once()
