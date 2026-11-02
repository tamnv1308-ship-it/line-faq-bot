"""TáoWork password sessions. No MWG credentials, network calls or BOT actions."""
import argparse
from contextlib import contextmanager
import getpass
import hashlib
import hmac
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import tempfile
import threading
import time

ROOT = Path(__file__).resolve().parents[1] / '.automation' / 'login'
N, R, P = 2**17, 8, 1
SESSION_SECONDS = 12 * 60 * 60
REMEMBER_SECONDS = 30 * 24 * 60 * 60
WINDOW = 300
ACCOUNT_FORMAT = 2


def valid_username(value):
    if not isinstance(value, str) or len(value) > 254:
        return False
    if re.fullmatch(r'[a-z0-9][a-z0-9._-]{2,31}', value):
        return True
    local, separator, domain = value.partition('@')
    return bool(separator and re.fullmatch(r'[a-z0-9][a-z0-9._%+\-]{0,63}', local)
                and not local.endswith('.') and '..' not in local
                and '.' in domain and all(re.fullmatch(r'[a-z0-9](?:[a-z0-9\-]{0,61}[a-z0-9])?', label)
                                          for label in domain.split('.')))


class AuthError(Exception):
    def __init__(self, message, code=401):
        super().__init__(message)
        self.code = code


def password_hash(password, salt):
    if not hasattr(hashlib, 'scrypt'):
        raise AuthError('Môi trường xác thực cloud chưa sẵn sàng.', 503)
    return hashlib.scrypt(password.encode('utf-8'), salt=bytes.fromhex(salt),
                          n=N, r=R, p=P, maxmem=256*1024*1024, dklen=32).hex()


def digest(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def atomic_private(path, value):
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, delete=False) as f:
        temporary = Path(f.name)
        json.dump(value, f, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())
    try:
        temporary.chmod(0o600)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def forwarded(headers):
    return any(headers.get(k) is not None for k in
               ('CF-Connecting-IP', 'CF-Ray', 'Forwarded', 'X-Forwarded-For',
                'X-Forwarded-Proto', 'X-Forwarded-Host', 'CF-Access-Jwt-Assertion'))


def local_request(handler):
    try:
        return ipaddress.ip_address(handler.client_address[0]).is_loopback and not forwarded(handler.headers)
    except (ValueError, AttributeError, IndexError):
        return False


def cookie_name(handler):
    return 'tao_local_session' if local_request(handler) else '__Host-tao_session'


def cookie_token(handler):
    from http.cookies import SimpleCookie, CookieError
    try:
        jar = SimpleCookie()
        jar.load(handler.headers.get('Cookie', ''))
        item = jar.get(cookie_name(handler))
        return item.value if item and re.fullmatch(r'[A-Za-z0-9_-]{43}', item.value) else ''
    except CookieError:
        return ''


def cookie_header(handler, token='', remember=False, clear=False):
    value = cookie_name(handler) + '=' + token + '; Path=/; HttpOnly; SameSite=Lax'
    if not local_request(handler):
        value += '; Secure'
    if clear:
        value += '; Max-Age=0'
    elif remember:
        value += '; Max-Age=' + str(REMEMBER_SECONDS)
    return value


class PasswordAuth:
    def __init__(self, root=ROOT, clock=time.time):
        self.root = Path(root)
        self.clock = clock
        self.lock = threading.RLock()

    @property
    def enabled(self):
        return (self.root/'required.json').exists() or (self.root/'account.json').exists()

    @staticmethod
    def read_account(path):
        try:
            a = json.loads(path.read_text())
            if (a.get('version') != 1 or a.get('kdf') != 'scrypt-131072-8-1'
                    or not valid_username(a['username'])
                    or not re.fullmatch(r'[0-9a-f]{32}', a['salt'])
                    or not re.fullmatch(r'[0-9a-f]{64}', a['hash'])
                    or not re.fullmatch(r'[0-9a-f]{32}', a['revision'])
                    or not re.fullmatch(r'[A-Za-z0-9_-]{43}', a['local_key'])):
                raise ValueError()
            return a
        except (OSError, ValueError, TypeError, KeyError, AttributeError):
            raise AuthError('Tài khoản chưa sẵn sàng. Kiểm tra thiết lập TáoWork.', 503) from None

    def account(self):
        return self.read_account(self.root/'account.json')

    @property
    def prepared_path(self):
        return self.root/'prepared-account.json'

    def prepare_account(self, username, password):
        """Store a hashed account without enabling an incompatible running web."""
        with self.lock:
            if self.enabled or self.prepared_path.exists():
                raise AuthError('Tài khoản đã được tạo hoặc chuẩn bị. Không ghi đè.', 409)
            with tempfile.TemporaryDirectory() as temporary:
                candidate = PasswordAuth(Path(temporary)/'login', clock=self.clock)
                candidate.setup(username, password)
                account = candidate.account()
            atomic_private(self.prepared_path, account)
            self.root.chmod(0o700)
            (self.root/'setup-ticket.json').unlink(missing_ok=True)

    def activate_prepared(self):
        """Called by the local updater only after the web reports ACCOUNT_FORMAT."""
        with self.lock:
            if not self.prepared_path.exists():
                return False
            account = self.read_account(self.prepared_path)
            if self.enabled:
                # Resume an interrupted activation, but never replace another owner.
                if not (self.root/'account.json').exists() or self.account() != account:
                    raise AuthError('Đã có tài khoản khác. Giữ nguyên tài khoản hiện tại.', 409)
            else:
                self.root.chmod(0o700)
                atomic_private(self.root/'required.json', {'version': 1})
                atomic_private(self.root/'account.json', account)
            with self.database() as db:
                db.execute('DELETE FROM sessions')
                db.execute('DELETE FROM attempts')
            self.prepared_path.unlink()
            (self.root/'setup-ticket.json').unlink(missing_ok=True)
            return True

    def setup(self, username, password, *, reset=False):
        if not isinstance(username, str):
            raise AuthError('Tên tài khoản không hợp lệ.', 400)
        username = username.strip().lower()
        if not valid_username(username):
            raise AuthError('Nhập email hợp lệ hoặc tên tài khoản 3–32 ký tự không dấu.', 400)
        if not isinstance(password, str) or not 8 <= len(password) <= 256:
            raise AuthError('Mật khẩu cần từ 8 đến 256 ký tự.', 400)
        try:
            password.encode('utf-8')
        except UnicodeError:
            raise AuthError('Mật khẩu có ký tự không hợp lệ.', 400) from None
        with self.lock:
            if self.enabled and not reset:
                raise AuthError('Tài khoản đã được thiết lập. Không ghi đè.', 409)
            salt = secrets.token_hex(16)
            account = dict(version=1, username=username, salt=salt,
                           hash=password_hash(password, salt), kdf='scrypt-131072-8-1',
                           revision=secrets.token_hex(16), local_key=secrets.token_urlsafe(32))
            self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
            self.root.chmod(0o700)
            # A partial setup fails closed; missing/corrupt credentials cannot
            # silently disable the gate on a subsequent server startup.
            atomic_private(self.root/'required.json', {'version': 1})
            atomic_private(self.root/'account.json', account)
            with self.database() as db:
                db.execute('DELETE FROM sessions')
                db.execute('DELETE FROM attempts')

    def prepare_setup(self):
        """Only the local launcher can issue this short-lived capability."""
        with self.lock:
            if self.enabled or self.prepared_path.exists():
                raise AuthError('Tài khoản đã được tạo. Em có thể đăng nhập.', 409)
            token = secrets.token_urlsafe(32)
            atomic_private(self.root/'setup-ticket.json',
                           {'digest': digest(token), 'expires': self.clock()+1200})
            self.root.chmod(0o700)
            return token

    def verify_setup_ticket(self, token):
        if self.enabled or self.prepared_path.exists():
            raise AuthError('Tài khoản đã được tạo. Em có thể đăng nhập.', 409)
        try:
            ticket = json.loads((self.root/'setup-ticket.json').read_text())
            if (not isinstance(token, str) or not re.fullmatch(r'[A-Za-z0-9_-]{43}', token)
                    or not isinstance(ticket.get('expires'), (int, float))
                    or ticket['expires'] <= self.clock()
                    or not hmac.compare_digest(digest(token), ticket['digest'])):
                raise ValueError()
        except (OSError, ValueError, TypeError, KeyError, AttributeError):
            raise AuthError('Phiên tạo tài khoản đã hết hạn. Mở lại file Cập nhật app trên Mac mini.', 403) from None

    def setup_from_browser(self, token, username, password, confirmation):
        with self.lock:
            self.verify_setup_ticket(token)
            if not isinstance(password, str) or not isinstance(confirmation, str) or password != confirmation:
                raise AuthError('Hai mật khẩu chưa khớp. Em kiểm tra lại nhé.', 400)
            self.setup(username, password)
            (self.root/'setup-ticket.json').unlink(missing_ok=True)

    @contextmanager
    def database(self):
        path = self.root/'sessions.sqlite3'
        if not path.exists():
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.close(fd)
        db = sqlite3.connect(path, timeout=5)
        db.row_factory = sqlite3.Row
        db.executescript('''
            CREATE TABLE IF NOT EXISTS sessions (
                token TEXT PRIMARY KEY, revision TEXT NOT NULL,
                expires REAL NOT NULL, csrf TEXT NOT NULL, created REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS attempts (peer TEXT NOT NULL, created REAL NOT NULL);
        ''')
        try:
            with db:
                yield db
        finally:
            db.close()

    def login(self, username, password, peer, remember=False):
        if not isinstance(username, str) or not isinstance(password, str) or len(username) > 254 or len(password) > 256:
            raise AuthError('Tài khoản hoặc mật khẩu chưa đúng.')
        try:
            username.encode('utf-8')
            password.encode('utf-8')
        except UnicodeError:
            raise AuthError('Tài khoản hoặc mật khẩu chưa đúng.') from None
        # Serialize expensive hashing and persist limits across web restarts.
        with self.lock:
            account = self.account()
            now = self.clock()
            key = digest(str(peer)[:128])
            with self.database() as db:
                db.execute('DELETE FROM attempts WHERE created <= ?', (now-WINDOW,))
                all_count, own_count = db.execute('SELECT count(*),coalesce(sum(peer=?),0) FROM attempts', (key,)).fetchone()
                if all_count >= 30 or own_count >= 5:
                    raise AuthError('Đã thử nhiều lần. Vui lòng chờ 5 phút rồi đăng nhập lại.', 429)
                db.execute('INSERT INTO attempts VALUES (?,?)', (key, now))
            actual = password_hash(password, account['salt'])
            valid = hmac.compare_digest(actual, account['hash'])
            valid = hmac.compare_digest(username.strip().lower().encode(), account['username'].encode()) and valid
            if not valid:
                raise AuthError('Tài khoản hoặc mật khẩu chưa đúng.')
            token = secrets.token_urlsafe(32)
            with self.database() as db:
                db.execute('DELETE FROM sessions WHERE expires <= ? OR revision != ?', (now, account['revision']))
                db.execute('DELETE FROM attempts WHERE peer=?', (key,))
                db.execute('INSERT INTO sessions VALUES (?,?,?,?,?)',
                           (digest(token), account['revision'], now+(REMEMBER_SECONDS if remember else SESSION_SECONDS),
                            secrets.token_urlsafe(32), now))
                db.execute('DELETE FROM sessions WHERE token NOT IN (SELECT token FROM sessions ORDER BY created DESC LIMIT 20)')
            return token

    def session(self, token):
        account = self.account()
        if not re.fullmatch(r'[A-Za-z0-9_-]{43}', token or ''):
            return None
        with self.lock, self.database() as db:
            row = db.execute('SELECT * FROM sessions WHERE token=? AND revision=? AND expires>?',
                             (digest(token), account['revision'], self.clock())).fetchone()
            return {'username': account['username'], 'csrf': row['csrf']} if row else None

    def logout(self, token):
        with self.lock, self.database() as db:
            db.execute('DELETE FROM sessions WHERE token=?', (digest(token),))

    def internal_read(self, handler):
        if not local_request(handler) or handler.headers.get('Origin') or handler.headers.get('Sec-Fetch-Site'):
            return False
        key = handler.headers.get('X-Tao-Local-Key', '')
        return bool(key and hmac.compare_digest(key.encode(), self.account()['local_key'].encode()))

    def local_headers(self):
        return {'X-Tao-Local-Key': self.account()['local_key']} if self.enabled else {}


def setup_interactive(auth=None, reset=False):
    auth = auth or PasswordAuth()
    if not os.isatty(0):
        raise AuthError('Mở Cap-nhat-app.command trong Terminal trên Mac mini để tự đặt mật khẩu.', 400)
    print('Thiết lập tài khoản riêng cho TáoWork. Mật khẩu được nhập ẩn, không phải mật khẩu MWG/Gmail.')
    username = input('Tên tài khoản [tam]: ').strip() or 'tam'
    password = getpass.getpass('Mật khẩu mới (ít nhất 8 ký tự): ')
    if password != getpass.getpass('Nhập lại mật khẩu: '):
        raise AuthError('Hai mật khẩu không khớp. Chưa thay đổi tài khoản.', 400)
    auth.setup(username, password, reset=reset)
    print('Đã lưu tài khoản TáoWork. Mật khẩu không được ghi vào nhật ký.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Thiết lập/khôi phục tài khoản TáoWork tại Mac mini.')
    parser.add_argument('--reset', action='store_true', help='Đặt lại mật khẩu và thu hồi tất cả phiên đăng nhập')
    args = parser.parse_args()
    try:
        setup_interactive(reset=args.reset)
    except (AuthError, OSError) as error:
        print(str(error))
        raise SystemExit(1)
