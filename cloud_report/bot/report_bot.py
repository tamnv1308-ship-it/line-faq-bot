import os
"""Daily Apple report runner. Credentials remain in .private, never in this file."""
import argparse
import fcntl
import importlib.util
import http.client
import json
import mimetypes
import os
import plistlib
import re
import sqlite3
import ssl
import subprocess
import sys
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
from mwg_auth import session_lock, refresh_if_due, LoginRequired, SessionBusy

ROOT = Path(os.environ['TAOWORK_REPORT_ROOT'])
PRIVATE = ROOT / '.private'
CONFIG = PRIVATE / 'telegram-bot.json'
VN = ZoneInfo('Asia/Ho_Chi_Minh')
TIMES = ['10:00', '12:00', '14:00', '16:00', '18:00', '20:00', '22:00']
TELEGRAM_CONNECT_TIMEOUT = 15
TELEGRAM_UPLOAD_TIMEOUT = 90
LABEL = 'vn.mwg.apple-daily-report'
FETCH_PYTHON = Path(sys.executable)
RENDER_PYTHON = Path(sys.executable)
sys.path.insert(0, str(ROOT / 'work'))
from report_comparison import attach_comparison, parse_time, numeric_data, number, percent, change_text, billion
from decimal import Decimal


class ApiRejected(RuntimeError):
    pass


class DeliveryUncertain(RuntimeError):
    pass


class TelegramHTTPSConnection(http.client.HTTPSConnection):
    """Keep TLS connection waits short; allow a separate budget for uploads."""
    def connect(self):
        super().connect()
        self.sock.settimeout(TELEGRAM_UPLOAD_TIMEOUT)


class TelegramHTTPSHandler(urllib.request.HTTPSHandler):
    def https_open(self, request):
        return self.do_open(TelegramHTTPSConnection, request, context=self._context)


def open_telegram_upload(request, context):
    # Preserve urllib's normal proxy handling and TLS verification. Never replay
    # a POST after a timeout: the server may already have received its photos.
    opener = urllib.request.build_opener(TelegramHTTPSHandler(context=context))
    return opener.open(request, timeout=TELEGRAM_CONNECT_TIMEOUT)


def now_vn():
    return datetime.now(VN)


def log(event, **fields):
    print(json.dumps(dict(time=now_vn().isoformat(), event=event, **fields), ensure_ascii=False), flush=True)


def read_config():
    config = json.loads(CONFIG.read_text())
    if config.get('timezone') != 'Asia/Ho_Chi_Minh' or config.get('report_times') != TIMES:
        raise RuntimeError('Lịch không khớp 7 mốc giờ Việt Nam đã chốt')
    if not config.get('token') or not config.get('chat_id'):
        raise RuntimeError('Thiếu cấu hình Telegram')
    return config


def save_json(path, value):
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.tmp')
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
    os.replace(temporary, path)


def telegram(config, method, fields=None, files=None, delivery=False):
    fields = fields or {}
    if files:
        boundary = 'mwg-' + uuid.uuid4().hex
        parts = []
        for key, value in fields.items():
            parts.append(('--' + boundary + '\r\nContent-Disposition: form-data; name="' + key + '"\r\n\r\n' + str(value) + '\r\n').encode())
        for key, path in files:
            path = Path(path)
            mime = mimetypes.guess_type(path.name)[0] or 'application/octet-stream'
            parts.append(('--' + boundary + '\r\nContent-Disposition: form-data; name="' + key + '"; filename="' + path.name + '"\r\nContent-Type: ' + mime + '\r\n\r\n').encode())
            parts.extend([path.read_bytes(), b'\r\n'])
        parts.append(('--' + boundary + '--\r\n').encode())
        payload = b''.join(parts)
        content_type = 'multipart/form-data; boundary=' + boundary
    else:
        # getMe has no fields: an empty multipart envelope is rejected upstream.
        payload = json.dumps(fields, ensure_ascii=False).encode('utf-8')
        content_type = 'application/json; charset=utf-8'
    request = urllib.request.Request('https://api.telegram.org/bot' + config['token'] + '/' + method, data=payload,
        headers={'Content-Type': content_type, 'Content-Length': str(len(payload))})
    context = ssl.create_default_context()
    if importlib.util.find_spec('certifi'):
        import certifi
        context = ssl.create_default_context(cafile=certifi.where())
    try:
        opened = (open_telegram_upload(request, context) if delivery and files else
                  urllib.request.urlopen(request, timeout=20, context=context))
        with opened as response:
            result = json.loads(response.read())
    except urllib.error.HTTPError as exc:
        log('telegram_http_error', method=method, status=exc.code, upload_bytes=len(payload))
        try:
            rejected = json.loads(exc.read())
        except (ValueError, OSError):
            rejected = {}
        if rejected.get('ok') is False:
            raise ApiRejected('Telegram từ chối yêu cầu, mã ' + str(exc.code)) from None
        if delivery:
            raise DeliveryUncertain('Chưa rõ Telegram đã nhận báo cáo; không tự gửi lại') from None
        raise RuntimeError('Không kiểm tra được Telegram: HTTP ' + str(exc.code) + ' (' + method + ')') from None
    except (urllib.error.URLError, OSError, ValueError) as exc:
        log('telegram_transport_error', method=method, error_type=type(exc).__name__,
            reason_type=type(exc.reason).__name__ if isinstance(exc, urllib.error.URLError) else None,
            upload_bytes=len(payload))
        if delivery:
            raise DeliveryUncertain('Kết nối Telegram gián đoạn trong lúc gửi ảnh. Chưa xác nhận kết quả; kiểm tra nhóm trước khi lấy số mới') from None
        raise RuntimeError('Không kết nối được Telegram') from None
    if not result.get('ok'):
        raise ApiRejected('Telegram không chấp nhận yêu cầu')
    return result['result']


def verify_telegram(config):
    me = telegram(config, 'getMe')
    if me['id'] != config['bot_id']:
        raise RuntimeError('Token không đúng bot đã cấu hình')
    chat = telegram(config, 'getChat', {'chat_id': config['chat_id']})
    member = telegram(config, 'getChatMember', {'chat_id': config['chat_id'], 'user_id': me['id']})
    if chat['id'] != config['chat_id'] or member['status'] not in ['administrator', 'member', 'creator']:
        raise RuntimeError('Bot chưa có quyền gửi vào nhóm')
    log('telegram_verified', bot=me.get('username'), chat=chat.get('title'))


def due_slot(now, window_minutes=10, one_off_slots=None):
    local = now.astimezone(VN)
    slots = [datetime.fromisoformat(value).astimezone(VN) for value in (one_off_slots or [])]
    for value in TIMES:
        hour, minute = map(int, value.split(':'))
        slots.append(local.replace(hour=hour, minute=minute, second=0, microsecond=0))
    for slot in sorted(slots, reverse=True):
        if 0 <= (local - slot).total_seconds() < window_minutes * 60:
            return slot
    return None


def next_slot(now, one_off_slots=None):
    local = now.astimezone(VN)
    candidates = [datetime.fromisoformat(value).astimezone(VN) for value in (one_off_slots or [])]
    for offset in [0, 1]:
        day = local + timedelta(days=offset)
        for value in TIMES:
            hour, minute = map(int, value.split(':'))
            candidate = day.replace(hour=hour, minute=minute, second=0, microsecond=0)
            candidates.append(candidate)
    return min(candidate for candidate in candidates if candidate > local)


def database():
    db = sqlite3.connect(PRIVATE / 'delivery.sqlite3', timeout=5)
    db.execute('CREATE TABLE IF NOT EXISTS jobs (slot TEXT PRIMARY KEY, state TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0, started TEXT, result TEXT)')
    db.execute('CREATE TABLE IF NOT EXISTS alerts (day TEXT PRIMARY KEY)')
    db.execute('CREATE TABLE IF NOT EXISTS telegram_cursor (id INTEGER PRIMARY KEY CHECK(id=1), offset INTEGER NOT NULL)')
    db.execute('CREATE TABLE IF NOT EXISTS command_requests (update_id INTEGER PRIMARY KEY, requested_at TEXT NOT NULL, state TEXT NOT NULL, result TEXT)')
    db.commit()
    return db


def run_child(command, log_path, timeout):
    with log_path.open('w') as handle:
        result = subprocess.run([str(x) for x in command], stdout=handle, stderr=subprocess.STDOUT, timeout=timeout)
    if result.returncode == 12:
        raise RuntimeError('Phiên MWG hết hạn. Mở Dang-nhap-MWG.command để đăng nhập lại')
    if result.returncode:
        raise RuntimeError('Chưa xuất hoặc kiểm tra được báo cáo; xem nhật ký của lần chạy')


def build_report(day, key, api_export=True):
    if not api_export: raise RuntimeError("Cloud chỉ dùng API MWG.")
    directory = ROOT / 'runs' / day.isoformat() / key
    directory.mkdir(parents=True, exist_ok=True)
    source = directory / 'BI_MOI_NGAY.xlsx'
    log('fetch_started', report_date=day.isoformat())
    fetch_python = RENDER_PYTHON if api_export else FETCH_PYTHON
    fetch_script = ROOT/'bot/mwg_api.py' if api_export else ROOT/'bot/mwg_fetch.py'
    run_child([fetch_python, fetch_script, '--date', day.isoformat(), '--output', source], directory/'fetch.log', 780)
    export_metadata=json.loads(source.with_suffix('.export.json').read_text())
    snapshot_time = parse_time(export_metadata['exported_at_vn']).strftime('%H:%M')
    checks = directory / 'checks.json'
    run_child([RENDER_PYTHON, ROOT/'work/build_three_tables.py', '--input', source,
        '--out', directory, '--date', day.isoformat(), '--snapshot', snapshot_time,
        '--checks', checks, '--combined', directory/'Apple_Bao_Cao_8_Bang.pdf'], directory/'render.log', 180)
    report = json.loads(checks.read_text())
    displayed_rows = export_metadata.get('source_rows')
    if displayed_rows is not None and report['source_rows'] != displayed_rows:
        raise RuntimeError('Số dòng file tải về không khớp tác vụ MWG vừa xuất')
    if report['report_date'] != day.isoformat() or len(report['tables']) != 8:
        raise RuntimeError('Kết quả không đủ bảng tổng quan và 6 nhóm chi tiết hoặc sai ngày')
    if len({Path(table['pdf']).name for table in report['tables']}) != 8:
        raise RuntimeError('Tệp báo cáo bị trùng')
    if [t.get('category') for t in report['tables'][2:]] != ['iPhone','iPad','Mac','Watch','AirPods','Phụ kiện tiện ích']:
        raise RuntimeError('Sai thứ tự hoặc thiếu nhóm chi tiết')
    for table in report['tables']:
        if not Path(table['pdf']).is_file():
            raise RuntimeError('Thiếu tệp PDF báo cáo')
    if day == now_vn().date():
        exported = parse_time(export_metadata['exported_at_vn'])
        slot = (datetime.combine(day, datetime.strptime(key[:4], '%H%M').time(), tzinfo=VN)
                if re.match(r'^\d{4}(?:-|$)', key) else exported.replace(second=0, microsecond=0))
        if not 0 <= (exported-slot).total_seconds() < 600:
            slot = exported.replace(second=0, microsecond=0)
        report = attach_comparison(report, export_metadata, slot, PRIVATE/'sales-snapshots', directory)
        from pypdf import PdfWriter
        combined = directory/'Apple_Bao_Cao_9_Bang.pdf'
        with PdfWriter() as writer:
            for table in report['tables']:
                writer.append(table['pdf'])
            writer.write(combined)
        report['combined_pdf'] = str(combined)
        save_json(checks, report)
    config = read_config()
    if day == now_vn().date() and config.get('report_layout') == 'three_images_aligned_v1':
        report = apply_report_layout(config, report, export_metadata, slot, directory)
        save_json(checks, report)
    elif day == now_vn().date() and config.get('period_model_comparison_enabled'):
        from period_model_comparison import build as build_period_comparisons
        report['period_comparison_photos'] = build_period_comparisons(ROOT, report, export_metadata, slot, directory)
        save_json(checks, report)
    elif day == now_vn().date() and config.get('period_overview_enabled'):
        from period_overview import build as build_overview
        report.pop('overview_photo', None)
        report['comparison_header_photo'] = str(build_overview(ROOT, report, export_metadata, slot, directory))
        save_json(checks, report)
    log('report_validated', report_date=day.isoformat(), rows=report['source_rows'], total=report['grand_total'][:2])
    return report


def apply_report_layout(config, report, metadata, slot, directory):
    """Scheduled and manual exports share the approved layout and photo selection."""
    if config.get('report_layout') != 'three_images_aligned_v1':
        return report
    from approved_report import build, LAYOUT, CALCULATION
    built = build(ROOT, report, metadata, slot, directory)
    return dict(report, delivery_layout=LAYOUT, delivery_calculation=CALCULATION,
                delivery_photos=built['photos'], comparison=built['comparison'])


def report_summary(report, slot, sample=False):
    today = [Decimal(v) for v in numeric_data(report)['total']]
    comparison = report.get('comparison', {})
    before = comparison.get('yesterday_total') if comparison.get('baseline_available') else None
    calendar_days = comparison.get('basis') == 'calendar_days_current_partial'
    heading = ('🧪 CHẠY THỬ | ' if sample else '📊 ') + slot.strftime('%d/%m %H:%M')
    if before is not None:
        heading += ' | So với cả ngày hôm qua' if calendar_days else ' | So với hôm qua cùng giờ'
        changes = []
        for i in (0,1):
            value = percent(today[i], Decimal(before[i]))
            text = change_text(value)
            icon = '🟢' if text.startswith('+') else '🔴' if text.startswith('-') and text != '-' else '⚪'
            changes.append(text + ' ' + icon)
        return heading + '\n📦 SL: ' + number(today[0]) + ' SP | ' + changes[0] + '\n💰 DT: ' + billion(today[1]) + ' tỷ | ' + changes[1]
    missing = 'Chưa có đủ số cả ngày hôm qua.' if calendar_days else 'Chưa có số hôm qua cùng giờ.'
    return heading + '\n📦 SL: ' + number(today[0]) + ' SP\n💰 DT: ' + billion(today[1]) + ' tỷ\n🕒 ' + missing


def send_report(config, report, slot, sample=False, scheduled=False):
    from report_photos import report_photos, album_sizes
    if config.get('report_layout') == 'three_images_aligned_v1':
        if report.get('delivery_layout') != config['report_layout'] or len(report.get('delivery_photos', [])) != 3:
            raise RuntimeError('Chưa dựng đủ 3 ảnh theo form mới; không gửi form cũ')
        if config.get('report_calculation') and report.get('delivery_calculation') != config['report_calculation']:
            raise RuntimeError('Báo cáo chưa áp dụng quy tắc so sánh hiện tại')
    if scheduled and config.get('omit_accessory_details_scheduled'):
        report = dict(report, tables=[t for t in report['tables'] if not t['stem'].startswith('03_06')])
    # Prepare and validate ALL photos before sending the first album.
    paths = report_photos(report)
    summary = report_summary(report, slot, sample)
    ids = []
    offset = 0
    for size in album_sizes(len(paths)):
        media, files = [], []
        for index, path in enumerate(paths[offset:offset+size], start=offset):
            attachment = 'report' + str(index + 1)
            item = {'type': 'photo', 'media': 'attach://' + attachment}
            if index == len(paths)-1:
                item['caption'] = summary
            media.append(item)
            files.append((attachment, path))
        try:
            sent = telegram(config, 'sendMediaGroup', {'chat_id': config['chat_id'],
                'media': json.dumps(media, ensure_ascii=False)}, files, delivery=True)
            if len(sent) != size or any(message['chat']['id'] != config['chat_id'] or not message.get('photo') for message in sent):
                raise DeliveryUncertain('Telegram trả kết quả gửi ảnh không đầy đủ')
        except Exception:
            if ids:
                raise DeliveryUncertain('Đã gửi một phần ảnh; không tự gửi lại để tránh trùng') from None
            raise
        ids.extend(message['message_id'] for message in sent)
        offset += size
    return ids


def run_now(request_id):
    if not request_id or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', request_id):
        raise RuntimeError('Cần mã chạy thử hợp lệ: --request-id sample-YYYYMMDD-HHMM')
    config = read_config()
    stamp = now_vn()
    key = 'manual:' + stamp.date().isoformat() + ':' + request_id
    with (PRIVATE/'runner.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('BOT đang xử lý báo cáo khác. Chờ báo cáo đó hoàn tất') from None
        with database() as db:
            previous = db.execute('SELECT state FROM jobs WHERE slot=?', (key,)).fetchone()
            if previous:
                raise RuntimeError('Lần chạy thử này đã được ghi nhận (' + previous[0] + '); không gửi lại')
            db.execute('INSERT INTO jobs(slot,state,attempts,started) VALUES (?,?,?,?)',
                (key, 'building', 1, stamp.isoformat()))
            db.commit()
            delivery_started = False
            try:
                print('Lấy dữ liệu ngày ' + stamp.strftime('%d/%m/%Y') + ' và gửi bộ báo cáo vào nhóm Telegram.', flush=True)
                def progress(phase, message):
                    save_json(PRIVATE/'last-manual-run.json', {'state':'building', 'request_id':request_id,
                        'phase':phase, 'message':message, 'started':stamp.isoformat(), 'updated_at':now_vn().isoformat()})
                progress('checking', 'Đang kiểm tra kết nối Telegram.')
                verify_telegram(config)
                progress('fetching', 'Đang lấy số mới từ MWG và dựng 3 ảnh báo cáo.')
                report = build_report(stamp.date(), 'manual-' + request_id, api_export=True)
                if now_vn().date() != stamp.date():
                    raise RuntimeError('Đã qua ngày mới. Chạy lại bằng mã thử mới để lấy đúng ngày')
                db.execute('UPDATE jobs SET state=? WHERE slot=?', ('sending', key)); db.commit()
                progress('sending', 'Đã có số mới. Đang gửi 3 ảnh sang Telegram.')
                delivery_started = True
                actual = parse_time(report['comparison']['slot']) if report.get('comparison',{}).get('slot') else now_vn()
                ids = send_report(config, report, actual, sample=True)
                db.execute('UPDATE jobs SET state=?,result=? WHERE slot=?', ('sent', json.dumps(ids), key)); db.commit()
                save_json(PRIVATE/'last-manual-run.json', {'state': 'sent', 'request_id': request_id,
                    'report_date': stamp.date().isoformat(), 'messages': ids, 'finished': now_vn().isoformat()})
                print('ĐÃ GỬI THỬ ' + str(len(ids)) + ' ẢNH. Lịch tự động giữ nguyên.', flush=True)
                log('manual_sent', request_id=request_id, messages=ids, total=report['grand_total'][:2])
            except Exception as exc:
                uncertain = delivery_started and not isinstance(exc, ApiRejected)
                state = 'unknown' if uncertain else 'failed'
                message = (str(exc) if isinstance(exc, DeliveryUncertain) else
                    'Kết quả gửi chưa xác định; kiểm tra nhóm Telegram trước khi lấy số mới' if uncertain else
                    str(exc) if isinstance(exc, RuntimeError) else 'Không hoàn tất chạy thử: ' + type(exc).__name__)
                db.execute('UPDATE jobs SET state=?,result=? WHERE slot=?', (state, message, key)); db.commit()
                progress_state = json.loads((PRIVATE/'last-manual-run.json').read_text()) if (PRIVATE/'last-manual-run.json').exists() else {}
                save_json(PRIVATE/'last-manual-run.json', {'state': state, 'request_id': request_id, 'message': message,
                    'finished':now_vn().isoformat(),
                    'phase':progress_state.get('phase') if progress_state.get('request_id') == request_id else None})
                raise RuntimeError(message) from None


def alert_once(db, config, message):
    day = now_vn().date().isoformat()
    if db.execute('SELECT day FROM alerts WHERE day=?', (day,)).fetchone():
        return
    db.execute('INSERT INTO alerts(day) VALUES (?)', (day,)); db.commit()
    try:
        telegram(config, 'sendMessage', {'chat_id': config['chat_id'], 'text': 'BOT báo cáo Apple: ' + message + '. Bot chưa gửi báo cáo cho mốc này.'}, delivery=True)
    except (RuntimeError, OSError):
        pass


def maintain_session():
    """Run between report slots too; refresh before the short MWG token expires."""
    path = PRIVATE / 'mwg-auth-status.json'
    previous = json.loads(path.read_text()) if path.exists() else {}
    stamp = now_vn()
    if previous.get('checked_at'):
        elapsed = (stamp - datetime.fromisoformat(previous['checked_at'])).total_seconds()
        if 0 <= elapsed < 60:
            return
    try:
        with session_lock():
            result = refresh_if_due()
    except SessionBusy:
        return
    except LoginRequired:
        result = {'state': 'login_required'}
    except RuntimeError:
        result = {'state': 'refresh_unavailable'}
    save_json(path, dict(result, checked_at=stamp.isoformat()))
    if result['state'] == 'refreshed' or result['state'] != previous.get('state'):
        log('mwg_session', **result)


def enable_commands():
    config = read_config()
    if not config.get('owner_user_id') or not config.get('bot_username'):
        raise RuntimeError('Thiếu tài khoản chủ bot hoặc tên bot trong cấu hình')
    with (PRIVATE/'runner.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('Bot đang xử lý báo cáo. Thử bật lệnh sau khi xong.') from None
        if telegram(config, 'getWebhookInfo').get('url'):
            raise RuntimeError('Bot đang dùng webhook; chưa bật bộ nhận lệnh.')
        verify_telegram(config)
        member = telegram(config, 'getChatMember', {'chat_id': config['chat_id'], 'user_id': config['owner_user_id']})
        if member['status'] not in ['creator', 'administrator', 'member']:
            raise RuntimeError('Tài khoản chủ bot chưa tham gia nhóm')
        scope = {'type': 'chat_member', 'chat_id': config['chat_id'], 'user_id': config['owner_user_id']}
        commands = [{'command': 'layso', 'description': 'Lấy số bán Apple mới nhất theo form 3 ảnh'}]
        telegram(config, 'setMyCommands', {'scope': scope, 'commands': commands})
        if telegram(config, 'getMyCommands', {'scope': scope}) != commands:
            raise RuntimeError('Chưa xác minh được menu lệnh')
        config.setdefault('commands_enabled_at', now_vn().isoformat())
        save_json(CONFIG, config)
        with database() as db:
            poll_commands(config, db)
        print('Đã bật /layso cho chủ bot trong nhóm đã cấu hình.', flush=True)


def poll_commands(config, db):
    """Persist accepted commands and the next offset together, before acknowledging."""
    if not config.get('commands_enabled_at'):
        return
    row = db.execute('SELECT offset FROM telegram_cursor WHERE id=1').fetchone()
    updates = telegram(config, 'getUpdates', {'offset': row[0] if row else 0,
        'timeout': 0, 'limit': 100, 'allowed_updates': ['message']})
    enabled = datetime.fromisoformat(config['commands_enabled_at'])
    for update in updates:
        message = update.get('message', {})
        text = message.get('text', '').strip()
        match = re.fullmatch(r'/layso(?:@([A-Za-z0-9_]+))?', text, re.IGNORECASE)
        addressed = match and (not match[1] or match[1].lower() == config['bot_username'].lower())
        if (addressed and message.get('chat', {}).get('id') == config['chat_id']
                and message.get('from', {}).get('id') == config['owner_user_id']
                and not message.get('from', {}).get('is_bot', False)):
            requested = datetime.fromtimestamp(message.get('date', 0), VN)
            if requested >= enabled:
                db.execute('INSERT OR IGNORE INTO command_requests VALUES (?,?,?,NULL)',
                    (update['update_id'], requested.isoformat(), 'queued'))
        db.execute('INSERT INTO telegram_cursor VALUES (1,?) ON CONFLICT(id) DO UPDATE SET offset=MAX(offset,excluded.offset)',
            (update['update_id'] + 1,))
    db.commit()
    save_json(PRIVATE/'command-listener.json', {'checked_at': now_vn().isoformat(), 'state': 'listening'})


def process_command(config, db):
    """Caller holds runner.lock; a request is never automatically sent twice."""
    # A previous process stopped before delivery; allow a fresh user request instead.
    db.execute("UPDATE command_requests SET state='failed',result='Tác vụ bị gián đoạn' WHERE state='building'")
    row = db.execute("SELECT update_id,requested_at FROM command_requests WHERE state='queued' ORDER BY update_id LIMIT 1").fetchone()
    if not row:
        db.commit()
        return
    request_id, requested_at = row
    stamp = now_vn()
    key = 'telegram-' + str(request_id)
    delivering = False
    try:
        if not 0 <= (stamp-datetime.fromisoformat(requested_at)).total_seconds() <= 1800:
            raise RuntimeError('Yêu cầu đã quá 30 phút. Em gõ /layso lại để lấy số mới nhé.')
        db.execute("UPDATE command_requests SET state='building' WHERE update_id=?", (request_id,)); db.commit()
        report = build_report(stamp.date(), key, api_export=True)
        if now_vn().date() != stamp.date():
            raise RuntimeError('Đã qua ngày mới. Em gõ /layso lại nhé.')
        actual = parse_time(report['comparison']['slot'])
        db.execute("UPDATE command_requests SET state='sending' WHERE update_id=?", (request_id,)); db.commit()
        delivering = True
        ids = send_report(config, report, actual)
        db.execute("UPDATE command_requests SET state='sent',result=? WHERE update_id=?", (json.dumps(ids), request_id)); db.commit()
        log('command_sent', update_id=request_id, messages=ids)
    except Exception as exc:
        uncertain = delivering and not isinstance(exc, ApiRejected)
        state = 'unknown' if uncertain else 'failed'
        message = str(exc) if isinstance(exc, RuntimeError) else 'Chưa xử lý được dữ liệu MWG.'
        db.execute('UPDATE command_requests SET state=?,result=? WHERE update_id=?', (state, message, request_id)); db.commit()
        log('command_failed', update_id=request_id, state=state)
        if not uncertain:
            try:
                telegram(config, 'sendMessage', {'chat_id': config['chat_id'],
                    'text': 'BOT chưa lấy được số: ' + message}, delivery=True)
            except (RuntimeError, OSError):
                pass


def maintain_history(config):
    if not config.get('sales_history_enabled'):
        return
    # Leave time for scheduled reports; commands and regular slots take priority.
    if config.get('scheduled') and (next_slot(now_vn(), config.get('one_off_slots'))-now_vn()).total_seconds()<900:
        return
    from sales_history import update_once
    try:
        result=update_once(ROOT,now_vn())
        if result['state']=='updated':log('sales_history_updated',**result)
    except RuntimeError as exc:
        log('sales_history_unavailable',message=str(exc))


def tick():
    config = read_config()
    listening = config.get('command_listener_enabled') and config.get('commands_enabled_at')
    if not config.get('scheduled') and not listening:
        return
    one_off_slots = config.get('one_off_slots', [])
    slot = due_slot(now_vn(), one_off_slots=one_off_slots) if config.get('scheduled') else None
    with (PRIVATE/'runner.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        if config.get('commands_enabled_at'):
            with database() as command_db:
                try:
                    poll_commands(config, command_db)
                except RuntimeError:
                    log('command_poll_unavailable')
        maintain_session()
        if slot is None:
            if config.get('commands_enabled_at'):
                with database() as command_db:
                    process_command(config, command_db)
            maintain_history(config)
            return
        with database() as db:
            key = slot.isoformat()
            row = db.execute('SELECT state,attempts FROM jobs WHERE slot=?', (key,)).fetchone()
            if row and (row[0] in ['sent', 'sending', 'unknown'] or row[1] >= 3):
                if config.get('commands_enabled_at'):
                    process_command(config, db)
                maintain_history(config)
                return
            attempts = (row[1] if row else 0) + 1
            db.execute('INSERT INTO jobs(slot,state,attempts,started) VALUES (?,?,?,?) ON CONFLICT(slot) DO UPDATE SET state=excluded.state,attempts=excluded.attempts,started=excluded.started',
                (key, 'building', attempts, now_vn().isoformat()))
            db.commit()
            delivery_started = False
            try:
                report_key = slot.strftime('%H%M')+'-try'+str(attempts)
                if slot.isoformat() in one_off_slots:
                    report = build_report(slot.date(), report_key, api_export=True)
                else:
                    report = build_report(slot.date(), report_key)
                if now_vn().date() != slot.date():
                    raise RuntimeError('Đã qua ngày mới, bỏ báo cáo cũ')
                db.execute('UPDATE jobs SET state=? WHERE slot=?', ('sending', key)); db.commit()
                delivery_started = True
                ids = send_report(config, report, slot, scheduled=True)
                db.execute('UPDATE jobs SET state=?,result=? WHERE slot=?', ('sent', json.dumps(ids), key)); db.commit()
                save_json(PRIVATE/'last-run.json', {'state': 'sent', 'slot': key, 'messages': ids, 'finished': now_vn().isoformat()})
                log('sent', slot=key, messages=ids)
            except DeliveryUncertain as exc:
                db.execute('UPDATE jobs SET state=?,result=? WHERE slot=?', ('unknown', str(exc), key)); db.commit()
                save_json(PRIVATE/'last-run.json', {'state': 'unknown', 'slot': key, 'message': str(exc)})
                log('delivery_uncertain', slot=key)
            except Exception as exc:
                # Keep only our bounded messages; exception URLs could contain credentials.
                message = str(exc) if isinstance(exc, RuntimeError) else 'Lỗi xử lý dữ liệu hoặc kết nối'
                if delivery_started and not isinstance(exc, ApiRejected):
                    db.execute('UPDATE jobs SET state=?,result=? WHERE slot=?', ('unknown', message, key)); db.commit()
                    log('delivery_uncertain', slot=key)
                    return
                db.execute('UPDATE jobs SET state=?,result=? WHERE slot=?', ('failed', message, key)); db.commit()
                save_json(PRIVATE/'last-run.json', {'state': 'failed', 'slot': key, 'message': message})
                log('run_failed', slot=key, message=message)
                if attempts >= 3:
                    alert_once(db, config, message)


def launchagent():
    logs = ROOT / 'logs'; logs.mkdir(exist_ok=True)
    return {'Label': LABEL, 'ProgramArguments': [str(RENDER_PYTHON), str(ROOT/'bot/report_bot.py'), 'tick'],
        'WorkingDirectory': str(ROOT), 'RunAtLoad': True, 'StartInterval': 30,
        'StandardOutPath': str(logs/'bot.log'), 'StandardErrorPath': str(logs/'bot-error.log'),
        'ProcessType': 'Background', 'EnvironmentVariables': {'TZ': 'Asia/Ho_Chi_Minh'}}


def manual_only():
    """Disable all timed reports while retaining the existing command listener."""
    with (PRIVATE/'runner.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('BOT đang xử lý tác vụ; thử đổi chế độ sau khi hoàn tất') from None
        config = read_config()
        if not config.get('commands_enabled_at'):
            raise RuntimeError('Cần bật /layso trước khi chuyển sang chỉ lấy số chủ động')
        config.update(scheduled=False, command_listener_enabled=True,
                      delivery_mode='on_demand', schedule_status='manual_only',
                      delivery_mode_updated_at=now_vn().isoformat())
        save_json(CONFIG, config)
    print('Đã tắt gửi báo cáo theo giờ. BOT vẫn nhận /layso trong nhóm đã cấu hình.', flush=True)


def install():
    config = read_config()
    on_demand = config.get('delivery_mode') == 'on_demand'
    config['scheduled'] = False
    config['schedule_status'] = 'preflight'
    save_json(CONFIG, config)
    print('1/4: Đăng nhập MWG trong cửa sổ riêng của BOT. Quét QR bằng MWGWork.', flush=True)
    login = subprocess.run([str(FETCH_PYTHON), str(ROOT/'bot/mwg_fetch.py'), '--login'])
    if login.returncode:
        raise RuntimeError('Chưa đăng nhập được MWG; lịch chưa được bật')
    print('2/4: Kiểm tra xuất dữ liệu ngày gần nhất và dựng đủ 3 bảng (không gửi vào nhóm).', flush=True)
    build_report(now_vn().date()-timedelta(days=1), 'kiem-tra-'+now_vn().strftime('%H%M%S'))
    print('3/4: Kiểm tra đúng bot và nhóm Telegram.', flush=True)
    verify_telegram(config)
    print('4/4: Bật lịch và tự chạy khi đăng nhập Mac.', flush=True)
    folder = Path.home()/'Library/LaunchAgents'
    folder.mkdir(parents=True, exist_ok=True)
    plist = folder/(LABEL+'.plist')
    plist.write_bytes(plistlib.dumps(launchagent()))
    os.chmod(plist, 0o644)
    domain = 'gui/'+str(os.getuid())
    subprocess.run(['/bin/launchctl', 'bootout', domain+'/'+LABEL], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(['/bin/launchctl', 'enable', domain+'/'+LABEL], check=True)
    result = subprocess.run(['/bin/launchctl', 'bootstrap', domain, str(plist)], capture_output=True)
    if result.returncode:
        raise RuntimeError('macOS chưa nhận lịch tự chạy; lịch vẫn tắt')
    result = subprocess.run(['/bin/launchctl', 'print', domain+'/'+LABEL], capture_output=True)
    if result.returncode:
        raise RuntimeError('Không xác minh được tác vụ nền; lịch vẫn tắt')
    config['scheduled'] = not on_demand
    config['schedule_status'] = 'manual_only' if on_demand else 'enabled'
    if on_demand:
        config['command_listener_enabled'] = True
    config['report_tables'] = [4, 1, 2]
    config['report_layout'] = 'three_images_aligned_v1'
    config['period_model_comparison_enabled'] = False
    config['period_overview_enabled'] = False
    config['last_preflight_at'] = now_vn().isoformat()
    save_json(CONFIG, config)
    if on_demand:
        print('ĐÃ BẬT nhận /layso. Chế độ chủ động: không tự gửi báo cáo theo giờ.', flush=True)
    else:
        print('ĐÃ BẬT: 10h, 12h, 14h, 16h, 18h, 20h, 22h — giờ Việt Nam.', flush=True)
        print('Lần kế tiếp: '+next_slot(now_vn()).strftime('%d/%m/%Y %H:%M')+'. Máy cần thức và có mạng.', flush=True)


def main():
    os.umask(0o077)
    PRIVATE.mkdir(mode=0o700, exist_ok=True)
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['tick', 'install', 'status', 'stop', 'login', 'check', 'run-now', 'enable-commands', 'manual-only'])
    parser.add_argument('--request-id')
    args = parser.parse_args()
    if args.action == 'tick':
        tick()
    elif args.action == 'enable-commands':
        enable_commands()
    elif args.action == 'manual-only':
        manual_only()
    elif args.action == 'run-now':
        run_now(args.request_id)
    elif args.action == 'install':
        install()
    elif args.action == 'login':
        return subprocess.call([str(FETCH_PYTHON), str(ROOT/'bot/mwg_fetch.py'), '--login'])
    elif args.action == 'status':
        config = read_config()
        log('status', scheduled=config.get('scheduled', False), stage=config.get('schedule_status'),
            times=TIMES if config.get('scheduled') else [],
            command_listener_enabled=bool(config.get('commands_enabled_at') and
                                          (config.get('scheduled') or config.get('command_listener_enabled'))),
            report_layout=config.get('report_layout', 'legacy'),
            timezone='Asia/Ho_Chi_Minh', next=next_slot(now_vn(), config.get('one_off_slots')).isoformat() if config.get('scheduled') else None,
            one_off_slots=config.get('one_off_slots', []), login_saved=(PRIVATE/'mwg-session.json').exists())
        if (PRIVATE/'last-run.json').exists():
            print((PRIVATE/'last-run.json').read_text())
        if (PRIVATE/'mwg-auth-status.json').exists():
            print((PRIVATE/'mwg-auth-status.json').read_text())
    elif args.action == 'check':
        verify_telegram(read_config())
    elif args.action == 'stop':
        config = read_config(); config['scheduled'] = False; config['command_listener_enabled'] = False
        config['schedule_status'] = 'paused'; save_json(CONFIG, config)
        subprocess.run(['/bin/launchctl', 'bootout', 'gui/'+str(os.getuid())+'/'+LABEL], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(['/bin/launchctl', 'disable', 'gui/'+str(os.getuid())+'/'+LABEL], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print('Đã tắt lịch BOT; giữ nguyên dữ liệu và cấu hình.')
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as exc:
        message = str(exc) if isinstance(exc, RuntimeError) else 'Không hoàn tất thao tác: '+type(exc).__name__
        log('stopped', message=message)
        sys.exit(1)
