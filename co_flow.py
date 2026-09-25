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

from transfer_parser import parse_form, parse_request, is_transfer_message
from co_results import items, preview_names, decode_results, result_text

class BotUnavailable(ValueError):
    pass

ADMIN_CO_COMMANDS={'BOT ON','BOT OFF','BOT STATUS','HUY CHO ALL','HUY CHỜ ALL','LISTADM'}

def admin_command(text):
    command=' '.join(text.strip().lstrip('!').upper().split())
    return command if command in ADMIN_CO_COMMANDS else None

def preview_text(job):
    p=json.loads(job['payload']);jid=job['id']
    blocks=[f"Xác nhận tạo CO — {jid}"]
    for n,item in enumerate(items(p),1):
        blocks.append(f"{n}. Kho xuất: {item['source']} → Kho nhận: {item['destination']}\n"
                      f"Tên sản phẩm MWG: {item.get('product_name','Chưa kiểm tra')}\n"
                      f"Số lượng: {item['quantity']}{' (mặc định)' if item.get('quantity_defaulted') else ''}\n"
                      f"Note: {item['note']}\nTrạng thái: {item.get('status','Mới')}")
    blocks.append(f"Thương hiệu: TGDD, DMX, TopZone\nGửi XACNHAN {jid} để tạo; HUY {jid} để hủy.\n"
                  "XACNHAN ALL / HUY ALL: áp dụng các bản đang chờ xác nhận. HUY CHO: hủy yêu cầu Mac chưa nhận.\nHiệu lực: 15 phút.")
    return '\n\n'.join(blocks)

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
              CREATE TABLE IF NOT EXISTS preview_replies (
                job_id TEXT PRIMARY KEY, token TEXT NOT NULL, received REAL NOT NULL);
              CREATE TABLE IF NOT EXISTS co_control (
                id INTEGER PRIMARY KEY, enabled INTEGER NOT NULL, heartbeat REAL NOT NULL);
              INSERT INTO co_control(id,enabled,heartbeat) VALUES(1,1,0) ON CONFLICT(id) DO NOTHING;
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

    def unavailable(self, db):
        row=db.execute('SELECT enabled,heartbeat FROM co_control WHERE id=1').fetchone()
        if not row['enabled']:
            return 'Bot CO đang tạm nghỉ theo lệnh ADM. Yêu cầu mới chưa được lưu; vui lòng gửi lại sau.'
        if time.time()-row['heartbeat']>30:
            return 'Bot trên Mac đang offline hoặc mất kết nối. Chưa nhận yêu cầu CO; vui lòng gửi lại khi Mac hoạt động.'
        return ''

    def heartbeat(self, online=True):
        with self.db() as db:
            db.execute('UPDATE co_control SET heartbeat=? WHERE id=1',(time.time() if online else 0,))

    def admin(self, command):
        with self.db() as db:
            if command=='BOT OFF':
                db.execute('UPDATE co_control SET enabled=0 WHERE id=1')
                return 'Đã tắt nhận CO mới và tạm dừng lấy việc từ hàng chờ. Việc đang xử lý vẫn hoàn tất; yêu cầu cũ được giữ lại. !bot on để mở lại.'
            if command=='BOT ON':
                row=db.execute('SELECT heartbeat FROM co_control WHERE id=1').fetchone()
                if time.time()-row['heartbeat']>30:
                    return 'Chưa bật được: Mac đang offline. Mở bot trên Mac, đăng nhập MWG và nhấn Enter, sau đó gửi !bot on.'
                db.execute('UPDATE co_control SET enabled=1 WHERE id=1')
                return 'Đã bật nhận CO. Mac đang kết nối.'
            if command in {'HUY CHO ALL','HUY CHỜ ALL'}:
                states="('draft','queued','verified_queued','preview_queued')"
                rows=db.execute('SELECT id FROM jobs WHERE state IN '+states).fetchall()
                db.execute("UPDATE jobs SET state='cancelled',updated=?,notified=1,result='ADM cancelled waiting requests' WHERE state IN "+states,(time.time(),))
                for row in rows:
                    db.execute('DELETE FROM preview_replies WHERE job_id=?',(row['id'],))
                return f'Đã hủy {len(rows)} yêu cầu chờ của tất cả người dùng, trong mọi chat. Yêu cầu đang xử lý, chưa rõ kết quả và CO đã tạo được giữ nguyên.'
            row=db.execute('SELECT enabled,heartbeat FROM co_control WHERE id=1').fetchone()
            counts={r['state']:r['n'] for r in db.execute('SELECT state,COUNT(*) AS n FROM jobs GROUP BY state')}
            online=time.time()-row['heartbeat']<=30
            waiting=sum(counts.get(k,0) for k in ('draft','queued','verified_queued','preview_queued'))
            active=sum(counts.get(k,0) for k in ('preview_running','running','submitting'))
            return (f"Mac: {'online' if online else 'offline'}\nNhận CO: {'BẬT' if row['enabled'] and online else 'TẮT'}\n"
                    f"ADM tạm dừng: {'không' if row['enabled'] else 'có'}\nĐang chờ: {waiting}\nĐang xử lý: {active}\nChưa rõ kết quả: {counts.get('unknown',0)}")

    def draft(self, event, owner, chat, payload, check_product=False, reply_token=None, require_online=False):
        now = time.time()
        with self.db() as db:
            old = db.execute('SELECT * FROM jobs WHERE event=?', (event,)).fetchone()
            if old:
                return dict(old)
            if require_online:
                reason=self.unavailable(db)
                if reason:raise BotUnavailable(reason)
            # Keep each preview pending so the owner can confirm several forms together.
            jid = secrets.token_hex(5)
            db.execute('INSERT INTO jobs(id,event,owner,chat,payload,state,created,updated) VALUES(?,?,?,?,?,?,?,?)',
                       (jid,event,owner,chat,json.dumps(payload,ensure_ascii=False),'preview_queued' if check_product else 'draft',now,now))
            if check_product and reply_token:
                db.execute('INSERT INTO preview_replies(job_id,token,received) VALUES(?,?,?)',(jid,reply_token,now))
            return dict(db.execute('SELECT * FROM jobs WHERE id=?',(jid,)).fetchone())

    def take_preview_reply(self, jid):
        # Consume once, across scheduler runs/processes; never expose tokens to Mac.
        with self.db() as db:
            row=db.execute('SELECT token,received FROM preview_replies WHERE job_id=?',(jid,)).fetchone()
            db.execute('DELETE FROM preview_replies WHERE job_id=?',(jid,))
            return dict(row) if row else None

    def overdue_preview_replies(self):
        with self.db() as db:
            return [dict(row) for row in db.execute(
                "SELECT j.id,j.state FROM jobs j JOIN preview_replies p ON p.job_id=j.id WHERE p.received<?",
                (time.time()-45,))]

    def confirm(self, jid, owner, chat, cancel=False, reply_token=None, require_online=False):
        with self.db() as db:
            if require_online and not cancel:
                reason=self.unavailable(db)
                if reason:raise BotUnavailable(reason)
            job = db.execute('SELECT * FROM jobs WHERE id=? AND owner=? AND chat=?',(jid,owner,chat)).fetchone()
            if not job:
                return 'Không tìm thấy yêu cầu của bạn trong cuộc chat này.'
            if cancel and job['state'] in {'queued','preview_queued','verified_queued'}:
                db.execute("UPDATE jobs SET state='cancelled',updated=? WHERE id=?",(time.time(),jid))
                return f'Đã hủy yêu cầu chờ {jid}; Mac sẽ không tạo yêu cầu này.'
            if cancel and job['state'] in {'running','submitting','unknown'}:
                return 'Không thể hủy: yêu cầu đang được xử lý hoặc chưa rõ kết quả. Cần kiểm tra MWG để tránh tạo trùng.'
            if job['state'] in {'preview_queued','preview_running'}:
                return 'Mac đang kiểm tra tên sản phẩm trên MWG. Chưa tạo CO; chờ bản xác nhận có tên sản phẩm.'
            if job['state'] != 'draft':
                return 'Yêu cầu đã được xử lý hoặc hủy; không tạo thêm bản trùng.'
            if time.time() - job['created'] > 900:
                db.execute("UPDATE jobs SET state='expired' WHERE id=?",(jid,))
                return 'Xác nhận đã hết hạn. Vui lòng gửi lại form.'
            state = 'cancelled' if cancel else ('verified_queued' if json.loads(job['payload']).get('product_name') else 'queued')
            db.execute('UPDATE jobs SET state=?,updated=? WHERE id=?',(state,time.time(),jid))
            if not cancel and reply_token:
                db.execute('DELETE FROM preview_replies WHERE job_id=?',(jid,))
                db.execute('INSERT INTO preview_replies(job_id,token,received) VALUES(?,?,?)',(jid,reply_token,time.time()))
                return None
            return 'Đã hủy. Bạn có thể gửi form đã sửa.' if cancel else f'Đã xác nhận yêu cầu {jid}. Đang chờ máy Mac xử lý.' + self.blocked_notice(db)

    def confirm_all(self, owner, chat, cancel=False, reply_token=None, require_online=False):
        now = time.time()
        with self.db() as db:
            if require_online and not cancel:
                reason=self.unavailable(db)
                if reason:raise BotUnavailable(reason)
            db.execute("UPDATE jobs SET state='expired',updated=? WHERE owner=? AND chat=? AND state='draft' AND created<?",
                       (now,owner,chat,now-900))
            jobs = db.execute("SELECT id,payload FROM jobs WHERE owner=? AND chat=? AND state='draft' ORDER BY created,id",
                              (owner,chat)).fetchall()
            if not jobs:
                return 'Không có yêu cầu còn hiệu lực đang chờ xác nhận của bạn trong cuộc chat này.'
            state = 'cancelled' if cancel else 'queued'
            for job in jobs:
                target='cancelled' if cancel else ('verified_queued' if json.loads(job['payload']).get('product_name') else 'queued')
                db.execute("UPDATE jobs SET state=?,updated=? WHERE id=? AND state='draft'",(target,now,job['id']))
            if not cancel and reply_token and len(jobs)==1:
                jid=jobs[0]['id']
                db.execute('DELETE FROM preview_replies WHERE job_id=?',(jid,))
                db.execute('INSERT INTO preview_replies(job_id,token,received) VALUES(?,?,?)',(jid,reply_token,now))
                return None
            action = 'Đã hủy' if cancel else 'Đã xác nhận'
            message = f'{action} {len(jobs)} yêu cầu đang chờ của bạn trong cuộc chat này.'
            if not cancel:
                message += ' Máy Mac sẽ xử lý lần lượt và trả kết quả từng yêu cầu.' + self.blocked_notice(db)
            return message

    def blocked_notice(self, db):
        if db.execute("SELECT 1 FROM jobs WHERE state='unknown'").fetchone():
            return ('\nHàng đợi hiện bị tạm dừng vì có yêu cầu chưa rõ kết quả trên MWG. '
                    'Cần đối soát trước khi chạy tiếp. Gửi HUY CHO nếu muốn hủy các yêu cầu chưa được Mac nhận.')
        return ''

    def cancel_waiting(self, owner, chat):
        with self.db() as db:
            count = db.execute("SELECT COUNT(*) AS n FROM jobs WHERE owner=? AND chat=? AND state IN ('queued','preview_queued','verified_queued')",
                               (owner,chat)).fetchone()['n']
            db.execute("UPDATE jobs SET state='cancelled',updated=? WHERE owner=? AND chat=? AND state IN ('queued','preview_queued','verified_queued')",
                       (time.time(),owner,chat))
            message = (f'Đã hủy {count} yêu cầu đã xác nhận nhưng chưa được Mac nhận trong cuộc chat này.'
                       if count else 'Không có yêu cầu đã xác nhận đang chờ Mac của bạn trong cuộc chat này.')
            message += '\nYêu cầu đang xử lý, chưa rõ kết quả và CO đã tạo không bị hủy.'
            return message + self.blocked_notice(db)

    def claim(self, preview_protocol=False, prepared_id=None, batch_protocol=False, require_online=False):
        with self.db() as db:
            if require_online and self.unavailable(db):
                return None
            db.execute("UPDATE jobs SET state='expired',updated=? WHERE state IN ('draft','queued','preview_queued','verified_queued') AND created<?",(time.time(),time.time()-900))
            # Never automatically replay an interrupted browser operation.
            cutoff = time.time() - 900
            db.execute("UPDATE jobs SET state='failed',result=?,updated=? WHERE state='preview_running' AND updated<?",
                       ('Mac gián đoạn khi kiểm tra sản phẩm; chưa tạo CO.',time.time(),cutoff))
            db.execute("UPDATE jobs SET state='unknown',result=?,updated=? WHERE state IN ('running','submitting') AND updated<?",
                       ('Máy Mac gián đoạn. Cần kiểm tra MWG trước khi gửi lại để tránh tạo trùng.',time.time(),cutoff))
            if db.execute("SELECT 1 FROM jobs WHERE state IN ('running','submitting','unknown','preview_running')").fetchone():
                return None
            eligible="('queued','preview_queued','verified_queued')" if preview_protocol else "('queued')"
            if prepared_id:
                prepared=db.execute('SELECT * FROM jobs WHERE id=?',(prepared_id,)).fetchone()
                if prepared and prepared['state']=='draft' and prepared['created']>=cutoff:
                    return None  # Keep the imported MWG row until its owner confirms/cancels.
                if prepared and prepared['state']=='draft':
                    db.execute("UPDATE jobs SET state='expired',updated=? WHERE id=?",(time.time(),prepared_id))
                if not prepared or prepared['state'] not in {'verified_queued','queued'}:
                    return {'release_preview':True}
                job=prepared
            else:
                job = db.execute("SELECT * FROM jobs WHERE state IN "+eligible+" ORDER BY created LIMIT 1").fetchone()
            if not job:
                return None
            if 'items' in json.loads(job['payload']) and not batch_protocol:
                return None
            lease = secrets.token_urlsafe(24)
            preview=job['state']=='preview_queued'
            db.execute("UPDATE jobs SET state=?,lease=?,updated=? WHERE id=?",('preview_running' if preview else 'running',lease,time.time(),job['id']))
            return {'id':job['id'],'lease':lease,'payload':json.loads(job['payload']),'mode':'preview' if preview else 'create'}

    def update(self, jid, lease, state, result=''):
        with self.db() as db:
            job = db.execute('SELECT * FROM jobs WHERE id=? AND lease=?',(jid,lease)).fetchone()
            if not job:
                return False
            if job['state'] == state and (job['result'] or '') == result:
                return True
            if state=='preview_ready' and job['state'] in {'draft','preview_running'}:
                payload=json.loads(job['payload'])
                try:
                    names=preview_names(payload,result)
                except (ValueError,TypeError):
                    return False
                if job['state']=='draft':
                    return job['result']=='MWG_PREVIEW' and [item.get('product_name') for item in items(payload)]==names
                for item,name in zip(items(payload),names):
                    item['product_name']=name
                if 'items' in payload:
                    payload['product_name']='MWG_BATCH_READY'
                now=time.time()
                db.execute("UPDATE jobs SET state='draft',payload=?,result='MWG_PREVIEW',created=?,updated=?,notified=0 WHERE id=?",
                           (json.dumps(payload,ensure_ascii=False),now,now,jid))
                return True
            if state in {'succeeded','failed','unknown'} and result.startswith('['):
                try:
                    rows=decode_results(json.loads(job['payload']),result)
                    if state=='succeeded' and (not all(row['co'] or row['error'] for row in rows) or not any(row['co'] for row in rows)):
                        return False
                    if state=='failed' and any(row['co'] for row in rows):
                        return False
                except (ValueError,TypeError):
                    return False
            allowed = {'preview_running':{'failed'},'running': {'submitting','failed','unknown'}, 'submitting': {'succeeded','failed','unknown'}}
            if state not in allowed.get(job['state'], set()):
                return False
            db.execute('UPDATE jobs SET state=?,result=?,updated=?,notified=0 WHERE id=?',(state,result,time.time(),jid))
            return True

    def notifications(self):
        with self.db() as db:
            return [dict(x) for x in db.execute("SELECT * FROM jobs WHERE (state IN ('succeeded','failed','unknown') OR (state='draft' AND result='MWG_PREVIEW')) AND notified=0")]

    def mark_notified(self, jid, state=None):
        with self.db() as db:
            db.execute('UPDATE jobs SET notified=1 WHERE id=? AND state=?',(jid,state)) if state else db.execute('UPDATE jobs SET notified=1 WHERE id=?',(jid,))

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
        body=request.get_json(silent=True) or {}
        prepared=body.get('prepared_id')
        if prepared is not None and (not isinstance(prepared,str) or not re.fullmatch(r'[0-9a-f]{10}',prepared)):
            abort(400)
        return jsonify(queue.claim(body.get('preview_protocol')==1,prepared,body.get('batch_protocol')==1,require_online=True))

    @app.post('/co/worker/heartbeat')
    def heartbeat():
        authenticated()
        body=request.get_json(silent=True) or {}
        queue.heartbeat(body.get('online') is True)
        return jsonify(ok=True)

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
        if state not in {'submitting','succeeded','failed','unknown','preview_ready'} or not isinstance(message,str) or len(message)>10000:
            abort(400)
        if state == 'succeeded' and not message.startswith('[') and not re.fullmatch(r'[0-9A-Z]+CO[0-9]+', message):
            abort(400)
        if not queue.update(data.get('id'),data.get('lease'),state,message):
            abort(409)
        return jsonify(ok=True)

    next_notice={}

    def notify():
        if not queue:
            return
        fallback=[]
        labels={'succeeded':'Tạo CO thành công', 'failed':'Không tạo được CO. Sửa thông tin và gửi lại form',
                'unknown':'Chưa xác định được kết quả. Cần kiểm tra MWG trước khi tạo lại'}
        # Deliver fresh replies before retrying old pushes (which may be quota-blocked).
        for job in queue.notifications():
            text=(preview_text(job) if job['state']=='draft' else result_text(job))
            pending=queue.take_preview_reply(job['id'])
            replied=False
            if pending and time.time()-pending['received']<55:
                try:
                    replied=reply(pending['token'],text) is True
                except Exception:
                    app.logger.warning('CO preview reply failed.')
            if replied:
                queue.mark_notified(job['id'],job['state'])
            else:
                fallback.append((job,text))
        # Do not silently hold an expiring LINE reply while MWG/Mac is slow.
        for waiting in queue.overdue_preview_replies():
            pending=queue.take_preview_reply(waiting['id'])
            if pending and time.time()-pending['received']<55:
                creating=waiting['state'] in {'running','submitting','unknown'}
                detail=('Chưa xác định được kết quả tạo CO; không gửi tạo lại trước khi kiểm tra MWG.' if creating else 'Chưa tạo CO.')
                reply(pending['token'],f"MWG chưa trả kết quả xử lý yêu cầu {waiting['id']}. {detail} Bot sẽ tự gửi kết quả khi có phản hồi.")
        # At most one push per tick so old failed deliveries cannot block new replies.
        fallback.sort(key=lambda item:(item[0]['state']!='draft',-item[0]['updated']))
        for job,text in fallback:
            key=(job['id'],job['state'])
            if time.monotonic()<next_notice.get(key,0):
                continue
            next_notice[key]=time.monotonic()+60
            import uuid
            retry_key=str(uuid.uuid5(uuid.NAMESPACE_URL,'co-result:'+job['id']+(':preview' if job['state']=='draft' else '')))
            try:
                if push(job['chat'],text,retry_key):
                    queue.mark_notified(job['id'],job['state'])
                    next_notice.pop(key,None)
            except Exception:
                app.logger.warning('CO notification pending; will retry.')
            break

    def handle(event):
        text=event.message.text.strip()
        adm=admin_command(text)
        is_form=is_transfer_message(text)
        is_command=text.upper().startswith(('XACNHAN ','HUY ','SUA ','XEM '))
        if not (adm or is_form or is_command):
            return False
        owner=getattr(event.source,'user_id',None)
        chat=getattr(event.source,'group_id',None) or getattr(event.source,'room_id',None) or owner
        if adm:
            if not owner or owner not in set(default_users):
                reply(event.reply_token,'Lệnh này chỉ dành cho tài khoản ADM đã được cấp quyền.'); return True
            if adm=='LISTADM':
                reply(event.reply_token, 'Lệnh ADM (chỉ ADM dùng được):\n!bot off — tắt nhận CO và tạm dừng hàng chờ\n!bot on — bật khi Mac online\n!bot status — trạng thái Mac và hàng chờ\n!huy cho all — hủy toàn bộ yêu cầu chưa xử lý của mọi người, mọi chat\n!listadm — xem hướng dẫn này\n!say <mã nhóm> | <nội dung> — gửi tin tới nhóm\n!list — danh sách từ khóa\n!reload — tải lại dữ liệu\n!test / !testreport / !sendall — lệnh báo cáo hiện có\nBOT OFF không hủy CO đã tạo và không dừng thao tác đang chạy.')
                return True
            if not enabled:
                reply(event.reply_token,'Chức năng CO chưa được cấu hình.'); return True
            reply(event.reply_token,queue.admin(adm)); return True
        if not enabled:
            reply(event.reply_token,'Chức năng tạo CO chưa được cấu hình.'); return True
        if not owner or owner not in users:
            reply(event.reply_token,'Tài khoản chưa được cấp quyền tạo CO.'); return True
        try:
            if is_form:
                payload=parse_request(text)
                event_id=getattr(event,'webhook_event_id',None)
                if not event_id:
                    event_id='message:'+event.message.id
                job=queue.draft(event_id,owner,chat,payload,check_product=True,reply_token=event.reply_token,require_online=True)
                if job['state'] in {'preview_queued','preview_running'}:
                    if os.getenv('CO_ACK_RECEIPT','0')=='1':
                        # Consume the form token once for receipt; MWG preview follows by push.
                        receipt=queue.take_preview_reply(job['id'])
                        if receipt:
                            reply(receipt['token'],f"Đã nhận yêu cầu {job['id']}, đang chờ lấy dữ liệu từ MWG. Vui lòng chờ thông tin xác nhận. Chưa tạo CO.")
                    return True
                if job['state']!='draft':
                    reply(event.reply_token,'Yêu cầu này đã được ghi nhận. Không tạo thêm bản trùng.')
                    return True
                preview=preview_text(job)
                reply(event.reply_token,preview)
            else:
                command,jid=text.split(maxsplit=1)
                if command.upper()=='XEM':
                    with queue.db() as db:
                        job=db.execute('SELECT * FROM jobs WHERE id=? AND owner=? AND chat=?',(jid.strip(),owner,chat)).fetchone()
                    if not job:
                        message='Không tìm thấy yêu cầu của bạn trong chat này.'
                    elif job['state']=='draft':
                        message=preview_text(job)
                    else:
                        labels={'preview_queued':'chờ kiểm tra MWG','preview_running':'đang kiểm tra MWG','queued':'chờ tạo','verified_queued':'chờ tạo','running':'đang xử lý','submitting':'đang tạo CO','failed':'không tạo được CO','succeeded':'đã tạo CO','unknown':'chưa rõ kết quả, cần đối soát','cancelled':'đã hủy','expired':'hết hạn'}
                        message=f"Yêu cầu {job['id']} — {labels.get(job['state'],job['state'])}\n{job['result'] or ''}"
                    reply(event.reply_token,message)
                elif command.upper() == 'HUY' and jid.strip().upper() in {'CHO','CHỜ'}:
                    reply(event.reply_token,queue.cancel_waiting(owner,chat))
                elif jid.strip().upper() == 'ALL' and command.upper() in {'XACNHAN','HUY'}:
                    message=queue.confirm_all(owner,chat,command.upper()=='HUY',reply_token=event.reply_token,require_online=True)
                    if message is not None:
                        reply(event.reply_token,message)
                else:
                    message=queue.confirm(jid.strip(),owner,chat,command.upper()!='XACNHAN',reply_token=event.reply_token if command.upper()=='XACNHAN' else None,require_online=True)
                    if message is not None:
                        reply(event.reply_token,message)
        except BotUnavailable as error:
            reply(event.reply_token,str(error))
        except ValueError as error:
            reply(event.reply_token,f'Form chưa hợp lệ: {error}\nVui lòng sửa và gửi lại.')
        return True
    return handle, notify
