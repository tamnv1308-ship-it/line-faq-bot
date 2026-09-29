from test_admin_control import AdminTests
from co_flow import MEMBER_CO_GROUP,DISABLED_CO_GROUP

class GroupCOTests(AdminTests):
    def event_in(self,text,group,owner='member'):
        e=self.event(text,owner);e.source.group_id=group;return e
    def test_member_form_accepted_only_in_designated_group(self):
        form='Kho xuất: 1\nKho nhận: 2\nMSP: 003'
        self.q.heartbeat();self.handle(self.event_in(form,MEMBER_CO_GROUP))
        with self.q.db() as db:
            row=db.execute('SELECT owner,chat FROM jobs').fetchone()
            self.assertEqual(row['owner'],'member');self.assertEqual(row['chat'],MEMBER_CO_GROUP)
        self.handle(self.event_in(form,'another-group'))
        self.assertIn('chưa được cấp quyền',self.replies[-1])
    def test_disabled_group_rejects_even_admin(self):
        for text in ['Kho xuất: 1\nKho nhận: 2\nMSP: 003','XACNHAN abc','XACNHAN ALL']:
            self.handle(self.event_in(text,DISABLED_CO_GROUP,'admin'))
            self.assertIn('ngừng nhận',self.replies[-1])
    def test_member_does_not_gain_admin_or_private_access(self):
        self.handle(self.event_in('!bot off',MEMBER_CO_GROUP));self.assertIn('chỉ dành',self.replies[-1])
        self.handle(self.event_in('XACNHAN ALL',None));self.assertIn('tin nhắn riêng',self.replies[-1])
    def test_confirm_all_still_scoped_to_sender(self):
        self.q.heartbeat()
        a=self.q.draft('a','member',MEMBER_CO_GROUP,self.p)
        b=self.q.draft('b','another',MEMBER_CO_GROUP,self.p)
        self.handle(self.event_in('XACNHAN ALL',MEMBER_CO_GROUP))
        with self.q.db() as db:
            states={r['id']:r['state'] for r in db.execute('SELECT id,state FROM jobs')}
        self.assertEqual(states[a['id']],'queued');self.assertEqual(states[b['id']],'draft')
