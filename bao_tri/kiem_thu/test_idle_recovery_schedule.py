import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import mac_worker as w


class IdleRecoveryScheduleTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.clock = 0.0
        self.page = MagicMock()
        self.page.url = w.URL
        self.page.is_closed.return_value = False
        self.guard = w.RecoveryGuard(self.page)
        self.reason = 'Ô trạng thái sản phẩm chưa sẵn sàng.'
        self.api = MagicMock(return_value={'states': {}})
        self.brands = MagicMock()
        for target, value in [('ROOT', self.root), ('api', self.api),
                              ('select_brands', self.brands), ('capture_failure', MagicMock())]:
            patcher = patch.object(w, target, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        for target, attr, kwargs in [
            (w.time, 'monotonic', {'side_effect': lambda: self.clock}),
            (self.guard, 'readiness_reason', {'side_effect': lambda: self.reason}),
        ]:
            patcher = patch.object(target, attr, **kwargs)
            patcher.start()
            self.addCleanup(patcher.stop)

    def step(self, seconds=0, prepared=None):
        self.clock += seconds
        return w.recover_idle_controls(self.page, self.guard, prepared)

    def test_waits_before_first_retry_and_between_retries_instead_of_five_minutes(self):
        self.assertFalse(self.step())
        self.assertFalse(self.step(14.9))
        self.brands.assert_not_called()
        self.assertFalse(self.step(.1))
        self.assertEqual(self.page.reload.call_count, 1)
        self.assertFalse(self.step(14.9))
        self.assertEqual(self.page.reload.call_count, 1)
        self.assertFalse(self.step(.1))
        self.assertEqual(self.page.reload.call_count, 2)

    def test_pending_data_clearing_resumes_at_next_fifteen_second_check(self):
        self.guard.pending.add(object())
        self.step()
        self.step(15)
        self.page.reload.assert_not_called()
        self.brands.assert_not_called()
        self.guard.pending.clear()
        self.brands.side_effect = lambda _: setattr(self, 'reason', None)
        self.assertTrue(self.step(15))
        self.brands.assert_called_once()
        self.assertEqual(self.clock, 30)
        self.assertEqual(self.guard.repair_attempts, 0)

    def test_pending_data_is_bounded_but_never_reloaded(self):
        self.guard.pending.add(object())
        self.step()
        for _ in range(5):
            self.step(15)
            self.assertFalse(self.guard.repair_failed)
        self.step(15)
        self.assertTrue(self.guard.repair_failed)
        self.assertEqual(self.guard.page_health(False), 'blocked')
        self.page.reload.assert_not_called()
        self.brands.assert_not_called()

    def test_fifth_retry_gets_settling_time_and_no_sixth_retry_or_keepalive_reload(self):
        self.step()
        for _ in range(5):
            self.step(15)
        self.assertFalse(self.guard.repair_failed)
        self.step(15)
        self.assertTrue(self.guard.repair_failed)
        for _ in range(10):
            self.step(300)
            self.assertFalse(w.refresh_idle(self.page, self.guard))
        self.assertEqual(self.page.reload.call_count, 5)
        self.assertEqual(self.brands.call_count, 5)
        self.reason = None
        self.assertTrue(self.step())
        self.assertFalse(self.guard.repair_failed)
        self.reason = 'Ô trạng thái chưa sẵn sàng.'
        self.step()
        self.step(15)
        self.assertEqual(self.page.reload.call_count, 6)

    def test_active_states_and_local_confirmation_never_consume_retries(self):
        self.step()
        for state in ('draft', 'verified_queued', 'preview_running', 'running', 'submitting'):
            self.api.return_value = {'states': {state: 1}}
            self.step(15)
        self.api.return_value = {'states': {}}
        self.step(15, prepared='pending-preview')
        self.assertEqual(self.guard.repair_attempts, 0)
        self.brands.assert_not_called()
        self.page.reload.assert_not_called()

    def test_confirmation_appearing_during_brand_wait_prevents_reload(self):
        self.step()
        self.api.side_effect = [{'states': {}}, {'states': {'draft': 1}}]
        self.step(15)
        self.brands.assert_called_once()
        self.page.reload.assert_not_called()

    def test_request_or_delivery_appearing_during_wait_prevents_reload(self):
        for kind in ('pending', 'late', 'unknown', 'delivery'):
            with self.subTest(kind=kind):
                self.guard.pending.clear()
                self.guard.late_submissions.clear()
                self.guard.uncertain_job = None
                (self.root / 'pending.json').unlink(missing_ok=True)
                self.guard.repair_at = self.clock
                def appeared(_):
                    if kind == 'pending': self.guard.pending.add(object())
                    elif kind == 'late': self.guard.late_submissions.append(object())
                    elif kind == 'unknown': self.guard.uncertain_job = 'uncertain'
                    else: (self.root / 'pending.json').write_text('{}')
                self.brands.side_effect = appeared
                self.step(15)
        self.page.reload.assert_not_called()

    def test_reload_timeout_still_consumes_budget_and_spaces_next_attempt(self):
        self.page.reload.side_effect = TimeoutError
        self.step()
        for _ in range(5):
            with self.assertRaises(TimeoutError): self.step(15)
            self.assertFalse(self.step(1))
            self.clock -= 1
        self.step(15)
        self.assertTrue(self.guard.repair_failed)
        self.assertEqual(self.page.reload.call_count, 5)

    def test_status_failure_defers_without_ui_mutation_or_tight_poll(self):
        self.step()
        self.api.side_effect = ConnectionError
        with self.assertRaises(ConnectionError): self.step(15)
        self.assertFalse(self.step(14))
        self.assertEqual(self.api.call_count, 1)
        self.api.side_effect = None
        self.step(1)
        self.page.reload.assert_called_once()

    def test_live_loop_keeps_processing_events_and_does_not_wait_five_minutes(self):
        runtime = MagicMock()
        context = MagicMock()
        module = types.SimpleNamespace(sync_playwright=lambda: MagicMock())
        seen = []
        def pump(_):
            seen.append(self.clock)
            self.clock += 5
            if self.clock > 95: raise SystemExit(0)
        self.page.wait_for_timeout.side_effect = pump
        with patch.object(w, 'Runtime', return_value=runtime), \
             patch.object(w, 'start_heartbeat', return_value=MagicMock()), \
             patch.object(w, 'open_browser', return_value=(context, self.page)), \
             patch.object(w, 'RecoveryGuard', return_value=self.guard), \
             patch.object(w, 'claim_with_reconnect', return_value=None), \
             patch.object(w, 'find_idle_mwg_page', return_value=self.page), \
             patch('sys.argv', ['worker', '--live']), \
             patch.dict('sys.modules', {'playwright.sync_api': module}):
            with self.assertRaises(SystemExit): w.main()
        self.assertEqual(self.page.reload.call_count, 5)
        self.assertTrue(self.guard.repair_failed)
        self.assertGreater(len(seen), 15)
        self.assertLess(self.clock, 300)


if __name__ == '__main__':
    unittest.main()
