"""Owner cancellation audit; never store tokens, cookies, raw UA or typed input."""
import hashlib
import hmac
import secrets
import time

RETENTION_SECONDS = 30 * 86400
LABELS = {
    'review_opened': 'Mở màn hình hủy',
    'review_closed': 'Quay lại, chưa gửi hủy',
    'review_checked': 'Đánh dấu đã kiểm tra MWG',
    'review_unchecked': 'Bỏ đánh dấu đã kiểm tra MWG',
    'cancel_requested': 'Gửi yêu cầu hủy',
    'cancel_rejected': 'Từ chối hủy',
    'cancelled': 'Đã hủy sau khi đối chiếu mã',
}
REASONS = {
    'code_mismatch': 'Mã nhập không khớp mã yêu cầu',
    'not_attested': 'Chưa xác nhận đã kiểm tra MWG',
    'invalid_revision': 'Thiếu thông tin đối chiếu',
    'stale_revision': 'Dữ liệu yêu cầu đã thay đổi',
    'not_cancellable': 'Trạng thái hoặc kết quả không cho phép hủy',
    'co_evidence': 'Đã có dấu vết kết quả CO',
    'not_found': 'Không tìm thấy yêu cầu',
}


def schema(db):
    db.executescript('''
      CREATE TABLE IF NOT EXISTS tao_owner_actions (
        event_id TEXT PRIMARY KEY, job_id TEXT NOT NULL, actor TEXT NOT NULL,
        at REAL NOT NULL, action TEXT NOT NULL, reason TEXT NOT NULL,
        channel TEXT NOT NULL, client TEXT NOT NULL, session_tag TEXT NOT NULL);
      CREATE INDEX IF NOT EXISTS tao_owner_action_job ON tao_owner_actions(job_id,at);
      CREATE INDEX IF NOT EXISTS tao_owner_action_time ON tao_owner_actions(at);
    ''')


def context(user, user_agent, secret):
    # Client label is a reported signal, not proof of a physical device/person.
    ua = str(user_agent or '')[:1000].lower()
    device = ('iPhone' if 'iphone' in ua else 'iPad' if 'ipad' in ua else
              'Android' if 'android' in ua else 'Mac' if 'macintosh' in ua else
              'Windows' if 'windows' in ua else 'Thiết bị chưa rõ')
    app = 'LINE/LIFF' if 'liff' in ua or 'line/' in ua else 'Trình duyệt'
    tag = hmac.new(secret.encode(), ('tao-audit-v1:' + user['uid'] + ':' +
                   user.get('csrf', '')).encode(), hashlib.sha256).hexdigest()[:16]
    return dict(actor=user['uid'], channel='liff', client=app+' · '+device, session_tag=tag)


def cleanup(db, cutoff):
    db.execute('DELETE FROM tao_owner_actions WHERE at<?', (cutoff,))


def record(db, jid, action, context, reason='', now=None):
    if action not in LABELS or (reason and reason not in REASONS):
        raise ValueError('Unknown audit event')
    now = time.time() if now is None else now
    event_id = secrets.token_hex(16)
    # Critical cancellation and its audit use the same transaction: fail closed.
    db.execute('INSERT INTO tao_owner_actions(event_id,job_id,actor,at,action,reason,channel,client,session_tag) VALUES(?,?,?,?,?,?,?,?,?)',
               (event_id,jid,context['actor'],now,action,reason,context['channel'],context['client'],context['session_tag']))
    cleanup(db, now-RETENTION_SECONDS)
    return event_id


def read(db, jid):
    rows = db.execute('SELECT at,action,reason,client,session_tag FROM tao_owner_actions WHERE job_id=? AND at>=? ORDER BY at DESC LIMIT 30',
                      (jid,time.time()-RETENTION_SECONDS)).fetchall()
    return [dict(at=r['at'],action=r['action'],label=LABELS.get(r['action'],'Thao tác hủy'),
                 reason=REASONS.get(r['reason'],''),client=r['client'],session=r['session_tag']) for r in rows]
