import io
import json
import os
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

import co_form_assist as ai
from bao_tri.kiem_thu.test_telegram_bridge import TelegramTests, form

BAD='Kho xuất: 3945\nKho nhận: 447\nMSP: 013149100541\nQL cho hàng: Anh A 12345'


def plan_for(bundle):
    return {'rows':[{key:next((f['id'] for f in bundle['fields'] if f['field']==key),None) for key in ai.FIELDS}]}


class ReferenceTests(unittest.TestCase):
    def test_no_notes_credentials_or_customer_details_go_to_provider(self):
        bundle=ai.extract(BAD+'\nIMEI: 123456789012345\nSĐT: 0901234567\nNote: private contact\nToken: 123456789:abcdefghijklmnopqrstuvwxyz')
        outgoing=json.dumps(bundle['fields'])
        for secret in ('Anh A','12345','private contact','0901234567','123456789012345','abcdefghijklmnopqrstuvwxyz'):
            self.assertNotIn(secret,outgoing)
        self.assertIn('Anh A',json.dumps(bundle['notes']))

    def test_no_invented_product_and_defaults_explicit(self):
        bundle=ai.extract(BAD)
        result=ai.render(bundle,plan_for(bundle),'abc123')
        self.assertIn('cần đúng 13 số',result)
        self.assertIn('[BỔ SUNG MÃ SẢN PHẨM]',result)
        self.assertIn('Kho xuất: 3945',result)
        self.assertIn('Số lượng: 1',result)
        self.assertIn('Trạng thái: Mới',result)
        self.assertIn('QL cho hàng: Anh A 12345',result)

    def test_reject_swapped_reused_invented_dropped_and_boolean_references(self):
        bundle=ai.extract(BAD)
        for change in ({'source':2},{'product':999},{'source':None},{'source':True}):
            p=plan_for(bundle);p['rows'][0].update(change)
            with self.assertRaises(ai.AssistError):ai.render(bundle,p,'x')
        p=plan_for(bundle);p['rows']*=2
        with self.assertRaises(ai.AssistError):ai.render(bundle,p,'x')

    def test_multiple_requests_keep_order_and_notes(self):
        bundle=ai.extract(BAD+'\n\nKho xuất: 100\nKho nhận: 200\nMSP: 0131491005415\nNote: second')
        p={'rows':[{key:next((f['id'] for f in bundle['fields'][n:n+3] if f['field']==key),None) for key in ai.FIELDS} for n in (0,3)]}
        result=ai.render(bundle,p,'x')
        self.assertLess(result.index('3945'),result.index('100'))
        self.assertLess(result.index('Anh A'),result.index('Kho xuất: 100'))
        p['rows'].reverse()
        with self.assertRaises(ai.AssistError):ai.render(bundle,p,'x')

    def test_missing_quantity_is_not_used_when_explicit_invalid(self):
        bundle=ai.extract(BAD+'\nSL: 0\nTrạng thái: sai')
        result=ai.render(bundle,plan_for(bundle),'x')
        self.assertNotIn('Số lượng: 1',result)
        self.assertNotIn('Trạng thái: Mới',result)

    def test_refusal_and_incomplete_never_become_message(self):
        for data in ({'status':'incomplete'},{'status':'completed','output':[{'type':'message','content':[{'type':'refusal','refusal':'unsafe text'}]}]}):
            with patch.dict(os.environ,OPENAI_API_KEY='test'),patch.object(ai,'urlopen',return_value=io.BytesIO(json.dumps(data).encode())):
                with self.assertRaises(ai.AssistError):ai.request_plan(ai.extract(BAD))

    def test_http_error_has_only_safe_code(self):
        error=HTTPError('https://api.openai.com',429,'private',{},io.BytesIO(b'{"error":{"code":"insufficient_quota","message":"secret"}}'))
        with patch.dict(os.environ,OPENAI_API_KEY='test'),patch.object(ai,'urlopen',side_effect=error):
            with self.assertRaisesRegex(ai.AssistError,'^insufficient_quota$'):ai.request_plan(ai.extract(BAD))

    def test_credit_exhaustion_distinct_from_transient_rate_limit(self):
        for code in ('credit_balance_exhausted','rate_limit_exceeded'):
            error=HTTPError('https://api.openai.com',429,'private',{},io.BytesIO(json.dumps({'error':{'code':code}}).encode()))
            with patch.dict(os.environ,OPENAI_API_KEY='test'),patch.object(ai,'urlopen',side_effect=error):
                with self.assertRaisesRegex(ai.AssistError,'^'+code+'$'):ai.request_plan(ai.extract(BAD))


class IntegrationTests(TelegramTests):
    # Reuse authorization/queue fixtures; these tests use a temporary DB and fake Telegram.
    def setUp(self):
        super().setUp()
        p=patch.dict(os.environ,AI_FORM_ASSIST_ENABLED='1',OPENAI_API_KEY='test')
        p.start();self.addCleanup(p.stop)
        self.ai=self.app.extensions['co_form_assist']

    def test_invalid_form_suggests_without_create_and_valid_form_remains_fast(self):
        with patch.object(ai,'request_plan',side_effect=lambda b:plan_for(b)) as call:
            self.send(BAD,uid=99)
            self.assertEqual(call.call_count,0)
            self.assertEqual(self.jobs(),[])
            self.ai.drain()
            self.assertEqual(call.call_count,1)
            self.assertEqual(self.jobs(),[])
            self.assertIn('Gợi ý sửa form',self.api.calls[-1][1]['text'])
            self.send(form(),uid=98)
            self.assertEqual(len(self.jobs()),1)
            self.assertEqual(self.jobs()[0]['state'],'preview_queued')
            self.assertEqual(call.call_count,1)

    def test_no_ai_for_unauthorized_group_dm_or_commands(self):
        for kwargs in ({'uid':99,'group':None},{'uid':99,'group':-999}):self.send(BAD,**kwargs)
        self.send('XACNHAN 1234567890',uid=99)
        self.send('HUY 1234567890',uid=99)
        with self.q.db() as db:self.assertEqual(db.execute('SELECT COUNT(*) n FROM co_form_assists').fetchone()['n'],0)

    def test_rate_limit_replay_off_mode_and_locked_users(self):
        update=self.send(BAD,uid=99);self.bridge.process(update,(self.handle,))
        self.send(BAD,uid=99)
        self.q.admin('BOT OFF');self.send(BAD,uid=98)
        with self.q.db() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) n FROM co_form_assists').fetchone()['n'],1)
        self.send(BAD,uid=1)
        with self.q.db() as db:self.assertEqual(db.execute('SELECT COUNT(*) n FROM co_form_assists').fetchone()['n'],2)

    def test_timeout_isolated_and_next_real_queue_entry_unaffected(self):
        self.send(BAD,uid=99)
        with patch.object(ai,'request_plan',side_effect=ai.AssistError('network_or_response')):
            self.ai.drain()
        self.send(form(),uid=98)
        self.assertEqual(self.jobs()[0]['state'],'preview_queued')
        self.assertIn('Chưa có gợi ý',self.api.calls[-1][1]['text'])

    def test_delivery_retry_does_not_repeat_api_call(self):
        self.send(BAD,uid=99)
        with patch.object(ai,'request_plan',side_effect=lambda b:plan_for(b)) as call:
            with patch.object(self.ai,'reply',side_effect=OSError()):self.ai.drain()
            with self.q.db() as db:db.execute('UPDATE co_form_assists SET lease=0')
            self.ai.drain()
            self.assertEqual(call.call_count,1)

    def test_expired_work_is_purged_without_api_or_co(self):
        self.send(BAD,uid=99)
        with self.q.db() as db:db.execute('UPDATE co_form_assists SET created=0')
        with patch.object(ai,'request_plan') as call:self.ai.drain();call.assert_not_called()
        self.assertEqual(self.jobs(),[])

    def test_disabled_and_locked_users_never_enqueue_assist(self):
        with patch.dict(os.environ,AI_FORM_ASSIST_ENABLED='0'):self.send(BAD,uid=99)
        with self.q.db() as db:
            db.execute("INSERT INTO co_confirmation_locks VALUES(?,?,3,0,?,?)",('telegram:99','test','old',0))
        self.send(BAD,uid=99)
        with self.q.db() as db:self.assertEqual(db.execute('SELECT COUNT(*) n FROM co_form_assists').fetchone()['n'],0)

    def test_unknown_business_error_is_not_sent_to_ai(self):
        # A valid form denied by intake controls is not a form-repair problem.
        self.q.admin('BOT OFF')
        self.send(form(),uid=99)
        with self.q.db() as db:self.assertEqual(db.execute('SELECT COUNT(*) n FROM co_form_assists').fetchone()['n'],0)
        self.assertEqual(self.jobs(),[])


if __name__=='__main__':unittest.main()
