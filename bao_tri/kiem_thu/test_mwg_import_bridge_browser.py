"""Opt-in isolated integration using locally supplied public MWG JS assets.

Only a loopback server is reachable. No worker queue, login or real CO endpoint.
Set CO_IMPORT_BROWSER_FIXTURES to a directory containing jquery.js, kendo.js
and controller.js (the observed public MWG controller) to run this contract test.
"""
import json,os,tempfile,threading,time,unittest
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
import mac_worker as w
import mwg_import_bridge as b
from bao_tri.kiem_thu.test_mwg_import_bridge import record,body

@unittest.skipUnless(os.environ.get('CO_IMPORT_BROWSER_FIXTURES'),'Opt-in offline import browser test')
class BrowserBridgeTests(unittest.TestCase):
 def test_actual_kendo_and_mwg_handlers_import_accept_without_creating(self):
  from playwright.sync_api import sync_playwright
  assets=Path(os.environ['CO_IMPORT_BROWSER_FIXTURES'])
  source=(assets/'controller.js').read_text()
  controller=source[source.index('StoreChangeOrderManuallyController'):source.index('StoreChangeOrderManuallyITController')]
  # Reuse only the observed import handlers; do not run site initializers or creation.
  begin=controller.index('$("#fileUpload").kendoUpload(')
  end=controller.index(';n.removeItem=',begin)
  upload=controller[begin:end]+';'
  begin=controller.index('n.AcceptExcel=function')
  end=controller.index(';n.ExportExcel=',begin)
  accept=controller[begin:end]+';'
  calls=[];response=body()
  html='''<!doctype html><meta charset="utf-8"><script src="/jquery.js"></script><script src="/kendo.js"></script>
  <input name="__RequestVerificationToken" value="offline-fixture-token"><input id="fileUpload" type="file" name="fileUpload">
  <input role="combobox" aria-label="Vui lòng chọn trạng thái sản phẩm" value="1 - Mới">
  <div id="popup" hidden><span>Dữ liệu trong tập tin excel</span><button id="accept">Đồng ý</button></div>
  <button disabled>Tạo CO</button><table id="main"><tbody></tbody></table><script>
  var n={model:{INVENTORYSTATUSID:1,STORECHANGETYPEID:1,STORECHANGEORDERTYPEID:0,CONTENT:''},strBRANDIDS:'1,2,16'};
  var f={ShowLoading:function(x){document.body.dataset.loading=String(x)}};
  var i=function(fn,ms){setTimeout(fn,ms)};var T=function(x){return x};
  n.ModalImportDataImport={title:function(){},open:function(){document.querySelector('#popup').hidden=false;return this},center:function(){},close:function(){document.querySelector('#popup').hidden=true}};
  '''+upload+accept+'''
  document.querySelector('#accept').onclick=function(){n.AcceptExcel();document.querySelector('#main tbody').innerHTML=n.lstStoreChangeOrder.map(r=>'<tr>'+[1,r.FROMSTOREID,r.TOSTOREID,r.PRODUCTID,r.PRODUCTNAME,r.QUANTITY,0,r.NOTE,0,'',''].map(v=>'<td>'+v+'</td>').join('')+'</tr>').join('')};
  </script>'''
  class Handler(BaseHTTPRequestHandler):
   def log_message(self,*args):pass
   def do_GET(self):
    if self.path=='/storechangeordermanually':data=html.encode();ct='text/html'
    elif self.path in ('/jquery.js','/kendo.js'):data=(assets/self.path[1:]).read_bytes();ct='application/javascript'
    else:self.send_error(404);return
    self.send_response(200);self.send_header('Content-Type',ct);self.end_headers();self.wfile.write(data)
   def do_POST(self):
    calls.append(self.path)
    raw=self.rfile.read(int(self.headers.get('Content-Length',0)))
    if self.path!='/StoreChangeOrderManually/ImportExcel':self.send_error(403);return
    # Require real browser session and origin headers, unlike the old Node request.
    if (self.headers.get('Origin')!=origin or
        self.headers.get('Referer')!=origin+'/storechangeordermanually' or
        self.headers.get('Cookie')!='fixture_session=authenticated'):
     self.send_error(403);return
    self.server.upload=raw;self.server.token=self.headers.get('X-XSRF-TOKEN')
    scenario=getattr(self.server,'scenario','ok')
    if scenario=='timeout':time.sleep(.3)
    self.send_response(401 if scenario=='unauthorized' else 200)
    self.send_header('Content-Type','application/json');self.end_headers()
    try:self.wfile.write(b'not-json' if scenario=='invalid_json' else json.dumps(response).encode())
    except (BrokenPipeError,ConnectionResetError):pass
  server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
  thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
  origin='http://127.0.0.1:'+str(server.server_port)
  try:
   with tempfile.TemporaryDirectory() as tmp,sync_playwright() as pw:
    output=Path(tmp)/'fixture.xlsx';output.write_bytes(b'isolated fixture')
    browser=pw.chromium.launch(channel='chrome',headless=True)
    try:
     page=browser.new_page();page.route('**/*',lambda r:r.continue_() if r.request.url.startswith(origin+'/') else r.abort())
     page.context.add_cookies([{'name':'fixture_session','value':'authenticated','url':origin}])
     page.goto(origin+'/storechangeordermanually');errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
     with patch.object(b,'ORIGIN',origin),patch.object(b,'IMPORT_URL',origin+'/StoreChangeOrderManually/ImportExcel'),patch.object(w,'progress'),patch.dict(os.environ,{'CO_IMPORT_TRANSPORT':'auto'}):
      responses=[];popup=w.import_with_retry(page,{'id':'a'*10,'mode':'preview','payload':dict(record(),status='Mới')},output,[],responses=responses,records=[record()])
     self.assertEqual(w.received_import_errors(responses,[record()]),[''])
     self.assertTrue(popup.is_visible());self.assertEqual(page.locator('#main td').count(),0)
     page.get_by_role('button',name='Đồng ý',exact=True).click()
     self.assertFalse(popup.is_visible());self.assertEqual(page.locator('#main td').count(),11)
     self.assertEqual(page.locator('#main td').nth(3).inner_text(),record()['product'])
     self.assertEqual(page.locator('#main td').nth(7).inner_text(),record()['note'])
     self.assertEqual(page.locator('body').get_attribute('data-loading'),'false')
     self.assertEqual(calls,['/StoreChangeOrderManually/ImportExcel'])
     self.assertEqual(server.token,'offline-fixture-token');self.assertIn(b'name="fileUpload"',server.upload)
     self.assertEqual(errors,[])
     self.assertTrue(page.get_by_role('button',name='Tạo CO').is_disabled())
     # Failed uploads must clear the loader, open no popup, and never replay.
     for scenario in ('unauthorized','invalid_json','timeout','network'):
      server.scenario=scenario
      page.goto(origin+'/storechangeordermanually')
      before=len(calls)
      if scenario=='network':page.route('**/ImportExcel',lambda route:route.abort())
      with patch.object(b,'ORIGIN',origin),patch.object(b,'IMPORT_URL',origin+'/StoreChangeOrderManually/ImportExcel'),patch.object(b,'IMPORT_TIMEOUT_MS',100 if scenario=='timeout' else 15000):
       with self.assertRaises(ValueError):b.import_preview(page,output,[record()],'1')
      self.assertEqual(len(calls),before+(0 if scenario=='network' else 1))
      self.assertEqual(page.locator('body').get_attribute('data-loading'),'false')
      self.assertFalse(page.locator('#popup').is_visible())
      self.assertEqual(page.locator('#main td').count(),0)
      self.assertTrue(page.get_by_role('button',name='Tạo CO').is_disabled())
      self.assertEqual(page.evaluate('window.__taoImportBridgeV1===undefined'),True)
    finally:browser.close()
  finally:server.shutdown();server.server_close();thread.join(timeout=2)
