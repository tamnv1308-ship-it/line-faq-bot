import os
"""Read-only business history adapter. Never import or execute a BOT.

Use the selected source for each day/industry in coverage, so refreshed exports
replace old partitions rather than doubling revenue. Fall back to the audited
daily export when the live SQLite history cannot be read.
"""
from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation, localcontext
from pathlib import Path
from zoneinfo import ZoneInfo
import json
import sqlite3
import threading
import shutil
import tempfile
from .apple_groups import GROUPING_RULE, product_group

REPORT = Path(os.getenv('TAOWORK_DATA_DIR', '/var/data/taowork')) / 'report'
DATABASE = REPORT / '.private/sales-history.sqlite3'
EXPORT = REPORT / 'outputs/history-2025-2026/daily_sales.json'
VN = ZoneInfo('Asia/Ho_Chi_Minh')
GROUPS = [
    {'id':'iphone','name':'iPhone','industries':['Điện thoại'],'color':'#5965e8'},
    {'id':'ipad','name':'iPad','industries':['Tablet'],'color':'#259b8b'},
    {'id':'mac','name':'Mac','industries':['Laptop','IT'],'color':'#3988cf'},
    {'id':'watch','name':'Watch','industries':['Wearable'],'color':'#d18b36'},
    {'id':'airpods','name':'AirPods','industries':['Phụ kiện tiện ích'],'color':'#5b9cba'},
    {'id':'accessories','name':'Phụ kiện','industries':['Phụ kiện tiện ích','Wearable'],'color':'#ad6f98'},
]
INDUSTRIES = {s for g in GROUPS for s in g['industries']}
_cache = None
_mutex = threading.Lock()

def fingerprint(paths):
    result = []
    for path in paths:
        try:
            st = path.stat()
            # SQLite readers may recreate/touch an empty WAL without changing
            # any data. Treat it like an absent WAL, otherwise each read drops
            # both report caches and repeats the full history aggregation.
            # Real WAL frames and checkpoints still change this fingerprint.
            if str(path).endswith('-wal') and st.st_size == 0:
                result.append((str(path), None, None))
            else:
                result.append((str(path), st.st_size, st.st_mtime_ns))
        except OSError:
            result.append((str(path), None, None))
    return tuple(result)

class DecimalSum:
    def __init__(self): self.value = Decimal(0)
    def step(self, value):
        if value is None: return
        n = Decimal(str(value))
        if not n.is_finite(): raise ValueError('Invalid history amount')
        self.value += n
    def finalize(self): return str(self.value)

def _query_database(path, *, local_copy=False):
    db = sqlite3.connect(str(path) if local_copy else path.as_uri()+'?mode=ro', uri=not local_copy, timeout=2)
    try:
        db.execute('PRAGMA query_only=ON')
        db.create_aggregate('exact_sum', 1, DecimalSum)
        db.create_function('apple_group', 2, product_group)
        # A transaction keeps the partition selection and amounts consistent.
        db.execute('BEGIN')
        rows = db.execute('''SELECT c.day,c.industry,c.final,c.as_of,apple_group(c.industry,p.name),
            exact_sum(f.quantity),exact_sum(f.revenue_raw)
            FROM coverage c LEFT JOIN facts f
              ON f.source_id=c.source_id AND f.day=c.day AND f.industry=c.industry
              AND f.status IN ('Mới','Mới giảm giá')
            LEFT JOIN products p ON p.code=f.product
            WHERE c.day>='2025-01-01' AND c.day<'2027-01-01'
            GROUP BY c.day,c.industry,c.final,c.as_of,apple_group(c.industry,p.name)
            ORDER BY c.day,c.industry''').fetchall()
        partitions = {}
        for d,i,final,stamp,g,q,rev in rows:
            item=partitions.setdefault((d,i),{'day':d,'industry':i,'final':bool(final),'as_of':stamp,'groups':{}})
            item['groups'][g]={'quantity':q or '0','revenue_raw':rev or '0'}
        for item in partitions.values():
            for metric in ('quantity','revenue_raw'):
                item[metric]=str(sum((Decimal(g[metric]) for g in item['groups'].values()),Decimal(0)))
        return list(partitions.values())
    finally:
        db.close()


def read_database(path):
    try:
        return _query_database(path)
    except sqlite3.OperationalError:
        paths=[path,Path(str(path)+'-wal')]
        for _ in range(2):
            before=fingerprint(paths)
            with tempfile.TemporaryDirectory(prefix='tao-overview-read-') as tmp:
                copied=Path(tmp)/path.name
                for original in paths:
                    if original.exists():shutil.copyfile(original,Path(tmp)/original.name)
                if before!=fingerprint(paths):continue
                return _query_database(copied,local_copy=True)
        raise ValueError('History changed during read')

def build_payload(rows, *, now=None, source_kind='export'):
    now = now or datetime.now(VN)
    partitions = {}
    for r in rows:
        d = date.fromisoformat(r['day'])
        if d.year not in (2025,2026) or d > now.date(): continue
        industry = r['industry']
        if industry not in INDUSTRIES: raise ValueError('Unknown sales industry')
        key = (r['day'],industry)
        if key in partitions: raise ValueError('Duplicate daily partition')
        q,rev = Decimal(str(r['quantity'])),Decimal(str(r['revenue_raw']))
        if not q.is_finite() or not rev.is_finite(): raise ValueError('Invalid history amount')
        if q != q.to_integral_value(): raise ValueError('Invalid quantity')
        if type(r['final']) is not bool: raise ValueError('Invalid coverage marker')
        stamp = datetime.fromisoformat(r['as_of'])
        if stamp.tzinfo is None: raise ValueError('Missing history timezone')
        allowed={g['id'] for g in GROUPS if industry in g['industries']}
        if len(allowed)==1:
            amounts={next(iter(allowed)):(q,rev)}
        else:
            # Industry-only exports cannot separate AirPods or Watch straps.
            split=r.get('groups')
            if not isinstance(split,dict) or not split or not set(split)<=allowed:
                raise ValueError('Product-level group split is missing')
            amounts={g:(Decimal(str(v['quantity'])),Decimal(str(v['revenue_raw']))) for g,v in split.items()}
            if any(not x.is_finite() for pair in amounts.values() for x in pair):raise ValueError('Invalid group amount')
            if any(v[0]!=v[0].to_integral_value() for v in amounts.values()):raise ValueError('Invalid group quantity')
            if sum((v[0] for v in amounts.values()),Decimal(0))!=q or sum((v[1] for v in amounts.values()),Decimal(0))!=rev:
                raise ValueError('Product-level group split does not reconcile')
        partitions[key] = (q,rev,r['final'],r['as_of'],amounts)
    if not partitions: raise ValueError('No comparable history')
    complete = {}
    for day in {key[0] for key in partitions}:
        complete[day] = all((day,i) in partitions and partitions[(day,i)][2]
                            for i in INDUSTRIES)
    paired = []
    for day in sorted(complete):
        if day.startswith('2026-') and day < now.date().isoformat() and complete[day] and complete.get('2025'+day[4:],False):
            paired.append(day)
    if not paired: raise ValueError('No complete matching periods')
    cutoff = paired[-1]
    expected = (date.fromisoformat(cutoff)-date(2026,1,1)).days+1
    valid = set(paired)
    gaps = [(date(2026,1,1)+timedelta(days=i)).isoformat()
            for i in range(expected)
            if (date(2026,1,1)+timedelta(days=i)).isoformat() not in valid]
    daily = []
    for day in paired:
        values = []
        for group in GROUPS:
            pair = []
            for year in ('2025','2026'):
                cells = [partitions[(year+day[4:],i)][4].get(group['id'],(Decimal(0),Decimal(0))) for i in group['industries']]
                qty = sum((x[0] for x in cells),Decimal(0))
                revenue = sum((x[1] for x in cells),Decimal(0))*Decimal('1.08')
                pair.extend([int(qty),float(revenue)])
            values.append(pair)
        # Each group: 2025 quantity/revenue, then 2026 quantity/revenue.
        daily.append([day,values])
    return {'schema':1,'grouping_rule':GROUPING_RULE,'state':'ready','years':[2025,2026],'cutoff':cutoff,
            'groups':GROUPS,'daily':daily,'missing_days':gaps,
            'expected_days':expected,'paired_days':len(paired),
            'source_as_of':max(v[3] for v in partitions.values()),
            'source_kind':source_kind,'generated_at':now.isoformat(),
            'latest_source_day':max(complete),
            'revenue_basis':'revenue_raw_x_1.08',
            'filters':['Apple','Mới','Mới giảm giá'],
            'notes':['Mac gồm Laptop và IT. AirPods là nhóm riêng; Phụ kiện gồm dây đeo Apple Watch, không gồm AirPods.',
                     'Doanh thu theo quy ước BOT: số gốc × 1,08.',
                     'Chỉ so sánh những ngày đủ dữ liệu của cả hai năm.']}

def load_business(database=DATABASE, exported=EXPORT, *, now=None):
    global _cache
    key = (GROUPING_RULE,fingerprint([database,Path(str(database)+'-wal'),exported]))
    today = (now or datetime.now(VN)).date().isoformat()
    with _mutex:
        if _cache and _cache[0] == (key,today): return _cache[1]
        with localcontext() as ctx:
            ctx.prec = 64
            kind = 'database'
            try:
                rows = read_database(database)
            except (OSError,sqlite3.Error,ValueError,InvalidOperation):
                kind = 'export'
                before = fingerprint([exported])
                rows = json.loads(exported.read_text())
                if before != fingerprint([exported]):
                    raise ValueError('History export changed while reading')
            try:
                result = build_payload(rows,now=now,source_kind=kind)
            except ValueError:
                if kind!='export':raise
                # Keep the checked six-group snapshot when an older industry-only
                # export cannot provide a valid AirPods split. Never invent zeros.
                bundle=(Path(__file__).resolve().parents[1]/'app/app.js').read_text()
                result,_=json.JSONDecoder().raw_decode(bundle.split('window.TAO_BUSINESS_DATA = ',1)[1])
                if result.get('grouping_rule')!=GROUPING_RULE:raise ValueError('No compatible overview snapshot')
                result['source_kind']='snapshot'
        _cache = ((key,today),result)
        return result

if __name__ == '__main__':
    print(json.dumps(load_business(),ensure_ascii=False,separators=(',',':')))
