import fcntl
import json
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch
import mac_worker as w
from worker_runtime import Runtime, atomic_json, request_stop, lock_held


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.root=Path(tmp.name)

    def test_cooperative_exit_closes_profile_before_releasing_lock(self):
        runtime=MagicMock();runtime.check_stop.side_effect=SystemExit(0)
        context=MagicMock();page=MagicMock();shutdown=MagicMock()
        manager=MagicMock()
        module=types.SimpleNamespace(sync_playwright=lambda:manager)
        def close():
            self.assertTrue(lock_held(self.root))
        context.close.side_effect=close
        with patch.object(w,'ROOT',self.root),patch.object(w,'Runtime',return_value=runtime),patch.object(w,'start_heartbeat',return_value=shutdown),patch.object(w,'open_browser',return_value=(context,page)),patch('sys.argv',['worker','--live']),patch.dict('sys.modules',{'playwright.sync_api':module}):
            with self.assertRaises(SystemExit):w.main()
        context.close.assert_called_once();shutdown.assert_called_once();runtime.close.assert_called_once()
        self.assertFalse(lock_held(self.root))

    def test_stop_targets_locked_instance_and_old_request_is_ignored(self):
        runtime=Runtime(self.root);runtime.persist()
        with (self.root/'worker.lock').open('a') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            self.assertTrue(lock_held(self.root))
            self.assertEqual(request_stop(self.root),'requested')
            self.assertTrue(runtime.stopping())
            with self.assertRaises(SystemExit):runtime.check_stop()
        next_runtime=Runtime(self.root)
        self.assertFalse(next_runtime.stopping())
        self.assertEqual(request_stop(self.root),'stopped')

    def test_old_worker_with_no_identity_is_not_killed(self):
        with (self.root/'worker.lock').open('a') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            self.assertEqual(request_stop(self.root),'legacy')
        self.assertFalse((self.root/'stop-request.json').exists())

    def test_pulses_do_not_refresh_main_thread_progress(self):
        with patch('worker_runtime.time.monotonic',side_effect=[100,100,170]):
            runtime=Runtime(self.root);runtime.set('ready')
            self.assertEqual(runtime.snapshot(),{'state':'ready','progress_age_seconds':70})

    def test_stop_during_result_failure_preserves_outcome(self):
        runtime=Runtime(self.root);runtime.request_shutdown()
        with patch.object(w,'ROOT',self.root),patch.object(w,'RUNTIME',runtime),patch.object(w,'api',side_effect=ConnectionError):
            with self.assertRaises(SystemExit):w.report({'id':'a','lease':'l'},'succeeded','001CO123')
        self.assertEqual(json.loads((self.root/'pending.json').read_text())['result'],'001CO123')

    def test_idle_repair_never_reloads_preview_or_current_unknown(self):
        page=MagicMock();guard=w.RecoveryGuard(page)
        guard.uncertain_job='current'
        with patch.object(w,'ROOT',self.root),patch.object(w,'api',return_value={'states':{'unknown':1}}):
            self.assertFalse(w.recover_idle_controls(page,guard,'prepared'))
            self.assertFalse(w.recover_idle_controls(page,guard))
        page.reload.assert_not_called()

    def test_historical_unknown_does_not_disable_idle_page_repair(self):
        page=MagicMock();page.url=w.URL;page.is_closed.return_value=False
        guard=w.RecoveryGuard(page)
        guard.repair_at=0
        with patch.object(w,'ROOT',self.root),patch.object(w,'api',return_value={'states':{'unknown':5}}),\
             patch.object(guard,'ready',side_effect=[False,False,True]),patch.object(w,'select_brands'):
            self.assertTrue(w.recover_idle_controls(page,guard))
        page.reload.assert_called_once()

    def test_idle_repair_preserves_active_work_and_pending_delivery(self):
        for state in ('draft','preview_running','running','submitting'):
            page=MagicMock();guard=w.RecoveryGuard(page)
            with patch.object(w,'ROOT',self.root),patch.object(w,'api',return_value={'states':{state:1}}):
                self.assertFalse(w.recover_idle_controls(page,guard))
            page.reload.assert_not_called()
        (self.root/'pending.json').write_text('{}')
        with patch.object(w,'ROOT',self.root),patch.object(w,'api') as api:
            self.assertFalse(w.recover_idle_controls(page,guard))
        api.assert_not_called();page.reload.assert_not_called()

    def test_untracked_api_mode_keeps_legacy_unknown_stop(self):
        page=MagicMock();guard=w.RecoveryGuard(page,track_submissions=False)
        with patch.object(w,'ROOT',self.root),patch.object(w,'api',return_value={'states':{'unknown':1}}):
            self.assertFalse(w.recover_idle_controls(page,guard))
            self.assertFalse(w.refresh_idle(page,guard))
        page.reload.assert_not_called()

    def test_idle_repair_bounded_to_five_fifteen_second_retries(self):
        page=MagicMock();page.url=w.URL;page.is_closed.return_value=False
        guard=w.RecoveryGuard(page);clock=[0.0]
        with patch.object(guard,'ready',return_value=False),patch.object(w.time,'monotonic',side_effect=lambda:clock[0]),\
             patch.object(w,'select_brands'),patch.object(w,'capture_failure'),patch.object(w,'ROOT',self.root),patch.object(w,'api',return_value={'states':{}}):
            self.assertFalse(w.recover_idle_controls(page,guard))
            for _ in range(6):
                clock[0]+=15
                self.assertFalse(w.recover_idle_controls(page,guard))
            self.assertTrue(guard.repair_failed)
        self.assertEqual(page.reload.call_count,5)

    def test_idle_repair_selects_brands_before_waiting_for_dependent_status(self):
        page=MagicMock();page.url=w.URL;page.is_closed.return_value=False
        guard=w.RecoveryGuard(page);guard.repair_at=0;ready=[False]
        with patch.object(w,'ROOT',self.root),patch.object(w,'api',return_value={'states':{'unknown':5}}),\
             patch.object(guard,'ready',side_effect=lambda:ready[0]),\
             patch.object(guard,'wait_ready',side_effect=lambda **kwargs:ready[0]),\
             patch.object(w,'select_brands',side_effect=lambda _:ready.__setitem__(0,True)) as brands:
            self.assertTrue(w.recover_idle_controls(page,guard))
        brands.assert_called_once();page.reload.assert_not_called()


if __name__=='__main__':unittest.main()
