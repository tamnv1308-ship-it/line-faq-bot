"""Owner diagnostics only. Observations never change a CO decision or queue state."""
import hashlib
import hmac
import json
import logging
import math
import re
import time
import unicodedata
from collections import Counter, defaultdict

VERSION = 1
WORKER_STAGES = {
    'reuse_page_before_request':'Kiểm tra trang MWG', 'reuse_imported_row':'Dùng dữ liệu đã xác nhận',
    'select_brands':'Chọn thương hiệu', 'select_product_status':'Chọn trạng thái',
    'reload_blank_product_status':'Chờ ô trạng thái', 'reload_brand_timeout':'Tải lại thương hiệu',
    'prepare_local_template':'Chuẩn bị file Excel', 'upload_excel':'Nhập file lên MWG',
    'retry_import_after_timeout':'Thử lại nhập file', 'import_response_verified':'Đối chiếu phản hồi nhập',
    'accept_import':'Nhận dữ liệu nhập', 'skip_invalid_import_rows':'Tách dòng lỗi',
    'submit_co':'Gửi tạo CO và chờ MWG', 'create_response_verified':'Đối chiếu kết quả CO',
    'late_create_response_verified':'Đối chiếu kết quả về muộn',
    'api_prepare':'Chuẩn bị MWG', 'api_import':'Nhập file qua API MWG',
    'api_submit_co':'Gửi tạo CO qua API MWG', 'send_result':'Gửi kết quả từ Mac về máy chủ',
}
ERRORS = {
    'timeout':('Quá thời gian chờ','Kiểm tra bước đang chậm và kết nối MWG. Nếu đã gửi tạo CO, đối chiếu MWG trước khi gửi lại.'),
    'browser_closed':('Chrome của bot đã đóng','Mở lại bot và đăng nhập MWG nếu được yêu cầu. Kiểm tra yêu cầu chưa rõ kết quả trước khi tạo lại.'),
    'login':('Phiên MWG cần đăng nhập','Đăng nhập trong Chrome của bot trên Mac, chờ báo Sẵn sàng.'),
    'product':('MWG báo mã sản phẩm không hợp lệ','Kiểm tra đủ 13 số và trạng thái sản phẩm; sửa dòng lỗi rồi gửi yêu cầu mới.'),
    'status':('Ô trạng thái chưa sẵn sàng','Kiểm tra Chrome của bot: thương hiệu và trạng thái phải hiển thị. Bot chỉ tự tải lại khi an toàn.'),
    'mismatch':('Dữ liệu MWG chưa đối chiếu được','Mở chi tiết để so lại kho, mã sản phẩm, số lượng với dữ liệu MWG.'),
    'network':('Kết nối bị gián đoạn','Kiểm tra mạng của Mac và dịch vụ bot. Kết quả đã lưu sẽ được thử gửi lại, không tạo lại CO.'),
    'service_auth':('Máy chủ từ chối kết nối từ Mac','Kiểm tra cấu hình kết nối bot trên Mac. Giữ kết quả đã lưu để đối chiếu; không tạo lại CO.'),
    'line_delivery':('Chưa gửi được thông báo LINE','Xem kết quả ngay trong Công cụ Táo; kiểm tra kết nối/hạn mức LINE. Bot tự thử gửi lại thông báo.'),
    'mwg_error':('MWG trả lỗi cho dòng yêu cầu','Mở chi tiết xem thông báo MWG, kiểm tra dữ liệu dòng lỗi trước khi gửi yêu cầu mới.'),
    'unclassified':('Chưa đủ dữ liệu xác định nguyên nhân','Mở chi tiết xem bước cuối và thông báo gốc; chưa kết luận do mã sản phẩm hay do MWG.'),
}
PHASES = {
    'received':('queue','Chờ và gom yêu cầu',{'preview_claimed','create_claimed'}),
    'preview_claimed':('prepare','Lấy dữ liệu MWG',{'preview_ready','result_received'}),
    'preview_ready':('preview_delivery','Đưa thông tin xác nhận tới người dùng',{'confirmation_delivered','confirmed'}),
    'confirmation_delivered':('confirmation','Người dùng chờ xác nhận',{'confirmed'}),
    'confirmed':('create_queue','Chờ đến lượt tạo CO',{'create_claimed'}),
    'create_claimed':('pre_submit','Kiểm tra trước khi tạo',{'submitting','result_received'}),
    'submitting':('create','MWG xử lý tạo CO',{'result_received'}),
    'result_received':('result_delivery','Gửi thông báo kết quả',{'result_delivered'}),
}
TERMINAL = {'succeeded','failed','unknown','cancelled','expired'}


def schema(db):
    db.executescript('''
      CREATE TABLE IF NOT EXISTS co_ops_events (
        event_id TEXT PRIMARY KEY, job_id TEXT NOT NULL, source TEXT NOT NULL,
        stage TEXT NOT NULL, at REAL NOT NULL, received REAL NOT NULL,
        duration_ms REAL, outcome TEXT NOT NULL, error_code TEXT NOT NULL);
      CREATE INDEX IF NOT EXISTS co_ops_job_time ON co_ops_events(job_id,at);
      CREATE INDEX IF NOT EXISTS co_ops_received ON co_ops_events(received);
      CREATE INDEX IF NOT EXISTS co_ops_jobs_updated ON jobs(updated);
    ''')


def record(db, jid, stage, key='', at=None, outcome='ok', error_code='',
           source='server', duration_ms=None, event_id=None):
    """Savepoint keeps optional telemetry failures out of business transactions."""
    now=time.time();at=now if at is None else at
    event_id=event_id or hashlib.sha256((jid+':'+stage+':'+str(key)).encode()).hexdigest()
    try:
        db.execute('SAVEPOINT co_ops_write')
        db.execute('INSERT INTO co_ops_events(event_id,job_id,source,stage,at,received,duration_ms,outcome,error_code) VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(event_id) DO NOTHING',
                   (event_id,jid,source,stage,at,now,duration_ms,outcome,error_code))
        db.execute('RELEASE SAVEPOINT co_ops_write')
        return True
    except Exception:
        try:
            db.execute('ROLLBACK TO SAVEPOINT co_ops_write')
            db.execute('RELEASE SAVEPOINT co_ops_write')
        except Exception:pass
        logging.getLogger(__name__).warning('CO diagnostics write unavailable; business state unchanged.')
        return False


def classify(text):
    value=''.join(c for c in unicodedata.normalize('NFD',str(text).lower().replace('đ','d')) if unicodedata.category(c)!='Mn')
    if any(x in value for x in ('targetclosed','has been closed','cua so da dong')):return 'browser_closed'
    if any(x in value for x in ('dang nhap','login','unauthorized','http 401')):return 'login'
    if any(x in value for x in ('timeout','timed out','qua thoi gian')):return 'timeout'
    if any(x in value for x in ('ma san pham khong ton tai','ma san pham khong hop le','du 13')):return 'product'
    if any(x in value for x in ('trang thai san pham trong','o trang thai','trang thai mwg')):return 'status'
    if any(x in value for x in ('khong khop','doi chieu','doi soat dong')):return 'mismatch'
    if any(x in value for x in ('urlerror','connection','ket noi','http 5','http 429','httperror','ssl')):return 'network'
    return 'mwg_error' if str(text).strip() else 'unclassified'


def ingest(db, events):
    """Worker auth is checked by the route; additionally require each job's lease."""
    if not isinstance(events,list) or len(events)>40:return []
    ack=[];now=time.time()
    for e in events:
        if not isinstance(e,dict):continue
        eid=e.get('event_id');jid=e.get('job_id');lease=e.get('lease')
        if not (isinstance(eid,str) and re.fullmatch(r'[a-f0-9]{32}',eid)
                and isinstance(jid,str) and re.fullmatch(r'[a-f0-9]{10}',jid)
                and isinstance(lease,str) and 1<=len(lease)<=200):continue
        if e.get('stage') not in WORKER_STAGES or e.get('outcome') not in {'start','ok','error'}:continue
        at=e.get('at');duration=e.get('duration_ms');code=e.get('error_code','')
        if isinstance(at,bool) or not isinstance(at,(int,float)) or not math.isfinite(at) or not now-30*86400<=at<=now+300:continue
        if duration is not None and (isinstance(duration,bool) or not isinstance(duration,(int,float)) or not math.isfinite(duration) or not 0<=duration<=86400000):continue
        if code not in ERRORS and code!='':continue
        row=db.execute('SELECT lease FROM jobs WHERE id=?',(jid,)).fetchone()
        # Superseded leases can never append misleading telemetry to a new attempt.
        # Acknowledge discard so a durable old batch does not block later observations.
        if not row or not hmac.compare_digest(row['lease'] or '',lease):
            ack.append(eid);continue
        if record(db,jid,e['stage'],at=at,outcome=e['outcome'],error_code=code,
                  source='mac',duration_ms=duration,event_id=eid):ack.append(eid)
    return ack


def read_events(db,jid):
    return [dict(r) for r in db.execute('SELECT * FROM co_ops_events WHERE job_id=? ORDER BY at,received,event_id',(jid,))]


def timeline(job, events, now=None):
    now=time.time() if now is None else now
    spans=[];opened=None
    for e in (r for r in events if r['source']=='server'):
        stage=e['stage']
        if opened:
            old,entry=opened;key,label,ends=PHASES[old]
            if stage in ends:
                elapsed=e['at']-entry['at']
                if elapsed>=0:spans.append(dict(key=key,label=label,seconds=round(elapsed,3),start=entry['at'],end=e['at'],complete=True))
                opened=None
        if stage in PHASES:opened=(stage,e)
        elif stage in {'cancelled','expired'}:opened=None
    if opened:
        stage,e=opened;key,label,_=PHASES[stage]
        ended=job['state'] in TERMINAL and not (stage=='result_received' and not job['notified'])
        end=min(now,job['updated']) if ended else now
        if end>=e['at']:
            spans.append(dict(key=key,label=label,seconds=round(end-e['at'],3),start=e['at'],end=end,complete=False,stopped=ended))
    mac=[dict(label=WORKER_STAGES[e['stage']],stage=e['stage'],at=e['at'],
              seconds=round(e['duration_ms']/1000,3) if e['duration_ms'] is not None else None,
              outcome=e['outcome'],error=ERRORS.get(e['error_code'],('',''))[0])
         for e in events if e['source']=='mac' and e['stage'] in WORKER_STAGES]
    return {'available':bool(events),'phases':spans,'mac_steps':mac,
            'notice':'Đo riêng thời gian chờ xác nhận. Chi tiết Mac có thể cập nhật trễ vài giây; dữ liệu cũ không được suy đoán.'}


def issues_for(job, events, now):
    from co_results import items, decode_results
    payload=json.loads(job['payload']);state=job['state'];issues=[]
    def add(kind,title,guidance,severity='warning',reason=''):
        issues.append(dict(kind=kind,title=title,guidance=guidance,severity=severity,
                           job_id=job['id'],requester=payload.get('requester_name') or 'Chưa có tên',
                           state=state,updated=job['updated'],reason=reason))
    if state=='unknown':
        add('unknown','Chưa rõ kết quả tạo CO','Kiểm tra mã CO trên MWG. Nếu đã kiểm tra chắc chắn chưa có CO, mở chi tiết và dùng quyền hủy của Tâm.','danger')
    errors=[]
    try:errors=[r['error'] for r in decode_results(payload,job['result'] or '') if r.get('error')]
    except (ValueError,TypeError):
        if state=='failed':errors=[job['result'] or '']
    excluded=[str(r.get('error','')) for r in payload.get('skipped_errors',[]) if isinstance(r,dict)]
    if excluded and state not in {'cancelled','expired','unknown'}:errors+=excluded
    if job['updated']>=now-86400 and (state in {'failed','succeeded'} or excluded) and errors:
        code=classify(' '.join(errors));title,guidance=ERRORS[code]
        add('row_error',title,guidance,reason=code)
    if state=='expired' and job['updated']>=now-86400:
        stages={e['stage'] for e in events}
        if 'notification_failed' in stages and 'confirmation_delivered' not in stages:
            add('delivery','Yêu cầu hết hạn trước khi gửi được xác nhận',
                'Chưa tạo CO. Kiểm tra lỗi gửi LINE, sau đó nhờ người gửi gửi lại yêu cầu.',reason='line_delivery')
    if not job['notified'] and state in {'succeeded','failed','unknown','draft'}:
        failures=[e for e in events if e['stage']=='notification_failed' and e['at']>=job['updated']]
        if failures or now-job['updated']>=15:
            add('delivery',*ERRORS['line_delivery'],reason='line_delivery')
    if state in {'preview_running','running','submitting'} and now-job['updated']>=45:
        latest=next((e for e in reversed(events) if e['source']=='mac'),None)
        label=WORKER_STAGES.get(latest['stage'],'Chưa có chi tiết từ Mac') if latest else 'Chưa có chi tiết từ Mac'
        add('slow','Yêu cầu đang xử lý lâu','Kiểm tra bước cuối trên Chrome của bot. Khi đã gửi tạo CO, giữ trang để đối chiếu kết quả.',reason=label)
    if state in {'queued','verified_queued','preview_queued'} and now-job['updated']>=60:
        add('waiting','Yêu cầu chờ đến lượt lâu','Kiểm tra Mac/MWG và yêu cầu phía trước. Chờ xác nhận của người khác cũng có thể giữ hàng chờ.')
    return issues


def overview(queue, now=None):
    from co_health import readiness
    now=time.time() if now is None else now
    with queue.db() as db:
        health=readiness(db,now)
        rows=[dict(r) for r in db.execute("SELECT * FROM jobs WHERE updated>=? OR state IN ('draft','preview_queued','preview_running','queued','verified_queued','running','submitting','unknown') ORDER BY updated DESC LIMIT 1001",(now-86400,))]
        events=defaultdict(list)
        for start in range(0,min(len(rows),1000),100):
            ids=[r['id'] for r in rows[start:start+100]]
            if ids:
                for e in db.execute('SELECT * FROM co_ops_events WHERE job_id IN ('+','.join('?' for _ in ids)+') ORDER BY at,received,event_id',tuple(ids)):
                    events[e['job_id']].append(dict(e))
    issues=[];samples=defaultdict(list);causes=Counter();error_stages=Counter();instrumented=0;mac_count=0
    system={
        'login':('MWG đang chờ đăng nhập','Đăng nhập trong Chrome của bot trên Mac; chờ trạng thái Sẵn sàng.'),
        'offline':('Mac đang mất kết nối','Kiểm tra Mac có bật, có mạng và bot đang chạy. Mở bot nếu cần.'),
        'blocked':('Bot cần kiểm tra','Xem Chrome của bot và bước cuối của các yêu cầu bên dưới. Giữ trang nếu còn kết quả cần đối chiếu.'),
        'reconnecting':('Bot đang kết nối lại','Kiểm tra mạng Mac và dịch vụ bot. Kết quả đã lưu được thử gửi lại tự động.'),
        'unverified':('Chưa kiểm tra được MWG','Kiểm tra bot trên Mac; đợi xác nhận trang MWG sẵn sàng.'),
    }
    if health['worker_state'] in system:
        title,guidance=system[health['worker_state']]
        issues.append(dict(kind='system',title=title,guidance=guidance,severity='danger',job_id=None,reason=health['worker_state']))
    for job in rows[:1000]:
        ev=events[job['id']];issues+=issues_for(job,ev,now)
        if job['updated']<now-86400:continue
        instrumented+=bool(ev);mac_count+=any(e['source']=='mac' for e in ev)
        for span in timeline(job,ev,now)['phases']:
            if span['complete'] and span['end']>=now-86400:samples[span['key']].append(span['seconds'])
        # One sample per recorded Mac span; start events are excluded.
        job_causes=set();job_error_stages=set()
        for e in ev:
            if e['source']=='mac' and e['duration_ms'] is not None and e['at']>=now-86400:
                samples['mac:'+e['stage']].append(e['duration_ms']/1000)
            if e['at']>=now-86400 and e['outcome']=='error' and e['error_code'] in ERRORS:
                job_causes.add(e['error_code'])
                label=WORKER_STAGES.get(e['stage'],'Gửi thông báo LINE' if e['stage']=='notification_failed' else 'Kết quả MWG')
                job_error_stages.add((label,e['error_code']))
        for issue in issues_for(job,ev,now):
            if issue['kind'] in {'row_error','delivery'}:job_causes.add(issue['reason'])
        causes.update(job_causes);error_stages.update(job_error_stages)
    timings=[]
    labels={x[0]:x[1] for x in PHASES.values()}
    labels.update({'mac:'+k:v for k,v in WORKER_STAGES.items()})
    for key,label in labels.items():
        values=sorted(samples[key]);n=len(values)
        if n:timings.append(dict(key=key,label=label,count=n,average=round(sum(values)/n,2),p95=round(values[math.ceil(n*.95)-1],2)))
    issues.sort(key=lambda x:(x['severity']!='danger',-(x.get('updated') or now)))
    return dict(version=VERSION,health=health,issues=issues[:60],issue_count=len(issues),
                timings=timings,errors=[dict(code=k,label=ERRORS[k][0],count=v) for k,v in causes.most_common(5)],
                error_stages=[dict(stage=k[0],label=ERRORS[k[1]][0],count=v) for k,v in error_stages.most_common(10)],
                coverage=dict(recent_requests=sum(r['updated']>=now-86400 for r in rows[:1000]),instrumented=instrumented,mac=mac_count),
                truncated=len(rows)>1000 or len(issues)>60,server_time=now,
                period='24 giờ gần nhất',retention_days=30)
