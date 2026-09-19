"""CO confirmation and durable queue. Enable only with persistent database storage."""
import hmac
import json
import os
import re
import secrets
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

FIELDS = {'kho xuất': 'source', 'kho nhận': 'destination', 'kho nhập': 'destination',
          'mã sản phẩm': 'product', 'số lượng': 'quantity', 'note': 'note', 'ghi chú': 'note'}

def parse_form(text):
    values = {}
    for line in text.strip().splitlines():
        if not line.strip():
            continue
        label, sep, value = line.partition(':')
        key = FIELDS.get(label.strip().lower())
        if not sep or not key or key in values:
            raise ValueError('Mỗi dòng cần đúng tên trường và dấu :, không lặp trường.')
        values[key] = value.strip()
    for key, label in [('source','Kho xuất'),('destination','Kho nhận'),('product','Mã sản phẩm'),('quantity','Số lượng')]:
        if not re.fullmatch(r'[0-9]{1,30}', values.get(key, '')):
            raise ValueError(f'{label} phải là mã/số chỉ gồm chữ số.')
    if values['source'] == values['destination']:
        raise ValueError('Kho xuất và kho nhận phải khác nhau.')
    values['quantity'] = int(values['quantity'])
    if not 1 <= values['quantity'] <= 100000:
        raise ValueError('Số lượng phải là số nguyên từ 1 đến 100000.')
    values.setdefault('note', '')
    if len(values['note']) > 500:
        raise ValueError('Note tối đa 500 ký tự.')
    return values

class Queue:
    def __init__(self, path):
        self.postgres = path.startswith(('postgresql://', 'postgres://'))
        if not self.postgres:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        with self.db() as db:
            db.executescript('''
              CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY, event TEXT UNIQUE NOT NULL, owner TEXT NOT NULL,
                chat TEXT NOT NULL, payload TEXT NOT NULL, state TEXT NOT NULL,
                created REAL NOT NULL, updated REAL NOT NULL, lease TEXT,
                result TEXT, notified INTEGER NOT NULL DEFAULT 0);
            ''')

    @contextmanager
    def db(self):
        if self.postgres:
            import psycopg
            from psycopg.rows import dict_row
            # Serialize the tiny queue transactions across web workers and Mac pollers.
            # Transaction-scoped locks also work with pooled PostgreSQL connections.
            with psycopg.connect(self.path, row_factory=dict_row, connect_timeout=15,
                                 options='-c statement_timeout=20000 -c lock_timeout=10000') as conn:
                conn.execute('SELECT pg_advisory_xact_lock(64526094531061)')
                yield PostgresStatements(conn)
            return
        db = sqlite3.connect(self.path, timeout=20)
        db.row_factory = sqlite3.Row
        try:
            db.execute('BEGIN IMMEDIATE')
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def draft(self, event, owner, chat, payload):
        now = time.time()
        with self.db() as db:
            old = db.execute('SELECT * FROM jobs WHERE event=?', (event,)).fetchone()
            if old:
                return dict(old)
            # Keep each preview pending so the owner can confirm several forms together.
            jid = secrets.token_hex(5)
            db.execute('INSERT INTO jobs(id,event,owner,chat,payload,state,created,updated) VALUES(?,?,?,?,?,?,?,?)',
                       (jid,event,owner,chat,json.dumps(payload,ensure_ascii=False),'draft',now,now))
            return dict(db.execute('SELECT * FROM jobs WHERE id=?',(jid,)).fetchone())

    def confirm(self, jid, owner, chat, cancel=False):
        with self.db() as db:
            job = db.execute('SELECT * FROM jobs WHERE id=? AND owner=? AND chat=?',(jid,owner,chat)).fetchone()
            if not job:
                return 'Không tìm thấy yêu cầu của bạn trong cuộc chat này.'
            if job['state'] != 'draft':
                return 'Yêu cầu đã được xử lý hoặc hủy; không tạo thêm bản trùng.'
            if time.time() - job['created'] > 900:
                db.execute("UPDATE jobs SET state='expired' WHERE id=?",(jid,))
                return 'Xác nhận đã hết hạn. Vui lòng gửi lại form.'
            state = 'cancelled' if cancel else 'queued'
            db.execute('UPDATE jobs SET state=?,updated=? WHERE id=?',(state,time.time(),jid))
            return 'Đã hủy. Bạn có thể gửi form đã sửa.' if cancel else f'Đã xác nhận yêu cầu {jid}. Đang chờ máy Mac xử lý.'

    def confirm_all(self, owner, chat, cancel=False):
        now = time.time()
        with self.db() as db:
            db.execute("UPDATE jobs SET state='expired',updated=? WHERE owner=? AND chat=? AND state='draft' AND created<?",
                       (now,owner,chat,now-900))
            jobs = db.execute("SELECT id FROM jobs WHERE owner=? AND chat=? AND state='draft' ORDER BY created,id",
                              (owner,chat)).fetchall()
            if not jobs:
                return 'Không có yêu cầu còn hiệu lực đang chờ xác nhận của bạn trong cuộc chat này.'
            state = 'cancelled' if cancel else 'queued'
            db.execute("UPDATE jobs SET state=?,updated=? WHERE owner=? AND chat=? AND state='draft'",
                       (state,now,owner,chat))
            action = 'Đã hủy' if cancel else 'Đã xác nhận'
            message = f'{action} {len(jobs)} yêu cầu đang chờ của bạn trong cuộc chat này.'
            if not cancel:
                message += ' Máy Mac sẽ xử lý lần lượt và trả kết quả từng yêu cầu.'
            return message

    def claim(self):
        with self.db() as db:
            # Never automatically replay an interrupted browser operation.
            cutoff = time.time() - 900
            db.execute("UPDATE jobs SET state='unknown',result=?,updated=? WHERE state IN ('running','submitting') AND updated<?",
                       ('Máy Mac gián đoạn. Cần kiểm tra MWG trước khi gửi lại để tránh tạo trùng.',time.time(),cutoff))
            if db.execute("SELECT 1 FROM jobs WHERE state IN ('running','submitting','unknown')").fetchone():
                return None
            job = db.execute("SELECT * FROM jobs WHERE state='queued' ORDER BY created LIMIT 1").fetchone()
            if not job:
                return None
            lease = secrets.token_urlsafe(24)
            db.execute("UPDATE jobs SET state='running',lease=?,updated=? WHERE id=?",(lease,time.time(),job['id']))
            return {'id':job['id'],'lease':lease,'payload':json.loads(job['payload'])}

    def update(self, jid, lease, state, result=''):
        with self.db() as db:
            job = db.execute('SELECT * FROM jobs WHERE id=? AND lease=?',(jid,lease)).fetchone()
            if not job:
                return False
            if job['state'] == state and (job['result'] or '') == result:
                return True
            allowed = {'running': {'submitting','failed','unknown'}, 'submitting': {'succeeded','failed','unknown'}}
            if state not in allowed.get(job['state'], set()):
                return False
            db.execute('UPDATE jobs SET state=?,result=?,updated=? WHERE id=?',(state,result,time.time(),jid))
            return True

    def notifications(self):
        with self.db() as db:
            return [dict(x) for x in db.execute("SELECT * FROM jobs WHERE state IN ('succeeded','failed','unknown') AND notified=0")]

    def mark_notified(self, jid):
        with self.db() as db:
            db.execute('UPDATE jobs SET notified=1 WHERE id=?',(jid,))

class PostgresStatements:
    """Adapt this module's fixed SQL statements; never interpolate user data."""
    def __init__(self, connection):
        self.connection = connection

    def execute(self, statement, params=()):
        statement = re.sub(r'\bjobs\b', 'co_jobs', statement)
        statement = re.sub(r'\bREAL\b', 'DOUBLE PRECISION', statement)
        return self.connection.execute(statement.replace('?', '%s'), params)

    def executescript(self, statement):
        return self.execute(statement)

def install(app, reply, push, default_users=()):
    from flask import request, jsonify, abort
    enabled = os.getenv('CO_ENABLED') == '1'
    queue = None
    if enabled:
        path = os.environ.get('CO_DATABASE_URL') or os.environ.get('CO_DB_PATH', '')
        token = os.environ['CO_WORKER_TOKEN']
        if len(token) < 32 or not (path.startswith(('postgresql://','postgres://')) or Path(path).is_absolute()):
            raise RuntimeError('CO cần DB bền vững và worker token ít nhất 32 ký tự.')
        queue = Queue(path)
    users = set(filter(None,(x.strip() for x in os.getenv('CO_ALLOWED_USER_IDS','').split(',')))) or set(default_users)

    def authenticated():
        if not queue:
            abort(503)
        supplied = request.headers.get('Authorization','')
        if not hmac.compare_digest(supplied, 'Bearer '+os.environ['CO_WORKER_TOKEN']):
            abort(401)

    @app.post('/co/worker/claim')
    def claim():
        authenticated()
        return jsonify(queue.claim())

    @app.get('/co/worker/status')
    def worker_status():
        authenticated()
        with queue.db() as db:
            counts={row['state']:row['n'] for row in db.execute('SELECT state,COUNT(*) AS n FROM jobs GROUP BY state')}
        return jsonify(enabled=True, states=counts, allowed_users=len(users))

    @app.post('/co/worker/result')
    def result():
        authenticated()
        data = request.get_json(silent=True) or {}
        if not isinstance(data,dict) or not isinstance(data.get('id'),str) or not isinstance(data.get('lease'),str):
            abort(400)
        state = data.get('state')
        message = data.get('result','')
        if state not in {'submitting','succeeded','failed','unknown'} or not isinstance(message,str) or len(message)>3000:
            abort(400)
        if state == 'succeeded' and not re.fullmatch(r'[0-9A-Z]+CO[0-9]+', message):
            abort(400)
        if not queue.update(data.get('id'),data.get('lease'),state,message):
            abort(409)
        return jsonify(ok=True)

    def notify():
        if not queue:
            return
        for job in queue.notifications():
            labels={'succeeded':'Tạo CO thành công', 'failed':'Không tạo được CO. Sửa thông tin và gửi lại form',
                    'unknown':'Chưa xác định được kết quả. Cần kiểm tra MWG trước khi tạo lại'}
            text=f"{labels[job['state']]}\nYêu cầu: {job['id']}\n{job['result']}"
            # Stable key permits LINE retry without duplicate pushes.
            import uuid
            retry_key=str(uuid.uuid5(uuid.NAMESPACE_URL,'co-result:'+job['id']))
            try:
                if push(job['chat'],text,retry_key):
                    queue.mark_notified(job['id'])
            except Exception:
                app.logger.warning('CO notification pending; will retry.')

    def handle(event):
        text=event.message.text.strip()
        is_form=any(line.partition(':')[0].strip().lower() in FIELDS for line in text.splitlines())
        is_command=text.upper().startswith(('XACNHAN ','HUY ','SUA '))
        if not (is_form or is_command):
            return False
        owner=getattr(event.source,'user_id',None)
        chat=getattr(event.source,'group_id',None) or getattr(event.source,'room_id',None) or owner
        if not enabled:
            reply(event.reply_token,'Chức năng tạo CO chưa được cấu hình.'); return True
        if not owner or owner not in users:
            reply(event.reply_token,'Tài khoản chưa được cấp quyền tạo CO.'); return True
        try:
            if is_form:
                payload=parse_form(text)
                event_id=getattr(event,'webhook_event_id',None)
                if not event_id:
                    event_id='message:'+event.message.id
                job=queue.draft(event_id,owner,chat,payload)
                if job['state']!='draft':
                    reply(event.reply_token,'Yêu cầu này đã được ghi nhận. Không tạo thêm bản trùng.')
                    return True
                p=json.loads(job['payload']); jid=job['id']
                preview=(f"Xác nhận tạo CO — {jid}\nKho xuất: {p['source']}\nKho nhận: {p['destination']}\n"
                         f"Mã sản phẩm: {p['product']}\nSố lượng: {p['quantity']}\nNote: {p['note']}\n"
                         f"Thương hiệu: TGDD, DMX, TopZone\n\nGửi XACNHAN {jid} để tạo.\n"
                         f"Gửi SUA {jid} để hủy bản này và gửi form sửa; HUY {jid} để hủy.\n"
                         "XACNHAN ALL / HUY ALL: xác nhận / hủy tất cả yêu cầu đang chờ của bạn trong chat này.\nHiệu lực: 15 phút.")
                reply(event.reply_token,preview)
            else:
                command,jid=text.split(maxsplit=1)
                if jid.strip().upper() == 'ALL' and command.upper() in {'XACNHAN','HUY'}:
                    reply(event.reply_token,queue.confirm_all(owner,chat,command.upper()=='HUY'))
                else:
                    reply(event.reply_token,queue.confirm(jid.strip(),owner,chat,command.upper()!='XACNHAN'))
        except ValueError as error:
            reply(event.reply_token,f'Form chưa hợp lệ: {error}\nVui lòng sửa và gửi lại.')
        return True
    return handle, notify
