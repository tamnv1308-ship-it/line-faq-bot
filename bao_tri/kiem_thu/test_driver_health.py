import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import MagicMock,patch

import mac_worker as w
from driver_health import DriverProbe
from worker_runtime import Runtime,CONTROL_STALE_SECONDS


class ProbeTests(unittest.TestCase):
    def test_discover_then_detect_exit_even_when_python_is_alive(self):
        rows=MagicMock(side_effect=[[(11,10,'S','/test/node')],[]]);clock=[0]
        with patch('driver_health.time.monotonic',side_effect=lambda:clock[0]):
            probe=DriverProbe(10,'/test/node',rows)
            self.assertEqual(probe.sample(),'alive')
            clock[0]=4;self.assertEqual(probe.sample(),'alive');self.assertEqual(rows.call_count,1)
            clock[0]=5;self.assertEqual(probe.sample(),'dead')
        self.assertEqual(rows.call_args.args,(11,))

    def test_reused_pid_wrong_parent_wrong_executable_and_zombie_fail_closed(self):
        for row in ((11,99,'S','/test/node'),(11,10,'S','/test/other'),(11,10,'Z','/test/node')):
            probe=DriverProbe(10,'/test/node',lambda pid:[row]);probe.pid=11
            self.assertEqual(probe.sample(),'dead')

    def test_ambiguous_or_unavailable_probe_is_not_reported_alive(self):
        for rows in (lambda pid:[],lambda pid:[(11,10,'S','/test/node'),(12,10,'S','/test/node')],MagicMock(side_effect=OSError)):
            self.assertEqual(DriverProbe(10,'/test/node',rows).sample(),'unverified')


class LivenessTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.root=Path(tmp.name);self.clock=[0.0]
        self.timer=patch('worker_runtime.time.monotonic',side_effect=lambda:self.clock[0]);self.timer.start();self.addCleanup(self.timer.stop)
        self.runtime=Runtime(self.root)
        self.runtime.driver_probe=MagicMock();self.runtime.driver_probe.sample.return_value='alive'

    def test_dead_driver_overrides_ready_processing_and_waiting_without_browser_actions(self):
        for state in ('ready','processing','awaiting_confirmation','loading_slow'):
            self.runtime.set(state);self.runtime.driver_probe.sample.return_value='dead'
            self.assertEqual(self.runtime.snapshot()['state'],'driver_error')
        self.assertEqual(list(self.root.iterdir()),[])

    def test_heartbeat_cannot_hide_a_stalled_controller(self):
        self.runtime.set('ready');self.clock[0]=CONTROL_STALE_SECONDS+1
        for _ in range(3):
            self.runtime.persist()
            self.assertEqual(self.runtime.snapshot()['state'],'control_stalled')
        self.assertEqual(self.runtime.snapshot()['progress_age_seconds'],CONTROL_STALE_SECONDS+1)

    def test_background_thread_cannot_forge_main_thread_progress(self):
        self.runtime.set('ready');self.clock[0]=CONTROL_STALE_SECONDS+1
        thread=threading.Thread(target=self.runtime.control_ok);thread.start();thread.join()
        self.assertEqual(self.runtime.snapshot()['state'],'control_stalled')

    def test_slow_mwg_and_waiting_confirmation_stay_healthy_while_events_are_pumped(self):
        for state in ('loading_slow','processing','awaiting_confirmation'):
            self.runtime.set(state)
            for _ in range(6):
                self.clock[0]+=30;self.runtime.control_ok()
                self.assertEqual(self.runtime.snapshot()['state'],state)

    def test_browser_wait_marks_progress_only_on_success_and_never_reloads(self):
        self.runtime.set('processing');page=MagicMock();self.clock[0]=10
        with patch.object(w,'RUNTIME',self.runtime):
            w.browser_wait(page,250)
            self.clock[0]=80;page.wait_for_timeout.side_effect=RuntimeError('driver error')
            with self.assertRaises(RuntimeError):w.browser_wait(page,250)
        self.assertEqual(self.runtime.snapshot()['state'],'control_stalled')
        page.reload.assert_not_called();page.goto.assert_not_called();page.close.assert_not_called()

    def test_old_browser_close_cannot_poison_replacement_context(self):
        self.runtime.set('ready');old=self.runtime.browser_opened();new=self.runtime.browser_opened()
        self.runtime.browser_closed(old);self.assertEqual(self.runtime.snapshot()['state'],'ready')
        self.runtime.browser_closed(new);self.assertEqual(self.runtime.snapshot()['state'],'driver_error')

    def test_manual_stop_is_never_overridden_or_restarted(self):
        self.runtime.request_shutdown();self.runtime.driver_probe.sample.return_value='dead'
        self.assertEqual(self.runtime.snapshot()['state'],'stopping')
        self.assertEqual(list(self.root.iterdir()),[])


if __name__=='__main__':unittest.main()
