import concurrent.futures
import time
import unittest
from unittest.mock import patch

from bao_tri.kiem_thu import test_telegram_bridge as fixtures
from telegram_bridge import TelegramError


class SingleUseButtonsTests(unittest.TestCase):
    setUp=fixtures.TelegramTests.setUp
    link=fixtures.TelegramTests.link
    update=fixtures.TelegramTests.update
    send=fixtures.TelegramTests.send
    jobs=fixtures.TelegramTests.jobs
    preview=fixtures.TelegramTests.preview

    def prepare(self,uid=99):
        self.send(fixtures.form(),uid=uid)
        return self.preview()

    def edits(self):return [p for m,p in self.api.calls if m=='editMessageReplyMarkup']
    def messages(self):return [p for m,p in self.api.calls if m=='sendMessage']
    def toast(self):return [p for m,p in self.api.calls if m=='answerCallbackQuery'][-1]

    def test_confirm_once_removes_both_buttons_and_repeated_or_opposite_click_is_noop(self):
        job=self.prepare();before=len(self.messages())
        self.send('XACNHAN '+job['id'],uid=99,callback=True)
        self.assertEqual(self.jobs()[0]['state'],'verified_queued')
        self.assertTrue(self.edits())
        self.assertEqual(self.edits()[-1]['reply_markup'],{'inline_keyboard':[]})
        self.assertIn('Đã xác nhận',self.toast()['text'])
        for action in ('XACNHAN','XACNHAN','HUY'):
            self.send(action+' '+job['id'],uid=99,callback=True)
            self.assertEqual(self.jobs()[0]['state'],'verified_queued')
        self.assertEqual(len(self.messages()),before)
        self.assertEqual(len(self.jobs()),1)

    def test_cancel_once_sends_one_receipt_and_cannot_be_confirmed_afterwards(self):
        job=self.prepare();before=len(self.messages())
        self.send('HUY '+job['id'],uid=99,callback=True)
        self.assertEqual(self.jobs()[0]['state'],'cancelled')
        self.assertEqual(len(self.messages()),before+1)
        for action in ('HUY','XACNHAN'):
            self.send(action+' '+job['id'],uid=99,callback=True)
        self.assertEqual(self.jobs()[0]['state'],'cancelled')
        self.assertEqual(len(self.messages()),before+1)

    def test_unauthorized_click_does_not_consume_or_remove_any_button(self):
        job=self.prepare()
        for action in ('HUY','XACNHAN'):
            self.send(action+' '+job['id'],uid=98,callback=True)
            self.assertEqual(self.jobs()[0]['state'],'draft')
            self.assertEqual(self.edits(),[])
            self.assertTrue(self.toast()['show_alert'])
        self.send('XACNHAN '+job['id'],uid=99,callback=True)
        self.assertEqual(self.jobs()[0]['state'],'verified_queued')

    def test_both_pinned_owner_identities_can_act_once_on_others(self):
        with self.q.db() as db:
            for tid in ('8942989524','1926022040'):
                db.execute('INSERT INTO co_telegram_identities VALUES(?,?)',(tid,fixtures.OWNER))
        for n,uid in enumerate((8942989524,1926022040),1):
            self.send(fixtures.form(n),uid=99)
            job=self.preview()
            self.send('HUY '+job['id'],uid=uid,callback=True)
            found=next(j for j in self.jobs() if j['id']==job['id'])
            self.assertEqual(found['state'],'cancelled')
            self.assertIn('Đã hủy',self.toast()['text'])

    def test_simultaneous_confirm_and_cancel_have_only_one_winner(self):
        job=self.prepare()
        def act(cancel):
            outcome={}
            self.q.confirm(job['id'],'telegram:99','tg:-100123',cancel=cancel,button_result=outcome)
            return outcome
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(act,(False,True)))
        self.assertCountEqual([x['status'] for x in results],['accepted','already'])
        self.assertIn(self.jobs()[0]['state'],('verified_queued','cancelled'))

    def test_offline_rejection_keeps_buttons_and_allows_retry_when_ready(self):
        job=self.prepare();self.q.heartbeat(False)
        self.send('XACNHAN '+job['id'],uid=99,callback=True)
        self.assertEqual(self.jobs()[0]['state'],'draft')
        self.assertFalse(self.edits());self.assertTrue(self.toast()['show_alert'])
        self.q.heartbeat()
        self.send('XACNHAN '+job['id'],uid=99,callback=True)
        self.assertEqual(self.jobs()[0]['state'],'verified_queued')

    def test_edit_network_failure_does_not_repeat_business_action(self):
        job=self.prepare();original=self.api.call
        def failed(method,payload):
            if method=='editMessageReplyMarkup':raise TelegramError(503)
            return original(method,payload)
        with patch.object(self.api,'call',side_effect=failed):
            self.send('XACNHAN '+job['id'],uid=99,callback=True)
        self.assertEqual(self.jobs()[0]['state'],'verified_queued')
        self.send('HUY '+job['id'],uid=99,callback=True)
        self.assertEqual(self.jobs()[0]['state'],'verified_queued')
        with self.q.db() as db:db.execute('UPDATE co_telegram_co_buttons SET retry_at=0')
        self.bridge.retire_co_buttons()
        self.assertTrue(self.edits())

    def test_expired_or_text_cancelled_form_loses_buttons_without_mutating_jobs(self):
        job=self.prepare()
        with self.q.db() as db:db.execute('UPDATE jobs SET created=? WHERE id=?',(time.time()-61,job['id']))
        self.bridge.retire_co_buttons()
        self.assertTrue(self.edits())
        self.assertEqual(self.jobs()[0]['state'],'draft')  # UI cleanup itself cannot change jobs.
        self.send('XACNHAN '+job['id'],uid=99,callback=True)
        self.assertEqual(self.jobs()[0]['state'],'expired')
        self.assertIn('hết hạn',self.toast()['text'])

    def test_text_and_liff_cancel_permissions_unchanged_after_confirm(self):
        job=self.prepare()
        self.send('XACNHAN '+job['id'],uid=99,callback=True)
        self.send('HUY '+job['id'],uid=98)
        self.assertEqual(self.jobs()[0]['state'],'verified_queued')
        self.send('HUY '+job['id'],uid=1)
        self.assertEqual(self.jobs()[0]['state'],'cancelled')


if __name__=='__main__':unittest.main()
