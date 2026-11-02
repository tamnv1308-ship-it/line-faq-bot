"""Independent TaoWork password sessions; no LINE login dependency."""
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import tempfile

from flask import Blueprint, jsonify, request, redirect, send_from_directory
from cloud_passwords import PasswordAuth, AuthError, atomic_private, REMEMBER_SECONDS
from taowork_dashboard import directory, install as reports

COOKIE = '__Host-taowork_session'
PREFIX = '/tao/dashboard'


class CloudError(Exception):
    def __init__(self, message, status=400):
        self.message, self.status = message, status


def worker_auth():
    token = os.getenv('CO_WORKER_TOKEN', '')
    if len(token) < 32 or not hmac.compare_digest(request.headers.get('Authorization', '').encode(), ('Bearer '+token).encode()):
        raise CloudError('Không được phép.', 401)


def install(app):
    bp = Blueprint('taowork', __name__, url_prefix='/tao')
    assets = Path(__file__).parent / 'taowork_assets/login'

    def auth():
        return PasswordAuth(directory() / 'auth')

    def secure():
        if not app.testing and request.headers.get('X-Forwarded-Proto') != 'https':
            raise CloudError('Vui lòng dùng HTTPS.', 403)

    def origin():
        secure()
        allowed = {'https://line-faq-bot-d5wv.onrender.com'}
        if os.getenv('TAOWORK_PUBLIC_ORIGIN'):
            allowed.add(os.environ['TAOWORK_PUBLIC_ORIGIN'].rstrip('/'))
        if app.testing:
            allowed.add('https://test.example')
        if request.headers.get('Origin') not in allowed or request.headers.get('Sec-Fetch-Site') == 'cross-site':
            raise CloudError('Phiên thao tác không hợp lệ.', 403)

    def session():
        token = request.cookies.get(COOKIE, '')
        if not re.fullmatch(r'[A-Za-z0-9_-]{43}', token):
            return None
        a = auth()
        return a.session(token) if a.enabled else None

    def identity():
        secure()
        user = session()
        if not user:
            raise CloudError('Cần đăng nhập TáoWork.', 401)
        return user

    @bp.errorhandler(CloudError)
    def error(e):
        if e.status == 401 and request.method == 'GET' and request.path in (PREFIX, PREFIX+'/'):
            return redirect(PREFIX+'/login/', code=303)
        return jsonify(error=e.message), e.status

    @bp.errorhandler(AuthError)
    def auth_error(e):
        return jsonify(error=str(e)), e.code

    @bp.after_request
    def headers(response):
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'; object-src 'none'"
        return response

    @bp.get('/dashboard/login/')
    def login_page():
        return send_from_directory(assets, 'index.html')

    @bp.get('/dashboard/login/<name>')
    def login_assets(name):
        if name not in {'login.js', 'login.css', 'icon.svg'}:
            raise CloudError('Không tìm thấy nội dung.', 404)
        return send_from_directory(assets, name)

    @bp.get('/dashboard/auth/session')
    def state():
        secure()
        user = session()
        return jsonify(configured=auth().enabled, authenticated=bool(user), **(user or {}))

    @bp.post('/dashboard/auth/<action>')
    def login(action):
        origin()
        if not request.is_json or not request.content_length or request.content_length > 4096:
            raise CloudError('Nội dung yêu cầu không hợp lệ.', 400)
        data = request.get_json(silent=True)
        a = auth()
        if not a.enabled:
            raise CloudError('Tài khoản cloud chưa được kích hoạt.', 503)
        if action == 'login':
            if not isinstance(data, dict) or set(data) != {'username', 'password', 'remember'} or type(data['remember']) is not bool:
                raise CloudError('Nội dung yêu cầu không hợp lệ.', 400)
            token = a.login(data['username'], data['password'], 'remote', data['remember'])
            response = jsonify(ok=True)
            response.set_cookie(COOKIE, token, secure=True, httponly=True, samesite='Lax', path='/',
                                max_age=REMEMBER_SECONDS if data['remember'] else None)
            return response
        if action == 'logout':
            user = identity()
            if not hmac.compare_digest(request.headers.get('X-Tao-Auth-CSRF', '').encode(), user['csrf'].encode()):
                raise CloudError('Phiên thao tác không hợp lệ.', 403)
            a.logout(request.cookies.get(COOKIE, ''))
            response = jsonify(ok=True)
            response.delete_cookie(COOKIE, secure=True, httponly=True, samesite='Lax', path='/')
            return response
        raise CloudError('Không tìm thấy nội dung.', 404)

    @bp.post('/dashboard/api/bootstrap-account')
    def bootstrap():
        secure()
        worker_auth()
        if not request.is_json or not request.content_length or request.content_length > 4096:
            raise CloudError('Yêu cầu không hợp lệ.', 400)
        data = request.get_json(silent=True)
        if not isinstance(data, dict) or set(data) != {'version', 'username', 'kdf', 'salt', 'hash'}:
            raise CloudError('Tài khoản không hợp lệ.', 400)
        a = auth()
        if (a.root/'account.json').exists():
            previous = a.account()
            if all(previous.get(k) == v for k, v in data.items()):
                return jsonify(configured=True)
            raise CloudError('Tài khoản đã có; không ghi đè.', 409)
        data.update(revision=secrets.token_hex(16), local_key=secrets.token_urlsafe(32))
        with tempfile.TemporaryDirectory() as temp:
            file = Path(temp)/'account.json'
            file.write_text(json.dumps(data))
            checked = PasswordAuth.read_account(file)
        atomic_private(a.root/'required.json', {'version': 1})
        atomic_private(a.root/'account.json', checked)
        return jsonify(configured=True)

    reports(bp, identity, lambda user: None, CloudError)
    from taowork_runtime import install as runtime
    runtime(bp, identity, origin, CloudError)
    app.register_blueprint(bp)
    return auth
