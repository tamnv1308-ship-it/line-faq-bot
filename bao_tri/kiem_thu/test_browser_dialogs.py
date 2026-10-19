import json
import unittest
from unittest.mock import MagicMock

from browser_dialogs import install_dialogs


class DialogTests(unittest.TestCase):
    def setUp(self):
        self.context=MagicMock();self.events={};self.diagnostic=MagicMock()
        self.context.on.side_effect=lambda name,fn:self.events.setdefault(name,fn)
        self.broker=install_dialogs(self.context,self.diagnostic)

    def dialog(self,page,kind='alert',message='Lỗi mô phỏng'):
        return MagicMock(page=page,type=kind,message=message)

    def test_one_lifetime_listener_even_after_multiple_jobs(self):
        page=MagicMock()
        old=self.broker.begin(page,'job1')
        self.events['dialog'](self.dialog(page,message='old'))
        new=install_dialogs(self.context).begin(page,'job2')
        self.events['dialog'](self.dialog(page,message='new'))
        self.assertEqual(old,['old']);self.assertEqual(new,['new'])
        self.assertEqual([c.args[0] for c in self.context.on.call_args_list].count('dialog'),1)
        self.context.remove_listener.assert_not_called()

    def test_late_dialog_on_preserved_page_is_not_assigned_to_next_job(self):
        old_page,new_page=MagicMock(),MagicMock()
        old=self.broker.begin(old_page,'unknown1');new=self.broker.begin(new_page,'next2')
        dialog=self.dialog(old_page,message='late after timeout')
        self.events['dialog'](dialog)
        self.assertEqual(old,['late after timeout']);self.assertEqual(new,[])
        dialog.accept.assert_called_once()
        for page in (old_page,new_page):
            page.reload.assert_not_called();page.goto.assert_not_called();page.close.assert_not_called()

    def test_duplicate_dialog_event_is_handled_once(self):
        page=MagicMock();alerts=self.broker.begin(page,'job')
        dialog=self.dialog(page)
        self.events['dialog'](dialog);self.events['dialog'](dialog)
        dialog.accept.assert_called_once();self.assertEqual(len(alerts),1)

    def test_only_informational_alerts_are_accepted(self):
        for kind in ('confirm','prompt','beforeunload'):
            dialog=self.dialog(MagicMock(),kind)
            self.events['dialog'](dialog)
            dialog.dismiss.assert_called_once();dialog.accept.assert_not_called()

    def test_already_closed_dialog_never_retries_or_exposes_text(self):
        dialog=self.dialog(MagicMock(),message='private form text')
        dialog.accept.side_effect=RuntimeError('Protocol error: No dialog is showing; secret')
        self.events['dialog'](dialog);self.events['dialog'](dialog)
        dialog.accept.assert_called_once()
        event=self.diagnostic.call_args.args[0]
        self.assertEqual(event['event'],'dialog_already_closed')
        self.assertNotIn('private',json.dumps(event));self.assertNotIn('secret',json.dumps(event))

    def test_unexpected_handler_error_and_logger_error_cannot_escape(self):
        dialog=self.dialog(MagicMock());dialog.accept.side_effect=ConnectionError('private')
        self.diagnostic.side_effect=OSError('disk unavailable')
        self.events['dialog'](dialog)
        self.assertEqual(self.diagnostic.call_args.args[0]['event'],'dialog_handler_error')
        dialog.accept.assert_called_once()

    def test_buffer_bounded_and_context_close_releases_sessions(self):
        page=MagicMock();alerts=self.broker.begin(page,'job')
        for n in range(25):self.events['dialog'](self.dialog(page,message=str(n)))
        self.assertEqual(alerts,[str(n) for n in range(5,25)])
        self.events['close']();self.assertEqual(len(self.broker.sessions),0)


if __name__=='__main__':unittest.main()
