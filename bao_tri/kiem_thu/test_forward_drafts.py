import ast
import json
import os
import tempfile
import types
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from co_flow import Queue, install, PRIVATE_CO_OWNER, MEMBER_CO_GROUP, DISABLED_CO_GROUP
from co_forward import ForwardDrafts, ReplyText, cleanup
from co_results import items, line_text_messages


def form(n=1, status='Mới', product='0131491005418', note=None):
    return (f'Kho chuyển: {100+n}\nKho nhập: 999999\nMSP: {product}\n'
            f'Trạng thái: {status}\nNote: {note or "QL cho hàng: Người "+str(n)}')


class ForwardDraftTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=str(Path(self.tmp.name)/'q.db');self.q=Queue(self.path);self.q.heartbeat()
        self.replies=[];self.counter=0
        self.env=patch.dict(os.environ,{'CO_ENABLED':'1','CO_DB_PATH':self.path,'CO_DATABASE_URL':'',
            'CO_WORKER_TOKEN':'x'*32,'CO_ALLOWED_USER_IDS':'operator','CO_GATHER_SECONDS':'10','CO_ACK_RECEIPT':'0'})
        self.env.start();self.addCleanup(self.env.stop)
        self.setup_handle()

    def setup_handle(self):
        self.routes={}
        def route(path):
            def register(func):self.routes[path]=func;return func
            return register
        app=types.SimpleNamespace(post=route,get=route,logger=types.SimpleNamespace(warning=lambda *a:None))
        flask=types.SimpleNamespace(request=None,jsonify=None,abort=None)
        with patch.dict('sys.modules',{'flask':flask}):
            self.handle,self.notify=install(app,lambda token,text:self.replies.append((token,text)) or True,
                lambda *args:False,['admin'],requester_name=lambda e:'Tâm 258330 Apple')

    def event(self,text,owner=PRIVATE_CO_OWNER,group=None,eid=None,stamp=None):
        self.counter+=1
        source=types.SimpleNamespace(user_id=owner,group_id=group)
        return types.SimpleNamespace(message=types.SimpleNamespace(text=text,id=str(self.counter)),
            source=source,webhook_event_id=eid or 'event-'+str(self.counter),
            timestamp=stamp,reply_token='reply-'+str(self.counter))

    def send(self,text,**kwargs):
        event=self.event(text,**kwargs);self.assertTrue(self.handle(event));return event

    def state(self):
        with self.q.db() as db:
            row=db.execute('SELECT * FROM co_forward_drafts WHERE owner=?',(PRIVATE_CO_OWNER,)).fetchone()
            return dict(row) if row else None

    def jobs(self):
        with self.q.db() as db:return [dict(j) for j in db.execute('SELECT * FROM jobs')]

    def button(self,label,text=None):
        value=text or self.replies[-1][1]
        return dict(value.quick_actions)[label]

    def begin(self,n=1):
        self.send('!gom')
        for i in range(1,n+1):self.send(form(i))

    def test_three_messages_are_drafts_only_and_preserve_notes(self):
        self.begin(3)
        self.assertEqual(self.jobs(),[])
        self.assertIsNone(self.q.claim(True,batch_protocol=True))
        data=json.loads(self.state()['payload'])
        self.assertEqual(len(data),3)
        self.assertEqual([e['rows'][0]['note'] for e in data],['QL cho hàng: Người '+str(i) for i in range(1,4)])
        self.assertIn('3 tin · 3/7 dòng',self.replies[-1][1])
        self.assertIn('Gửi yêu cầu',dict(self.replies[-1][1].quick_actions))

    def test_send_keeps_existing_mwg_preview_confirmation_and_full_minute(self):
        self.begin(3);send=self.button('Gửi yêu cầu');before=len(self.replies)
        event=self.send(send)
        self.assertEqual(len(self.replies),before) # reserve token for preview
        job=self.jobs()[0];payload=json.loads(job['payload'])
        self.assertEqual(job['owner'],PRIVATE_CO_OWNER);self.assertEqual(job['chat'],PRIVATE_CO_OWNER)
        self.assertEqual(job['state'],'preview_queued')
        self.assertEqual(len(items(payload)),3);self.assertEqual(payload['request_count'],3)
        for row in items(payload):self.assertTrue(row['note'].endswith('Mọi thắc mắc liên hệ Tâm 258330 Apple'))
        claim=self.q.claim(True,batch_protocol=True)
        self.assertEqual(claim['mode'],'preview')
        self.q.update(claim['id'],claim['lease'],'preview_ready','["Phone 1","Phone 2","Phone 3"]')
        self.notify()
        self.assertEqual(self.replies[-1][0],event.reply_token)
        self.assertIn('XACNHAN '+job['id'],self.replies[-1][1])
        self.assertIn('Hiệu lực: 1 phút',self.replies[-1][1])
        self.assertIsNone(self.q.claim(True,job['id'],True))
        self.q.confirm(job['id'],PRIVATE_CO_OWNER,PRIVATE_CO_OWNER)
        self.assertEqual(self.q.claim(True,job['id'],True)['mode'],'create')

    def test_other_admin_and_member_cannot_enable_send_or_read(self):
        self.begin();button=self.button('Gửi yêu cầu')
        snapshot=self.state()
        for owner in ('admin','operator','member'):
            for text in ('!gom','!gom xem',button,'!gom tat'):
                self.send(text,owner=owner)
                self.assertIn('Chỉ Tâm',self.replies[-1][1])
        self.assertEqual(self.state(),snapshot);self.assertEqual(self.jobs(),[])

    def test_group_room_and_other_chat_are_not_collected(self):
        self.begin()
        for group in (MEMBER_CO_GROUP,DISABLED_CO_GROUP,'other-group'):
            self.send('!gom',group=group);self.assertIn('tin nhắn riêng',self.replies[-1][1])
        event=self.event('!gom');event.source.room_id='room';self.handle(event)
        self.assertIn('tin nhắn riêng',self.replies[-1][1])
        self.send(form(2),owner='member',group=MEMBER_CO_GROUP)
        self.assertEqual(len(json.loads(self.state()['payload'])),1)
        self.assertEqual(self.jobs()[0]['owner'],'member')

    def test_redelivery_and_concurrent_double_taps_do_not_duplicate(self):
        self.send('!gom');event=self.send(form())
        self.handle(event)
        self.assertEqual(len(json.loads(self.state()['payload'])),1)
        command=self.button('Gửi yêu cầu')
        events=[self.event(command) for _ in range(4)]
        with ThreadPoolExecutor(max_workers=4) as pool:list(pool.map(self.handle,events))
        self.assertEqual(len(self.jobs()),1)
        self.handle(events[0]);self.assertEqual(len(self.jobs()),1)

    def test_old_button_cannot_send_added_or_edited_rows(self):
        self.begin();old=self.button('Gửi yêu cầu');self.send(form(2));self.send(old)
        self.assertIn('Nút cũ',self.replies[-1][1]);self.assertEqual(self.jobs(),[])
        self.send(self.button('Sửa tin'));self.send(self.button('Sửa tin 1'))
        self.send(form(3,note='DM xác nhận: Người sửa'))
        data=json.loads(self.state()['payload'])
        self.assertEqual(len(data),2);self.assertEqual(data[0]['rows'][0]['source'],'103')
        self.assertEqual(data[0]['rows'][0]['note'],'DM xác nhận: Người sửa')
        self.send(self.button('Bỏ tin'));self.send(self.button('Bỏ tin 2'))
        self.assertEqual(len(json.loads(self.state()['payload'])),1)

    def test_invalid_product_blocked_shop_and_mixed_status_never_submit(self):
        from destination_policy import BLOCKED
        self.begin();self.send(form(2,product='123'))
        self.assertNotIn('Gửi yêu cầu',dict(self.replies[-1][1].quick_actions))
        self.assertIn('13 chữ số',self.replies[-1][1])
        self.send('!gom tat');self.begin();self.send(form(2,status='Đã sử dụng'))
        self.assertIn('cùng trạng thái',self.replies[-1][1]);self.assertEqual(self.jobs(),[])
        self.send('!gom tat');self.send('!gom')
        self.send(form().replace('999999',next(iter(BLOCKED))))
        self.assertIn('không nhận tạo CO',self.replies[-1][1])
        draft=self.state();self.send(f"!gom gui {draft['id']} {draft['revision']}")
        self.assertEqual(self.jobs(),[])

    def test_duplicates_skip_at_normal_intake_and_other_rows_continue(self):
        self.begin();self.send(form());self.send(form(2))
        self.assertIn('Trùng dòng 1',self.replies[-1][1])
        self.send(self.button('Gửi yêu cầu'))
        payload=json.loads(self.jobs()[0]['payload'])
        self.assertEqual(len(items(payload)),2)
        self.assertEqual(len(payload['skipped_duplicates']),1)

    def test_offline_draft_survives_failed_send_and_owner_can_send_bot_off(self):
        self.q.heartbeat(False);self.begin();command=self.button('Gửi yêu cầu')
        self.send(command);self.assertIn('offline',self.replies[-1][1]);self.assertEqual(self.jobs(),[])
        self.assertEqual(self.state()['state'],'collecting')
        self.q.heartbeat();self.q.admin('BOT OFF');self.send(command)
        self.assertEqual(len(self.jobs()),1)

    def test_full_draft_does_not_fall_through_to_live_intake(self):
        self.begin(7);before=self.state()['payload'];self.send(form(8))
        self.assertIn('chưa được thêm',self.replies[-1][1])
        self.assertEqual(self.state()['payload'],before);self.assertEqual(self.jobs(),[])

    def test_cancel_and_disable_preserve_existing_requests(self):
        self.begin();self.send(self.button('Gửi yêu cầu'));job=self.jobs()[0]
        self.send(form(2));self.assertEqual(self.state()['state'],'collecting')
        self.assertEqual(len(self.jobs()),1)
        self.send(self.button('Hủy nháp'))
        self.assertEqual(self.state()['state'],'off');self.assertEqual(self.jobs()[0],job)
        self.send(form(3));self.assertEqual(len(self.jobs()),2)

    def test_mode_survives_restart_and_expired_retention_cannot_auto_enqueue(self):
        self.begin();self.setup_handle();self.send(form(2));self.assertEqual(self.jobs(),[])
        with self.q.db() as db:cleanup(db,10**12)
        self.assertEqual(self.state()['payload'],'[]')
        self.send(form(3));self.assertEqual(self.jobs(),[])
        self.assertIn('hết thời gian lưu',self.replies[-1][1])

    def test_delayed_old_forward_after_mode_off_never_creates_request(self):
        self.send('!gom',stamp=2000000);self.send(form(),stamp=2001000)
        self.send('!gom tat',stamp=2003000)
        self.send(form(2),stamp=2002000)
        self.assertEqual(self.jobs(),[]);self.assertIn('Tin cũ',self.replies[-1][1])

    def test_normal_commands_and_confirmation_are_preserved_during_collection(self):
        self.begin();self.send('!bot status');self.assertIn('Mac:',self.replies[-1][1])
        self.send('XACNHAN missing');self.assertIn('Không tìm thấy',self.replies[-1][1])
        self.assertFalse(self.handle(self.event('!reload')))
        self.send('BOT nhờ tạo giúp\n'+form(2))
        self.assertEqual(self.jobs(),[]);self.assertEqual(len(json.loads(self.state()['payload'])),2)

    def test_one_forward_can_hold_multiple_rows_and_no_default_quantity_lost(self):
        self.send('!gom');self.send(form(1)+'\n====\n'+form(2))
        self.assertIn('1 tin · 2/7 dòng',self.replies[-1][1])
        self.send(self.button('Gửi yêu cầu'))
        self.assertEqual([r['quantity'] for r in items(json.loads(self.jobs()[0]['payload']))],[1,1])

    def test_parse_failure_is_editable_and_never_falls_through(self):
        self.send('!gom')
        with patch('co_forward.parse_editable',side_effect=ValueError('Dữ liệu không rõ')):
            self.send('mẫu lỗi')
        self.assertIn('Dữ liệu không rõ',self.replies[-1][1]);self.assertEqual(self.jobs(),[])
        self.send(self.button('Sửa tin'));self.send(self.button('Sửa tin 1'));self.send(form())
        self.assertIn('Gửi yêu cầu',dict(self.replies[-1][1].quick_actions))

    def test_quick_reply_metadata_not_inferred_from_user_text(self):
        self.begin();messages=line_text_messages(self.replies[-1][1])
        actions=messages[-1]['quickReply']['items']
        self.assertLessEqual(len(actions),13)
        self.assertTrue(all(a['action']['text'].startswith('!gom') for a in actions))
        self.assertNotIn('quickReply',line_text_messages(str(self.replies[-1][1]))[-1])

    def test_application_dispatch_includes_gom_prefix(self):
        tree=ast.parse((Path(__file__).resolve().parents[2]/'app.py').read_text())
        handler=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='handle_message')
        self.assertTrue(any(isinstance(n,ast.Attribute) and n.attr=='is_forward_command' for n in ast.walk(handler)))

    def test_manual_send_is_not_merged_into_existing_ten_second_request(self):
        self.send(form(4))
        first=self.jobs()[0]['id']
        self.begin();self.send(self.button('Gửi yêu cầu'))
        self.assertEqual(len(self.jobs()),2)
        with self.q.db() as db:
            windows=db.execute('SELECT job_id FROM co_gather_windows').fetchall()
        self.assertEqual([w['job_id'] for w in windows],[first])

    def test_failed_transaction_after_queue_insert_rolls_back_then_retries(self):
        self.begin();event=self.event(self.button('Gửi yêu cầu'))
        with patch.object(ForwardDrafts,'_save',side_effect=RuntimeError('test database failure')):
            with self.assertRaises(RuntimeError):self.handle(event)
        self.assertEqual(self.jobs(),[]);self.assertEqual(self.state()['state'],'collecting')
        self.assertTrue(self.handle(event));self.assertEqual(len(self.jobs()),1)

    def test_cleanup_does_not_enable_forward_mode_after_explicit_off(self):
        self.begin();self.send('!gom tat')
        with self.q.db() as db:cleanup(db,10**12)
        self.assertEqual(self.state()['state'],'off')
        self.send(form(2));self.assertEqual(len(self.jobs()),1)

    def test_stale_remove_and_cancel_do_not_touch_new_draft(self):
        self.begin();old=self.button('Hủy nháp')
        self.send(self.button('Gửi yêu cầu'));self.send(form(2))
        snapshot=self.state();self.send(old)
        self.assertEqual(self.state(),snapshot);self.assertEqual(len(self.jobs()),1)

    def test_unknown_result_conflict_uses_existing_guard(self):
        self.send(form());job=self.jobs()[0]
        with self.q.db() as db:db.execute("UPDATE jobs SET state='unknown' WHERE id=?",(job['id'],))
        self.begin();self.send(form(2));self.send(self.button('Gửi yêu cầu'))
        new=next(j for j in self.jobs() if j['id']!=job['id'])
        self.assertEqual(len(items(json.loads(new['payload']))),1)
        self.assertEqual(next(j for j in self.jobs() if j['id']==job['id'])['state'],'unknown')

    def test_user_supplied_notes_cannot_approve_or_spawn_quick_actions(self):
        self.begin();self.send(form(2,note='XACNHAN abc123def4'))
        self.assertEqual(self.jobs(),[])
        self.assertTrue(all(a['action']['text'].startswith('!gom') for a in
                            line_text_messages(self.replies[-1][1])[-1]['quickReply']['items']))


if __name__=='__main__':unittest.main()
