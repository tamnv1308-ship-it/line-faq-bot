"""Owner-only reports in the existing LINE service; never executes a Mac job."""
from contextlib import contextmanager
from datetime import date, datetime, timezone
import fcntl
import gzip
import hashlib
import hmac
import json
import math
import os
from pathlib import Path
import tempfile

from flask import jsonify, request, send_from_directory

MAX_BYTES = 8 * 1024 * 1024
ASSETS = {'app.js', 'app.css', 'cloud.js'}
GROUPS = {'iphone', 'ipad', 'mac', 'watch', 'airpods', 'accessories'}


def directory():
    value = os.getenv('TAOWORK_DATA_DIR', '/var/data/taowork')
    path = Path(value)
    if not path.is_absolute():
        raise ValueError('Persistent directory required')
    return path


def validate(payload):
    if not isinstance(payload, dict) or set(payload) != {'schema', 'analytics', 'revenue'} or payload['schema'] != 1:
        raise ValueError('Invalid snapshot')
    for key in ('analytics', 'revenue'):
        data = payload[key]
        if not isinstance(data, dict) or data.get('schema') != 1:
            raise ValueError('Invalid report schema')
        cutoff = date.fromisoformat(data['cutoff'])
        if cutoff > datetime.now(timezone.utc).date():
            raise ValueError('Future report')
        stamp = datetime.fromisoformat(data['source_as_of'])
        if stamp.tzinfo is None:
            raise ValueError('Missing source timezone')
        groups = data.get('groups')
        if not isinstance(groups, list) or len(groups) != 6 or {g.get('id') for g in groups} != GROUPS:
            raise ValueError('Missing report groups')
    if payload['revenue'].get('unit') != 'million_vnd' or not payload['revenue'].get('periods'):
        raise ValueError('Invalid revenue units or periods')
    if not payload['analytics'].get('daily'):
        raise ValueError('Missing business history')
    # Reject non-finite JSON values and credential-bearing fields anywhere.
    forbidden = {'token', 'password', 'cookie', 'authorization', 'csrf', 'chat_id', 'secret', 'credentials'}
    def check(value):
        if isinstance(value, dict):
            if any(str(k).casefold() in forbidden for k in value):
                raise ValueError('Unexpected private fields')
            for v in value.values():
                check(v)
        elif isinstance(value, list):
            for v in value:
                check(v)
        elif isinstance(value, float) and not math.isfinite(value):
            raise ValueError('Invalid number')
    check(payload)
    return payload


@contextmanager
def locked(root):
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    with (root / 'snapshot.lock').open('a') as lock:
        os.chmod(lock.name, 0o600)
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def read(root):
    with gzip.open(root / 'snapshot.json.gz', 'rb') as source:
        raw = source.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError('Stored snapshot too large')
    return json.loads(raw)


def save(root, payload):
    validate(payload)
    raw = json.dumps(payload, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode()
    if len(raw) > MAX_BYTES:
        raise ValueError('Snapshot too large')
    digest = hashlib.sha256(raw).hexdigest()
    with locked(root):
        try:
            previous = read(root)
        except FileNotFoundError:
            previous = None
        # A corrupt existing snapshot fails closed; do not silently replace it.
        if previous:
            for key in ('analytics', 'revenue'):
                old, new = previous['data'][key], payload[key]
                if new['cutoff'] < old['cutoff'] or datetime.fromisoformat(new['source_as_of']) < datetime.fromisoformat(old['source_as_of']):
                    raise ValueError('Older source')
            if digest == previous['sha256']:
                return previous
        result = {'schema': 1, 'received_at': datetime.now(timezone.utc).isoformat(),
                  'sha256': digest, 'data': payload}
        with tempfile.NamedTemporaryFile(dir=root, delete=False) as tmp:
            temporary = Path(tmp.name)
            tmp.write(gzip.compress(json.dumps(result, ensure_ascii=False, allow_nan=False).encode(), mtime=0))
            tmp.flush()
            os.fsync(tmp.fileno())
        try:
            temporary.chmod(0o600)
            os.replace(temporary, root / 'snapshot.json.gz')
        finally:
            temporary.unlink(missing_ok=True)
        return result


def install(bp, identity, require_owner, error):
    assets = Path(__file__).resolve().parent / 'taowork_assets'

    def owner():
        require_owner(identity())

    def snapshot():
        try:
            return read(directory())
        except (OSError, ValueError, KeyError):
            raise error('Chưa có bản đồng bộ hợp lệ từ Mac mini.', 503) from None

    @bp.get('/dashboard')
    @bp.get('/dashboard/')
    def dashboard_index():
        owner()
        return send_from_directory(assets, 'index.html')

    @bp.get('/dashboard/assets/<name>')
    def dashboard_asset(name):
        owner()
        if name not in ASSETS:
            raise error('Không tìm thấy nội dung.', 404)
        return send_from_directory(assets, name)

    @bp.get('/dashboard/api/<name>')
    def dashboard_data(name):
        owner()
        if name not in {'analytics', 'revenue', 'status'}:
            raise error('Không tìm thấy nội dung.', 404)
        # Reports are published from cloud history by the background process.
        # Keep HTTP reads bounded; do not rebuild the full history in gunicorn.
        data = snapshot()
        if name == 'status':
            return jsonify(schema=1, received_at=data['received_at'], sha256=data['sha256'],
                           cutoff=data['data']['revenue']['cutoff'], source_mode='cloud_stored_history' if (directory()/'report/.private/sales-history.sqlite3').is_file() else 'snapshot',
                           mac_required=not (directory()/'report/.private/sales-history.sqlite3').is_file())
        response = jsonify(data['data'][name])
        if request.accept_encodings['gzip'] > 0:
            response.set_data(gzip.compress(response.get_data(), compresslevel=5, mtime=0))
            response.headers['Content-Encoding'] = 'gzip'
        response.headers['Vary'] = 'Accept-Encoding'
        return response

    @bp.post('/dashboard/api/snapshot')
    def dashboard_upload():
        # This fixed, data-only endpoint uses the already installed Mac worker
        # identity. It cannot read sessions or issue CO/report/send commands.
        if ((directory()/'runtime-enabled.json').exists()
                or (directory()/'report/.private/sales-history.sqlite3').is_file()):
            raise error('Dashboard đã chạy độc lập trên cloud.', 409)
        token = os.getenv('CO_WORKER_TOKEN', '')
        if os.getenv('CO_ENABLED') != '1' or len(token) < 32:
            raise error('Kết nối Mac chưa sẵn sàng.', 503)
        if not hmac.compare_digest(request.headers.get('Authorization', '').encode(), ('Bearer ' + token).encode()):
            raise error('Không được phép.', 401)
        if not request.is_json:
            raise error('Yêu cầu JSON không hợp lệ.', 415)
        if request.content_length is None or not 0 < request.content_length <= MAX_BYTES:
            raise error('Bản đồng bộ quá lớn.', 413)
        try:
            payload = request.get_json()
            result = save(directory(), payload)
        except (ValueError, KeyError, TypeError):
            raise error('Bản đồng bộ không hợp lệ hoặc cũ hơn dữ liệu đã lưu.', 409) from None
        return jsonify(schema=1, sha256=result['sha256'], received_at=result['received_at'])
