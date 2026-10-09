import unittest,tempfile,json,time
from pathlib import Path
from datetime import datetime
from co_flow import Queue,PRIVATE_CO_OWNER
from co_summary import period,aggregate,cleanup,TZ
class SummaryTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.q=Queue(self.tmp.name+'/q.db');self.p=dict(source='1',destination='2',product='0131491005418',quantity=2,note='')
 def job(self,e='e',owner='other',chat='group'):return self.q.draft(e,owner,chat,self.p)
 def test_only_owner_cross_chat(self):
  j=self.job();self.q.confirm(j['id'],'admin','group');self.assertIsNone(self.q.claim())
  self.q.confirm(j['id'],PRIVATE_CO_OWNER,'private');self.assertIsNotNone(self.q.claim())
 def test_owner_bulk_stays_in_chat(self):
  a=self.job();b=self.job('b','second','elsewhere');self.q.confirm_all(PRIVATE_CO_OWNER,'group',cancel=True)
  with self.q.db() as d:self.assertEqual(d.execute('SELECT state FROM jobs WHERE id=?',(a['id'],)).fetchone()['state'],'cancelled');self.assertEqual(d.execute('SELECT state FROM jobs WHERE id=?',(b['id'],)).fetchone()['state'],'draft')
 def test_owner_cancel_waiting(self):
  a=self.job();self.q.confirm(a['id'],'other','group');self.q.cancel_waiting('admin','group');self.q.cancel_waiting(PRIVATE_CO_OWNER,'group');self.assertIsNone(self.q.claim())
 def test_period(self):
  now=datetime(2026,10,2);self.assertEqual(period('7ngay',now)[0].strftime('%d/%m'),'26/09')
  with self.assertRaises(ValueError):period('02/09/2026',now)
 def test_recent_thirty_calendar_days(self):
  from datetime import timezone,timedelta
  now=datetime(2026,10,9,23,59,tzinfo=TZ)
  for arg in ('30ngay','30','30 ngày',' 30NGAY '):
   start,end=period(arg,now)
   self.assertEqual(start.isoformat(),'2026-09-10T00:00:00+07:00')
   self.assertEqual(end.isoformat(),'2026-10-10T00:00:00+07:00')
   self.assertEqual((end-start).days,30)
  self.assertEqual(period('10/09/2026',now)[0].day,10)
  for arg in ('09/09/2026','10/10/2026'):
   with self.assertRaises(ValueError):period(arg,now)
  utc=datetime(2026,10,9,18,tzinfo=timezone.utc)
  self.assertEqual(period('30ngay',utc)[1].isoformat(),'2026-10-11T00:00:00+07:00')
 def test_partial_and_quantity(self):
  p={'items':[self.p,self.p], 'requester_name':'Name'}
  j=dict(owner='u',payload=json.dumps(p),state='unknown',result=json.dumps([dict(co='12CO123',error=''),dict(co='',error='Unknown')]))
  stats,ranks,names=aggregate([j],{'1':{'region':'R','province':'P'}})
  self.assertEqual((stats['co'],stats['quantity'],stats['unknown']),(1,2,1));self.assertEqual(ranks['region']['R'],1)
 def test_cleanup_keeps_unknown(self):
  a=self.job();b=self.job('b');old=time.time()-31*86400
  with self.q.db() as d:
   d.execute("UPDATE jobs SET created=?,updated=?,notified=1,state='failed'",(old,old));d.execute("UPDATE jobs SET state='unknown' WHERE id=?",(b['id'],))
  cleanup(self.q,Path(self.tmp.name)/'imgs')
  with self.q.db() as d:self.assertEqual([r['id'] for r in d.execute('SELECT id FROM jobs')],[b['id']])
 def test_pruned_event_cannot_replay(self):
  from co_flow import DuplicateRequest
  self.job();old=time.time()-31*86400
  with self.q.db() as d:d.execute("UPDATE jobs SET created=?,updated=?,state='cancelled'",(old,old))
  cleanup(self.q,Path(self.tmp.name)/'imgs')
  with self.assertRaises(DuplicateRequest):self.job()
 def test_image_route_and_owner_gate(self):
  from unittest.mock import patch
  from types import SimpleNamespace as NS
  import co_summary
  messages=[];images=[];scheduler=NS(add_job=lambda *a,**k:None)
  with patch.dict('os.environ',{'CO_DB_PATH':self.tmp.name+'/q.db','CO_DATABASE_URL':'','CO_SUMMARY_DIR':self.tmp.name+'/images'}):
   routes={}
   def register(url):
    def bind(fn):routes[url]=fn;return fn
    return bind
   def abort(code):raise ValueError(code)
   app=NS(get=register)
   with patch.dict('sys.modules',{'flask':NS(send_from_directory=lambda d,f:200,abort=abort)}):
    handle=co_summary.install(app,lambda t,m:messages.append(m),lambda t,m:images.append(m),scheduler,'https://example.com')
   event=NS(message=NS(text='!tongket'),source=NS(user_id='other-admin'),reply_token='test')
   self.assertTrue(handle(event));self.assertEqual(len(images),0);self.assertIn('Chỉ Tâm',messages[-1])
   folder=Path(self.tmp.name)/'images';folder.mkdir();name='a'*48+'.png';(folder/name).write_bytes(b'PNG')
   route=routes['/co-summary-images/<filename>']
   self.assertEqual(route(name),200)
   with self.assertRaises(ValueError):route('not-valid.png')

class RetentionThirtyTests(unittest.TestCase):
 def test_history_thirty_images_seven(self):
  import os
  from co_flow import Queue
  with tempfile.TemporaryDirectory() as tmp:
   q=Queue(tmp+'/q.db');p=dict(source='1',destination='2',product='003',quantity=1,note='')
   j=q.draft('retain','user','chat',p)
   with q.db() as db:db.execute("UPDATE jobs SET state='succeeded',created=?,updated=?",(time.time()-20*86400,time.time()-20*86400))
   folder=Path(tmp)/'images';folder.mkdir();image=folder/'old.png';image.write_bytes(b'x');os.utime(image,(time.time()-8*86400,)*2)
   cleanup(q,folder)
   with q.db() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM jobs').fetchone()[0],1)
   self.assertFalse(image.exists())
