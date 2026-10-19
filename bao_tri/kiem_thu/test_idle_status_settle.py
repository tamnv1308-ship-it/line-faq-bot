"""Regression: delayed status data must finish before an idle reload decision."""
import tempfile,unittest
from pathlib import Path
from unittest.mock import MagicMock,patch
import mac_worker as w


class IdleStatusSettleTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  self.root=Path(self.tmp.name);self.clock=100.;self.due=None;self.status=False
  self.page=MagicMock();self.page.url=w.URL;self.page.is_closed.return_value=False
  self.guard=w.RecoveryGuard(self.page);self.guard.repair_at=0
  self.page.wait_for_timeout.side_effect=self.pump
  self.api=MagicMock(return_value={'states':{}})
  self.brands=MagicMock(side_effect=self.select)
  for target,name,kw in [(w,'ROOT',{'new':self.root}),
                         (w,'api',{'new':self.api}),
                         (w,'select_brands',{'new':self.brands}),
                         (w.time,'monotonic',{'side_effect':lambda:self.clock}),
                         (self.guard,'readiness_reason',{'side_effect':self.reason})]:
   p=patch.object(target,name,**kw);p.start();self.addCleanup(p.stop)
 def reason(self):
  if self.guard.uncertain_job or self.guard.late_submissions:return 'submission'
  if self.guard.pending:return 'loading'
  return None if self.status else 'blank'
 def select(self,page):
  self.due=self.clock+1.5;self.guard.pending.add('status-read')
 def pump(self,ms):
  self.clock+=ms/1000
  if self.due is not None and self.clock>=self.due:
   self.guard.pending.discard('status-read');self.status=True;self.due=None
 def test_brand_change_waits_for_pending_status_without_second_reload(self):
  self.assertTrue(w.recover_idle_controls(self.page,self.guard))
  self.assertGreaterEqual(self.clock,102.5)
  self.assertLess(self.clock,107)
  self.assertFalse(self.guard.pending);self.assertTrue(self.guard.ready())
  self.page.reload.assert_not_called();self.brands.assert_called_once()
 def test_periodic_refresh_reinitializes_status_in_same_cycle(self):
  self.status=True
  def reload(**kw):self.status=False
  self.page.reload.side_effect=reload
  self.assertTrue(w.refresh_idle(self.page,self.guard))
  self.page.reload.assert_called_once();self.brands.assert_called_once()
  self.assertTrue(self.guard.ready())
 def test_periodic_refresh_waits_for_initial_data_before_selecting_brands(self):
  def reload(**kw):
   self.guard.pending.add('status-read');self.due=self.clock+.5
  self.page.reload.side_effect=reload
  self.assertTrue(w.refresh_idle(self.page,self.guard));self.assertTrue(self.guard.ready())
  self.assertGreaterEqual(self.clock,103)
  self.page.reload.assert_called_once()
 def test_slow_status_never_reloads_a_pending_request(self):
  def slow(page):self.guard.pending.add('status-read')
  self.brands.side_effect=slow
  self.assertFalse(w.recover_idle_controls(self.page,self.guard))
  self.assertGreaterEqual(self.clock,107);self.assertLess(self.clock,107.3)
  self.page.reload.assert_not_called()
 def test_active_server_states_prevent_reload_and_brand_changes(self):
  for state in ('draft','verified_queued','preview_running','running','submitting'):
   self.api.return_value={'states':{state:1}}
   self.guard.repair_at=0
   self.assertFalse(w.refresh_idle(self.page,self.guard))
   self.assertFalse(w.recover_idle_controls(self.page,self.guard))
  self.page.reload.assert_not_called();self.brands.assert_not_called()
 def test_new_confirmation_during_settle_prevents_reload(self):
  self.brands.side_effect=lambda page:None
  self.api.side_effect=[{'states':{}},{'states':{'draft':1}}]
  self.assertFalse(w.recover_idle_controls(self.page,self.guard))
  self.page.reload.assert_not_called()
 def test_request_starting_during_status_read_blocks_scheduled_reload(self):
  def status(*a,**k):self.guard.pending.add('late');return {'states':{}}
  self.api.side_effect=status
  self.assertFalse(w.refresh_idle(self.page,self.guard))
  self.page.reload.assert_not_called();self.brands.assert_not_called()
 def test_confirmation_after_reload_prevents_control_mutations(self):
  self.api.side_effect=[{'states':{}},{'states':{'draft':1}}]
  self.assertTrue(w.refresh_idle(self.page,self.guard))
  self.page.reload.assert_called_once();self.brands.assert_not_called()
 def test_prepared_or_unknown_page_never_enters_settle(self):
  self.assertFalse(w.recover_idle_controls(self.page,self.guard,'prepared'))
  self.guard.uncertain_job='unknown'
  self.assertFalse(w.recover_idle_controls(self.page,self.guard))
  self.assertFalse(w.refresh_idle(self.page,self.guard))
  self.brands.assert_not_called();self.page.reload.assert_not_called()

