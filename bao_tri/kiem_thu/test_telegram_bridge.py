import json
import logging
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from flask import Flask
from co_flow import Queue, install, PRIVATE_CO_OWNER as OWNER
from co_forward import ReplyText
from telegram_bridge import Bridge, TelegramError, install_webhook
from bao_tri.kiem_thu.test_forward_drafts import form
from bao_tri.kiem_thu import test_tao_portal as fixtures

ENV={'TELEGRAM_ENABLED':'1','TELEGRAM_BOT_TOKEN':'12345:'+'a'*32,
     'TELEGRAM_WEBHOOK_SECRET':'b'*32,'TELEGRAM_BOT_USERNAME':'test_tao_bot',
     'TELEGRAM_CO_GROUP_ID':'-100123','CO_INTAKE_TRANSPORT':'telegram'}


class FakeTelegram:
    def __init__(self):self.calls=[];self.fail=None
    def call(self,method,data):
        if self.fail:raise self.fail
        self.calls.append((method,data))
        if method=='getChatMember':return {'status':'member','user':{'id':data['user_id']}}
        return {'message_id':len(self.calls)}


class TelegramTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        path=str(Path(tmp.name)/'q.db')
        env=patch.dict(os.environ,dict(ENV,CO_DB_PATH=path,CO_DATABASE_URL='',CO_ENABLED='1',
            CO_WORKER_TOKEN='x'*32,CO_GATHER_SECONDS='0',CO_ACK_RECEIPT='0',CO_ALLOWED_USER_IDS=fixtures.ADMIN))
        env.start();self.addCleanup(env.stop)
        self.q=Queue(path);self.q.heartbeat();self.api=FakeTelegram();self.bridge=Bridge(self.q,self.api)
        self.app=Flask(__name__);self.app.testing=True
        install_webhook(self.app,self.bridge);self.http=self.app.test_client();self.counter=0
        self.handle,self.notify=install(self.app,self.bridge.reply,self.bridge.send,[fixtures.ADMIN],
            requester_name=lambda e:e.requester_name)
        self.link(OWNER,1);self.link(fixtures.MEMBER,2);self.link(fixtures.OTHER,3);self.link(fixtures.ADMIN,4)

    def link(self,uid,tid):
        url=self.bridge.begin_link(uid);token=url.split('link_')[1]
        self.bridge.offer_link(token,dict(id=tid,first_name='User '+str(tid)))
        self.bridge.confirm_link(uid,str(tid))

    def update(self,text,uid=1,group=-100123,callback=False):
        self.counter+=1
        message={'message_id':self.counter,'date':int(time.time()),
            'from':{'id':uid,'is_bot':False,'first_name':'Tâm'},
            'chat':{'id':group if group is not None else uid,'type':'supergroup' if group is not None else 'private'},'text':text}
        if callback:
            sender=message['from'];message['from']={'id':12345,'is_bot':True}
            return {'update_id':self.counter,'callback_query':{'id':str(self.counter),'from':sender,'message':message,'data':text}}
        return {'update_id':self.counter,'message':message}

    def send(self,text,**kwargs):
        update=self.update(text,**kwargs);self.bridge.process(update,(self.handle,));return update

    def jobs(self):
        with self.q.db() as db:return [dict(r) for r in db.execute('SELECT * FROM jobs')]

    def preview(self):
        job=self.q.claim(True,batch_protocol=True)
        self.assertEqual(job['mode'],'preview')
        payload=job['payload'];count=len(payload.get('items',[payload]))
        result=json.dumps(['iPhone test']*count) if 'items' in payload else 'iPhone test'
        self.q.update(job['id'],job['lease'],'preview_ready',result);self.notify()
        return job

    def test_link_requires_both_accounts_and_does_not_accept_display_name(self):
        self.send(form(),uid=99,group=None);self.assertEqual(self.jobs(),[])
        uid='U'+'5'*32;url=self.bridge.begin_link(uid);token=url.split('link_')[1]
        self.bridge.offer_link(token,dict(id=99,first_name='Tâm 258330 Apple'))
        self.assertIsNone(self.bridge.linked(telegram_user=99))
        with self.assertRaises(ValueError):self.bridge.confirm_link(OWNER,'99')
        with self.assertRaises(ValueError):self.bridge.confirm_link(uid,'98')
        self.bridge.confirm_link(uid,'99')
        self.assertEqual(self.bridge.linked(telegram_user=99)['line_user'],uid)
        self.assertNotEqual(uid,OWNER)
        with self.assertRaises(ValueError):self.bridge.offer_link(token,dict(id=100,first_name='X'))

    def test_link_expires_and_cannot_reassign_existing_identity(self):
        with self.assertRaises(ValueError):self.bridge.begin_link(OWNER)
        uid='U'+'6'*32;token=self.bridge.begin_link(uid).split('link_')[1]
        with self.q.db() as db:db.execute('UPDATE co_telegram_link_requests SET expires=0 WHERE line_user=?',(uid,))
        with self.assertRaises(ValueError):self.bridge.offer_link(token,dict(id=99))
        self.assertIsNone(self.bridge.linked(telegram_user=99))

    def test_webhook_secret_and_update_replay(self):
        update=self.update(form(),uid=2)
        self.assertEqual(self.http.post('/telegram/webhook',json=update).status_code,403)
        headers={'X-Telegram-Bot-Api-Secret-Token':ENV['TELEGRAM_WEBHOOK_SECRET']}
        for _ in range(2):self.assertEqual(self.http.post('/telegram/webhook',json=update,headers=headers).status_code,200)
        with self.q.db() as db:self.assertEqual(db.execute('SELECT COUNT(*) AS n FROM co_telegram_updates').fetchone()['n'],1)
        self.bridge.drain((self.handle,),logging.getLogger(__name__))
        self.bridge.drain((self.handle,),logging.getLogger(__name__))
        self.assertEqual(len(self.jobs()),1);self.assertEqual(self.jobs()[0]['owner'],fixtures.MEMBER)
        self.assertEqual(self.jobs()[0]['chat'],'tg:-100123')
        with self.q.db() as db:self.assertEqual(db.execute('SELECT payload FROM co_telegram_updates').fetchone()['payload'],'{}')

    def test_only_allowed_group_and_owner_private(self):
        self.send(form(),uid=2,group=-999);self.send(form(),uid=2,group=None)
        self.send(form(),uid=4,group=None);self.assertEqual(self.jobs(),[])
        self.send(form(),uid=1,group=None)
        self.assertEqual(self.jobs()[0]['owner'],OWNER);self.assertEqual(self.jobs()[0]['chat'],'tg:1')

    def test_setup_group_discovery_does_not_grant_access_or_keep_messages(self):
        update=self.update('/start@test_tao_bot',group=-999)
        update['message']['chat']['title']='CÔNG CỤ HỖ TRỢ'
        self.bridge.process(update,(self.handle,))
        self.send(form(),group=-999)
        self.assertEqual(self.jobs(),[]);self.assertEqual(self.api.calls,[])
        with self.q.db() as db:
            rows=[dict(r) for r in db.execute('SELECT * FROM co_telegram_seen_groups')]
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['chat_id'],'-999')
        self.assertEqual(rows[0]['title'],'CÔNG CỤ HỖ TRỢ')
        self.assertEqual(set(rows[0]),{'bot_id','chat_id','title','seen'})
        self.send('/start@another_bot',group=-998)
        self.send('/start',group=-997)
        stale=self.update('/start@test_tao_bot',group=-996)
        stale['message']['date']=int(time.time())-301
        self.bridge.process(stale,(self.handle,))
        with self.q.db() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) n FROM co_telegram_seen_groups').fetchone()['n'],1)
            db.execute('UPDATE co_telegram_seen_groups SET seen=0')
        self.bridge.cleanup()
        with self.q.db() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) n FROM co_telegram_seen_groups').fetchone()['n'],0)

    def test_unlinked_members_self_only_and_owner_override(self):
        self.send('/taoco '+form(),uid=99);job=self.preview()
        self.assertEqual(self.jobs()[0]['owner'],'telegram:99')
        for uid in (98,2,4):
            for command in ('XACNHAN ','HUY '):
                self.send(command+job['id'],uid=uid,callback=True)
                self.assertEqual(self.jobs()[0]['state'],'draft')
        self.send('XACNHAN '+job['id'],uid=99,callback=True)
        self.assertEqual(self.jobs()[0]['state'],'verified_queued')
        self.send('HUY '+job['id'],uid=1,callback=True)
        self.assertEqual(self.jobs()[0]['state'],'cancelled')

    def test_native_identity_survives_link_and_self_cancel(self):
        self.send(form(),uid=99);job=self.preview()
        self.link('U'+'9'*32,99)
        self.send('HUY '+job['id'],uid=99,callback=True)
        self.assertEqual(self.jobs()[0]['state'],'cancelled')
        self.send(form(2),uid=99)
        self.assertEqual(self.jobs()[-1]['owner'],'telegram:99')

    def test_unlinked_group_gate_off_and_no_admin_by_name(self):
        self.send(form(),uid=99,group=None)
        self.send(form(),uid=99,group=-999)
        anonymous=self.update(form(),uid=99)
        anonymous['message']['sender_chat']={'id':-100123}
        self.bridge.process(anonymous,(self.handle,))
        self.assertEqual(self.jobs(),[])
        self.send('/bot off',uid=99)
        self.send(form(),uid=99)
        self.assertEqual(len(self.jobs()),1)
        self.send('/bot off',uid=1,group=None)
        self.send(form(2),uid=98)
        self.assertEqual(len(self.jobs()),1)
        self.send(form(3),uid=1,group=None)
        self.assertEqual(len(self.jobs()),2)

    def test_unlinked_expiry_lock_survives_later_link(self):
        self.send(form(),uid=99);job=self.preview()
        with self.q.db() as db:db.execute('UPDATE jobs SET created=? WHERE id=?',(time.time()-61,job['id']))
        self.send('XACNHAN '+job['id'],uid=99,callback=True)
        self.assertEqual(self.jobs()[0]['state'],'expired')
        self.link('U'+'9'*32,99)
        self.send(form(2),uid=99)
        self.assertEqual(len(self.jobs()),1)

    def test_preview_buttons_and_other_user_cannot_confirm_or_cancel(self):
        self.send(form(),uid=2);job=self.preview()
        buttons=self.api.calls[-1][1]['reply_markup']['inline_keyboard']
        self.assertEqual([x['text'] for row in buttons for x in row],['Xác nhận','Hủy'])
        for uid in (3,4):
            self.send('XACNHAN '+job['id'],uid=uid,callback=True)
            self.send('HUY '+job['id'],uid=uid,callback=True)
            self.assertEqual(self.jobs()[0]['state'],'draft')
        self.send('XACNHAN '+job['id'],uid=2,callback=True)
        self.assertEqual(self.jobs()[0]['state'],'verified_queued')
        # Repeated button clicks cannot queue a second job or call MWG directly.
        self.send('XACNHAN '+job['id'],uid=2,callback=True)
        self.assertEqual(len(self.jobs()),1)

    def test_owner_can_cancel_other_user_and_off_mode_preserved(self):
        self.send(form(),uid=2);job=self.preview()
        self.send('HUY '+job['id'],uid=1,callback=True)
        self.assertEqual(self.jobs()[0]['state'],'cancelled')
        self.send('/bot off',uid=1,group=None)
        self.send(form(2),uid=2);self.assertEqual(len(self.jobs()),1)
        self.send(form(3),uid=1,group=None);self.assertEqual(len(self.jobs()),2)

    def test_expired_confirmation_still_cancels_and_locks_member(self):
        self.send(form(),uid=2);job=self.preview()
        with self.q.db() as db:db.execute('UPDATE jobs SET created=? WHERE id=?',(time.time()-61,job['id']))
        self.send('XACNHAN '+job['id'],uid=2,callback=True)
        self.assertEqual(self.jobs()[0]['state'],'expired')
        self.send(form(2),uid=2);self.assertEqual(len(self.jobs()),1)

    def test_forward_three_edit_drop_and_submit_to_preview_only(self):
        self.send('/gom',group=None)
        for n in (1,2,3):self.send(form(n),group=None)
        self.assertEqual(self.jobs(),[])
        from co_forward import ForwardDrafts
        from co_flow import add_requester_note
        store=ForwardDrafts(self.q,OWNER,add_requester_note)
        with self.q.db() as db:
            draft=store._read(db);rows=store.snapshot(draft)['rows']
            values=dict(rows[0]['values'],quantity='2')
            store.change_row(db,draft,0,0,values);store.change_row(db,draft,1,0,remove=True)
            command=store._action(draft,'gui')
        self.send(command,group=None,callback=True)
        self.assertEqual(self.jobs()[0]['chat'],'tg:1')
        self.assertEqual(self.jobs()[0]['state'],'preview_queued')
        payload=json.loads(self.jobs()[0]['payload'])
        self.assertEqual([r['quantity'] for r in payload['items']],[2,1])
        job=self.preview();self.assertEqual(self.jobs()[0]['state'],'draft')
        self.assertIsNone(self.q.claim(True,job['id'],batch_protocol=True))

    def test_send_chunks_buttons_receipts_and_rate_limit(self):
        text=ReplyText('😀'*2500,[('Hủy','HUY 0123456789')])
        self.assertTrue(self.bridge.send('tg:1',text,'test'))
        calls=list(self.api.calls);self.assertEqual(len(calls),2)
        self.assertEqual(''.join(c[1]['text'] for c in calls),str(text))
        self.assertNotIn('reply_markup',calls[0][1]);self.assertIn('reply_markup',calls[-1][1])
        self.assertTrue(self.bridge.send('tg:1',text,'test'));self.assertEqual(self.api.calls,calls)
        self.api.fail=TelegramError(429,90)
        self.assertFalse(self.bridge.send('tg:1','Wait','rate'))
        self.api.fail=None;self.assertFalse(self.bridge.send('tg:1','Wait','rate'))

    def test_stale_message_bot_sender_other_bot_and_forged_callback_ignored(self):
        update=self.update(form());update['message']['date']=int(time.time())-301
        self.bridge.process(update,(self.handle,));self.assertEqual(self.jobs(),[])
        update=self.update(form());update['message']['from']['is_bot']=True
        self.bridge.process(update,(self.handle,));self.assertEqual(self.jobs(),[])
        self.send('/taoco@wrong_bot '+form());self.assertEqual(self.jobs(),[])
        update=self.update('HUY 0123456789',callback=True);update['callback_query']['message']['from']['id']=999
        before=len(self.api.calls);self.bridge.process(update,(self.handle,));self.assertEqual(len(self.api.calls),before)

    def test_result_delivery_uses_origin_chat_and_preserves_code(self):
        self.send('/taoco '+form(),uid=2);job=self.preview()
        self.send('XACNHAN '+job['id'],uid=2,callback=True)
        work=self.q.claim(True,job['id'],batch_protocol=True)
        self.q.update(work['id'],work['lease'],'submitting','')
        result=json.dumps([{'co':'00454CO26105838862','error':'','state':'succeeded'}])
        self.q.update(work['id'],work['lease'],'succeeded',result)
        self.notify();self.notify()
        sent=[data for method,data in self.api.calls if method=='sendMessage' and '00454CO26105838862' in data['text']]
        self.assertEqual(len(sent),1);self.assertEqual(sent[0]['chat_id'],'-100123')

    def test_cutover_redirects_new_line_forms_but_keeps_line_available_by_default(self):
        from types import SimpleNamespace
        event=SimpleNamespace(source=SimpleNamespace(user_id=OWNER,group_id=None),
            message=SimpleNamespace(text=form(),id='line1'),webhook_event_id='line1',reply_token='line-token',
            requester_name='Tâm')
        replies=[]
        app=Flask('cutover')
        handle,_=install(app,lambda token,text:replies.append(str(text)) or True,lambda *a:True,
                         requester_name=lambda e:e.requester_name)
        handle(event);self.assertEqual(self.jobs(),[]);self.assertEqual('Bot đã ngừng hỗ trợ nhận yêu cầu tạo CO trên LINE.',replies[-1])
        with patch.dict(os.environ,{'CO_INTAKE_TRANSPORT':'line'}):handle(event)
        self.assertEqual(len(self.jobs()),1);self.assertEqual(self.jobs()[0]['chat'],OWNER)

    def test_send_failure_retains_inbox_for_retry(self):
        update=self.update('/bot status',uid=1,group=None)
        headers={'X-Telegram-Bot-Api-Secret-Token':ENV['TELEGRAM_WEBHOOK_SECRET']}
        self.http.post('/telegram/webhook',json=update,headers=headers)
        self.api.fail=TelegramError(503);self.bridge.drain((self.handle,),logging.getLogger(__name__))
        with self.q.db() as db:
            row=db.execute('SELECT * FROM co_telegram_updates').fetchone()
            self.assertEqual(row['state'],'processing');self.assertNotEqual(row['payload'],'{}')
            db.execute('UPDATE co_telegram_updates SET lease=0');db.execute('UPDATE co_telegram_deliveries SET retry_at=0')
        self.api.fail=None;self.bridge.drain((self.handle,),logging.getLogger(__name__))
        with self.q.db() as db:self.assertEqual(db.execute('SELECT state FROM co_telegram_updates').fetchone()['state'],'done')


class TelegramPortalTests(unittest.TestCase):
    call=fixtures.PortalTests.call
    login=fixtures.PortalTests.login
    job=fixtures.PortalTests.job
    def setUp(self):
        fixtures.PortalTests.setUp(self)
        env=patch.dict(os.environ,ENV);env.start();self.addCleanup(env.stop)
        self.bridge=Bridge(self.q,FakeTelegram())

    def link(self,uid,tid):
        self.login(uid);response=self.call('telegram/link','POST',{});self.assertEqual(response.status_code,200)
        self.bridge.offer_link(response.json['url'].split('link_')[1],dict(id=tid,first_name='Name'))
        response=self.call('telegram/confirm','POST',{'telegram_id':str(tid)})
        self.assertEqual(response.status_code,200)

    def test_auth_csrf_origin_and_two_sided_link(self):
        self.assertEqual(self.call('telegram/link','POST',{}).status_code,401)
        self.login(OWNER)
        for headers in ({'X-Tao-CSRF':''},{'Origin':'https://evil.test'}):
            self.assertEqual(self.call('telegram/link','POST',{},headers).status_code,403)
        response=self.call('telegram/link','POST',{});token=response.json['url'].split('link_')[1]
        self.bridge.offer_link(token,dict(id=1,first_name='Tâm'))
        self.assertIsNone(self.bridge.linked(OWNER))
        self.login(fixtures.MEMBER)
        self.assertEqual(self.call('telegram/confirm','POST',{'telegram_id':'1'}).status_code,409)
        self.login(OWNER);self.assertEqual(self.call('telegram/confirm','POST',{'telegram_id':'1'}).status_code,200)
        self.assertEqual(self.call('me').json['telegram']['linked']['id'],'1')

    def test_liff_submit_routes_telegram_and_requires_membership(self):
        self.link(fixtures.MEMBER,2)
        rows=self.call('compose/parse','POST',{'text':form()}).json['rows']
        with patch.object(Bridge,'verify_member',side_effect=ValueError('not member')):
            response=self.call('compose/submit','POST',{'key':'a'*32,'scope':'group','rows':rows})
            self.assertEqual(response.status_code,403)
        with patch.object(Bridge,'verify_member',return_value=None):
            response=self.call('compose/submit','POST',{'key':'a'*32,'scope':'group','rows':rows})
        self.assertEqual(response.status_code,200)
        with self.q.db() as db:
            job=db.execute('SELECT * FROM jobs').fetchone()
            self.assertEqual((job['chat'],job['owner'],job['state']),('tg:-100123',fixtures.MEMBER,'preview_queued'))

    def test_shared_basket_liff_routes_owner_telegram(self):
        self.link(OWNER,1)
        draft=self.call('forward-draft/start','POST',{'id':None,'revision':0}).json['draft']
        from co_forward import ForwardDrafts
        from co_flow import add_requester_note
        store=ForwardDrafts(self.q,OWNER,add_requester_note)
        with self.q.db() as db:store._append(db,store._read(db),form(),time.time())
        draft=self.call('forward-draft').json['draft']
        response=self.call('forward-draft/submit','POST',{k:draft[k] for k in ('id','revision')})
        self.assertEqual(response.status_code,200)
        with self.q.db() as db:self.assertEqual(db.execute('SELECT chat FROM jobs').fetchone()['chat'],'tg:1')

