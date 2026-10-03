import json,tempfile,time,unittest
from co_flow import Queue,honor,preview_text,HONORS
from co_results import line_text_messages
class Honors(unittest.TestCase):
 def test_thresholds(self):
  for i,(n,label) in enumerate(HONORS):
   self.assertEqual(honor(n),label)
   if i:self.assertEqual(honor(n-1),HONORS[i-1][1])
 def test_count_owner_success_unique_and_period(self):
  with tempfile.TemporaryDirectory() as d:
   q=Queue(d+'/q.db');p=dict(source='1',destination='2',product='123',quantity=1,note='',requester_name='Tâm')
   job=q.draft('current','a','chat',p)
   with q.db() as db:
    for i in range(55):
     owner='a' if i<53 else 'b'
     result='XCO'+str(i if i<50 else 0)
     updated=time.time() if i!=49 else time.time()-9*86400
     db.execute('INSERT INTO jobs(id,event,owner,chat,payload,state,created,updated,result) VALUES(?,?,?,?,?,?,?,?,?)',(str(i),str(i),owner,'other',json.dumps(p),'succeeded',updated,updated,result))
   text=q.confirmation(job)
   self.assertIn('MẦM NON',text) # 49 distinct current owner codes
   with q.db() as db:db.execute('UPDATE jobs SET updated=? WHERE id=?',(time.time(),'49'))
   text=q.confirmation(job)
   self.assertIn('BÀN TAY VÀNG',text)
   self.assertIn('Mời Tâm xác nhận',text)
   self.assertNotIn('XÁC NHẬN TẠO CO',text)
   actions=line_text_messages(text)[-1]['quickReply']['items']
   self.assertEqual([a['action']['text'] for a in actions],['XACNHAN '+job['id'],'HUY '+job['id']])
