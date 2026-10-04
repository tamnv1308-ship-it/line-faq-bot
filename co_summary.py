"""Owner-only seven calendar day CO reports; never drives queue state."""
import json, os, re, secrets, time, zlib, base64, hashlib
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
from PIL import Image, ImageDraw, ImageFont
from co_results import items, decode_results
TZ=ZoneInfo('Asia/Ho_Chi_Minh')
OWNER='U60751d1a57eb4707a3dff9c06f3240a4'
TERMINAL=('succeeded','failed','cancelled','expired')

def period(arg='',now=None):
    today=(now or datetime.now(TZ)).date(); first=today-timedelta(days=6)
    if arg.lower()=='7ngay':start,end=first,today
    elif not arg:start=end=today
    else:
        try:start=end=datetime.strptime(arg,'%d/%m/%Y').date()
        except ValueError:raise ValueError('Dùng !tongket, !tongket DD/MM/YYYY hoặc !tongket 7ngay.')
        if not first<=start<=today:raise ValueError('Chỉ xem được hôm nay và 6 ngày trước theo giờ Việt Nam.')
    return datetime.combine(start,datetime.min.time(),TZ),datetime.combine(end+timedelta(days=1),datetime.min.time(),TZ)

def aggregate(jobs,stores):
    stats=Counter(); ranks={k:Counter() for k in ('people','source','destination','region','province','product')};names={}
    seen=set()
    for j in jobs:
        p=json.loads(j['payload']); data=items(p); stats['requests']+=1
        names[j['owner']]=p.get('requester_name') or 'Chưa có tên'
        try:results=decode_results(p,j['result'] or '')
        except (ValueError,TypeError):
            valid=len(data)==1 and j['state']=='succeeded' and re.fullmatch(r'[0-9A-Z]+CO[0-9]+',j['result'] or '')
            results=[{'co':j['result'] if valid else '', 'error':''} for _ in data]
        for item,result in zip(data,results):
            if result['co'] and not result['error']:
                key=(result['co'],item['source'],item['destination'],item['product'],int(item['quantity']))
                if key in seen:continue
                seen.add(key);stats['success_rows']+=1;stats['quantity']+=int(item['quantity'])
                ranks['people'][j['owner']]+=1
                for side in ('source','destination'):ranks[side][str(item[side])]+=1
                store=stores.get(str(item['source']),{})
                ranks['region'][store.get('region','Chưa phân vùng')]+=1
                ranks['province'][store.get('province','Chưa phân vùng')]+=1
                product=item['product'];names[product]=item.get('product_name') or 'Chưa có tên sản phẩm'
                ranks['product'][product]+=1
            elif j['state'] in ('unknown','succeeded'):stats['unknown']+=1
            elif j['state']=='failed' or result['error']:stats['failed']+=1
            elif j['state'] in ('cancelled','expired'):stats['cancelled']+=1
            else:stats['pending']+=1
    stats['co']=len({x[0] for x in seen})
    return stats,ranks,names

def render(jobs,stores,start,end,directory):
    from co_summary_view import draw_dashboard
    stats,_,_=aggregate(jobs,stores)
    return draw_dashboard(jobs,stores,start,end,directory,stats,TZ)


def cleanup(queue,directory):
    image_cutoff=period('7ngay')[0].timestamp()
    cutoff=(datetime.now(TZ).replace(hour=0,minute=0,second=0,microsecond=0)-timedelta(days=29)).timestamp()
    with queue.db() as db:
        ids=[r['id'] for r in db.execute("SELECT id FROM jobs WHERE state IN ('succeeded','failed','cancelled','expired') AND created<? AND updated<?",(cutoff,cutoff))]
        for jid in ids:
            row=db.execute('SELECT event FROM jobs WHERE id=?',(jid,)).fetchone()
            db.execute('INSERT INTO co_event_tombstones(digest) VALUES(?) ON CONFLICT(digest) DO NOTHING',(hashlib.sha256(row['event'].encode()).hexdigest(),))
            for table in ('preview_replies','co_note_rows','co_note_outbox'):db.execute('DELETE FROM '+table+' WHERE job_id=?',(jid,))
            db.execute('DELETE FROM jobs WHERE id=?',(jid,))
    if directory.exists():
        for p in directory.glob('*.png'):
            if p.stat().st_mtime<image_cutoff:p.unlink()

def install(app,reply,reply_image,scheduler,base_url):
    from flask import send_from_directory,abort
    from co_flow import Queue
    directory=Path(os.getenv('CO_SUMMARY_DIR','/var/data/co-summaries'))
    path=os.environ.get('CO_DATABASE_URL') or os.environ.get('CO_DB_PATH')
    q=Queue(path) if path else None
    @app.get('/co-summary-images/<filename>')
    def summary_image(filename):
        if not re.fullmatch('[0-9a-f]{48}\\.png',filename):abort(404)
        p=directory/filename
        if not p.exists() or p.stat().st_mtime<period('7ngay')[0].timestamp():abort(404)
        return send_from_directory(directory,filename)
    if q:scheduler.add_job(lambda:cleanup(q,directory),'interval',hours=1,id='co_summary_cleanup',max_instances=1)
    def handle(event):
        bits=event.message.text.strip().split(maxsplit=1)
        if not bits or bits[0].lower()!='!tongket':return False
        if getattr(event.source,'user_id',None)!=OWNER:
            reply(event.reply_token,'Chỉ Tâm 258330 được xem tổng kết CO.');return True
        try:
            if not q or not base_url:raise ValueError('Báo cáo CO chưa được cấu hình.')
            start,end=period(bits[1] if len(bits)>1 else '')
            with q.db() as db:jobs=[dict(r) for r in db.execute('SELECT * FROM jobs WHERE created>=? AND created<? ORDER BY created',(start.timestamp(),end.timestamp()))]
            mapping=Path(os.getenv('CO_STORES_PATH','/var/data/co_stores.json'))
            if os.getenv('CO_STORES_ZLIB'):
                stores=json.loads(zlib.decompress(base64.b64decode(os.environ['CO_STORES_ZLIB'])))
            elif mapping.exists():stores=json.loads(mapping.read_text())
            else:raise ValueError('Chưa nạp danh mục kho để tạo báo cáo.')
            name=render(jobs,stores,start,end,directory)
            reply_image(event.reply_token,base_url.rstrip('/')+'/co-summary-images/'+name)
        except ValueError as e:reply(event.reply_token,str(e))
        except Exception:
            app.logger.exception('CO summary failed')
            reply(event.reply_token,'Chưa tạo được hình tổng kết; vui lòng thử lại.')
        return True
    return handle
