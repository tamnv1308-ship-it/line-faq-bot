"""Persistent cloud report runner. No Excel, launchd or Mac callback."""
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import zipfile

from flask import jsonify, request, send_file
from taowork_dashboard import directory, save

FILES = {
    'history': 'report/.private/sales-history.sqlite3',
    'mwg': 'report/.private/mwg-session.json',
    'telegram': 'report/.private/telegram-bot.json',
    'delivery': 'report/.private/delivery.sqlite3',
    'dictionary': 'report/inputs/ten_viet_tat.xlsx',
    'fontregular': 'report/fonts/Arial.ttf',
    'fontbold': 'report/fonts/Arial Bold.ttf',
    'fontlicense': 'report/fonts/OFL.txt',
    'calendar': 'settings/apple-calendar.json',
    'targets': 'settings/revenue-targets.json',
    'lastreceipt': 'report/.private/last-manual-run.json',
    'snapshots': 'snapshots.zip',
}
CODE = Path(__file__).resolve().parent


def initialize():
    root = directory()
    for name in ('report/.private', 'report/inputs', 'report/runs', 'report/fonts', 'settings'):
        (root/name).mkdir(mode=0o700, parents=True, exist_ok=True)
    for name in ('bot', 'work'):
        path = root/'report'/name
        if not path.exists():
            path.symlink_to(CODE/'cloud_report'/name, target_is_directory=True)
    return root


@contextmanager
def worker_lock(root):
    with (root/'runtime.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield


def atomic(path, value):
    from cloud_passwords import atomic_private
    atomic_private(path, value)


def enabled(root):
    try:
        return json.loads((root/'runtime-enabled.json').read_text()).get('enabled') is True
    except (OSError, ValueError):
        return False


def publish():
    from cloud_analytics.business_analytics import load_business
    from cloud_analytics.revenue_report import load_revenue
    payload = {'schema': 1, 'analytics': load_business(), 'revenue': load_revenue()}
    return save(directory(), payload)


def cli(mode, request_id=''):
    root = initialize()
    os.environ['TAOWORK_REPORT_ROOT'] = str(root/'report')
    sys.path[:0] = [str(CODE/'cloud_report/bot'), str(CODE/'cloud_report/work')]
    with worker_lock(root):
        if mode == 'publish':
            publish()
            return
        if mode == 'probe':
            atomic(root/'last-error.json', {'operation': mode, 'phase': 'mwg', 'state': 'checking'})
            import ssl
            import uuid
            import urllib.request
            from mwg_auth import read_state, local_tokens, ORIGIN, NoRedirect
            token = local_tokens(read_state())['access_token']
            context = ssl.create_default_context()
            try:
                import certifi
                context.load_verify_locations(certifi.where())
            except ImportError:
                pass
            opener = urllib.request.build_opener(NoRedirect(), urllib.request.HTTPSHandler(context=context))
            req = urllib.request.Request(ORIGIN+'/kb-api/reports/export-templates?report_key=margin-daily',
                                         headers={'Authorization': 'Bearer '+token, 'Origin': ORIGIN,
                                                  'Content-Type': 'application/json', 'X-Request-ID': str(uuid.uuid4())})
            with opener.open(req, timeout=30) as response:
                data = json.loads(response.read())
            assert any(x.get('name') == 'BI MỖI NGÀY' for x in data.get('templates', []))
            import report_bot as bot
            atomic(root/'last-error.json', {'operation': mode, 'phase': 'telegram', 'state': 'checking'})
            bot.verify_telegram(bot.read_config())
            atomic(root/'mwg-probe.json', {'ok': True, 'at': datetime.now(timezone.utc).isoformat(),
                                         'telegram_destination_verified': True, 'mac_callback': False})
            return
        import report_bot as bot
        try:
            prior = json.loads((root/'report/.private/last-manual-run.json').read_text())
        except (OSError, ValueError):
            prior = {}
        if prior.get('state') in ('unknown', 'sending', 'building'):
            raise RuntimeError('Unresolved report delivery; owner review required')
        if mode == 'dry-run':
            started = time.monotonic()
            report = bot.build_report(bot.now_vn().date(), 'cloud-acceptance-'+secrets.token_hex(8), api_export=True)
            from report_photos import report_photos, validate_photos
            photos = report_photos(report)
            validate_photos(photos, expected=3)
            atomic(root/'acceptance.json', {'ok': True, 'source_mode': 'authenticated_mwg_api',
                   'report_date': report['report_date'], 'rows': report['source_rows'], 'photos': 3,
                   'seconds': round(time.monotonic()-started, 3), 'telegram_sent': False,
                   'mac_callback': False, 'photo_bytes': sum(Path(p).stat().st_size for p in photos)})
            atomic(root/'acceptance-private.json', {'photos': [str(p) for p in photos]})
        elif mode == 'report':
            bot.run_now(request_id)
        elif mode == 'refresh':
            from sales_history import update_once
            update_once(root/'report', force=True)
        elif mode == 'tick':
            bot.tick()
        else:
            raise ValueError('Unknown cloud operation')
        publish()


def invoke(mode, request_id=''):
    root = initialize()
    env = dict(os.environ, TAOWORK_DATA_DIR=str(root), TAOWORK_REPORT_ROOT=str(root/'report'))
    with (root/'runtime.log').open('ab') as log:
        return subprocess.run([sys.executable, str(Path(__file__)), mode, request_id], env=env,
                              stdin=subprocess.DEVNULL, stdout=log, stderr=log, timeout=1200).returncode


def state_db(root):
    db = sqlite3.connect(root/'runtime.sqlite3', timeout=5)
    db.row_factory = sqlite3.Row
    db.execute('CREATE TABLE IF NOT EXISTS actions(id TEXT PRIMARY KEY, action TEXT, state TEXT, created REAL, finished REAL)')
    db.commit()
    return db


def run_action(root, action, request_id):
    try:
        code = invoke('report' if action == 'report.run' else 'refresh', request_id)
        outcome = 'done' if code == 0 else 'failed'
        receipt = root/'report/.private/last-manual-run.json'
        if action == 'report.run' and receipt.exists():
            value = json.loads(receipt.read_text())
            if value.get('request_id') == request_id:
                outcome = ('done' if value.get('state') == 'sent' else
                           'unknown' if value.get('state') in ('unknown', 'sending', 'building') else 'failed')
    except Exception:
        outcome = 'unknown' if action == 'report.run' else 'failed'
    with state_db(root) as db:
        db.execute('UPDATE actions SET state=?,finished=? WHERE id=?', (outcome, time.time(), request_id))


def status(root):
    with state_db(root) as db:
        jobs = [dict(x) for x in db.execute('SELECT * FROM actions ORDER BY created DESC LIMIT 10')]
    receipt = {}
    try:
        raw = json.loads((root/'report/.private/last-manual-run.json').read_text())
        receipt = {k: raw.get(k) for k in ('state', 'phase', 'request_id', 'finished')}
    except (OSError, ValueError):
        pass
    return {'enabled': enabled(root), 'actions': jobs, 'report': receipt,
            'mac_required': False, 'source_mode': 'authenticated_mwg_api',
            'mwg_configured': (root/FILES['mwg']).exists(),
            'history_present': (root/FILES['history']).exists()}


def install(bp, identity, same_origin, error):
    from taowork_accounts import worker_auth

    @bp.post('/dashboard/api/import/<name>/<int:offset>')
    def upload(name, offset):
        worker_auth()
        if name not in FILES or enabled(directory()):
            raise error('Không nhận dữ liệu khởi tạo khi runtime đã bật.', 409)
        length = request.content_length
        if not length or not 0 < length <= 2*1024*1024:
            raise error('Gói dữ liệu không hợp lệ.', 413)
        digest = request.headers.get('X-Upload-SHA256', '')
        chunk_digest = request.headers.get('X-Content-SHA256', '')
        try:
            total = int(request.headers.get('X-Total-Size', ''))
        except ValueError:
            raise error('Kích thước không hợp lệ.', 400) from None
        if not re.fullmatch(r'[a-f0-9]{64}', digest) or not 0 < total <= 128*1024*1024 or offset+length > total:
            raise error('Gói dữ liệu không hợp lệ.', 400)
        root = initialize()
        incoming = root/'incoming'
        incoming.mkdir(mode=0o700, exist_ok=True)
        target = root/FILES[name]
        if target.exists() and hashlib.sha256(target.read_bytes()).hexdigest() == digest:
            return jsonify(offset=total, complete=True, sha256=digest)
        raw = request.get_data(cache=False)
        if len(raw) != length or hashlib.sha256(raw).hexdigest() != chunk_digest:
            raise error('Mã kiểm tra không khớp.', 409)
        path = incoming/(name+'-'+digest)
        with (incoming/'upload.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            size = path.stat().st_size if path.exists() else 0
            if offset < size:
                with path.open('rb') as prior:
                    prior.seek(offset)
                    if prior.read(length) != raw:
                        raise error('Nội dung gói đã nhận khác lần trước.', 409)
                return jsonify(offset=size, complete=False)
            if offset != size:
                raise error('Thứ tự gói không hợp lệ.', 409)
            with path.open('ab') as output:
                output.write(raw)
                output.flush()
                os.fsync(output.fileno())
            path.chmod(0o600)
            size += length
            if size == total:
                if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                    raise error('Mã kiểm tra tổng không khớp.', 409)
                if name in ('history', 'delivery'):
                    with sqlite3.connect(path.as_uri()+'?mode=ro', uri=True) as db:
                        if db.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
                            raise error('Cơ sở dữ liệu chưa hợp lệ.', 409)
                if target.exists():
                    target.replace(target.with_suffix(target.suffix+'.before-cloud-import'))
                os.replace(path, target)
                if name == 'snapshots':
                    with zipfile.ZipFile(target) as archive:
                        if sum(x.file_size for x in archive.infolist()) > 64*1024*1024:
                            raise error('Gói lịch sử quá lớn.', 413)
                        for item in archive.infolist():
                            if not re.fullmatch(r'\d{4}-\d{2}-\d{2}/\d{4}\.json', item.filename):
                                raise error('Tên bản chụp không hợp lệ.', 400)
                            data = archive.read(item)
                            json.loads(data)
                            dest = root/'report/.private/sales-snapshots'/item.filename
                            dest.parent.mkdir(parents=True, exist_ok=True)
                            dest.write_bytes(data)
            return jsonify(offset=size, complete=size == total, sha256=digest if size == total else None)

    @bp.post('/dashboard/api/bootstrap-verify/<operation>')
    def verify(operation):
        worker_auth()
        if operation == 'status':
            root = initialize()
            result = status(root)
            for name in ('runtime-heartbeat', 'acceptance', 'mwg-probe', 'verification', 'last-error'):
                try:
                    result[name] = json.loads((root/(name+'.json')).read_text())
                except (OSError, ValueError):
                    result[name] = None
            return jsonify(result)
        if operation not in ('publish', 'probe', 'dry-run') or enabled(directory()):
            raise error('Thao tác khởi tạo không hợp lệ.', 409)
        root = initialize()
        with (root/'verification.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                previous = json.loads((root/'verification.json').read_text())
            except (OSError, ValueError):
                previous = {}
            if previous.get('state') == 'running':
                return jsonify(verification=previous), 202
            atomic(root/'verification.json', {'operation': operation, 'state': 'running'})
        def run():
            try:
                code = invoke(operation)
            except Exception:
                code = -1
            atomic(root/'verification.json', {'operation': operation, 'state': 'done' if code == 0 else 'failed'})
        threading.Thread(target=run, daemon=True, name='taowork-verify').start()
        return jsonify(accepted=True, operation=operation), 202

    @bp.get('/dashboard/api/bootstrap-export/mwg')
    def rollback_session():
        worker_auth()
        if enabled(directory()):
            raise error('Khởi tạo đã kết thúc.', 409)
        return send_file(directory()/FILES['mwg'], mimetype='application/json')

    @bp.get('/dashboard/api/bootstrap-photo/<int:index>')
    def acceptance_photo(index):
        worker_auth()
        root = directory()
        if enabled(root) or index not in (0, 1, 2):
            raise error('Không tìm thấy nội dung.', 404)
        photos = json.loads((root/'acceptance-private.json').read_text())['photos']
        target = Path(photos[index]).resolve()
        target.relative_to((root/'report/runs').resolve())
        return send_file(target, mimetype='image/jpeg')

    @bp.post('/dashboard/api/bootstrap-activate')
    def activate():
        worker_auth()
        root = initialize()
        if (not all((root/FILES[n]).exists() for n in FILES)
                or not (root/'mwg-probe.json').exists() or not (root/'acceptance.json').exists()
                or not (root/'auth/account.json').exists()):
            raise error('Chưa đủ dữ liệu hoặc chưa xác minh MWG từ cloud.', 409)
        atomic(root/'runtime-enabled.json', {'enabled': True})
        return jsonify(enabled=True, mac_required=False)

    @bp.get('/dashboard/api/runtime')
    def runtime_status():
        identity()
        return jsonify(status(initialize()))

    @bp.post('/dashboard/api/action')
    def action():
        user = identity()
        same_origin()
        if not hmac_compare(request.headers.get('X-App-CSRF', ''), user['csrf']):
            raise error('Phiên thao tác không hợp lệ.', 403)
        if not request.is_json or not request.content_length or request.content_length > 1024:
            raise error('Yêu cầu không hợp lệ.', 400)
        data = request.get_json()
        if not isinstance(data, dict) or set(data) != {'action', 'request_id'} or data['action'] not in ('report.run', 'data.refresh') or not re.fullmatch(r'[a-f0-9]{32}', str(data['request_id'])):
            raise error('Yêu cầu không hợp lệ.', 400)
        root = initialize()
        if not enabled(root):
            raise error('Cloud chưa hoàn tất kích hoạt.', 503)
        with state_db(root) as db:
            db.execute('BEGIN IMMEDIATE')
            previous = db.execute('SELECT * FROM actions WHERE id=?', (data['request_id'],)).fetchone()
            if previous:
                if previous['action'] != data['action']:
                    raise error('Mã thao tác đã được dùng.', 409)
                return jsonify(job=dict(previous)), 202
            if db.execute("SELECT 1 FROM actions WHERE state IN ('running','unknown')").fetchone():
                raise error('Đang xử lý hoặc cần đối soát lượt trước; không gửi lại.', 409)
            db.execute('INSERT INTO actions VALUES (?,?,?,?,NULL)', (data['request_id'], data['action'], 'running', time.time()))
        threading.Thread(target=run_action, args=(root, data['action'], data['request_id']), daemon=True).start()
        return jsonify(job={'id': data['request_id'], 'state': 'running'}), 202

    if os.getenv('RENDER') == 'true':
        def loop():
            root = initialize()
            with state_db(root) as db:
                db.execute("UPDATE actions SET state=CASE WHEN action='report.run' THEN 'unknown' ELSE 'failed' END WHERE state='running'")
            while True:
                if enabled(root):
                    try:
                        code = invoke('tick')
                        atomic(root/'runtime-heartbeat.json', {'at': datetime.now(timezone.utc).isoformat(),
                                                              'state': 'ok' if code == 0 else 'failed'})
                    except Exception:
                        pass  # Existing snapshots and delivery receipts remain authoritative.
                time.sleep(60)
        threading.Thread(target=loop, daemon=True, name='taowork-cloud').start()


def hmac_compare(a, b):
    import hmac
    return hmac.compare_digest(a.encode(), b.encode())


if __name__ == '__main__':
    try:
        cli(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else '')
    except Exception as exc:
        root = initialize()
        try:
            detail = json.loads((root/'last-error.json').read_text())
        except (OSError, ValueError):
            detail = {}
        detail.update(operation=sys.argv[1], state='failed', exception=type(exc).__name__,
                      http_status=getattr(exc, 'code', None))
        atomic(root/'last-error.json', detail)
        raise
