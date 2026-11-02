import os
"""Versioned daily sales history. Daily totals never masquerade as intraday snapshots."""
import argparse
import fcntl
import hashlib
import json
import sqlite3
from datetime import date, datetime, timedelta
from decimal import Decimal, getcontext, InvalidOperation
from pathlib import Path
from zoneinfo import ZoneInfo
from openpyxl import load_workbook
from openpyxl.utils.datetime import from_excel, CALENDAR_WINDOWS_1900

VN=ZoneInfo('Asia/Ho_Chi_Minh')
INDUSTRIES=('Điện thoại','Tablet','Laptop','IT','Wearable','Phụ kiện tiện ích')
GROUP_IDS={'Điện thoại':'13','Phụ kiện tiện ích':'16','Laptop':'22','Wearable':'23','Tablet':'244','IT':'364'}
STATUSES={'Mới':'Mới','Mới (Giảm giá)':'Mới giảm giá','Mới giảm giá':'Mới giảm giá'}
UPLOAD_HEADERS=['Mã sản phẩm','Tên sản phẩm','Tên viết tắt','Tình trạng SP','Hãng sản xuất','Ngành hàng','Kênh','Mã siêu thị','Tên siêu thị','Chuỗi','Tỉnh thành','Vùng RSM','Ngày xuất','Tháng xuất','Số lượng','Doanh thu','Lãi gộp']
LIVE_HEADERS=['MÃ SẢN PHẨM','TÊN SẢN PHẨM','LÀ HTX BÁN HÀNG?','TÊN TÌNH TRẠNG SP','HÃNG SẢN XUẤT','NGÀNH HÀNG','KÊNH BÁN HÀNG','MÃ SIÊU THỊ','SIÊU THỊ','TÊN THƯƠNG HIỆU','TỈNH/THÀNH','KHU VỰC RSM','NGÀY','THÁNG','SỐ LƯỢNG (SUM)','DOANH THU (SUM)','LÃI GỘP (SUM)']
SCHEMA='''
CREATE TABLE IF NOT EXISTS sources(id INTEGER PRIMARY KEY,sha TEXT UNIQUE NOT NULL,path TEXT NOT NULL,mode TEXT NOT NULL,as_of TEXT NOT NULL,stats TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS rejected_rows(source_id INTEGER NOT NULL,sheet TEXT NOT NULL,row_number INTEGER NOT NULL,day TEXT,industry TEXT,raw TEXT NOT NULL,reason TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS products(code TEXT PRIMARY KEY,name TEXT NOT NULL,abbreviation TEXT);
CREATE TABLE IF NOT EXISTS stores(code TEXT PRIMARY KEY,name TEXT,province TEXT);
CREATE TABLE IF NOT EXISTS facts(source_id INTEGER NOT NULL,day TEXT NOT NULL,industry TEXT NOT NULL,product TEXT NOT NULL,status TEXT NOT NULL,channel TEXT NOT NULL,store TEXT NOT NULL,chain TEXT NOT NULL,region TEXT NOT NULL,quantity TEXT NOT NULL,revenue_raw TEXT NOT NULL,margin_raw TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS facts_partition ON facts(source_id,day,industry);
CREATE TABLE IF NOT EXISTS coverage(day TEXT NOT NULL,industry TEXT NOT NULL,source_id INTEGER NOT NULL,mode TEXT NOT NULL,as_of TEXT NOT NULL,final INTEGER NOT NULL,PRIMARY KEY(day,industry));
CREATE TABLE IF NOT EXISTS maintenance(id INTEGER PRIMARY KEY CHECK(id=1),last_attempt TEXT,last_error TEXT);
'''

def connect(path):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    db=sqlite3.connect(path,timeout=10)
    db.execute('PRAGMA journal_mode=WAL');db.executescript(SCHEMA)
    return db


def source_date(v,epoch=CALENDAR_WINDOWS_1900):
    if isinstance(v,datetime):return v.date()
    if isinstance(v,date):return v
    text=str(v).strip()
    if isinstance(v,(int,float,Decimal)) or (text.isdigit() and len(text)==5):
        result=from_excel(float(v),epoch)
        if not isinstance(result,datetime):raise ValueError('Ngày Excel không hợp lệ')
        return result.date()
    return date.fromisoformat(text.replace('/','-'))


def decimal(v):
    n=Decimal(str(v))
    if not n.is_finite():raise ValueError('Số liệu không hữu hạn')
    return n


def date_range(first,last):
    while first<=last:
        yield first
        first+=timedelta(days=1)


def import_file(db_path,path,*,mode='provided_file',expected_day=None,expected_industries=None,as_of=None,expected_rows=None,sheet_names=None,quarantine_invalid=False):
    """Upload files cover their full observed date span, including zero-sale days.
    A fresh MWG export takes precedence over an uploaded partition. Reimports
    of the same bytes are no-ops; overlapping sources are selected, never added.
    """
    getcontext().prec=max(getcontext().prec,64)
    path=Path(path)
    with path.open('rb') as handle:
        digest=hashlib.file_digest(handle,'sha256').hexdigest()
    stamp=as_of or datetime.now(VN)
    identity_parts=[digest,mode,expected_day.isoformat() if expected_day else None,sorted(expected_industries or [])]
    if sheet_names:identity_parts.append(sorted(sheet_names))
    identity=hashlib.sha256(json.dumps(identity_parts,ensure_ascii=False).encode()).hexdigest()
    with connect(db_path) as db:
        old=db.execute("SELECT stats,id,sha FROM sources WHERE sha=? OR (sha=? AND mode='provided_file' AND ?='provided_file')",(identity,digest,mode)).fetchone()
        if old:
            if old[2]!=identity:db.execute('UPDATE sources SET sha=? WHERE id=?',(identity,old[1]))
            cached=json.loads(old[0])
            if expected_rows is not None and cached['rows']!=expected_rows:
                raise RuntimeError('Số dòng tải bù không khớp tác vụ xuất')
            if mode=='mwg_api':
                db.execute('UPDATE coverage SET as_of=?,final=? WHERE source_id=? AND as_of<=?',(stamp.isoformat(),int(expected_day<stamp.date()),old[1],stamp.isoformat()))
            return cached
        stats={'sheets':[],'file':path.name,'sha256':digest,'rows':0,'accepted_rows':0,'statuses':{},'excluded_statuses':{},'excluded_brands':{},'total_quantity':'0','revenue_raw':'0','revenue_vnd':'0','date_from':None,'date_to':None,'industries':[],'mode':mode}
        cursor=db.execute('INSERT INTO sources(sha,path,mode,as_of,stats) VALUES (?,?,?,?,?)',(identity,str(path.resolve()),mode,stamp.isoformat(),'{}'))
        source_id=cursor.lastrowid
        rejected=set();stats['invalid_rows']=0
        found=set();dates=[];quantity=Decimal(0);revenue=Decimal(0);batch=[]
        products={};stores={}
        wb=load_workbook(path,read_only=True,data_only=True)
        try:
            readable=0
            if sheet_names and not set(sheet_names)<=set(wb.sheetnames):
                raise RuntimeError('Thiếu sheet lịch sử đã chỉ định')
            for sheet in wb:
                if sheet_names and sheet.title not in sheet_names:continue
                rows=sheet.iter_rows(values_only=True)
                header=next(rows,())
                if not header or all(v is None for v in header):continue
                if list(header[:17]) not in [UPLOAD_HEADERS,LIVE_HEADERS]:
                    raise RuntimeError('Cấu trúc sheet lịch sử chưa được nhận diện: '+sheet.title)
                readable+=1
                stats['sheets'].append(sheet.title)
                upload=list(header[:17])==UPLOAD_HEADERS
                for row_number,r in enumerate(rows,2):
                    if not r or r[0] is None:continue
                    if len(r)<17:raise RuntimeError('Dòng lịch sử thiếu cột')
                    stats['rows']+=1
                    day=source_date(r[12],getattr(wb,'epoch',CALENDAR_WINDOWS_1900))
                    if day.year not in (2025,2026) or day>stamp.date():raise RuntimeError('Dữ liệu nằm ngoài năm 2025–2026 hoặc ở tương lai')
                    if expected_day and day!=expected_day:raise RuntimeError('Ngày tải bù không khớp ngày yêu cầu')
                    industry=str(r[5]).strip()
                    if industry not in INDUSTRIES:raise RuntimeError('Ngành hàng lịch sử chưa được nhận diện: '+industry)
                    if expected_industries and industry not in expected_industries:raise RuntimeError('Ngành hàng nằm ngoài phạm vi file')
                    found.add(industry);dates.append(day)
                    raw_status=str(r[3]).strip()
                    stats['statuses'][raw_status]=stats['statuses'].get(raw_status,0)+1
                    if str(r[4]).strip()!='Apple':
                        brand=str(r[4]);stats['excluded_brands'][brand]=stats['excluded_brands'].get(brand,0)+1;continue
                    if raw_status not in STATUSES:
                        stats['excluded_statuses'][raw_status]=stats['excluded_statuses'].get(raw_status,0)+1;continue
                    try:
                        q,rev,margin=map(decimal,(r[14],r[15],r[16]))
                        if q!=q.to_integral_value():raise ValueError('Số lượng lịch sử không nguyên')
                    except (InvalidOperation,ValueError):
                        if not quarantine_invalid:raise RuntimeError('Số liệu lịch sử không hợp lệ tại '+sheet.title+' dòng '+str(row_number)) from None
                        db.execute('INSERT INTO rejected_rows VALUES (?,?,?,?,?,?,?)',(source_id,sheet.title,row_number,day.isoformat(),industry,json.dumps(list(r[:17]),ensure_ascii=False,default=str),'Số lượng/doanh thu/lãi gộp không hợp lệ'))
                        rejected.add((day,industry));stats['invalid_rows']+=1;continue
                    code=str(r[0]).strip().removesuffix('.0').zfill(13)
                    if len(code)!=13 or not code.isdigit():raise RuntimeError('Mã sản phẩm lịch sử không hợp lệ')
                    channel=str(r[6]).strip();chain=str(r[9]).strip()
                    if channel not in ['Kênh Offline','Kênh Online'] or chain not in ['Thế Giới Di Động','Điện Máy Xanh','TopZone']:
                        raise RuntimeError('Kênh hoặc chuỗi lịch sử chưa được nhận diện')
                    store=str(r[7]).strip().removesuffix('.0')
                    products[code]=(code,str(r[1]),str(r[2]) if upload else '')
                    stores[store]=(store,str(r[8]),str(r[10]))
                    batch.append((source_id,day.isoformat(),industry,code,STATUSES[raw_status],channel,store,chain,str(r[11]),str(q),str(rev),str(margin)))
                    quantity+=q;revenue+=rev;stats['accepted_rows']+=1
                    if len(batch)>=5000:
                        db.executemany('INSERT INTO facts VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',batch);batch=[]
            if not readable:raise RuntimeError('Không có sheet dữ liệu lịch sử')
            if batch:db.executemany('INSERT INTO facts VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',batch)
        finally:wb.close()
        if expected_rows is not None and stats['rows']!=expected_rows:
            raise RuntimeError('Số dòng tải bù không khớp tác vụ xuất')
        if not dates and expected_day is None:raise RuntimeError('File lịch sử trống, chưa xác định được phạm vi ngày')
        first=expected_day or min(dates);last=expected_day or max(dates)
        scopes=set(expected_industries or found)
        if mode=='mwg_api' and stats['rows']==0:
            for industry in scopes:
                previous=db.execute('SELECT source_id FROM coverage WHERE day=? AND industry=?',(first.isoformat(),industry)).fetchone()
                if previous and (db.execute('SELECT 1 FROM facts WHERE source_id=? AND day=? AND industry=? LIMIT 1',(previous[0],first.isoformat(),industry)).fetchone() or db.execute('SELECT 1 FROM rejected_rows WHERE source_id=? AND day=? AND industry=? LIMIT 1',(previous[0],first.isoformat(),industry)).fetchone()):
                    raise RuntimeError('MWG trả file trống cho ngày đã có dữ liệu; giữ lịch sử để đối chiếu')
        db.executemany('INSERT INTO products VALUES (?,?,?) ON CONFLICT(code) DO UPDATE SET name=excluded.name,abbreviation=CASE WHEN excluded.abbreviation!=\'\' THEN excluded.abbreviation ELSE products.abbreviation END',products.values())
        db.executemany('INSERT INTO stores VALUES (?,?,?) ON CONFLICT(code) DO UPDATE SET name=excluded.name,province=excluded.province',stores.values())
        for day in date_range(first,last):
            for industry in scopes:
                db.execute('''INSERT INTO coverage VALUES (?,?,?,?,?,?) ON CONFLICT(day,industry) DO UPDATE SET source_id=excluded.source_id,mode=excluded.mode,as_of=excluded.as_of,final=excluded.final
                    WHERE (excluded.mode='mwg_api' AND (coverage.mode!='mwg_api' OR excluded.as_of>=coverage.as_of)) OR (excluded.mode='provided_file' AND coverage.mode!='mwg_api')''',
                    (day.isoformat(),industry,source_id,mode,stamp.isoformat(),int(day<stamp.date() and (day,industry) not in rejected)))
        stats['repair_partitions']=[(day.isoformat(),industry) for day,industry in sorted(rejected)]
        stats.update(date_from=first.isoformat(),date_to=last.isoformat(),industries=sorted(scopes),total_quantity=str(quantity),revenue_raw=str(revenue),revenue_vnd=str(revenue*Decimal('1.08')))
        db.execute('UPDATE sources SET stats=? WHERE id=?',(json.dumps(stats,ensure_ascii=False),source_id))
    return stats


def missing_days(db,now):
    start=date(2026,1,1);end=min(now.date()-timedelta(days=1),date(2026,12,31))
    complete={day for day,n in db.execute('SELECT day,COUNT(*) FROM coverage WHERE final=1 GROUP BY day') if n==len(INDUSTRIES)}
    return [d for d in date_range(start,end) if d.isoformat() not in complete]


def status(db_path,now=None):
    now=now or datetime.now(VN)
    with connect(db_path) as db:
        missing=missing_days(db,now)
        sources=[json.loads(r[0]) for r in db.execute('SELECT stats FROM sources ORDER BY id')]
        return {'year':2026,'filters':['Apple','Mới','Mới giảm giá'],'missing_days':[x.isoformat() for x in missing],
            'coverage':list(db.execute('SELECT industry,MIN(day),MAX(day),COUNT(*) FROM coverage GROUP BY industry')),
            'sources':sources,'repair_partitions':list(db.execute("SELECT day,industry FROM coverage WHERE final=0 AND day<? AND day LIKE '2025-%' ORDER BY day,industry",(now.date().isoformat(),))),
            'last_maintenance':db.execute('SELECT last_attempt,last_error FROM maintenance WHERE id=1').fetchone()}


def daily_series(db_path):
    """Exact money, selected partitions only. Return raw and VAT-inclusive values."""
    getcontext().prec=max(getcontext().prec,64)
    values={}
    with connect(db_path) as db:
        for day,industry,q,rev,margin in db.execute("""SELECT f.day,f.industry,f.quantity,f.revenue_raw,f.margin_raw
            FROM coverage c JOIN facts f ON f.source_id=c.source_id AND f.day=c.day AND f.industry=c.industry"""):
            key=(day,industry)
            metrics=values.setdefault(key,[Decimal(0),Decimal(0),Decimal(0)])
            for i,value in enumerate((q,rev,margin)):metrics[i]+=Decimal(value)
        result=[]
        for day,industry,final,mode,as_of in db.execute('SELECT day,industry,final,mode,as_of FROM coverage ORDER BY day,industry'):
            q,rev,margin=values.get((day,industry),[Decimal(0)]*3)
            result.append({'day':day,'industry':industry,'quantity':str(q),'revenue_raw':str(rev),
                'revenue_vnd':str(rev*Decimal('1.08')),'margin_raw':str(margin),'final':bool(final),'source_mode':mode,'as_of':as_of})
    return result


def update_once(root,now=None,force=False):
    """One bounded export per idle tick. Finalize past days; refresh today every 2h."""
    root=Path(root);private=root/'.private';now=now or datetime.now(VN)
    if now.year<2026:return {'state':'outside_year'}
    with (private/'sales-history.lock').open('a') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:return {'state':'busy'}
        db_path=private/'sales-history.sqlite3'
        with connect(db_path) as db:
            previous=db.execute('SELECT last_attempt,last_error FROM maintenance WHERE id=1').fetchone()
            if not force and previous and (now-datetime.fromisoformat(previous[0])).total_seconds()<(600 if previous[1] else 60):return {'state':'cooldown'}
            missing=missing_days(db,now)
            repairs=list(db.execute("SELECT day,industry FROM coverage WHERE final=0 AND day<? AND day LIKE '2025-%' ORDER BY day,industry",(now.date().isoformat(),)))
            target=missing[0] if missing else date.fromisoformat(repairs[0][0]) if repairs else now.date()
            if now.year>2026 and not missing and not repairs:return {'state':'complete'}
            covered={r[0] for r in db.execute('SELECT industry FROM coverage WHERE day=? AND final=1',(target.isoformat(),))}
            scopes=([industry for industry in INDUSTRIES if industry not in covered] if missing else [industry for day,industry in repairs if day==target.isoformat()] if repairs else list(INDUSTRIES))
            if not missing and not repairs:
                recent=db.execute('SELECT MIN(as_of),COUNT(*) FROM coverage WHERE day=?',(target.isoformat(),)).fetchone()
                if recent[1]==len(INDUSTRIES) and (now-datetime.fromisoformat(recent[0])).total_seconds()<7200:return {'state':'current'}
            db.execute('INSERT INTO maintenance VALUES (1,?,NULL) ON CONFLICT(id) DO UPDATE SET last_attempt=excluded.last_attempt,last_error=NULL',(now.isoformat(),))
        from mwg_api import export_file
        import time
        run=root/'runs/history-backfill'/target.isoformat()/str(time.time_ns())
        source=run/'BI_MOI_NGAY.xlsx'
        try:
            export_file(target,source,inventory_status_ids=None,main_group_ids=','.join(GROUP_IDS[i] for i in scopes))
            metadata=json.loads(source.with_suffix('.export.json').read_text())
            exported=datetime.fromisoformat(metadata['exported_at_vn']).astimezone(VN)
            result=import_file(db_path,source,mode='mwg_api',expected_day=target,expected_industries=scopes,as_of=exported,expected_rows=metadata.get('source_rows'))
            return {'state':'updated','day':target.isoformat(),'rows':result['accepted_rows']}
        except Exception as exc:
            error=str(exc) if isinstance(exc,RuntimeError) else type(exc).__name__
            with connect(db_path) as db:db.execute('UPDATE maintenance SET last_error=? WHERE id=1',(error,))
            raise RuntimeError('Chưa cập nhật được lịch sử: '+error) from None


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['import','status','update-once'])
    parser.add_argument('--file');parser.add_argument('--sheet',action='append');parser.add_argument('--quarantine-invalid',action='store_true');parser.add_argument('--root',type=Path,default=Path(__file__).resolve().parents[1]);args=parser.parse_args()
    db=args.root/'.private/sales-history.sqlite3'
    if args.action=='import':result=import_file(db,args.file,sheet_names=args.sheet,quarantine_invalid=args.quarantine_invalid)
    elif args.action=='status':result=status(db)
    else:result=update_once(args.root)
    print(json.dumps(result,ensure_ascii=False),flush=True)
