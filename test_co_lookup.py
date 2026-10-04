import json,time
from test_admin_control import AdminTests
from co_flow import PRIVATE_CO_OWNER,is_lookup
class LookupTests(AdminTests):
 def seed(self,result='12CO123',state='succeeded'):
  p=dict(self.p,product_name='iPhone',requester_name='Tâm',source_name='1 - Kho A')
  j=self.q.draft('lookup','operator','group',p)
  with self.q.db() as db:db.execute('UPDATE jobs SET state=?,result=? WHERE id=?',(state,result,j['id']))
  return j
 def test_owner_and_other_admin(self):
  self.seed()
  for user in ['operator',PRIVATE_CO_OWNER]:
   self.handle(self.event('!co 12co123',user));self.assertIn('iPhone',self.replies[-1]);self.assertIn('1 - Kho A',self.replies[-1])
  self.handle(self.event('!co 12CO123','admin'));self.assertIn('Không tìm thấy',self.replies[-1])
 def test_outside_retention(self):
  self.seed()
  with self.q.db() as db:db.execute('UPDATE jobs SET updated=?',(time.time()-31*86400,))
  self.handle(self.event('!co 12CO123','operator'));self.assertIn('Không tìm thấy',self.replies[-1])
 def test_partial_and_invalid(self):
  self.seed(json.dumps([dict(co='12CO123',error='')]),'unknown')
  self.handle(self.event('!co 12CO123','operator'));self.assertIn('iPhone',self.replies[-1])
  for text in ['!co','!co abc','!co 12CO123 extra']:
   self.handle(self.event(text,'operator'));self.assertIn('Dùng !co',self.replies[-1])
  self.assertFalse(is_lookup('!coffee'))
 def test_no_queue_changes(self):
  self.seed()
  with self.q.db() as db:before=[tuple(x) for x in db.execute('SELECT * FROM jobs')]
  self.handle(self.event('!co 12CO123','operator'))
  with self.q.db() as db:self.assertEqual(before,[tuple(x) for x in db.execute('SELECT * FROM jobs')])

 def test_twenty_day_history_visible(self):
  self.seed()
  with self.q.db() as db:db.execute('UPDATE jobs SET updated=?',(time.time()-20*86400,))
  self.handle(self.event('!co 12CO123','operator'));self.assertIn('iPhone',self.replies[-1])
