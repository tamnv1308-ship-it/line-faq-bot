import base64
import io
import json
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

import mwg_auth as auth


def token(exp, issuer=auth.ISSUER):
    payload = {'exp': exp, 'iss': issuer, 'azp': auth.CLIENT}
    return 'test.' + base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip('=') + '.test'


class SessionRefreshTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'session.json'
        self.state = {'cookies': [
            {'name': 'token', 'value': token(1500), 'domain': auth.CLIENT, 'expires': 90000},
            {'name': 'refresh_token', 'value': token(1800), 'domain': auth.CLIENT, 'expires': 90000},
            {'name': 'unrelated', 'value': 'keep', 'domain': 'other.example', 'expires': 5000},
        ], 'origins': [{'origin': auth.ORIGIN, 'localStorage': [
            {'name': 'access_token', 'value': token(1500)},
            {'name': 'refresh_token', 'value': token(1800)},
            {'name': 'user', 'value': 'keep-user'},
        ]}]}
        auth.save_state(self.state, self.path)

    def tearDown(self):
        self.temp.cleanup()

    def test_fresh_session_does_not_call_server(self):
        with patch.object(auth, 'request_tokens') as request:
            self.assertEqual(auth.refresh_if_due(self.path, now=100)['state'], 'valid')
        request.assert_not_called()

    def test_refresh_rotates_both_tokens_and_preserves_unrelated_state(self):
        with patch.object(auth, 'request_tokens', return_value={
                'access_token': token(2500), 'refresh_token': token(2800)}):
            self.assertEqual(auth.refresh_if_due(self.path, now=1000)['state'], 'refreshed')
        state = auth.read_state(self.path)
        self.assertEqual(auth.local_tokens(state)['refresh_token'], token(2800))
        self.assertEqual(auth.local_tokens(state)['user'], 'keep-user')
        self.assertEqual(state['cookies'][0]['value'], token(2500))
        self.assertEqual(state['cookies'][0]['expires'], 2500)
        self.assertEqual(state['cookies'][2], self.state['cookies'][2])
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)

    def test_expired_refresh_requires_login_without_sending_credentials(self):
        before = self.path.read_bytes()
        with patch.object(auth, 'request_tokens') as request:
            with self.assertRaises(auth.LoginRequired):
                auth.refresh_if_due(self.path, now=1801)
        request.assert_not_called()
        self.assertEqual(self.path.read_bytes(), before)

    def test_wrong_issuer_and_rejected_refresh_preserve_session(self):
        before = self.path.read_bytes()
        with patch.object(auth, 'request_tokens', side_effect=auth.LoginRequired('login')):
            with self.assertRaises(auth.LoginRequired):
                auth.refresh_if_due(self.path, now=1000)
        self.assertEqual(self.path.read_bytes(), before)
        with patch.object(auth, 'request_tokens', return_value={
                'access_token': token(2500, 'https://other.example'), 'refresh_token': token(2800)}):
            with self.assertRaises(RuntimeError):
                auth.refresh_if_due(self.path, now=1000)
        self.assertEqual(self.path.read_bytes(), before)

    def test_server_denial_is_redacted(self):
        secret = 'secret-not-for-logs'
        error = urllib.error.HTTPError(auth.TOKEN_URL, 400, secret, {}, io.BytesIO(secret.encode()))
        with patch.object(auth.urllib.request.OpenerDirector, 'open', side_effect=error):
            with self.assertRaises(auth.LoginRequired) as result:
                auth.request_tokens(secret)
        self.assertNotIn(secret, str(result.exception))

    def test_new_mwg_issuer_refreshes_only_at_its_own_server(self):
        for item in self.state['origins'][0]['localStorage']:
            if item['name'] in ('access_token','refresh_token'):
                item['value']=token(1800,auth.CURRENT_ISSUER)
        auth.save_state(self.state,self.path)
        with patch.object(auth,'request_tokens',return_value={
                'access_token':token(2500,auth.CURRENT_ISSUER),
                'refresh_token':token(2800,auth.CURRENT_ISSUER)}) as request:
            result=auth.refresh_if_due(self.path,force=True,now=1000)
        self.assertEqual(result['state'],'refreshed')
        self.assertEqual(request.call_args.kwargs['issuer'],auth.CURRENT_ISSUER)

    def test_unknown_issuer_is_rejected_before_sending_credentials(self):
        with patch.object(auth.urllib.request.OpenerDirector,'open') as request:
            with self.assertRaises(auth.LoginRequired):
                auth.request_tokens('test-secret',issuer='https://other.example/realm')
        request.assert_not_called()


if __name__ == '__main__':
    unittest.main()
