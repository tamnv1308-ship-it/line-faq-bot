"""No live credentials, MWG actions or outbound messages in these tests."""
import copy
import gzip
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

from bao_tri.kiem_thu.test_tao_portal import PortalTests as PortalFixture, OWNER, MEMBER, BASE
import taowork_dashboard as dashboard


class DashboardTests(unittest.TestCase):
    call = PortalFixture.call
    login = PortalFixture.login
    # Reuse the existing real LINE-session fixture, not a bypass of identity().
    def setUp(self):
        PortalFixture.setUp(self)
        self.storage = Path(self.path).parent / 'dashboard'
        env = patch.dict(os.environ, {'TAOWORK_DATA_DIR': str(self.storage), 'CO_WORKER_TOKEN': 'T' * 40})
        env.start()
        self.addCleanup(env.stop)
        groups = [{'id': x} for x in sorted(dashboard.GROUPS)]
        common = dict(schema=1, cutoff='2026-11-01', source_as_of='2026-11-02T13:00:00+07:00', groups=groups)
        self.snapshot_payload = dict(schema=1, analytics=dict(common, daily=[{'day': '2026-11-01'}]),
                            revenue=dict(common, unit='million_vnd', periods=[{'id': '2026-11'}]))

    def upload(self, payload=None, token='T' * 40):
        return self.client.post('/tao/dashboard/api/snapshot', json=payload or self.snapshot_payload,
                                base_url=BASE, headers={'Authorization': 'Bearer ' + token})

    def test_unauthenticated_and_members_cannot_read_assets_or_data(self):
        for suffix in ['', '/assets/app.js', '/assets/app.css', '/api/revenue', '/api/status']:
            self.assertEqual(self.client.get('/tao/dashboard' + suffix, base_url=BASE).status_code, 401)
        self.login(MEMBER)
        for suffix in ['', '/assets/app.js', '/api/revenue']:
            self.assertEqual(self.client.get('/tao/dashboard' + suffix, base_url=BASE).status_code, 403)

    def test_snapshot_upload_does_not_modify_co_jobs(self):
        self.assertEqual(self.upload(token='wrong').status_code, 401)
        with self.q.db() as db:
            before = db.execute('SELECT count(*) FROM jobs').fetchone()[0]
        sent = self.upload()
        self.assertEqual(sent.status_code, 200)
        self.assertNotIn('data', sent.json)
        self.login(OWNER)
        for key in ('analytics', 'revenue'):
            response = self.client.get('/tao/dashboard/api/' + key, base_url=BASE)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json, self.snapshot_payload[key])
            self.assertEqual(response.headers['Cache-Control'], 'no-store')
        with self.q.db() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM jobs').fetchone()[0], before)
        self.assertEqual((self.storage / 'snapshot.json.gz').stat().st_mode & 0o777, 0o600)

    def test_older_or_invalid_snapshot_keeps_last_success(self):
        self.assertEqual(self.upload().status_code, 200)
        before = (self.storage / 'snapshot.json.gz').read_bytes()
        variants = []
        for change in ('cutoff', 'source_as_of', 'unit', 'groups', 'password', 'nan'):
            p = copy.deepcopy(self.snapshot_payload)
            if change == 'cutoff': p['revenue']['cutoff'] = '2026-10-31'
            elif change == 'source_as_of': p['analytics']['source_as_of'] = '2026-11-01T13:00:00+07:00'
            elif change == 'unit': p['revenue']['unit'] = 'vnd'
            elif change == 'groups': p['revenue']['groups'] = []
            elif change == 'password': p['revenue']['password'] = 'never-store-this'
            else: p['revenue']['bad_number'] = float('nan')
            variants.append(p)
        for p in variants:
            self.assertEqual(self.upload(p).status_code, 409)
            self.assertEqual((self.storage / 'snapshot.json.gz').read_bytes(), before)
        again = self.upload()
        self.assertEqual(again.status_code, 200)
        self.assertEqual((self.storage / 'snapshot.json.gz').read_bytes(), before)

    def test_html_assets_and_routes_are_scoped(self):
        self.login(OWNER)
        self.assertEqual(self.client.get('/tao/dashboard/api/revenue', base_url=BASE).status_code, 503)
        with self.client.get('/tao/dashboard', base_url=BASE) as response:
            self.assertEqual(response.status_code, 200)
        with self.client.get('/tao/dashboard/assets/app.js', base_url=BASE) as response:
            self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.get('/tao/dashboard/assets/snapshot.json.gz', base_url=BASE).status_code, 404)
        self.assertEqual(self.client.post('/tao/dashboard/api/action', json={'action': 'report.run'}, base_url=BASE).status_code, 405)
        root = Path(dashboard.__file__).parent / 'taowork_assets'
        code = (root / 'app.js').read_text()
        self.assertNotIn('window.TAO_BUSINESS_DATA =', code)
        self.assertNotIn('window.TAO_REVENUE_GZIP =', code)
        self.assertNotIn("fetch('/api/app/", code)
        self.assertNotIn('report.run', code)

    def test_gzip_response_preserves_exact_report_and_size_limit(self):
        self.assertEqual(self.upload().status_code, 200)
        self.login(OWNER)
        response = self.client.get('/tao/dashboard/api/revenue', base_url=BASE,
                                   headers={'Accept-Encoding': 'gzip'})
        self.assertEqual(response.headers['Content-Encoding'], 'gzip')
        self.assertEqual(json.loads(gzip.decompress(response.data)), self.snapshot_payload['revenue'])
        self.assertEqual(response.headers['Vary'], 'Accept-Encoding')
        before = (self.storage / 'snapshot.json.gz').read_bytes()
        with patch.object(dashboard, 'MAX_BYTES', 10):
            self.assertEqual(self.upload().status_code, 413)
        self.assertEqual((self.storage / 'snapshot.json.gz').read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
