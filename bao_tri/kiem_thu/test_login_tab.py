import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import mac_worker as worker


class LoginTabTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.root_patch = patch.object(worker, 'ROOT', self.root)
        self.root_patch.start()
        self.addCleanup(self.root_patch.stop)
        self.current = self.page('https://login.example/')
        self.target = self.page(worker.URL + '/?from=login#form')
        self.context = MagicMock()
        self.context.pages = [self.current, self.target]
        self.guard = worker.RecoveryGuard(self.current)

    def page(self, url):
        page = MagicMock()
        page.url = url
        page.is_closed.return_value = False
        return page

    def choose(self, states=None, prepared=None):
        with patch.object(worker, 'api', return_value={'states': states or {}}):
            result = worker.find_idle_mwg_page(self.context, self.current, self.guard, prepared)
        for page in self.context.pages:
            page.goto.assert_not_called()
            page.reload.assert_not_called()
            page.close.assert_not_called()
            page.bring_to_front.assert_not_called()
        return result

    def test_follows_single_mwg_tab_after_login_without_navigation(self):
        self.assertIs(self.choose({'preview_queued': 1}), self.target)

    def test_keeps_current_mwg_tab_even_when_another_tab_exists(self):
        self.current.url = worker.URL
        with patch.object(worker, 'api') as api:
            self.assertIs(worker.find_idle_mwg_page(self.context, self.current, self.guard), self.current)
        api.assert_not_called()

    def test_preserves_preview_active_and_uncertain_submissions(self):
        self.assertIs(self.choose(prepared='preview-id'), self.current)
        for state in ('draft', 'preview_running', 'running', 'submitting'):
            self.assertIs(self.choose({state: 1}), self.current)
        self.guard.uncertain_job = {'id': 'uncertain'}
        self.assertIs(self.choose(), self.current)
        self.guard.uncertain_job = None
        self.guard.late_submissions = [{'id': 'late'}]
        self.assertIs(self.choose(), self.current)

    def test_preserves_pending_results_and_inflight_page_requests(self):
        pending = self.root / 'pending.json'
        pending.write_text('{}')
        self.assertIs(self.choose(), self.current)
        pending.unlink()
        self.guard.pending.add(object())
        self.assertIs(self.choose(), self.current)

    def test_does_not_guess_among_multiple_forms_or_other_origins(self):
        self.context.pages.append(self.page(worker.URL))
        self.assertIs(self.choose(), self.current)
        self.context.pages = [self.current, self.page(worker.URL + '.example.invalid/')]
        self.assertIs(self.choose(), self.current)
        self.context.pages = [self.current, self.page(worker.URL.replace('https:', 'http:'))]
        self.assertIs(self.choose(), self.current)

    def test_ignores_closed_tabs_and_optional_discovery_errors(self):
        self.target.is_closed.return_value = True
        self.assertIs(self.choose(), self.current)
        self.target.is_closed.return_value = False
        with patch.object(worker, 'api', side_effect=TimeoutError):
            self.assertIs(worker.find_idle_mwg_page(self.context, self.current, self.guard), self.current)

    def test_never_reclaims_preserved_submission_as_login_tab(self):
        self.current.url='about:blank'
        with patch.object(worker,'api',return_value={'states':{'unknown':1}}):
            chosen=worker.find_idle_mwg_page(self.context,self.current,self.guard,
                                            excluded_pages=[self.target])
        self.assertIs(chosen,self.current)
        self.target.reload.assert_not_called();self.target.goto.assert_not_called()

    def test_login_handoff_ignores_old_submission_but_accepts_new_login_tab(self):
        login_target=self.page(worker.URL)
        self.context.pages.append(login_target)
        with patch.object(worker,'api',return_value={'states':{'unknown':1}}):
            chosen=worker.find_idle_mwg_page(self.context,self.current,self.guard,
                                            excluded_pages=[self.target])
        self.assertIs(chosen,login_target)
        self.target.reload.assert_not_called();self.target.close.assert_not_called()

    def test_unknown_api_submission_keeps_existing_form(self):
        self.guard.track_submissions = False
        self.assertIs(self.choose({'unknown': 1}), self.current)


if __name__ == '__main__':
    unittest.main()
