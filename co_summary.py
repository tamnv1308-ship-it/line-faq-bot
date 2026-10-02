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
    stats,ranks,names=aggregate(jobs,stores)
    image=Image.new('RGB',(1600,1800),'#f0f4f8');d=ImageDraw.Draw(image)
    fontpaths=['/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf','/System/Library/Fonts/Supplemental/Arial.ttf']
    fp=next(p for p in fontpaths if Path(p).exists())
    def text(x,y,t,size=24,color='#162b45'):d.text((x,y),str(t),font=ImageFont.truetype(fp,size),fill=color)
    def fit(t,width,size=24):
        f=ImageFont.truetype(fp,size)
        while d.textlength(t,font=f)>width:t=t[:-2]
        return t
    text(48,30,'APPLE BOT | TỔNG KẾT CO',40)
    text(48,91,start.strftime('%d/%m/%Y')+' — '+(end-timedelta(days=1)).strftime('%d/%m/%Y'),26)
    text(48,132,'Theo ngày nhận yêu cầu • Giờ Việt Nam • Danh mục kho 09/2026',22)
    cards=[('Yêu cầu',stats['requests']),('CO thành công',stats['co']),('SL sản phẩm',stats['quantity']),('Dòng lỗi',stats['failed']),('Dòng chờ',stats['pending']),('Chưa rõ kết quả',stats['unknown'])]
    for n,(label,value) in enumerate(cards):
        x=48+n*252;d.rounded_rectangle((x,190,x+238,330),14,fill='white');text(x+16,208,label,20);text(x+16,250,value,42,'#00845b')
    titles={'people':'TOP 5 NGƯỜI YÊU CẦU','source':'TOP 5 KHO XUẤT','destination':'TOP 5 KHO NHẬN','region':'TOP 5 VÙNG XUẤT','province':'TOP 5 TỈNH/THÀNH XUẤT','product':'TOP 5 SẢN PHẨM'}
    for n,key in enumerate(titles):
        x=48+(n%2)*770;y=365+(n//2)*425
        d.rounded_rectangle((x,y,x+738,y+395),14,fill='white');text(x+22,y+20,titles[key],25)
        text(x+22,y+61,'Xếp theo số dòng CO thành công',18,'#607187')
        top=sorted(ranks[key].items(),key=lambda v:(-v[1],v[0]))[:5]
        if not top:text(x+22,y+130,'Chưa có dữ liệu thành công',24)
        for i,(label,value) in enumerate(top):
            if key in ('source','destination'):label=label+' - '+stores.get(label,{}).get('name','Chưa có tên kho')
            elif key in ('people','product'):label=names.get(label,label)
            yy=y+110+i*52;text(x+22,yy,str(i+1),23);text(x+65,yy,fit(label,570,22),22);text(x+665,yy,value,23,'#00845b')
    text(48,1660,'Dòng đã hủy/hết hạn: '+str(stats['cancelled'])+' • Xếp hạng bỏ qua dòng lỗi và chưa rõ kết quả.',21)
    text(48,1700,'Một CO có thể chứa nhiều dòng. Vùng/tỉnh tính theo kho xuất; không cộng cả hai phía.',20)
    text(48,1740,'Tạo lúc '+datetime.now(TZ).strftime('%H:%M %d/%m/%Y')+' • Lịch sử 7 ngày',20)
    directory.mkdir(parents=True,exist_ok=True);name=secrets.token_hex(24)+'.png';image.save(directory/name)
    return name

def cleanup(queue,directory):
    cutoff=period('7ngay')[0].timestamp()
    with queue.db() as db:
        ids=[r['id'] for r in db.execute("SELECT id FROM jobs WHERE state IN ('succeeded','failed','cancelled','expired') AND created<? AND updated<?",(cutoff,cutoff))]
        for jid in ids:
            row=db.execute('SELECT event FROM jobs WHERE id=?',(jid,)).fetchone()
            db.execute('INSERT INTO co_event_tombstones(digest) VALUES(?) ON CONFLICT(digest) DO NOTHING',(hashlib.sha256(row['event'].encode()).hexdigest(),))
            for table in ('preview_replies','co_note_rows','co_note_outbox'):db.execute('DELETE FROM '+table+' WHERE job_id=?',(jid,))
            db.execute('DELETE FROM jobs WHERE id=?',(jid,))
    if directory.exists():
        for p in directory.glob('*.png'):
            if p.stat().st_mtime<cutoff:p.unlink()

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
