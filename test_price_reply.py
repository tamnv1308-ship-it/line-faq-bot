import copy
import base64
import hashlib
import hmac
import json
import os
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from flask import Flask
from co_results import message_chunks
from price_reply import NOTE_GROUP, install, render_report, render_cards, sync_key, validate_snapshot


def sample(n=1):
    return dict(version=1, scope='all_kdbt', checked=datetime.now(timezone.utc).isoformat(), items=[
        dict(sku=str(100+i), name=f'MacBook Air M5 16GB 512GB Bạc {i}', retailer=r,
             mw_price=33_690_000, price=33_190_000 if r=='FPT' else 33_690_000)
        for i in range(n) for r in ('FPT', 'CPS')])


class PriceReplyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.env = patch.dict(os.environ, CO_DATABASE_URL='', CO_DB_PATH=str(Path(self.tmp.name)/'bot.db'), CO_WORKER_TOKEN='test-key-'*8)
        self.env.start(); self.addCleanup(self.env.stop)
        self.app = Flask(__name__); self.reply = Mock(return_value=True); self.verify = Mock(return_value=True)
        self.handle = install(self.app, self.reply, self.verify)
        self.client = self.app.test_client()
        self.headers = {'Authorization': 'Bearer '+sync_key('test-key-'*8)}

    def upload(self, data=None):
        return self.client.put('/price/report', json=data or sample(), headers=self.headers)

    def event(self, text='!gia', group=NOTE_GROUP, event='event1'):
        return SimpleNamespace(message=SimpleNamespace(text=text, id='message1'), source=SimpleNamespace(group_id=group),
                               reply_token='reply-token-test', webhook_event_id=event)

    def test_protected_api_and_scoped_key(self):
        self.assertEqual(self.client.put('/price/report', json=sample()).status_code, 401)
        self.assertEqual(self.client.get('/price/status').status_code, 401)
        self.assertEqual(self.client.put('/price/report', json=sample(), headers={'Authorization':'Bearer '+'test-key-'*8}).status_code, 401)
        self.assertEqual(self.upload().status_code, 200)
        self.assertEqual(self.client.get('/price/status', headers=self.headers).json['products'], 1)

    def test_note_reply_no_push_and_webhook_redelivery(self):
        self.upload(); self.handle(self.event()); self.handle(self.event())
        self.reply.assert_called_once()
        token, text = self.reply.call_args.args
        self.assertEqual(token, 'reply-token-test')
        self.assertIn('rẻ hơn MW 500.000đ', text); self.assertIn('bằng MW', text)
        self.assertIsNotNone(self.client.get('/price/status', headers=self.headers).json['last_reply'])

    def test_other_groups_and_unverified_note_are_silent(self):
        for group in ('CO', 'Ca6ebad8571ec436ed0cc4a68729d22c0', None):
            self.assertTrue(self.handle(self.event(group=group)))
        self.verify.assert_not_called(); self.reply.assert_not_called()
        self.verify.return_value = False
        self.handle(self.event()); self.reply.assert_not_called()
        self.assertFalse(self.handle(self.event('!giay')))

    def test_failed_reply_can_retry_without_push_fallback(self):
        self.upload(); self.reply.return_value=False
        self.handle(self.event())
        self.assertIsNone(self.client.get('/price/status', headers=self.headers).json['last_reply'])
        self.reply.return_value=True; self.handle(self.event())
        self.assertEqual(self.reply.call_count, 2)

    def test_pagination_search_and_actual_line_limits(self):
        self.upload(sample(65)); self.handle(self.event('!gia 7'))
        text=self.reply.call_args.args[1]
        self.assertIn('Trang 7/7', text); self.assertEqual(text.count('\nMW:'),5)
        self.handle(self.event('!gia bac 64', event='search'))
        self.assertIn('1 sản phẩm', self.reply.call_args.args[1])
        extreme=sample(10)
        for i in extreme['items']:i['name']='😀'*500
        chunks=message_chunks(render_report(validate_snapshot(extreme)))
        self.assertLessEqual(len(chunks),5)
        self.assertTrue(all(len(c.encode('utf-16-le'))//2<=4500 for c in chunks))

    def test_stale_empty_and_invalid_page(self):
        old=sample();old['checked']=(datetime.now(timezone.utc)-timedelta(days=2)).isoformat()
        self.assertIn('quá 18 giờ', render_report(validate_snapshot(old)))
        self.assertIn('Chưa có báo cáo', render_report(None))
        self.assertIn('chưa có sản phẩm', render_report(validate_snapshot(dict(sample(),items=[]))))
        self.assertIn('Dùng !gia', render_report(validate_snapshot(sample()), '0'))

    def test_reject_partial_future_invalid_price_conflicts_and_oversize(self):
        for change in (dict(scope='selected_rows'),dict(checked=(datetime.now(timezone.utc)+timedelta(days=1)).isoformat())):
            self.assertEqual(self.upload(dict(sample(),**change)).status_code,400)
        for price in (True, -1, '33190000'):
            data=sample();data['items'][0]['price']=price
            self.assertEqual(self.upload(data).status_code,400)
        data=sample();data['items'][1]['mw_price']+=100000
        self.assertEqual(self.upload(data).status_code,400)
        self.assertEqual(self.client.put('/price/report',data=b'x'*300001,headers=self.headers).status_code,413)

    def test_idempotent_upload_and_older_report_cannot_replace_newer(self):
        data=sample();self.assertEqual(self.upload(data).status_code,200)
        self.assertEqual(self.upload(data).status_code,200)
        conflict=copy.deepcopy(data);conflict['items'][0]['price']+=10000
        self.assertEqual(self.upload(conflict).status_code,409)
        old=copy.deepcopy(data);old['checked']=(datetime.now(timezone.utc)-timedelta(hours=1)).isoformat()
        self.assertEqual(self.upload(old).status_code,409)

    def test_cards_keep_prices_and_navigation_within_line_limits(self):
        from linebot.v3.messaging import FlexMessage
        data=sample(65)
        cards=render_cards(validate_snapshot(data),'air /2')
        bubbles=[b for m in cards for b in m['contents']['contents']]
        self.assertEqual(len(bubbles),10)
        serialized=json.dumps(cards,ensure_ascii=False)
        self.assertIn('33.690.000đ',serialized)
        self.assertIn('Rẻ hơn MW 500.000đ',serialized)
        self.assertIn('!gia air /1',serialized);self.assertIn('!gia air /3',serialized)
        for item in data['items']:item['name']='😀'*500
        for message in render_cards(validate_snapshot(data)):
            self.assertLess(len(json.dumps(message,ensure_ascii=False).encode()),50000)
            self.assertLessEqual(len(message['contents']['contents']),12)
            self.assertEqual(FlexMessage.from_dict(message).type,'flex')
        single=sample();single['items']=single['items'][:1]
        self.assertNotIn('CellphoneS',json.dumps(render_cards(validate_snapshot(single)),ensure_ascii=False))
        self.assertIsNone(render_cards(validate_snapshot(single),'no-match'))

    def test_failed_card_reply_never_falls_back_to_another_send(self):
        cards=Mock(return_value=False)
        app=Flask('price-card-failure')
        handle=install(app,self.reply,self.verify,reply_cards=cards)
        self.upload()
        handle(self.event())
        cards.assert_called_once();self.reply.assert_not_called()


class SignedWebhookTests(unittest.TestCase):
    def test_signed_note_command_uses_reply_api_and_bad_signature_is_rejected(self):
        import importlib
        import sys
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {
            'CO_ENABLED':'0', 'CO_DATABASE_URL':'', 'CO_DB_PATH':str(Path(tmp)/'bot.db'),
            'CO_WORKER_TOKEN':'test-key-'*8, 'CHANNEL_ACCESS_TOKEN':'test-access-token',
            'CHANNEL_SECRET':'test-channel-secret'}), patch('apscheduler.schedulers.background.BackgroundScheduler.start'):
            sys.modules.pop('app',None);sys.modules.pop('config',None)
            app_module=importlib.import_module('app')
            self.addCleanup(lambda:sys.modules.pop('app',None))
            self.addCleanup(lambda:sys.modules.pop('config',None))
            client=app_module.app.test_client()
            self.assertEqual(client.put('/price/report',json=sample(),headers={
                'Authorization':'Bearer '+sync_key('test-key-'*8)}).status_code,200)
            body=json.dumps({'destination':'U'+'1'*32,'events':[{
                'type':'message','mode':'active','timestamp':int(time.time()*1000),
                'source':{'type':'group','groupId':NOTE_GROUP,'userId':'U'+'2'*32},
                'webhookEventId':'signed-gia-event','deliveryContext':{'isRedelivery':False},
                'replyToken':'r'*32,'message':{'type':'text','id':'123','text':'!gia','quoteToken':'q'*32}}]})
            signature=base64.b64encode(hmac.new(b'test-channel-secret',body.encode(),hashlib.sha256).digest()).decode()
            with patch.object(app_module,'MessagingApi') as api:
                api.return_value.get_group_summary.return_value=SimpleNamespace(group_id=NOTE_GROUP,group_name='NOTE')
                api.return_value.reply_message.return_value=SimpleNamespace(sent_messages=[])
                response=client.post('/callback',data=body,headers={'X-Line-Signature':signature,'Content-Type':'application/json'})
                self.assertEqual(response.status_code,200)
                api.return_value.reply_message.assert_called_once()
                api.return_value.push_message.assert_not_called()
                payload=api.return_value.reply_message.call_args.args[0]
                self.assertEqual(payload.messages[0].type,'flex')
                self.assertIn('Giá Apple',payload.messages[0].alt_text)
                self.assertEqual(client.post('/callback',data=body,headers={'X-Line-Signature':'invalid'}).status_code,400)
                api.return_value.reply_message.assert_called_once()


if __name__=='__main__': unittest.main()
