import os
"""Refresh the bot's own MWG session through the normal OIDC grant.

No passwords, cookie lifetime extensions, or authentication-policy overrides.
JWT payloads below are used only for timing and routing checks; the HTTPS
identity provider decides whether the refresh grant is still authorized.
"""
import base64
import contextlib
import fcntl
import importlib.util
import json
import os
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

PRIVATE = Path(os.environ['TAOWORK_REPORT_ROOT']) / '.private'
STATE = PRIVATE / 'mwg-session.json'
ORIGIN = 'https://baocao.dienmayxanh.com'
ISSUER = 'https://authkey.tgdd.vn/realms/procurement'
CURRENT_ISSUER = 'https://authkey.dmx.vn/realms/mwg-central'
# Both exact issuers were published by the MWG report application's config.
ALLOWED_ISSUERS = frozenset((ISSUER, CURRENT_ISSUER))
CLIENT = 'baocao.dienmayxanh.com'
TOKEN_URL = ISSUER + '/protocol/openid-connect/token'


class LoginRequired(RuntimeError):
    pass


class SessionBusy(RuntimeError):
    pass


@contextlib.contextmanager
def session_lock():
    PRIVATE.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd = os.open(PRIVATE / 'mwg-auth.lock', os.O_CREAT | os.O_RDWR, 0o600)
    with os.fdopen(fd, 'a') as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SessionBusy('Phiên MWG đang được sử dụng') from None
        yield


def claims(token):
    try:
        value = json.loads(base64.urlsafe_b64decode(token.split('.')[1] + '==='))
        if not isinstance(value, dict):
            raise ValueError()
        return value
    except (ValueError, IndexError, TypeError):
        raise LoginRequired('Phiên MWG chưa hợp lệ; cần đăng nhập lại') from None


def local_tokens(state):
    for origin in state.get('origins', []):
        if origin.get('origin') == ORIGIN:
            return {item['name']: item['value'] for item in origin.get('localStorage', [])}
    return {}


def read_state(path=STATE):
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        return {'cookies': [], 'origins': []}


def save_state(state, path=STATE):
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.tmp')
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as handle:
        json.dump(state, handle, ensure_ascii=False)
    os.replace(temporary, path)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def request_tokens(refresh_token, issuer=ISSUER):
    if issuer not in ALLOWED_ISSUERS:
        raise LoginRequired('Máy chủ xác thực MWG chưa được xác minh')
    context = ssl.create_default_context()
    if importlib.util.find_spec('certifi'):
        import certifi
        context = ssl.create_default_context(cafile=certifi.where())
    opener = urllib.request.build_opener(NoRedirect(), urllib.request.HTTPSHandler(context=context))
    request = urllib.request.Request(issuer + '/protocol/openid-connect/token', data=urllib.parse.urlencode({
        'grant_type': 'refresh_token', 'client_id': CLIENT,
        'refresh_token': refresh_token,
    }).encode(), headers={'Content-Type': 'application/x-www-form-urlencoded'})
    try:
        with opener.open(request, timeout=25) as response:
            result = json.loads(response.read())
    except urllib.error.HTTPError as exc:
        if exc.code in (400, 401, 403):
            raise LoginRequired('MWG yêu cầu đăng nhập lại') from None
        raise RuntimeError('Chưa gia hạn được phiên MWG: HTTP ' + str(exc.code)) from None
    except (OSError, ValueError, urllib.error.URLError):
        raise RuntimeError('Chưa kết nối được máy chủ gia hạn MWG') from None
    if not isinstance(result, dict) or not result.get('access_token') or not result.get('refresh_token'):
        raise RuntimeError('Máy chủ MWG chưa trả đủ phiên mới')
    return result


def refresh_if_due(path=STATE, force=False, now=None):
    """Caller must hold session_lock while refreshing or using the browser."""
    now = time.time() if now is None else now
    state = read_state(path)
    tokens = local_tokens(state)
    access = claims(tokens.get('access_token', ''))
    refresh = claims(tokens.get('refresh_token', ''))
    issuer = access.get('iss')
    if issuer not in ALLOWED_ISSUERS or access.get('azp') != CLIENT or refresh.get('iss') != issuer:
        raise LoginRequired('Phiên lưu không thuộc ứng dụng MWG đã cấu hình')
    if refresh.get('exp', 0) <= now:
        raise LoginRequired('Phiên gia hạn MWG hết hạn; cần đăng nhập lại')
    if not force and min(access.get('exp', 0), refresh.get('exp', 0)) - now > 600:
        return {'state': 'valid', 'expires_at': access['exp']}
    result = request_tokens(tokens['refresh_token'], issuer=issuer)
    new_access = claims(result['access_token'])
    new_refresh = claims(result['refresh_token'])
    if (new_access.get('iss') != issuer or new_access.get('azp') != CLIENT
            or new_refresh.get('iss') != issuer
            or min(new_access.get('exp', 0), new_refresh.get('exp', 0)) <= now):
        raise RuntimeError('Phiên mới từ MWG chưa hợp lệ')
    replacements = {'access_token': result['access_token'], 'refresh_token': result['refresh_token']}
    for origin in state.get('origins', []):
        if origin.get('origin') == ORIGIN:
            for item in origin.get('localStorage', []):
                if item['name'] in replacements:
                    item['value'] = replacements[item['name']]
    cookie_values = {'token': result['access_token'], 'refresh_token': result['refresh_token']}
    if result.get('id_token'):
        cookie_values['idToken'] = result['id_token']
    for cookie in state.get('cookies', []):
        if cookie.get('domain', '').lstrip('.') == CLIENT and cookie.get('name') in cookie_values:
            token = cookie_values[cookie['name']]
            cookie['value'] = token
            cookie['expires'] = claims(token)['exp']
    save_state(state, path)
    return {'state': 'refreshed', 'expires_at': new_access['exp']}
