import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import mac_worker as w
from co_flow import Queue, BotUnavailable
from co_health import readiness, validate_health


class LoadingHealthTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.page = MagicMock()
        self.page.url = w.URL
        self.page.is_closed.return_value = False
        self.guard = w.RecoveryGuard(self.page)
        self.clock = 100.0
        for target, value in [('ROOT', self.root), ('api', MagicMock(return_value={'states': {}}))]:
            patcher = patch.object(w, target, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = patch.object(w.time, 'monotonic', side_effect=lambda: self.clock)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_pending_data_stays_loading_then_slow_without_fake_readiness(self):
        self.guard.pending.add(object())
        self.assertFalse(self.guard.ready())
        self.assertEqual(self.guard.page_health(False), 'loading')
        self.assertFalse(w.recover_idle_controls(self.page, self.guard))
        self.clock += 14.9
        self.assertEqual(self.guard.page_health(False), 'loading')
        self.clock += .1
        self.assertEqual(self.guard.page_health(False), 'loading_slow')
        self.clock += 300
        self.assertEqual(self.guard.page_health(False), 'loading_slow')
        self.assertFalse(self.guard.repair_failed)
        self.page.reload.assert_not_called()
        self.page.get_by_role.return_value.click.assert_not_called()

    def test_loading_reason_changes_do_not_restart_timer_and_ready_clears_it(self):
        for delta, reason in [(0, 'Còn kết nối dữ liệu'), (10, 'Ô trạng thái trống'), (6, 'Loading')]:
            self.clock += delta
            with patch.object(self.guard, 'readiness_reason', return_value=reason):
                self.assertFalse(self.guard.ready())
                state = self.guard.page_health(False)
        self.assertEqual(state, 'loading_slow')
        self.guard.repair_failed = True
        with patch.object(self.guard, 'readiness_reason', return_value=None):
            self.assertTrue(self.guard.ready())
        self.assertEqual(self.guard.page_health(True), 'ready')
        self.clock += 100
        self.assertEqual(self.guard.page_health(False), 'loading')
        self.assertFalse(self.guard.repair_failed)

    def test_only_exhausted_idle_repair_marks_loading_as_blocked(self):
        self.guard.page_health(False)
        with patch.object(self.guard, 'ready', return_value=False), \
             patch.object(self.guard, 'wait_ready', return_value=False) as wait, \
             patch.object(w, 'select_brands'), patch.object(w, 'capture_failure'):
            self.assertFalse(w.recover_idle_controls(self.page, self.guard))
        self.assertEqual(wait.call_count, 5)
        self.assertTrue(all(call.kwargs['timeout'] == 7 for call in wait.call_args_list))
        self.assertEqual(self.page.reload.call_count, 4)
        self.assertEqual(self.guard.page_health(False), 'blocked')
        self.assertEqual(self.guard.page_health(True), 'ready')
        self.assertFalse(self.guard.repair_failed)

    def test_preview_and_submit_barriers_hold_even_after_loading_grace(self):
        for state in ('draft', 'preview_running', 'running', 'submitting'):
            with self.subTest(state=state), patch.object(w, 'api', return_value={'states': {state: 1}}):
                self.guard.page_health(False)
                self.clock += 60
                self.assertEqual(self.guard.page_health(False), 'loading_slow')
                self.assertFalse(w.recover_idle_controls(self.page, self.guard))
                self.assertFalse(w.refresh_idle(self.page, self.guard))
                self.assertFalse(self.guard.repair_failed)
        self.assertFalse(w.recover_idle_controls(self.page, self.guard, 'prepared'))
        self.assertEqual(self.guard.page_health(True, 'prepared'), 'awaiting_confirmation')
        self.page.reload.assert_not_called()
        self.page.goto.assert_not_called()
        self.page.get_by_role.return_value.click.assert_not_called()

    def test_unknown_result_and_closed_page_remain_real_blocks(self):
        self.guard.uncertain_job = 'unknown-co'
        self.assertEqual(self.guard.page_health(False), 'blocked')
        self.assertFalse(w.recover_idle_controls(self.page, self.guard))
        self.guard.uncertain_job = None
        self.guard.late_submissions.append(object())
        self.assertEqual(self.guard.page_health(False), 'blocked')
        self.assertFalse(w.refresh_idle(self.page, self.guard))
        self.guard.late_submissions.clear()
        self.page.is_closed.return_value = True
        self.assertEqual(self.guard.page_health(False), 'blocked')
        self.page.reload.assert_not_called()

    def test_login_has_separate_status_and_resets_loading_timer(self):
        self.guard.page_health(False)
        self.clock += 20
        self.page.url = 'https://login.example/'
        self.assertEqual(self.guard.page_health(False), 'login')
        self.page.url = w.URL
        self.assertEqual(self.guard.page_health(False), 'loading')

    def test_server_reports_slow_loading_and_does_not_accept_or_claim(self):
        queue = Queue(str(self.root / 'queue.db'))
        payload = dict(source='1', destination='2', product='0131491005414', quantity=1, note='')
        queued = queue.draft('old', 'owner', 'chat', payload, check_product=True)
        health = {'state': 'loading_slow', 'progress_age_seconds': 0}
        validate_health(health)
        queue.heartbeat(True, health)
        with self.assertRaisesRegex(BotUnavailable, 'MWG tải chậm'):
            queue.draft('new', 'owner', 'chat', payload, require_online=True)
        self.assertIsNone(queue.claim(require_online=True, preview_protocol=True))
        with queue.db() as db:
            status = readiness(db)
            self.assertEqual(db.execute('SELECT state FROM jobs WHERE id=?', (queued['id'],)).fetchone()['state'], 'preview_queued')
        self.assertTrue(status['online'])
        self.assertFalse(status['accepting'])
        self.assertEqual(status['worker_label'], 'MWG tải chậm / đang chờ dữ liệu')

    def test_live_loop_no_longer_overwrites_loading_with_blocked(self):
        self.guard.pending.add(object())
        runtime = MagicMock()
        context = MagicMock()
        manager = MagicMock()
        module = types.SimpleNamespace(sync_playwright=lambda: manager)
        self.page.wait_for_timeout.side_effect = SystemExit(0)
        with patch.object(w, 'Runtime', return_value=runtime), \
             patch.object(w, 'start_heartbeat', return_value=MagicMock()), \
             patch.object(w, 'open_browser', return_value=(context, self.page)), \
             patch.object(w, 'RecoveryGuard', return_value=self.guard), \
             patch.object(w, 'claim_with_reconnect', return_value=None), \
             patch('sys.argv', ['worker', '--live']), \
             patch.dict('sys.modules', {'playwright.sync_api': module}):
            with self.assertRaises(SystemExit):
                w.main()
        states = [call.args[0] for call in runtime.set.call_args_list]
        self.assertIn('loading', states)
        self.assertNotIn('blocked', states)
        self.page.reload.assert_not_called()
        self.page.get_by_role.return_value.click.assert_not_called()


if __name__ == '__main__':
    unittest.main()
