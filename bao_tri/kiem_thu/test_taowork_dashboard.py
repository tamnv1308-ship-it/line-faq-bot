"""Cloud password identity, atomic migration, and delivery protections; no network."""
import copy
import gzip
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from flask import Flask
from cloud_passwords import PasswordAuth
import taowork_accounts as accounts
import taowork_dashboard as dashboard
import taowork_runtime as runtime

BASE='https://test.example'
class DashboardTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
  env=patch.dict(os.environ,{'TAOWORK_DATA_DIR':str(self.root),'CO_WORKER_TOKEN':'T'*40,'CO_ENABLED':'1','RENDER':''});env.start();self.addCleanup(env.stop)
  self.app=Flask(__name__,static_folder=None);self.app.testing=True;accounts.install(self.app);self.client=self.app.test_client()
  self.auth=PasswordAuth(self.root/'auth');self.auth.setup('cloud-test','test-only-password-2026');self.csrf=''
  common=dict(schema=1,cutoff='2026-11-01',source_as_of='2026-11-02T13:00:00+07:00',groups=[{'id':x} for x in sorted(dashboard.GROUPS)])
  self.payload=dict(schema=1,analytics=dict(common,daily=[{'day':'2026-11-01'}]),revenue=dict(common,unit='million_vnd',periods=[{'id':'2026-11'}]))
 def call(self,path,method='GET',data=None,headers=None):
  return self.client.open('/tao/dashboard/'+path,method=method,json=data,base_url=BASE,headers={'Origin':BASE,**(headers or {})})
 def login(self):
  response=self.call('auth/login','POST',dict(username='cloud-test',password='test-only-password-2026',remember=False));self.assertEqual(response.status_code,200)
  self.csrf=self.call('auth/session').json['csrf'];return response
 def upload(self,payload=None,token='T'*40):
  return self.call('api/snapshot','POST',payload or self.payload,{'Authorization':'Bearer '+token})
 def test_no_line_identity_dependency_and_anonymous_cannot_read(self):
  for suffix in ('api/revenue','assets/app.js','api/runtime'):
   self.assertEqual(self.call(suffix).status_code,401)
  self.assertEqual(self.call('').status_code,303)
  self.client.set_cookie('__Host-tao_session','x'*43,domain='test.example')
  self.assertEqual(self.call('api/revenue').status_code,401)
  with self.call('login/') as r:self.assertEqual(r.status_code,200);self.assertNotIn(b'static.line-scdn',r.data)
 def test_password_login_cookie_csrf_logout_and_wrong_origin(self):
  self.assertEqual(self.call('auth/login','POST',{'username':'cloud-test','password':'wrong','remember':False}).status_code,401)
  response=self.login();cookie=response.headers['Set-Cookie'];self.assertIn('__Host-taowork_session=',cookie);self.assertIn('Secure',cookie);self.assertIn('HttpOnly',cookie)
  self.assertEqual(self.call('auth/logout','POST',{}).status_code,403)
  self.assertEqual(self.call('auth/logout','POST',{}, {'X-Tao-Auth-CSRF':self.csrf}).status_code,200)
  self.assertFalse(self.call('auth/session').json['authenticated'])
  self.assertEqual(self.call('auth/login','POST',{}, {'Origin':'https://other.example'}).status_code,403)
 def test_snapshot_migration_gzip_and_owner_read(self):
  self.assertEqual(self.upload(token='wrong').status_code,401);self.assertEqual(self.upload().status_code,200);self.login()
  response=self.call('api/revenue',headers={'Accept-Encoding':'gzip'})
  self.assertEqual(response.headers['Content-Encoding'],'gzip');self.assertEqual(json.loads(gzip.decompress(response.data)),self.payload['revenue'])
  self.assertEqual((self.root/'snapshot.json.gz').stat().st_mode&0o777,0o600)
 def test_invalid_or_old_data_keeps_last_success(self):
  self.assertEqual(self.upload().status_code,200);before=(self.root/'snapshot.json.gz').read_bytes()
  p=copy.deepcopy(self.payload);p['revenue']['cutoff']='2026-10-31';self.assertEqual(self.upload(p).status_code,409)
  p=copy.deepcopy(self.payload);p['revenue']['password']='forbidden';self.assertEqual(self.upload(p).status_code,409)
  self.assertEqual((self.root/'snapshot.json.gz').read_bytes(),before)
  with patch.object(dashboard,'MAX_BYTES',10):self.assertEqual(self.upload().status_code,413)
 def test_bootstrap_cannot_replace_existing_account(self):
  d={k:v for k,v in self.auth.account().items() if k in {'version','username','kdf','salt','hash'}}
  header={'Authorization':'Bearer '+'T'*40};self.assertEqual(self.call('api/bootstrap-account','POST',d,header).status_code,200)
  d['hash']='a'*64;self.assertEqual(self.call('api/bootstrap-account','POST',d,header).status_code,409)
 def test_asset_allowlist_and_no_sales_in_public_code(self):
  self.login()
  self.assertEqual(self.call('assets/snapshot.json.gz').status_code,404)
  code=(Path(dashboard.__file__).parent/'taowork_assets/app.js').read_text();self.assertNotIn('window.TAO_BUSINESS_DATA =',code);self.assertNotIn('window.TAO_REVENUE_GZIP =',code)
 def test_action_is_idempotent_and_unknown_blocks_new_send(self):
  self.login();runtime.initialize();runtime.atomic(self.root/'runtime-enabled.json',{'enabled':True})
  data={'action':'report.run','request_id':'a'*32};headers={'X-App-CSRF':self.csrf}
  self.assertEqual(self.call('api/action','POST',data).status_code,403)
  with patch.object(runtime.threading,'Thread') as thread:
   self.assertEqual(self.call('api/action','POST',data,headers).status_code,202)
   self.assertEqual(self.call('api/action','POST',data,headers).status_code,202);self.assertEqual(thread.call_count,1)
   self.assertEqual(self.call('api/action','POST',dict(data,request_id='b'*32),headers).status_code,409)
  with runtime.state_db(self.root) as db:db.execute("UPDATE actions SET state='unknown'")
  self.assertEqual(self.call('api/action','POST',dict(data,request_id='b'*32),headers).status_code,409)
 def test_upload_rejects_paths_and_preserves_chunks(self):
  body=b'{"schema":1}';digest=hashlib.sha256(body).hexdigest();headers={'Authorization':'Bearer '+'T'*40,'X-Content-SHA256':digest,'X-Upload-SHA256':digest,'X-Total-Size':str(len(body))}
  def send(name):return self.client.post('/tao/dashboard/api/import/'+name+'/0',data=body,headers=headers,base_url=BASE)
  self.assertEqual(send('unknown').status_code,409);self.assertEqual(send('calendar').status_code,200);self.assertEqual(send('calendar').status_code,200)
  self.assertEqual((self.root/'settings/apple-calendar.json').read_bytes(),body)
 def test_no_mac_snapshot_overwrite_after_activation(self):
  runtime.atomic(self.root/'runtime-enabled.json',{'enabled':True});self.assertEqual(self.upload().status_code,409)
 def test_cloud_uses_only_api_export(self):
  code=(Path(runtime.__file__).parent/'cloud_report/bot/report_bot.py').read_text();self.assertIn('if not api_export: raise',code)
  ui=(Path(runtime.__file__).parent/'taowork_assets/index.html').read_text();self.assertNotIn('BOT trên Mac',ui);self.assertNotIn('Công cụ CO',ui)
 def test_acceptance_requests_return_async_and_do_not_start_duplicates(self):
  header={'Authorization':'Bearer '+'T'*40}
  with patch.object(runtime.threading,'Thread') as thread,patch.object(runtime,'invoke') as invoke:
   self.assertEqual(self.call('api/bootstrap-verify/dry-run','POST',{},header).status_code,202)
   self.assertEqual(self.call('api/bootstrap-verify/dry-run','POST',{},header).status_code,202)
   self.assertEqual(thread.call_count,1);invoke.assert_not_called()
 def test_successful_delivery_survives_publish_failure_and_unknown_is_preserved(self):
  runtime.initialize();jid='c'*32
  with runtime.state_db(self.root) as db:db.execute('INSERT INTO actions VALUES (?,?,?,?,NULL)',(jid,'report.run','running',1))
  runtime.atomic(self.root/'report/.private/last-manual-run.json',{'request_id':jid,'state':'sent'})
  with patch.object(runtime,'invoke',return_value=1):runtime.run_action(self.root,'report.run',jid)
  with runtime.state_db(self.root) as db:self.assertEqual(db.execute('SELECT state FROM actions').fetchone()[0],'done')
  runtime.atomic(self.root/'report/.private/last-manual-run.json',{'request_id':jid,'state':'sending'})
  with patch.object(runtime,'invoke',side_effect=TimeoutError):runtime.run_action(self.root,'report.run',jid)
  with runtime.state_db(self.root) as db:self.assertEqual(db.execute('SELECT state FROM actions').fetchone()[0],'unknown')

 def test_cloud_history_serves_published_data_without_mac_and_rejects_snapshot(self):
  self.assertEqual(self.upload().status_code,200)
  history=self.root/'report/.private/sales-history.sqlite3';history.parent.mkdir(parents=True,exist_ok=True);history.touch()
  self.login()
  with patch('cloud_analytics.revenue_report.load_revenue',side_effect=AssertionError('HTTP must not rebuild history')):
   response=self.call('api/revenue');self.assertEqual(response.status_code,200);self.assertEqual(response.json,self.payload['revenue'])
   self.assertFalse(self.call('api/status').json['mac_required'])
  self.assertEqual(self.upload().status_code,409)
