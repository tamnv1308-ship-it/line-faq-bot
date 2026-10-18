import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch
import mac_worker as w

class ReloadBarrierTests(unittest.TestCase):
    def test_active_network_and_late_submit_block_both_reload_paths(self):
        with tempfile.TemporaryDirectory() as root, patch.object(w,'ROOT',Path(root)), patch.object(w,'api',return_value={'states':{}}):
            for field,value in [('pending',{object()}),('late_submissions',[object()]),('uncertain_job','job')]:
                page=MagicMock();guard=w.RecoveryGuard(page);setattr(guard,field,value)
                self.assertFalse(w.refresh_idle(page,guard))
                self.assertFalse(w.recover_idle_controls(page,guard))
                page.reload.assert_not_called()
                page.goto.assert_not_called()
    def test_late_submission_prevents_claim_readiness(self):
        page=MagicMock();guard=w.RecoveryGuard(page)
        guard.late_submissions=[object()]
        self.assertFalse(guard.ready())
        page.reload.assert_not_called()
