"""Opt-in integration: empty temporary Chrome, all network requests blocked.

CO_OFFLINE_BROWSER_TEST=1 python -m unittest bao_tri.kiem_thu.test_dialogs_browser_offline
Never loads MWG, the bot profile, a request form, or the queue.
"""
import os
import tempfile
import unittest
from pathlib import Path

from browser_dialogs import install_dialogs
from worker_runtime import Runtime


@unittest.skipUnless(os.environ.get('CO_OFFLINE_BROWSER_TEST')=='1','Opt-in isolated browser test')
class OfflineBrowserTests(unittest.TestCase):
    def test_late_dialogs_and_next_page_keep_the_driver_healthy(self):
        from playwright.sync_api import sync_playwright
        with tempfile.TemporaryDirectory() as directory, sync_playwright() as pw:
            runtime=Runtime(Path(directory));runtime.watch_driver()
            browser=pw.chromium.launch(channel='chrome',headless=True,
                                      args=['--disable-background-networking'])
            try:
                context=browser.new_context()
                context.route('**/*',lambda route:route.abort())
                events=[];broker=install_dialogs(context,events.append)
                old=context.new_page();old_alerts=broker.begin(old,'offline_old')
                new=context.new_page();new_alerts=broker.begin(new,'offline_next')
                # A notice arriving after work moved to a different page stays
                # associated with the preserved page and does not kill the driver.
                old.evaluate("setTimeout(() => alert('late simulation'), 20)")
                new.wait_for_timeout(100)
                self.assertEqual(old_alerts,['late simulation']);self.assertEqual(new_alerts,[])
                self.assertFalse(new.evaluate("confirm('simulation only')"))
                self.assertIsNone(new.evaluate("prompt('simulation only')"))
                self.assertEqual(new.evaluate('1+1'),2)
                runtime.set('ready')
                self.assertEqual(runtime.snapshot()['state'],'ready')
                self.assertEqual(runtime.driver_probe.sample(),'alive')
                old.close();new.evaluate("alert('still alive')")
                self.assertEqual(new.evaluate('2+2'),4)
                self.assertEqual(events,[])
                context.close();self.assertEqual(len(broker.sessions),0)
            finally:browser.close()


if __name__=='__main__':unittest.main()
