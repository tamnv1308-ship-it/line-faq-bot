import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import mac_worker as w
from mwg_submit_capture import CreateCapture, CREATE_URL


class WorkspaceRetirementTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.clock = 100.0
        self.previous = [dict(co='', error='Waiting for reconciliation', state='unknown')]
        self.snapshot = dict(found=True, state='unknown', lease_matches=True,
                             result=json.dumps(self.previous))
        self.api = MagicMock(side_effect=lambda *a, **kw: dict(self.snapshot))
        for name, value in [('ROOT', self.root), ('api', self.api), ('report', MagicMock()),
                            ('progress', MagicMock()), ('capture_failure', MagicMock())]:
            p = patch.object(w, name, value); p.start(); self.addCleanup(p.stop)
        p = patch.object(w.time, 'monotonic', side_effect=lambda: self.clock)
        p.start(); self.addCleanup(p.stop)

    def page(self):
        page = MagicMock(); page.url = w.URL
        page.is_closed.return_value = False
        page.locator.return_value.count.return_value = 0
        page.get_by_text.return_value.all.return_value = []
        page.get_by_text.return_value.is_visible.return_value = False
        page.get_by_role.return_value.input_value.return_value = '1 - Mới'
        page.close.side_effect = lambda **kw: setattr(page.is_closed, 'return_value', True)
        return page

    def submission(self, number=1, finished=True):
        page = self.page(); guard = w.RecoveryGuard(page)
        job = dict(id=f'{number:010x}', lease='test-lease', payload=dict(
            source='206', destination='255', product='0131491005411', quantity=2))
        capture = CreateCapture(page, [job['payload']])
        request = MagicMock(method='POST', url=CREATE_URL, resource_type='xhr')
        request.response.return_value.status = 502
        capture.request(request); guard.request(request)
        if finished:
            capture.finished(request); guard.finished(request)
        guard.uncertain_job = job['id']
        guard.late_submissions = [(job, capture, self.previous)]
        return page, guard, job, capture, request

    def test_eight_completed_unknowns_do_not_fill_three_page_limit(self):
        context = MagicMock(); context.new_page.side_effect = self.page
        preserved = []
        for number in range(1, 9):
            page, guard, job, _, _ = self.submission(number)
            w.reconcile_late_submissions(guard)
            self.assertTrue(guard.retirement_ready)
            _, _, isolated = w.isolate_workspace(context, page, guard, preserved)
            self.assertTrue(isolated); self.assertEqual(preserved, [])
            page.close.assert_called_once(); page.reload.assert_not_called()
            evidence = self.root/'settled-submissions'/(job['id']+'.json')
            data = json.loads(evidence.read_text())
            self.assertEqual(data['previous_outcomes'], self.previous)
            self.assertFalse(data['replay_allowed'])
            self.assertNotIn('lease', data)
            self.assertEqual(evidence.stat().st_mode & 0o777, 0o600)
        w.report.assert_not_called()
        self.assertTrue(all(c.args[0]=='result-status' for c in self.api.call_args_list))

    def test_finished_old_pages_are_removed_before_capacity_check(self):
        old = [self.submission(i) for i in (1, 2, 3)]
        for _, guard, _, _, _ in old:w.reconcile_late_submissions(guard)
        preserved = [row[1] for row in old]
        page, guard, _, _, _ = self.submission(4, finished=False)
        fresh, _, ok = w.isolate_workspace(MagicMock(), page, guard, preserved)
        self.assertTrue(ok); self.assertEqual(preserved, [guard])
        page.close.assert_not_called()
        for prior, *_ in old:prior.close.assert_called_once()

    def test_three_inflight_pages_remain_bounded_and_untouched(self):
        preserved = [self.submission(i, finished=False)[1] for i in (1, 2, 3)]
        page, guard, _, _, _ = self.submission(4, finished=False)
        context = MagicMock()
        self.assertFalse(w.isolate_workspace(context, page, guard, preserved)[2])
        context.new_page.assert_not_called()
        for saved in preserved+[guard]:saved.page.close.assert_not_called()

    def test_cancelled_matching_evidence_can_release_page_without_releasing_job(self):
        self.snapshot.update(state='cancelled', lease_matches=False)
        page, guard, _, _, _ = self.submission()
        w.reconcile_late_submissions(guard)
        self.assertTrue(guard.retirement_ready)
        self.assertTrue(w.retire_workspace(guard))
        w.report.assert_not_called()

    def test_missing_nonterminal_wrong_lease_or_changed_cancel_evidence_keeps_page(self):
        cases = [dict(found=False), dict(state='submitting'), dict(lease_matches=False),
                 dict(state='cancelled', lease_matches=False, result='[]')]
        for changes in cases:
            with self.subTest(changes=changes):
                self.snapshot = dict(found=True, state='unknown', lease_matches=True,
                                     result=json.dumps(self.previous), **{})
                self.snapshot.update(changes)
                page, guard, _, _, _ = self.submission()
                w.reconcile_late_submissions(guard)
                self.assertFalse(guard.retirement_ready)
                self.assertFalse(w.retire_workspace(guard))
                page.close.assert_not_called()

    def test_disk_failure_retains_capture_and_retries_only_after_fifteen_seconds(self):
        page, guard, _, capture, _ = self.submission()
        with patch.object(w, 'atomic_json', side_effect=OSError('disk full')):
            w.reconcile_late_submissions(guard)
        self.assertFalse(guard.retirement_ready)
        self.assertEqual(len(guard.late_submissions), 1)
        w.reconcile_late_submissions(guard); self.assertEqual(self.api.call_count, 1)
        self.clock += 15
        w.reconcile_late_submissions(guard); self.assertTrue(guard.retirement_ready)

    def test_network_failure_does_not_discard_evidence_or_stop_other_guards(self):
        page, guard, _, _, _ = self.submission()
        self.api.side_effect = TimeoutError()
        w.reconcile_late_submissions(guard)
        self.assertFalse(guard.retirement_ready); page.close.assert_not_called()
        self.assertEqual(len(guard.late_submissions), 1)

    def test_pending_delivery_and_confirmation_prevent_cleanup(self):
        page, guard, _, _, _ = self.submission()
        w.reconcile_late_submissions(guard)
        preserved = [guard]
        w.prune_preserved_workspaces(preserved, 'waiting-confirmation')
        self.assertEqual(preserved, [guard]); page.close.assert_not_called()
        (self.root/'pending.json').write_text('{}')
        w.prune_preserved_workspaces(preserved)
        self.assertEqual(preserved, [guard]); page.close.assert_not_called()
        self.assertFalse(w.isolate_workspace(MagicMock(), page, guard, preserved)[2])

    def test_no_observed_create_request_never_retires_page(self):
        page, guard, job, _, _ = self.submission()
        capture = CreateCapture(page, [job['payload']])
        guard.late_submissions = [(job, capture, self.previous)]
        w.reconcile_late_submissions(guard)
        self.api.assert_not_called(); self.assertFalse(guard.retirement_ready)

    def test_new_request_revokes_archive_and_keeps_late_capture_attached(self):
        page, guard, _, capture, _ = self.submission()
        w.reconcile_late_submissions(guard)
        self.assertTrue(guard.retirement_ready)
        second = MagicMock(method='POST', url=CREATE_URL, resource_type='xhr')
        capture.request(second); guard.request(second)
        self.assertFalse(guard.retirement_ready); self.assertFalse(capture.done)
        self.assertFalse(w.retire_workspace(guard)); page.close.assert_not_called()

    def test_completed_response_with_other_network_pending_keeps_page(self):
        page, guard, _, _, _ = self.submission()
        guard.pending.add(object())
        w.reconcile_late_submissions(guard)
        self.api.assert_not_called(); self.assertFalse(guard.retirement_ready)

    def test_completed_response_with_loading_overlay_keeps_original_page(self):
        page, guard, _, _, _ = self.submission()
        page.locator.return_value.count.return_value = 1
        w.reconcile_late_submissions(guard)
        self.api.assert_not_called(); self.assertFalse(guard.retirement_ready)
        self.assertFalse(w.retire_workspace(guard)); page.close.assert_not_called()
        preserved=[]
        _, _, isolated=w.isolate_workspace(MagicMock(),page,guard,preserved)
        self.assertTrue(isolated);self.assertEqual(preserved,[guard])
        page.close.assert_not_called();page.reload.assert_not_called()

    def test_loading_appearing_after_archive_prevents_retirement(self):
        page, guard, _, _, _ = self.submission()
        w.reconcile_late_submissions(guard)
        self.assertTrue(guard.retirement_ready)
        page.locator.return_value.count.return_value = 1
        self.assertFalse(w.retire_workspace(guard));page.close.assert_not_called()

    def test_unreadable_or_login_page_does_not_prove_finished_processing(self):
        for kind in ('unreadable','login'):
            page, guard, _, _, _ = self.submission()
            if kind=='unreadable':page.locator.side_effect=RuntimeError('read failed')
            else:page.url='https://sso.example/login'
            w.reconcile_late_submissions(guard)
            self.assertFalse(guard.retirement_ready);page.close.assert_not_called()

    def test_archive_preserves_partial_codes_and_existing_manual_holds(self):
        page, guard, job, capture, _ = self.submission()
        capture.rows = [dict(co='206CO123', error='Conflict', state='unknown')]
        hold = self.root/'reconciliation-holds.json'; hold.write_text('{"untouched":true}')
        w.reconcile_late_submissions(guard)
        data = json.loads((self.root/'settled-submissions'/(job['id']+'.json')).read_text())
        self.assertEqual(data['observed_outcomes'][0]['co'], '206CO123')
        self.assertEqual(hold.read_text(), '{"untouched":true}')
        w.report.assert_not_called()

    def test_capture_waits_for_every_observed_request_before_done(self):
        page, guard, _, capture, first = self.submission(finished=False)
        second = MagicMock(method='POST', url=CREATE_URL)
        capture.request(second)
        capture.finished(first)
        self.assertFalse(capture.done)
        capture.failed(second)
        self.assertTrue(capture.done); self.assertIsNone(capture.rows)

    def test_page_with_verified_result_is_pruned_without_new_server_operation(self):
        guard = w.RecoveryGuard(self.page()); preserved = [guard]
        w.prune_preserved_workspaces(preserved)
        self.assertEqual(preserved, []); self.api.assert_not_called()

    def test_replacement_failure_does_not_close_original_page(self):
        page, guard, _, _, _ = self.submission()
        w.reconcile_late_submissions(guard)
        context = MagicMock(); context.new_page.side_effect = RuntimeError('browser unavailable')
        with self.assertRaises(RuntimeError):w.isolate_workspace(context, page, guard, [])
        page.close.assert_not_called()

    def test_second_post_during_evidence_capture_requires_new_archive(self):
        page, guard, _, capture, _ = self.submission()
        second = MagicMock(method='POST', url=CREATE_URL, resource_type='xhr')
        def during_capture(*args):
            capture.request(second); guard.request(second)
            capture.failed(second); guard.finished(second)
        w.capture_failure.side_effect = during_capture
        w.reconcile_late_submissions(guard)
        self.assertFalse(guard.retirement_ready)
        page.close.assert_not_called()


if __name__ == '__main__':unittest.main()
