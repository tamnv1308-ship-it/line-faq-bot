"""Authenticated mobile UI over the existing queue; never submits directly to MWG."""
import hashlib
import hmac
import json
import os
import re
import secrets
import threading
import time
from collections import defaultdict, deque
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

from flask import Blueprint, jsonify, request, send_from_directory
from itsdangerous import BadSignature, URLSafeTimedSerializer

from co_flow import (Queue, PRIVATE_CO_OWNER, MEMBER_CO_GROUP, DISABLED_CO_GROUP,
                     BotUnavailable, CONFIRM_SECONDS, BOT_OFF_NOTICE, MAX_BATCH_ROWS,
                     GATHER_SECONDS, add_requester_note)
from tao_compose import parse_editable, validate_rows, queue_payload, STATUSES
from co_health import readiness
from co_results import items, decode_results
from co_regions import region_label, cluster_condition, stores
from co_conditions import load_conditions, fold, condition_text
from co_summary import aggregate, period, TZ
from co_summary_view import details as summary_details

VERSION = 4
COOKIE = '__Host-tao_session'
SESSION_SECONDS = 900
ROOT = Path(__file__).resolve().parent
ACTIVE = ('draft', 'preview_queued', 'preview_running', 'queued', 'verified_queued', 'running', 'submitting', 'unknown')
WAITING = ('draft', 'preview_queued', 'queued', 'verified_queued')
PROCESSING = ('preview_running', 'running', 'submitting')
LABELS = {'draft':'Chờ xác nhận', 'preview_queued':'Chờ nhập file', 'preview_running':'Đang lấy dữ liệu MWG',
          'queued':'Chờ tạo CO', 'verified_queued':'Chờ tạo CO', 'running':'Đang xử lý',
          'submitting':'Đang tạo CO', 'unknown':'Chưa rõ kết quả', 'succeeded':'Đã có kết quả CO',
          'failed':'Không tạo được CO', 'cancelled':'Đã hủy', 'expired':'Hết hạn xác nhận'}


class PortalError(Exception):
    def __init__(self, message, status=400):
        self.message, self.status = message, status


def unknown_revision(job):
    fields=('id','owner','chat','state','payload','result','lease','created','updated','notified')
    return hashlib.sha256(json.dumps({k:job[k] for k in fields},sort_keys=True,
                                    separators=(',',':')).encode()).hexdigest()


def unknown_cancel_reason(job):
    if job['state']!='unknown':return 'Yêu cầu không còn ở trạng thái chưa rõ kết quả.'
    payload=json.loads(job['payload']);result=job['result'] or ''
    evidence=result+' '+json.dumps(payload.get('late_reconciliation',{}),ensure_ascii=False)
    if re.search(r'[0-9A-Z]+CO[0-9]+',evidence,re.I):
        return 'Đã có dấu vết mã CO. Không thể hủy toàn bộ yêu cầu này.'
    if result.lstrip().startswith(('[','{')):
        try:
            if any(row['co'] or row.get('state')=='succeeded' for row in decode_results(payload,result)):
                return 'Có dòng đã có CO. Không thể hủy toàn bộ yêu cầu này.'
        except (ValueError,TypeError):return 'Dữ liệu kết quả không đầy đủ; cần kiểm tra trước khi hủy.'
    return ''


def settings():
    try:
        values = json.loads((ROOT / 'tao_portal_config.json').read_text())
    except (OSError, ValueError):
        values = {}
    liff_id = os.getenv('TAO_LIFF_ID', values.get('liff_id', ''))
    channel = os.getenv('TAO_LINE_LOGIN_CHANNEL_ID', values.get('channel_id', ''))
    base = os.getenv('REPORT_PUBLIC_BASE_URL') or os.getenv('RENDER_EXTERNAL_URL') or values.get('base_url', '')
    ready = bool(re.fullmatch(r'[0-9]+-[a-zA-Z0-9]+', liff_id) and
                 re.fullmatch(r'[0-9]+', channel) and liff_id.split('-')[0] == channel)
    public_launch = os.getenv('TAO_PUBLIC_LAUNCH', str(values.get('public_launch', False))).lower() in ('1','true')
    return {'liff_id':liff_id, 'channel_id':channel, 'base_url':base.rstrip('/'), 'ready':ready, 'public_launch':public_launch}


def verify_id_token(token, channel):
    """Trust only LINE's server-side verification, never a browser-provided user ID."""
    data = urlencode({'id_token':token, 'client_id':channel}).encode()
    req = Request('https://api.line.me/oauth2/v2.1/verify', data=data,
                  headers={'Content-Type':'application/x-www-form-urlencoded'})
    try:
        with urlopen(req, timeout=6) as response:
            identity = json.loads(response.read(32768))
    except HTTPError as error:
        if error.code in (400,401,403):
            raise PortalError('Phiên LINE không hợp lệ. Đóng rồi mở lại Công cụ Táo.', 401) from None
        raise PortalError('LINE đang bận. Vui lòng thử lại sau.', 503) from None
    except (URLError, TimeoutError, OSError, ValueError):
        raise PortalError('Chưa xác thực được với LINE. Vui lòng thử lại.', 503) from None
    if (not isinstance(identity, dict) or identity.get('iss') != 'https://access.line.me' or
            str(identity.get('aud')) != channel or not re.fullmatch(r'U[0-9a-f]{32}', str(identity.get('sub',''))) or
            not isinstance(identity.get('exp'), (int,float)) or identity['exp'] <= time.time()):
        raise PortalError('Tài khoản LINE chưa được xác thực đúng kênh.', 401)
    return identity


def verify_chat_member(chat, user, channel_token):
    """Recheck group membership before a web confirmation; LIFF context is not proof."""
    if not re.fullmatch(r'[CR][0-9a-f]{32}', chat) or not channel_token:
        raise PortalError('Không xác minh được quyền trong cuộc chat của yêu cầu.', 403)
    kind = 'group' if chat.startswith('C') else 'room'
    req = Request(f'https://api.line.me/v2/bot/{kind}/{chat}/member/{user}',
                  headers={'Authorization':'Bearer '+channel_token})
    try:
        with urlopen(req, timeout=5) as response:
            member = json.loads(response.read(32768))
    except HTTPError as error:
        if error.code in (400,403,404):
            raise PortalError('Không xác minh được bạn còn trong nhóm của yêu cầu. Hãy thao tác trong LINE.', 403) from None
        raise PortalError('LINE chưa xác minh được nhóm. Chưa thay đổi yêu cầu.', 503) from None
    except (URLError, TimeoutError, OSError, ValueError):
        raise PortalError('Chưa kết nối được LINE để kiểm tra nhóm. Chưa thay đổi yêu cầu.', 503) from None
    if member.get('userId') != user:
        raise PortalError('Không có quyền với cuộc chat này.', 403)


def install(app, reply, default_users=()):
    bp = Blueprint('tao', __name__, url_prefix='/tao')
    path = os.environ.get('CO_DATABASE_URL') or os.environ.get('CO_DB_PATH')
    q = Queue(path) if os.getenv('CO_ENABLED') == '1' and path else None
    secret = os.environ.get('CHANNEL_SECRET', '')
    signer = URLSafeTimedSerializer(hashlib.sha256(('tao-session-v1:'+secret).encode()).hexdigest(), salt='tao-v1')
    admins = set(default_users) | {PRIVATE_CO_OWNER}
    allowed_users = set(filter(None,(x.strip() for x in os.getenv('CO_ALLOWED_USER_IDS','').split(',')))) or set(default_users)
    limits, rate_lock = defaultdict(deque), threading.Lock()

    def rate(key, count=180, seconds=60):
        now=time.monotonic()
        with rate_lock:
            if len(limits)>2000:
                for k in list(limits):
                    if not limits[k] or limits[k][-1]<now-60:del limits[k]
                if len(limits)>2500:raise PortalError('Hệ thống đang bận. Thử lại sau ít phút.',429)
            bucket=limits[key]
            while bucket and bucket[0]<now-seconds:bucket.popleft()
            if len(bucket)>=count:raise PortalError('Thao tác quá nhanh. Vui lòng chờ một chút.',429)
            bucket.append(now)

    def body():
        if not request.is_json:raise PortalError('Yêu cầu không hợp lệ.',415)
        data=request.get_json(silent=True)
        if not isinstance(data,dict):raise PortalError('Yêu cầu không hợp lệ.')
        return data

    def same_origin():
        origin=request.headers.get('Origin','')
        base=settings()['base_url']
        if not base or origin != base or urlsplit(base).scheme!='https':
            raise PortalError('Hãy mở Công cụ Táo từ đường dẫn chính thức.',403)

    def identity(mutate=False):
        if not q or len(secret)<16 or not settings()['ready']:
            raise PortalError('Công cụ Táo đang được kết nối. Vui lòng thử lại sau.',503)
        try:
            user=signer.loads(request.cookies.get(COOKIE,''), max_age=SESSION_SECONDS)
            if (not isinstance(user,dict) or user.get('exp',0)<=time.time() or
                    not re.fullmatch(r'U[0-9a-f]{32}',str(user.get('uid','')))):
                raise BadSignature('Invalid session')
        except (BadSignature,TypeError,ValueError):
            raise PortalError('Phiên đăng nhập đã hết hạn. Vui lòng đăng nhập lại bằng LINE.',401) from None
        rate(('user',user['uid']))
        if mutate:
            same_origin()
            if not hmac.compare_digest(request.headers.get('X-Tao-CSRF',''), user.get('csrf','')):
                raise PortalError('Phiên thao tác đã thay đổi. Vui lòng mở lại công cụ.',403)
        return user

    def require_owner(user):
        if user['uid'] != PRIVATE_CO_OWNER:
            raise PortalError('Chỉ Tâm 258330 được sử dụng chức năng này.',403)

    def get_job(jid,user):
        if not re.fullmatch(r'[a-f0-9]{10}',jid):raise PortalError('Mã yêu cầu không hợp lệ.',404)
        with q.db() as db:
            row=db.execute('SELECT * FROM jobs WHERE id=?',(jid,)).fetchone()
        if not row or (user['uid']!=PRIVATE_CO_OWNER and row['owner']!=user['uid']):
            raise PortalError('Không tìm thấy yêu cầu của bạn.',404)
        return dict(row)

    def operation_allowed(job,user,cancel=False):
        uid=user['uid'];chat=job['chat']
        if not cancel and chat==DISABLED_CO_GROUP:
            raise PortalError('Nhóm Apple Bot đã ngừng nhận và xác nhận CO.',403)
        if uid==PRIVATE_CO_OWNER:return
        if chat.startswith('U'):
            if not cancel:raise PortalError('Chỉ Tâm được xác nhận yêu cầu qua tin nhắn riêng.',403)
        elif chat!=MEMBER_CO_GROUP and uid not in allowed_users:
            raise PortalError('Bạn chưa được cấp quyền trong cuộc chat này.',403)
        if chat.startswith(('C','R')):verify_chat_member(chat,uid,os.getenv('CHANNEL_ACCESS_TOKEN',''))

    def public_job(job,user,details=False):
        payload=json.loads(job['payload']);rows=items(payload)
        try:results=decode_results(payload,job['result'] or '')
        except (ValueError,TypeError):
            code=job['result'] if job['state']=='succeeded' and len(rows)==1 and re.fullmatch(r'[0-9A-Z]+CO[0-9]+',job['result'] or '') else ''
            results=[{'co':code,'error':job['result'] if job['state'] in ('failed','unknown') else ''} for _ in rows]
        deadline=job['created']+CONFIRM_SECONDS if job['state']=='draft' and job['notified'] else None
        result={'id':job['id'],'state':job['state'],'label':LABELS.get(job['state'],'Đang xử lý'),
                'requester':payload.get('requester_name') or 'Chưa có tên','mine':job['owner']==user['uid'],
                'updated':job['updated'],'expires_at':deadline,'rows':[],
                'can_confirm':job['state']=='draft' and bool(deadline and deadline>time.time()) and job['chat']!=DISABLED_CO_GROUP,
                'can_cancel':job['state'] in WAITING}
        result['can_ack_preview']=bool(details and job['owner']==user['uid'] and payload.get('portal_requests')
            and job['state']=='draft' and job['result']=='MWG_PREVIEW' and not job['notified'])
        if result['can_ack_preview']:result['preview_revision']=unknown_revision(job)
        policies=load_conditions() if details and any('iphone' in fold(x.get('product_name','')) for x in rows) else {}
        for item,outcome in zip(rows,results):
            public={k:item.get(k,'') for k in ('source','destination','source_name','destination_name','product','product_name','quantity','status')}
            public.update(co=outcome.get('co',''),error=outcome.get('error',''),row_state=outcome.get('state',''))
            if details:
                public['note']=item.get('note','')
                policy=condition_text(item,policies)
                relation,label=region_label(item)
                if relation=='same':label='✅ Cùng vùng:'+label.split(':',1)[1]
                elif relation=='different':label='❌ Khác vùng:'+label.split(':',1)[1]
                public['conditions']=(policy.splitlines()[1:] if policy else [])+[label,cluster_condition(item)]
            result['rows'].append(public)
        if details:
            result['skipped_duplicates']=payload.get('skipped_duplicates',[])
            result['skipped_errors']=payload.get('skipped_errors',[])
            if user['uid']==PRIVATE_CO_OWNER and job['state']=='unknown':
                reason=unknown_cancel_reason(job)
                result['unknown_resolution']={'revision':unknown_revision(job),'can_cancel':not reason,'reason':reason}
            audit=payload.get('owner_no_co_cancellation')
            if isinstance(audit,dict) and audit.get('actor')==PRIVATE_CO_OWNER:
                result['owner_cancelled_at']=audit['cancelled_at']
        return result

    @bp.before_request
    def guard():
        limit=65536 if request.path.startswith('/tao/api/compose/') else 16384
        if request.path.startswith('/tao/api/') and request.content_length and request.content_length>limit:
            raise PortalError('Yêu cầu quá lớn.',413)

    @bp.after_request
    def headers(response):
        response.headers['Cache-Control']='no-store'
        response.headers['X-Content-Type-Options']='nosniff'
        response.headers['Referrer-Policy']='no-referrer'
        response.headers['X-Frame-Options']='DENY'
        response.headers['Content-Security-Policy']=("default-src 'self'; script-src 'self' https://static.line-scdn.net; "
            "style-src 'self'; img-src 'self' data:; connect-src 'self' https://api.line.me https://access.line.me https://liff.line.me; "
            "frame-src https://access.line.me; frame-ancestors 'none'; base-uri 'none'; form-action 'self'; object-src 'none'")
        return response

    @bp.errorhandler(PortalError)
    def portal_error(error):return jsonify(error=error.message),error.status

    @bp.errorhandler(Exception)
    def unexpected(error):
        from werkzeug.exceptions import HTTPException
        if isinstance(error,HTTPException):return jsonify(error='Không tìm thấy nội dung.'),error.code
        app.logger.error('Tao portal error: %s',type(error).__name__)
        return jsonify(error='Chưa tải được dữ liệu. Vui lòng thử lại; không tự gửi lại lệnh tạo CO.'),503

    @bp.get('')
    @bp.get('/')
    def index():return send_from_directory(ROOT/'static'/'tao','index.html')

    @bp.get('/privacy')
    def privacy():return send_from_directory(ROOT/'static'/'tao','privacy.html')

    @bp.get('/assets/<filename>')
    def asset(filename):
        if filename not in ('app.js','app.css','apple.svg'):raise PortalError('Không tìm thấy.',404)
        return send_from_directory(ROOT/'static'/'tao',filename)

    @bp.get('/api/config')
    def config():
        cfg=settings()
        return jsonify(liff_id=cfg['liff_id'] if cfg['ready'] else '', ready=bool(cfg['ready'] and q and len(secret)>=16),version=VERSION)

    @bp.post('/api/auth')
    def auth():
        same_origin();rate(('auth',request.remote_addr),30)
        cfg=settings()
        if not cfg['ready'] or not q or len(secret)<16:raise PortalError('Chưa hoàn tất kết nối LINE.',503)
        token=body().get('id_token')
        if not isinstance(token,str) or not 100<=len(token)<=8192:raise PortalError('Thiếu xác thực LINE.',401)
        verified=verify_id_token(token,cfg['channel_id'])
        user={'uid':verified['sub'],'name':str(verified.get('name') or 'Thành viên LINE')[:150],
              'exp':min(verified['exp'],time.time()+SESSION_SECONDS),'csrf':secrets.token_urlsafe(24)}
        response=jsonify(ok=True)
        response.set_cookie(COOKIE,signer.dumps(user),secure=True,httponly=True,samesite='Lax',max_age=SESSION_SECONDS,path='/')
        return response

    @bp.post('/api/logout')
    def logout():
        identity(True);response=jsonify(ok=True)
        response.delete_cookie(COOKIE,path='/',secure=True,httponly=True,samesite='Lax');return response

    @bp.get('/api/me')
    def me():
        user=identity()
        with q.db() as db:
            health=readiness(db)
            enabled=bool(db.execute('SELECT enabled FROM co_control WHERE id=1').fetchone()['enabled'])
        return jsonify(name=user['name'],owner=user['uid']==PRIVATE_CO_OWNER,admin=user['uid'] in admins,
                       csrf=user['csrf'],expires_at=user['exp'],health=health,enabled=enabled,
                       notice=BOT_OFF_NOTICE if not enabled and user['uid']!=PRIVATE_CO_OWNER else '')

    @bp.get('/api/jobs')
    def jobs():
        user=identity();q.expire_confirmations()
        try:offset=int(request.args.get('offset','0'))
        except ValueError:raise PortalError('Trang không hợp lệ.')
        if not 0<=offset<=10000:raise PortalError('Trang không hợp lệ.')
        scope='1=1' if user['uid']==PRIVATE_CO_OWNER else 'owner=?'
        params=[] if user['uid']==PRIVATE_CO_OWNER else [user['uid']]
        selected=request.args.get('filter','active')
        if selected not in ('active','waiting','attention','done','all'):raise PortalError('Bộ lọc không hợp lệ.')
        if selected!='all':
            states=WAITING if selected=='waiting' else ('unknown',) if selected=='attention' else ACTIVE
            scope+=' AND state '+('NOT IN' if selected=='done' else 'IN')+' ('+','.join('?' for _ in states)+')'
            params+=list(states)
        with q.db() as db:
            found=db.execute('SELECT * FROM jobs WHERE '+scope+' ORDER BY updated DESC,id LIMIT 21 OFFSET ?',tuple(params+[offset])).fetchall()
        return jsonify(jobs=[public_job(dict(j),user) for j in found[:20]],more=len(found)>20,offset=offset,server_time=time.time())

    @bp.get('/api/compose')
    def compose_options():
        user=identity()
        scopes=[{'value':'group','label':'Nhóm TÁO - CÔNG CỤ HỖ TRỢ'}]
        if user['uid']==PRIVATE_CO_OWNER:scopes.append({'value':'private','label':'Tin nhắn riêng với bot (Tâm)'} )
        return jsonify(statuses=STATUSES,max_rows=MAX_BATCH_ROWS,scopes=scopes)

    def compose_review(data,user,parse=False):
        try:
            review=parse_editable(data.get('text')) if parse else validate_rows(data.get('rows'),MAX_BATCH_ROWS)
            # Same mandatory contact note as LINE, counted before accepting the form.
            suffix='Mọi thắc mắc liên hệ '+' '.join(user['name'].split())
            for row,bad in zip(review['rows'],review['errors']):
                note=row['note']
                if not (note==suffix or note.endswith(' '+suffix) or note.endswith('\n'+suffix)):
                    note+=(' ' if note else '')+suffix
                if len(note)>500:bad['note']='Note gồm thông tin liên hệ vượt 500 ký tự. Vui lòng rút gọn.'
            review['valid']=not any(review['errors']) and not review['global_errors']
            return review
        except ValueError as error:raise PortalError(str(error)) from None

    @bp.post('/api/compose/parse')
    def compose_parse():
        user=identity(True);rate(('compose-parse',user['uid']),20)
        return jsonify(**compose_review(body(),user,True))

    @bp.post('/api/compose/validate')
    def compose_validate():
        user=identity(True);rate(('compose-validate',user['uid']),40)
        return jsonify(**compose_review(body(),user))

    def compose_event(key,user):
        if not isinstance(key,str) or not re.fullmatch(r'[a-f0-9]{32}',key):
            raise PortalError('Mã lần gửi không hợp lệ. Hãy mở lại form.')
        return 'tao:'+user['uid']+':'+key

    @bp.get('/api/compose/submissions/<key>')
    def compose_submission(key):
        user=identity();event=compose_event(key,user)
        with q.db() as db:
            job=db.execute('SELECT * FROM jobs WHERE event=? AND owner=?',(event,user['uid'])).fetchone()
            if not job:
                job=db.execute('SELECT j.* FROM jobs j JOIN co_gather_events e ON e.job_id=j.id WHERE e.event=? AND j.owner=?',(event,user['uid'])).fetchone()
            skipped=bool(db.execute('SELECT 1 FROM co_event_tombstones WHERE digest=?',(hashlib.sha256(event.encode()).hexdigest(),)).fetchone())
        return jsonify(found=bool(job),skipped=skipped,job=public_job(dict(job),user,True) if job else None)

    @bp.post('/api/compose/submit')
    def compose_submit():
        user=identity(True);rate(('compose-submit',user['uid']),12);data=body()
        event=compose_event(data.get('key'),user);scope=data.get('scope')
        if scope=='group':chat=MEMBER_CO_GROUP
        elif scope=='private' and user['uid']==PRIVATE_CO_OWNER:chat=user['uid']
        else:raise PortalError('Bạn không có quyền gửi yêu cầu vào cuộc chat này.',403)
        operation_allowed({'chat':chat},user)
        review=compose_review(data,user)
        if not review['valid']:return jsonify(error='Sửa các ô báo lỗi trước khi gửi.',review=review),400
        fingerprint=hashlib.sha256(json.dumps({'scope':scope,'rows':review['rows']},sort_keys=True,
                                             separators=(',',':')).encode()).hexdigest()
        try:
            payload=queue_payload(review);add_requester_note(payload,user['name'])
            gather=int(os.getenv('CO_GATHER_SECONDS',str(GATHER_SECONDS)))
            job=q.draft(event,user['uid'],chat,payload,check_product=True,require_online=True,
                        check_duplicates=True,gather_seconds=gather,request_fingerprint=fingerprint)
        except (ValueError,BotUnavailable) as error:raise PortalError(str(error),409) from None
        if job['state']=='skipped':return jsonify(skipped=True,message=job['result'])
        return jsonify(job=public_job(job,user,True),server_time=time.time(),
                       message='Đã nhận yêu cầu, đang lấy dữ liệu từ MWG. Kiểm tra thông tin rồi bấm Xác nhận để tạo CO.')

    @bp.post('/api/jobs/<jid>/preview-seen')
    def preview_seen(jid):
        user=identity(True);job=get_job(jid,user);operation_allowed(job,user)
        revision=body().get('revision')
        if not isinstance(revision,str):raise PortalError('Thiếu bản xác nhận đang hiển thị.')
        with q.db() as db:
            row=db.execute('SELECT * FROM jobs WHERE id=?',(jid,)).fetchone()
            if not row or row['owner']!=user['uid'] or not json.loads(row['payload']).get('portal_requests'):
                raise PortalError('Chỉ người gửi được ghi nhận đã xem form của mình.',403)
            if row['state']=='draft' and row['result']=='MWG_PREVIEW' and row['notified']:
                pass  # LINE or another tab already started the same one-minute deadline.
            elif (row['state']!='draft' or row['result']!='MWG_PREVIEW'
                    or time.time()>=row['created']+300 or not hmac.compare_digest(revision,unknown_revision(dict(row)))):
                raise PortalError('Bản xác nhận đã thay đổi hoặc hết hạn. Tải lại để kiểm tra.',409)
            else:
                db.execute("UPDATE jobs SET created=?,notified=1 WHERE id=? AND state='draft' AND notified=0",(time.time(),jid))
        return jsonify(job=public_job(get_job(jid,user),user,True),server_time=time.time())

    @bp.get('/api/jobs/<jid>')
    def job_detail(jid):
        user=identity();q.expire_confirmations()
        return jsonify(job=public_job(get_job(jid,user),user,True),server_time=time.time())

    @bp.post('/api/jobs/<jid>/<action>')
    def act(jid,action):
        user=identity(True);rate(('action',user['uid']),20)
        if action not in ('confirm','cancel'):raise PortalError('Thao tác không hợp lệ.',404)
        job=get_job(jid,user);operation_allowed(job,user,action=='cancel')
        if action=='confirm' and not (job['state']=='draft' and job['notified']):
            raise PortalError('Yêu cầu chưa sẵn sàng xác nhận hoặc đã được xử lý. Vui lòng tải lại.',409)
        try:
            message=q.confirm(jid,user['uid'],job['chat'],cancel=action=='cancel',require_online=True,playful_cancel=action=='cancel')
        except BotUnavailable as error:raise PortalError(str(error),409) from None
        return jsonify(message=message,job=public_job(get_job(jid,user),user,True),server_time=time.time())

    @bp.get('/api/lookup')
    def lookup():
        user=identity();rate(('lookup',user['uid']),20)
        code=request.args.get('code','').strip().upper()
        if re.fullmatch(r'[0-9a-fA-F]{10}',code):
            return jsonify(job=public_job(get_job(code.lower(),user),user,True))
        if not re.fullmatch(r'[0-9A-Z]{1,30}CO[0-9]{1,30}',code):raise PortalError('Nhập mã CO hoặc mã yêu cầu 10 ký tự.')
        return jsonify(text=q.lookup(code,user['uid']))

    @bp.get('/api/conditions')
    def conditions():
        user=identity();rate(('conditions',user['uid']),30)
        code=request.args.get('code','').strip()
        if not re.fullmatch(r'[0-9]{13}',code):raise PortalError('Mã sản phẩm phải có đủ 13 chữ số.')
        values=load_conditions().get(code)
        if values is None:return jsonify(found=False,code=code,message='Chưa có điều kiện của mã này trong DATA. Không suy đoán là được phép.')
        return jsonify(found=True,code=code,conditions=[{'label':label,'value':value or 'Chưa rõ',
            'state':'yes' if fold(value) in {'mo','duoc','co','duoc phep','yes','true','✅'} else
                    'no' if fold(value) in {'khoa','khong','khong duoc','khong duoc phep','no','false','❌'} else 'unknown'}
            for label,value in zip(('Bán thường','Chiến giá','Chuyển kho'),values)])

    @bp.get('/api/summary')
    def summary():
        user=identity();require_owner(user);rate(('summary',user['uid']),12)
        token=request.args.get('period','today')
        if token not in ('today','7','30'):raise PortalError('Chọn hôm nay, 7 ngày hoặc 30 ngày gần nhất.')
        start,end=period('' if token=='today' else token+'ngay')
        with q.db() as db:
            rows=[dict(j) for j in db.execute('SELECT * FROM jobs WHERE created>=? AND created<? ORDER BY created',(start.timestamp(),end.timestamp()))]
        directory=stores();stats,_,_=aggregate(rows,directory)
        info=summary_details(rows,directory,TZ)
        top={}
        for category,ranking in info['ranked'].items():
            top[category]=[{'name':(key+' · ' if category in ('source','destination') else '')+info['labels'].get((category,key),key),
                           'count':count,'quantity':quantity} for key,count,quantity in ranking]
        return jsonify(stats=dict(stats),top=top,start=start.isoformat(),end=end.isoformat(),recent=info['recent'])

    @bp.post('/api/admin/intake')
    def intake():
        user=identity(True)
        if user['uid'] not in admins:raise PortalError('Chỉ ADM được bật/tắt nhận CO.',403)
        enabled=body().get('enabled')
        if not isinstance(enabled,bool):raise PortalError('Trạng thái không hợp lệ.')
        message=q.admin('BOT ON' if enabled else 'BOT OFF')
        return jsonify(message=message)

    def waiting_snapshot(db):
        # Called inside Queue.db(): the same transaction lock used by Mac claims.
        rows=db.execute('SELECT id,state,updated FROM jobs WHERE state IN ('+
                        ','.join('?' for _ in WAITING)+') ORDER BY id',WAITING).fetchall()
        revision=hashlib.sha256(json.dumps([dict(r) for r in rows],sort_keys=True,
                                          separators=(',',':')).encode()).hexdigest()
        counts={r['state']:r['n'] for r in db.execute('SELECT state,COUNT(*) AS n FROM jobs GROUP BY state')}
        return rows,dict(waiting=len(rows),processing=sum(counts.get(s,0) for s in PROCESSING),
                         unknown=counts.get('unknown',0),revision=revision)

    @bp.get('/api/admin/queue')
    def queue_overview():
        user=identity();require_owner(user);q.expire_confirmations()
        with q.db() as db:_,overview=waiting_snapshot(db)
        return jsonify(**overview)

    @bp.post('/api/admin/cancel-waiting')
    def cancel_waiting_all():
        user=identity(True);require_owner(user);rate(('cancel-waiting',user['uid']),10)
        revision=body().get('revision')
        if not isinstance(revision,str) or not re.fullmatch(r'[0-9a-f]{64}',revision):
            raise PortalError('Hãy tải lại hàng chờ trước khi hủy.')
        with q.db() as db:
            rows,overview=waiting_snapshot(db)
            if not hmac.compare_digest(revision,overview['revision']):
                raise PortalError('Hàng chờ đã thay đổi. Tải lại và kiểm tra số yêu cầu trước khi hủy.',409)
            # Preserve payload/result history. Never touch work already claimed by Mac.
            db.execute("UPDATE jobs SET state='cancelled',lease=NULL,notified=1,updated=? WHERE state IN ("+
                       ','.join('?' for _ in WAITING)+')',(time.time(),)+WAITING)
            for row in rows:db.execute('DELETE FROM preview_replies WHERE job_id=?',(row['id'],))
        message=(f'Đã hủy {len(rows)} yêu cầu chờ của tất cả người dùng, trong mọi chat. '
                 'Yêu cầu đang xử lý, chưa rõ kết quả và CO đã tạo được giữ nguyên.')
        return jsonify(cancelled=len(rows),message=message)

    @bp.post('/api/admin/jobs/<jid>/cancel-unknown')
    def cancel_unknown(jid):
        user=identity(True);require_owner(user);rate(('cancel-unknown',user['uid']),10)
        if not re.fullmatch(r'[a-f0-9]{10}',jid):raise PortalError('Mã yêu cầu không hợp lệ.',404)
        data=body();revision=data.get('revision')
        if data.get('checked_mwg_no_co') is not True:
            raise PortalError('Cần xác nhận đã kiểm tra MWG và chưa có CO ở tất cả dòng của yêu cầu.')
        if not isinstance(revision,str) or not re.fullmatch(r'[0-9a-f]{64}',revision):
            raise PortalError('Hãy mở lại chi tiết yêu cầu trước khi hủy.')
        with q.db() as db:
            row=db.execute('SELECT * FROM jobs WHERE id=?',(jid,)).fetchone()
            if not row:raise PortalError('Không tìm thấy yêu cầu.',404)
            job=dict(row)
            if not hmac.compare_digest(revision,unknown_revision(job)):
                raise PortalError('Kết quả đã thay đổi. Tải lại và kiểm tra MWG trước khi hủy.',409)
            reason=unknown_cancel_reason(job)
            if reason:raise PortalError(reason,409)
            if db.execute('SELECT 1 FROM co_note_outbox WHERE job_id=?',(jid,)).fetchone():
                raise PortalError('Đã có kết quả CO được ghi nhận. Không thể hủy yêu cầu này.',409)
            now=time.time();payload=json.loads(job['payload'])
            payload['owner_no_co_cancellation']={'actor':user['uid'],'cancelled_at':now,
                'checked_mwg_no_co':True,'previous_state':job['state'],'previous_result':job['result'],
                'revision':revision}
            # Keep the lease only for authenticated late result reconciliation, never for a new claim.
            db.execute("UPDATE jobs SET state='cancelled',payload=?,notified=1,updated=? WHERE id=?",
                       (json.dumps(payload,ensure_ascii=False),now,jid))
            db.execute('DELETE FROM preview_replies WHERE job_id=?',(jid,))
        return jsonify(message=f'Đã hủy yêu cầu #{jid} theo xác nhận của Tâm: đã kiểm tra MWG, chưa có CO. Đã lưu lịch sử đối soát.',
                       job=public_job(get_job(jid,user),user,True),server_time=time.time())

    @bp.get('/api/admin/locks')
    def locks():
        user=identity();require_owner(user);q.expire_confirmations()
        with q.db() as db:
            rows=db.execute('SELECT owner,name,strikes,locked_until,last_job,updated FROM co_confirmation_locks WHERE strikes>=3 OR locked_until>? ORDER BY updated,owner LIMIT 50',(time.time(),)).fetchall()
        return jsonify(locks=[dict(r) for r in rows])

    @bp.post('/api/admin/unlock')
    def unlock_user():
        user=identity(True);require_owner(user);data=body()
        target,last_job=data.get('owner'),data.get('last_job');stamp=data.get('updated')
        if not isinstance(target,str) or not re.fullmatch(r'U[0-9a-f]{32}',target) or not isinstance(stamp,(int,float)):
            raise PortalError('Danh sách mở khóa không hợp lệ.')
        # Same lock reset as !mokhoa, with identity and revision rather than a mutable list position.
        with q.db() as db:
            row=db.execute('SELECT * FROM co_confirmation_locks WHERE owner=?',(target,)).fetchone()
            if not row or row['last_job']!=last_job or row['updated']!=stamp:
                raise PortalError('Trạng thái đã thay đổi. Tải lại danh sách trước khi mở khóa.',409)
            db.execute('DELETE FROM co_confirmation_locks WHERE owner=?',(target,))
            db.execute('DELETE FROM co_unlock_choices WHERE target=?',(target,))
            message=f"Đã mở khóa {row['name']}. Số lần quá hạn đã reset về 0; có thể gửi yêu cầu CO mới."
            db.execute('INSERT INTO co_unlock_events(event,message,created) VALUES(?,?,?)',('tao:'+secrets.token_hex(16),message,time.time()))
        return jsonify(message=message)

    app.register_blueprint(bp)

    def handle(event):
        if event.message.text.strip().casefold() not in ('!congcu','!côngcụ','!tao','!công cụ'):return False
        cfg=settings()
        if not cfg['ready'] or not cfg['public_launch']:
            reply(event.reply_token,'Công cụ Táo đang được hoàn tất kết nối. Các lệnh của bot vẫn dùng như hiện tại.');return True
        reply(event.reply_token,'🍏 CÔNG CỤ TÁO\nTra cứu CO · Yêu cầu · Điều kiện sản phẩm\n\nhttps://liff.line.me/'+cfg['liff_id']+'\n\nĐăng nhập bằng tài khoản LINE của bạn. Quyền và quy tắc tạo CO giữ nguyên.')
        return True
    return handle
