import os
"""Read-only Apple revenue comparisons; targets are separate from sales/forecast.

Select the history's winning source for each day and industry. Never run a BOT,
read credentials, or modify its database. Missing coverage is not zero sales.
"""
import calendar
import hashlib
from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation, localcontext
import json
from pathlib import Path
import re
import shutil
import sqlite3
import tempfile
import threading
import unicodedata

from .business_analytics import DATABASE, INDUSTRIES, VN, DecimalSum, fingerprint
from .apple_groups import GROUPING_RULE, is_airpods, is_watch_band
from .revenue_models import MODEL_RULE, model_name
from .apple_weeks import APPLE_WEEK_RULE, CALENDAR_PATH, build_apple_weeks

ROOT = Path(os.getenv('TAOWORK_DATA_DIR', '/var/data/taowork'))
TARGETS = ROOT / 'settings/revenue-targets.json'
SNAPSHOT = ROOT / 'app/revenue-snapshot.json'
IPHONE_N_RULE = 'year-cohorts-2026-18pro-duo-2025-17-air-v1'
QUANTITY_RULE = 'source-quantity-net-v1'
GROUPS = [
    ('iphone', 'iPhone', [('iphone_n','iPhone N'),('iphone_old','iPhone N-')]),
    ('ipad','iPad',[('ipad_base','iPad'),('ipad_air','iPad Air'),('ipad_pro','iPad Pro'),('ipad_mini','iPad mini'),('ipad_other','iPad khác')]),
    ('mac','Mac',[('mac_neo','MacBook Neo'),('mac_air','MacBook Air'),('mac_pro','MacBook Pro'),('imac','iMac'),('mac_mini','Mac mini'),('mac_studio','Mac Studio'),('mac_other','Màn hình / Mac khác')]),
    ('watch','Watch',[('watch_se','Watch SE'),('watch_s','Watch S'),('watch_ultra','Watch Ultra'),('watch_other','Watch khác')]),
    ('airpods','AirPods',[('airpods_base','AirPods'),('airpods_pro','AirPods Pro'),('airpods_max','AirPods Max')]),
    ('accessories','Phụ kiện',[('pk_iphone','PK iPhone'),('case_iphone','Ốp lưng iPhone'),('pk_ipad','PK iPad'),('pk_mac','PK Mac'),('pk_watch_band','Dây đeo Apple Watch'),('pk_shared','PK dùng chung / khác')]),
]
DETAIL_GROUP = {k:g for g,_,details in GROUPS for k,_ in details}
DETAIL_NAMES = {k:n for _,_,details in GROUPS for k,n in details}
ALL_IDS = [g for g,_,_ in GROUPS]+list(DETAIL_GROUP)+['nonphone','total']
_cache = None
_lock = threading.Lock()


def normalized(value):
    value = unicodedata.normalize('NFKD', str(value or '').casefold()).replace('đ','d')
    return re.sub(r'\s+',' ', ''.join(c for c in value if not unicodedata.combining(c))).strip()


def classify(industry, name, *, year=2026):
    n = normalized(name)
    if industry in ('Wearable','Phụ kiện tiện ích') and is_watch_band(name):
        return 'pk_watch_band'
    if industry == 'Điện thoại':
        # N compares each year's designated generation, not the same models.
        # The default is also the stable 2026 display-catalog classification.
        if year not in (2025,2026):
            raise ValueError('No confirmed iPhone cohort for this year')
        pattern = r'\biphone (?:17e?|air)\b' if year==2025 else r'\biphone (?:18 pro(?: max)?|duo)\b'
        is_n = re.search(pattern, n)
        return 'iphone_n' if is_n else 'iphone_old'
    if industry == 'Tablet':
        for word,key in [('air','ipad_air'),('pro','ipad_pro'),('mini','ipad_mini')]:
            if re.search(r'\bipad '+word+r'\b', n): return key
        return 'ipad_base' if re.search(r'\bipad\b',n) else 'ipad_other'
    if industry in ('Laptop','IT'):
        for word,key in [('macbook neo','mac_neo'),('macbook air','mac_air'),('macbook pro','mac_pro'),('imac','imac'),('mac mini','mac_mini'),('mac studio','mac_studio')]:
            if word in n: return key
        return 'mac_other'
    if industry == 'Wearable':
        if re.search(r'\bwatch se\b', n): return 'watch_se'
        if re.search(r'\bwatch ultra\b', n): return 'watch_ultra'
        if re.search(r'\bwatch (?:series ?\d+|s\d+)\b', n): return 'watch_s'
        return 'watch_other'
    if industry == 'Phụ kiện tiện ích':
        if is_airpods(n):
            if re.search(r'\bairpods pro\b',n): return 'airpods_pro'
            if re.search(r'\bairpods max\b',n): return 'airpods_max'
            return 'airpods_base'
        if 'iphone' in n and ('op lung' in n or 'case' in n): return 'case_iphone'
        # Multi-device chargers/cables remain shared rather than guessed as iPhone.
        if 'ipad' in n or 'pencil' in n:
            return 'pk_shared' if 'iphone' in n else 'pk_ipad'
        if 'iphone' in n: return 'pk_iphone'
        if any(t in n for t in ['macbook','mac mini','imac','mac studio','magic mouse']): return 'pk_mac'
        return 'pk_shared'
    raise ValueError('Unknown industry')


def _query(path, *, local_copy=False):
    # A copied WAL database may create its own shm file only in a temporary dir.
    db = sqlite3.connect(str(path) if local_copy else path.as_uri()+'?mode=ro', uri=not local_copy, timeout=3)
    try:
        db.execute('PRAGMA query_only=ON'); db.execute('BEGIN')
        db.create_aggregate('exact_sum',1,DecimalSum)
        coverage = db.execute('SELECT day,industry,final,as_of FROM coverage').fetchall()
        rows = db.execute('''SELECT f.day,f.industry,f.chain,p.name,
            exact_sum(f.quantity),exact_sum(f.revenue_raw)
            FROM coverage c JOIN facts f ON f.source_id=c.source_id
              AND f.day=c.day AND f.industry=c.industry
            LEFT JOIN products p ON p.code=f.product
            WHERE c.final=1 AND f.status IN ('Mới','Mới giảm giá')
            GROUP BY f.day,f.industry,f.chain,f.product''').fetchall()
        return coverage, rows
    finally: db.close()


def read_history(path):
    try: return _query(path)
    except sqlite3.OperationalError:
        # Some Mac sandboxes cannot create SQLite's shared-memory sidecar beside
        # the BOT's DB. Copy a stable DB + WAL pair and read that private copy.
        paths = [path,Path(str(path)+'-wal')]
        for _ in range(2):
            before = fingerprint(paths)
            with tempfile.TemporaryDirectory(prefix='tao-revenue-read-') as tmp:
                dest=Path(tmp)/path.name
                for original in paths:
                    if original.exists(): shutil.copyfile(original,Path(tmp)/original.name)
                if before != fingerprint(paths): continue
                return _query(dest,local_copy=True)
        raise ValueError('History changed while preparing a consistent read')


def days(first,last):
    return [(first+timedelta(days=i)).isoformat() for i in range((last-first).days+1)]


def safe_date(year,month,day):
    return date(year,month,min(day,calendar.monthrange(year,month)[1]))


def growth(current, previous):
    if current is None or previous is None or previous <= 0: return None
    return float((current/previous-1)*100)


def build_payload(coverage, rows, targets, *, now=None):
    now=now or datetime.now(VN)
    by_day=defaultdict(set)
    for day,industry,final,stamp in coverage:
        if industry in INDUSTRIES and final and day<now.date().isoformat(): by_day[day].add(industry)
    complete={d for d,v in by_day.items() if v==INDUSTRIES}
    candidates=[d for d in complete if d.startswith('2026-')]
    if not candidates: raise ValueError('No completed 2026 revenue day')
    cutoff=date.fromisoformat(max(candidates))
    values=defaultdict(lambda:defaultdict(Decimal))
    quantities=defaultdict(lambda:defaultdict(Decimal))
    models={}
    model_cache={}
    unmapped=set()
    for day,industry,chain,name,qty,raw in rows:
        if day not in complete: continue
        if chain not in ('Thế Giới Di Động','Điện Máy Xanh','TopZone'): raise ValueError('Unknown chain')
        amount=Decimal(str(raw))
        if not amount.is_finite(): raise ValueError('Invalid revenue')
        quantity=Decimal(str(qty))
        if not quantity.is_finite() or quantity!=quantity.to_integral_value():
            raise ValueError('Invalid quantity')
        detail=classify(industry,name,year=int(day[:4]));group=DETAIL_GROUP[detail]
        # An actual model keeps one ID and full history even when its N/N-
        # membership differs between years. Only cohort aggregates use `detail`.
        catalog_detail=classify(industry,name)
        identity=(group,catalog_detail,name)
        if identity not in model_cache:
            label=model_name(group,catalog_detail,normalized(name),DETAIL_NAMES[catalog_detail])
            model_id='model_'+hashlib.sha256((group+'|'+catalog_detail+'|'+label).encode()).hexdigest()[:16]
            models[model_id]={'id':model_id,'name':label,'group':group,'detail':catalog_detail}
            model_cache[identity]=model_id
        model_id=model_cache[identity]
        if detail.endswith('_other') or name is None: unmapped.add((industry,name or 'Thiếu tên sản phẩm'))
        amount=amount*Decimal('1.08')/Decimal('1000000')
        ids=[detail,group,'total']+(['nonphone'] if group!='iphone' else [])
        for scope in ['system']+(['topzone'] if chain=='TopZone' else []):
            for key in ids:
                values[(scope,day)][key]+=amount
                quantities[(scope,day)][key]+=quantity
        values[('system',day)][model_id]+=amount
        quantities[('system',day)][model_id]+=quantity

    def total(scope,key,first,last,*,quantity=False):
        period=days(first,last)
        if not all(d in complete for d in period): return None
        source=quantities if quantity else values
        return sum((source[(scope,d)].get(key,Decimal(0)) for d in period),Decimal(0))

    def target_at(kind,period,scope,key):
        group_targets=targets.get(kind,{}).get(period,{}).get(scope,{})
        if key in ('total','nonphone'):
            keys=[g for g,_,_ in GROUPS if key=='total' or g!='iphone']
            if not all(k in group_targets for k in keys): return None
            value=sum((Decimal(str(group_targets[k])) for k in keys),Decimal(0))
        elif key in group_targets: value=Decimal(str(group_targets[key]))
        else: return None
        if not value.is_finite() or value<=0: raise ValueError('Invalid target')
        return value

    def compare(scope,key,ranges,*,quantity=False):
        result={}
        for metric,(a,b,c,d) in ranges.items():
            curr,prev=total(scope,key,a,b,quantity=quantity),total(scope,key,c,d,quantity=quantity)
            number=int if quantity else float
            result[metric]={'current':None if curr is None else number(curr),'previous':None if prev is None else number(prev),'growth':growth(curr,prev)}
        return result

    periods=[]
    for month in range(1,cutoff.month+1):
        month_key=f'2026-{month:02d}'
        end=cutoff if month==cutoff.month else date(2026,month,calendar.monthrange(2026,month)[1])
        start=date(2026,month,1)
        previous_last=start-timedelta(days=1)
        matched_day=min(end.day,previous_last.day)
        quarter_start=date(2026,((month-1)//3)*3+1,1)
        week_start=end-timedelta(days=end.weekday())
        ranges={
            'wow':(week_start,end,week_start-timedelta(days=7),end-timedelta(days=7)),
            'mom':(start,date(2026,month,matched_day),previous_last.replace(day=1),previous_last.replace(day=matched_day)),
            'yoy':(start,end,date(2025,month,1),safe_date(2025,month,end.day)),
            'qtd':(quarter_start,end,quarter_start.replace(year=2025),safe_date(2025,month,end.day)),
            'ytd':(date(2026,1,1),end,date(2025,1,1),safe_date(2025,month,end.day)),
        }
        item={'id':month_key,'end':end.isoformat(),'quarter':(month-1)//3+1,
              'forecast_days':end.day,'month_days':calendar.monthrange(2026,month)[1],
              'ranges':{k:[d.isoformat() for d in r] for k,r in ranges.items()},'scopes':{}}
        item['models']={key:{**compare('system',key,ranges),
                             'quantity':compare('system',key,ranges,quantity=True)} for key in models}
        for scope in ('system','topzone'):
            records={}
            for key in ALL_IDS:
                record=compare(scope,key,ranges)
                record['quantity']=compare(scope,key,ranges,quantity=True)
                actual_quantity=total(scope,key,start,end,quantity=True)
                record['quantity']['actual']=None if actual_quantity is None else int(actual_quantity)
                actual=total(scope,key,start,end)
                forecast=None if actual is None else actual/Decimal(end.day)*Decimal(item['month_days'])
                target=target_at('months',month_key,scope,key)
                annual=target_at('years','2026',scope,key)
                ytd=total(scope,key,date(2026,1,1),end)
                year_est=None if forecast is None or ytd is None or actual is None else ytd-actual+forecast
                record.update(actual=None if actual is None else float(actual),forecast=None if forecast is None else float(forecast),target=None if target is None else float(target),
                    attainment=None if actual is None or target is None else float(actual/target*100),
                    projected_attainment=None if forecast is None or target is None else float(forecast/target*100),
                    annual_target=None if annual is None else float(annual),ytd_month_end=None if year_est is None else float(year_est),
                    annual_attainment=None if annual is None or year_est is None else float(year_est/annual*100))
                records[key]=record
            item['scopes'][scope]=records
        periods.append(item)
    group_order={g:i for i,(g,_,_) in enumerate(GROUPS)}
    catalog=sorted(models.values(),key=lambda m:(group_order[m['group']],m['name'].casefold()))
    weekly=build_apple_weeks(cutoff,complete,ALL_IDS+list(models),total)
    return {'schema':1,'iphone_n_rule':IPHONE_N_RULE,'grouping_rule':GROUPING_RULE,'model_rule':MODEL_RULE,'models':catalog,'apple_weeks':weekly,'state':'ready','cutoff':cutoff.isoformat(),'generated_at':now.isoformat(),
            'source_as_of':max(r[3] for r in coverage),'source_kind':'database',
            'unit':'million_vnd','quantity_unit':'product','quantity_rule':QUANTITY_RULE,
            'filters':['Apple','Mới','Mới giảm giá'],'vat_multiplier':1.08,
            'groups':[{'id':g,'name':n,'details':[{'id':k,'name':v} for k,v in details]} for g,n,details in GROUPS],
            'periods':periods,'target_source':targets.get('source',''), 'target_note':targets.get('source_note',''),
            'unclassified_product_count':len(unmapped),
            'notes':['Hệ thống gồm TGDD, ĐMX và TopZone; TopZone là phần nằm trong Hệ thống.',
                     'AirPods gồm toàn bộ dòng AirPods, AirPods Pro và AirPods Max. Phụ kiện gồm dây đeo Apple Watch bán rời và các phụ kiện còn lại, không gồm AirPods. Đồng hồ kèm dây vẫn thuộc Watch.',
                     'iPhone N theo năm bán: 2026 gồm iPhone 18 Pro, 18 Pro Max, Duo; 2025 gồm toàn bộ dòng iPhone 17 và iPhone Air. N- là các iPhone còn lại của từng năm. Model riêng vẫn so cùng model qua các năm.',
                     'Phụ kiện dùng chung được giữ riêng, không tự gán cáp/sạc dùng nhiều thiết bị vào iPhone hoặc Mac.',
                     'Chỉ dùng ngày đã hoàn tất. Thiếu dữ liệu hiển thị —, không thay bằng 0.',
                     'Số lượng lấy từ cột quantity của nguồn bán hàng, đơn vị sản phẩm; giữ số âm/điều chỉnh theo nguồn, không nhân VAT và không suy ra từ doanh thu.',
                     'Tuần từ thứ Hai đến ngày chốt, so cùng số ngày tuần trước. Tháng so cùng ngày tháng trước; quý và năm so cùng kỳ năm trước, theo lịch dương.',
                     'Model gộp dung lượng, màu và kết nối; Mac/iPad giữ kích thước màn hình và chip nếu tên nguồn có ghi. Phụ kiện theo dòng; tên chưa nhận diện được giữ ở mục chưa tách model.',
                     'Target đã có VAT; không nhân VAT lần nữa. Tổng target là tổng sáu nhóm.']}


def load_revenue(database=DATABASE, target_path=TARGETS, *, now=None, snapshot=SNAPSHOT):
    global _cache
    today=(now or datetime.now(VN)).date().isoformat()
    key=(IPHONE_N_RULE,GROUPING_RULE,MODEL_RULE,QUANTITY_RULE,APPLE_WEEK_RULE,fingerprint([database,Path(str(database)+'-wal'),target_path,CALENDAR_PATH]),today)
    with _lock:
        if _cache and _cache[0]==key: return _cache[1]
        try:
            targets=json.loads(target_path.read_text())
            if targets.get('unit')!='million_vnd_including_vat': raise ValueError('Target unit mismatch')
            with localcontext() as ctx:
                ctx.prec=64
                coverage,rows=read_history(database)
                payload=build_payload(coverage,rows,targets,now=now)
        except (OSError,sqlite3.Error,ValueError,InvalidOperation):
            if snapshot is None: raise
            payload=json.loads(snapshot.read_text())
            if (payload.get('schema')!=1 or payload.get('iphone_n_rule')!=IPHONE_N_RULE or payload.get('grouping_rule')!=GROUPING_RULE
                    or payload.get('model_rule')!=MODEL_RULE or payload.get('quantity_rule')!=QUANTITY_RULE
                    or payload.get('apple_weeks',{}).get('rule')!=APPLE_WEEK_RULE):
                raise ValueError('Invalid or outdated revenue model snapshot')
            payload['source_kind']='snapshot'
        _cache=(key,payload)
        return payload
