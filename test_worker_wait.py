import unittest
from unittest.mock import Mock,patch
from mac_worker import wait_ui

class WorkerWaitTests(unittest.TestCase):
    def test_ready_has_no_added_delay(self):
        page=Mock();wait_ui(page,lambda:True,'error');page.wait_for_timeout.assert_not_called()
    def test_waits_until_ready(self):
        page=Mock();ready=Mock(side_effect=[False,False,True])
        wait_ui(page,ready,'error');self.assertEqual(page.wait_for_timeout.call_count,2)
    def test_timeout_stops_instead_of_continuing(self):
        with patch('mac_worker.time.monotonic',side_effect=[0,16]):
            with self.assertRaisesRegex(RuntimeError,'not ready'):
                wait_ui(Mock(),lambda:False,'not ready')
