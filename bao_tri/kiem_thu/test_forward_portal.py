"""Shared LINE/LIFF owner basket: permissions, versioning and existing CO flow."""
import json
import time
import types
import unittest
from bao_tri.kiem_thu import test_tao_portal as fixtures
from bao_tri.kiem_thu.test_forward_drafts import form
from co_forward import ForwardDrafts, SENT
from co_flow import add_requester_note
from co_results import items
OWNER=fixtures.OWNER

class ForwardPortalTests(unittest.TestCase):
    setUp=fixtures.PortalTests.setUp
    call=fixtures.PortalTests.call
    login=fixtures.PortalTests.login
    def store(self):return ForwardDrafts(self.q,OWNER,add_requester_note)
    def line(self,text):
        event=types.SimpleNamespace(source=types.SimpleNamespace(user_id=OWNER,group_id=None),
            message=types.SimpleNamespace(text=text,id=str(time.time_ns())),timestamp=None,
            webhook_event_id='test-'+str(time.time_ns()),reply_token='test-reply')
        return self.store().process(event,lambda e:'Tâm 258330 Apple')
    def begin(self,count=3):
        self.login(OWNER);self.line('!gom')
        for n in range(count):self.line(form(n+1))
        return self.view()
    def view(self):return self.call('forward-draft').json['draft']
    def key(self,draft):return {k:draft[k] for k in ('id','revision')}
    def change(self,draft,index=0,remove=False,**values):
        row=draft['rows'][index]
        return self.call('forward-draft/row','POST',dict(self.key(draft),entry=row['entry'],row=row['row'],
            action='remove' if remove else 'save',values=dict(row['values'],**values)))
    def submit(self,draft):return self.call('forward-draft/submit','POST',self.key(draft))
    def jobs(self):
        with self.q.db() as db:return [dict(r) for r in db.execute('SELECT * FROM jobs')]

    def test_read_write_and_receipts_owner_only(self):
        draft=self.begin()
        for uid in (fixtures.MEMBER,fixtures.ADMIN):
            self.login(uid)
            for path,method,data in [('forward-draft','GET',None),('forward-draft/submissions/'+draft['id'],'GET',None),
                ('forward-draft/row','POST',{}),('forward-draft/submit','POST',self.key(draft)),('forward-draft/start','POST',{})]:
                self.assertEqual(self.call(path,method,data).status_code,403,(uid,path))
        self.assertEqual(self.jobs(),[])

    def test_anonymous_csrf_and_origin(self):
        self.assertEqual(self.call('forward-draft').status_code,401)
        draft=self.begin()
        for headers in ({'X-Tao-CSRF':''},{'Origin':'https://evil.example'}):
            self.assertEqual(self.call('forward-draft/submit','POST',self.key(draft),headers).status_code,403)
        self.assertEqual(self.view(),draft)

    def test_start_from_liff_and_edit_remove_individual_row_shared_with_line(self):
        self.login(OWNER)
        self.assertEqual(self.call('forward-draft/start','POST',dict(id=None,revision=0)).status_code,200)
        self.line(form(1)+'\n===\n'+form(2));self.line(form(3))
        draft=self.view();self.assertEqual((draft['messages'],len(draft['rows'])),(2,3))
        saved=self.change(draft,1,quantity='3',note='QL cho hàng: A · ĐM xác nhận: B')
        self.assertEqual(saved.status_code,200)
        result=str(self.line('!gom xem'));self.assertIn('SL: 3',result);self.assertIn('QL cho hàng: A · ĐM xác nhận: B',result)
        self.assertEqual(self.jobs(),[])
        self.assertEqual(self.change(self.view(),1,remove=True).status_code,200)
        remaining=self.view();self.assertEqual((remaining['messages'],len(remaining['rows'])),(2,2))
        self.assertEqual([r['values']['source'] for r in remaining['rows']],['101','103'])
        self.assertIn('2 tin · 2/7 dòng',str(self.line('!gom xem')))

    def test_old_line_buttons_and_liff_snapshot_do_not_overwrite_new_messages(self):
        old=self.begin(1);oldbutton=self.store()._action(old,'gui')
        self.assertEqual(self.change(old,note='Sửa trên điện thoại').status_code,200)
        self.line(oldbutton);self.assertEqual(self.jobs(),[])
        previous=self.view();self.line(form(2))
        self.assertEqual(self.change(previous,remove=True).status_code,409)
        self.assertEqual(self.submit(previous).status_code,409)
        self.assertEqual(len(self.view()['rows']),2);self.assertEqual(self.jobs(),[])

    def test_two_devices_conflict_and_invalid_indices(self):
        old=self.begin(2);self.assertEqual(self.change(old,quantity='2').status_code,200)
        self.assertEqual(self.change(old,note='stale').status_code,409);current=self.view()
        for index in (-1,99,True,'0',None):
            response=self.call('forward-draft/row','POST',dict(self.key(current),entry=index,row=0,action='remove'))
            self.assertEqual(response.status_code,400,index)
        self.assertEqual(self.view(),current)

    def test_invalid_and_mixed_status_stay_drafts(self):
        draft=self.begin(2);self.assertEqual(self.change(draft,product='131491005418').status_code,200)
        invalid=self.view();self.assertIn('product',invalid['rows'][0]['errors'])
        self.assertFalse(invalid['can_send']);self.assertEqual(self.submit(invalid).status_code,409)
        self.change(invalid,product='0131491005418',status='Đã sử dụng')
        self.assertTrue(self.view()['global_errors']);self.assertEqual(self.submit(self.view()).status_code,409)
        self.assertEqual(self.jobs(),[])

    def test_parse_failure_is_visible_and_editable(self):
        self.login(OWNER);store=self.store()
        with self.q.db() as db:
            draft=store._new(db,OWNER,time.time())
            store._save(db,draft,payload=json.dumps([{'rows':[],'error':'Tin lỗi cần sửa'}]))
        view=self.view();self.assertIsNone(view['rows'][0]['row']);self.assertFalse(view['can_send'])
        self.assertEqual(self.submit(view).status_code,409)
        valid=dict(source='3945',destination='447',product='0131491005415',quantity='1',status='Mới',note='Giữ note')
        self.assertEqual(self.change(view,**valid).status_code,200);self.assertTrue(self.view()['can_send'])
        self.assertEqual(self.change(self.view(),remove=True).status_code,200)
        self.assertEqual(self.view()['rows'],[]);self.assertEqual(self.view()['messages'],0)

    def test_send_once_across_line_liff_and_next_basket(self):
        draft=self.begin();button=self.store()._action(draft,'gui')
        response=self.submit(draft);self.assertEqual(response.status_code,200,response.json)
        jid=response.json['job']['id'];self.assertEqual(response.json['job']['state'],'preview_queued')
        self.assertFalse(response.json['job']['can_confirm'])
        self.line(button);self.assertEqual(self.submit(draft).json['job']['id'],jid)
        self.line(form(4));nextdraft=self.view();self.assertNotEqual(nextdraft['id'],draft['id'])
        self.assertEqual(self.submit(draft).json['job']['id'],jid)
        receipt=self.call('forward-draft/submissions/'+draft['id']).json
        self.assertTrue(receipt['found']);self.assertEqual(receipt['job']['id'],jid)
        self.assertEqual(len(self.jobs()),1);job=self.jobs()[0];payload=json.loads(job['payload'])
        self.assertEqual(job['owner'],OWNER);self.assertEqual(job['chat'],OWNER);self.assertEqual(payload['request_count'],3)
        for n,row in enumerate(items(payload),1):
            self.assertIn('QL cho hàng: Người '+str(n),row['note']);self.assertEqual(row['note'].count('Mọi thắc mắc liên hệ'),1)
        self.assertEqual(self.view(),nextdraft)

    def test_line_send_recovered_by_liff(self):
        draft=self.begin(1);self.assertIs(self.line(self.store()._action(draft,'gui')),SENT)
        response=self.submit(draft);self.assertEqual(response.status_code,200);self.assertEqual(len(self.jobs()),1)
        self.assertEqual(self.view()['job_id'],response.json['job']['id'])

    def test_full_duplicates_remain_idempotent_after_next_basket(self):
        draft=self.begin(1);self.submit(draft);self.line('!gom');self.line(form(1));second=self.view()
        response=self.submit(second);self.assertTrue(response.json['skipped'],response.json)
        self.line(form(3));third=self.view();self.assertTrue(self.submit(second).json['skipped'])
        self.assertTrue(self.call('forward-draft/submissions/'+second['id']).json['skipped'])
        self.assertEqual(len(self.jobs()),1);self.assertEqual(self.view(),third)

    def test_long_final_note_keeps_draft(self):
        draft=self.begin(1);self.change(draft,note='x'*500);before=self.view()
        response=self.submit(before);self.assertEqual(response.status_code,409)
        self.assertIn('500',response.json['error']);self.assertEqual(self.view(),before);self.assertEqual(self.jobs(),[])

    def test_line_edit_must_finish_liff_save_finishes_it(self):
        draft=self.begin(1);self.line(self.store()._action(draft,'sua',1));draft=self.view()
        self.assertFalse(draft['can_send']);self.assertEqual(self.submit(draft).status_code,409)
        self.change(draft,note='Sửa dòng trên LIFF');self.assertEqual(self.view()['edit_index'],-1);self.assertTrue(self.view()['can_send'])

    def test_owner_off_exception_and_worker_readiness(self):
        draft=self.begin(1);self.q.admin('BOT OFF');self.assertEqual(self.submit(draft).status_code,200)
        self.line('!gom');self.line(form(2));draft=self.view()
        with self.q.db() as db:db.execute('UPDATE co_control SET heartbeat=0')
        response=self.submit(draft);self.assertEqual(response.status_code,409)
        self.assertEqual(self.view(),draft);self.assertEqual(len(self.jobs()),1)

    def test_mwg_preview_then_same_one_minute_confirmation(self):
        draft=self.begin(1);jid=self.submit(draft).json['job']['id']
        self.assertEqual(self.call('jobs/'+jid+'/confirm','POST',{}).status_code,409)
        job=self.q.claim(preview_protocol=True,batch_protocol=True)
        self.q.update(job['id'],job['lease'],'preview_ready','iPhone thử nghiệm')
        preview=self.call('jobs/'+jid).json['job'];self.assertTrue(preview['can_ack_preview']);self.assertFalse(preview['can_confirm'])
        ack=self.call('jobs/'+jid+'/preview-seen','POST',{'revision':preview['preview_revision']})
        self.assertEqual(ack.status_code,200,ack.json);deadline=ack.json['job']['expires_at']
        self.assertAlmostEqual(deadline-time.time(),60,delta=2)
        repeat=self.call('jobs/'+jid+'/preview-seen','POST',{'revision':preview['preview_revision']})
        self.assertEqual(repeat.json['job']['expires_at'],deadline);self.assertEqual(self.jobs()[0]['state'],'draft')
        confirmed=self.call('jobs/'+jid+'/confirm','POST',{})
        self.assertEqual(confirmed.status_code,200);self.assertIn(confirmed.json['job']['state'],('queued','verified_queued'))

    def test_cancel_blocks_stale_submit_and_start(self):
        draft=self.begin(1);self.line('!gom tat');self.assertEqual(self.submit(draft).status_code,409)
        self.assertEqual(self.call('forward-draft/start','POST',self.key(draft)).status_code,409)
        self.assertEqual(self.view()['state'],'off');self.assertEqual(self.jobs(),[])

    def test_simultaneous_sends_share_one_job(self):
        from concurrent.futures import ThreadPoolExecutor
        from tao_portal import COOKIE
        draft=self.begin(2)
        cookie=self.client.get_cookie(COOKIE,domain='test.example').value
        def send_once(_):
            client=self.app.test_client();client.set_cookie(COOKIE,cookie,domain='test.example')
            return client.post('/tao/api/forward-draft/submit',json=self.key(draft),base_url=fixtures.BASE,
                headers={'Origin':fixtures.BASE,'X-Tao-CSRF':self.csrf})
        with ThreadPoolExecutor(max_workers=2) as pool:responses=list(pool.map(send_once,range(2)))
        self.assertEqual([r.status_code for r in responses],[200,200])
        self.assertEqual(responses[0].json['job']['id'],responses[1].json['job']['id'])
        self.assertEqual(len(self.jobs()),1)
