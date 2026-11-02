import os
"""Comparison header for the existing first report photo.

Use the existing daily report's Mới scope; historical raw money gets VAT once.
Daily growth uses same-clock snapshots; longer periods use completed days.
"""
import calendar
import hashlib
import json
import sqlite3
from datetime import date, timedelta
from decimal import Decimal, getcontext, ROUND_HALF_UP
from pathlib import Path

from report_comparison import CATEGORIES, numeric_data, parse_time, validate_data, percent

D = Decimal
ZERO = lambda: [[D(0), D(0)] for _ in CATEGORIES]


def category(industry, name):
    lower = name.casefold()
    if lower.startswith(('dây', 'day ')) or 'watch band' in lower:
        return 5
    if 'airpods' in lower:
        return 4
    return {'Điện thoại': 0, 'Tablet': 1, 'Laptop': 2, 'IT': 2, 'Wearable': 3}.get(industry, 5)


def from_snapshot(data):
    validate_data(data)
    result = ZERO()
    for name, item in data['models'].items():
        group = item['category']
        if name.casefold().startswith('dây') or 'watch band' in name.casefold():
            group = 5
        for i in range(2):
            result[group][i] += D(item['values'][i])
    return result


def history_days(root, today):
    """Cache exact per-day sums against the full authoritative coverage map."""
    getcontext().prec = max(64, getcontext().prec)
    path = root / '.private/sales-history.sqlite3'
    with sqlite3.connect('file:' + str(path) + '?mode=ro', uri=True, timeout=10) as db:
        db.execute('BEGIN')
        coverage = db.execute('SELECT day,industry,source_id,final,as_of FROM coverage WHERE day<? ORDER BY day,industry', (today.isoformat(),)).fetchall()
        digest = hashlib.sha256(json.dumps(coverage, ensure_ascii=False).encode()).hexdigest()
        cache = root / '.private/period-cache.json'
        if cache.exists():
            cached = json.loads(cache.read_text())
            if cached.get('schema') == 1 and cached.get('digest') == digest:
                return {date.fromisoformat(k): [[D(x) for x in v] for v in rows] for k, rows in cached['days'].items()}
        covered = {}
        for day, industry, source_id, final, as_of in coverage:
            if final:
                covered.setdefault(day, set()).add(industry)
        complete = {day for day, industries in covered.items() if len(industries) == 6}
        sums = {day: ZERO() for day in complete}
        query = '''SELECT f.day,f.industry,p.name,f.quantity,f.revenue_raw
                   FROM coverage c JOIN facts f
                   ON f.source_id=c.source_id AND f.day=c.day AND f.industry=c.industry
                   JOIN products p ON p.code=f.product
                   WHERE c.day<? AND c.final=1 AND f.status='Mới' '''
        for day, industry, name, qty, revenue in db.execute(query, (today.isoformat(),)):
            if day not in sums:
                continue
            row = sums[day][category(industry, name)]
            row[0] += D(qty)
            row[1] += D(revenue) * D('1.08')
    from report_comparison import save_json
    save_json(cache, {'schema': 1, 'digest': digest, 'days': {k: [[str(v) for v in row] for row in rows] for k, rows in sums.items()}})
    return {date.fromisoformat(k): rows for k, rows in sums.items()}


def previous_month(day):
    first = day.replace(day=1)
    previous = first - timedelta(days=1)
    return previous.replace(day=min(day.day, previous.day))


def periods(day):
    old_month = previous_month(day)
    old_year = day.replace(year=day.year-1, day=min(day.day, calendar.monthrange(day.year-1, day.month)[1]))
    quarter = day.replace(month=((day.month-1)//3)*3+1, day=1)
    previous_quarter_last = quarter-timedelta(days=1)
    previous_quarter = previous_quarter_last.replace(month=((previous_quarter_last.month-1)//3)*3+1, day=1)
    old_quarter_end = min(previous_quarter+(day-quarter), previous_quarter_last)
    return [
        ('HÔM NAY', day, day-timedelta(days=1), day-timedelta(days=1)),
        ('THÁNG NÀY', day.replace(day=1), old_month.replace(day=1), old_month),
        ('QUÝ NÀY', quarter, previous_quarter, old_quarter_end),
        ('LŨY KẾ NĂM', day.replace(month=1, day=1), old_year.replace(month=1, day=1), old_year),
    ]


def boundary(root, day, slot, exported):
    path = root / '.private/sales-snapshots' / day.isoformat() / (slot.strftime('%H%M')+'.json')
    try:
        saved = json.loads(path.read_text())
        saved_slot = parse_time(saved['slot'])
        saved_export = parse_time(saved['exported_at'])
        if (saved.get('schema') != 1 or saved.get('revenue_vat_applied') is not True
                or saved.get('report_date') != day.isoformat() or saved_slot.date() != day
                or saved_slot.strftime('%H:%M:%S') != slot.strftime('%H:%M:%S')
                or not 0 <= (saved_export-saved_slot).total_seconds() < 600
                or abs((saved_export-saved_slot).total_seconds()-(exported-slot).total_seconds()) > 180):
            return None
        return from_snapshot(saved['data'])
    except (OSError, ValueError, KeyError, TypeError, AssertionError):
        return None


def accumulate(days, start, end, endpoint):
    if endpoint is None:
        return None
    result = [row[:] for row in endpoint]
    day = start
    while day < end:
        if day not in days:
            return None
        for group in range(6):
            for metric in range(2):
                result[group][metric] += days[day][group][metric]
        day += timedelta(days=1)
    return result


def totals(rows):
    return None if rows is None else [sum((r[i] for r in rows), D(0)) for i in range(2)]


def overview(root, report, metadata, slot):
    exported = parse_time(metadata['exported_at_vn'])
    if exported.date() != slot.date() or not 0 <= (exported-slot).total_seconds() < 600:
        raise ValueError('Mốc xuất không khớp tổng quan')
    days = history_days(root, slot.date())
    current = from_snapshot(numeric_data(report))
    result = []
    for index, (title, start, old_start, old_end) in enumerate(periods(slot.date())):
        end = slot.date()
        basis = 'same_clock'
        if index == 0:
            now = current
            before = boundary(root, old_end, slot, exported)
        else:
            basis = 'closed_days'
            end -= timedelta(days=1)
            if end < start:
                now = before = None
            else:
                # Recompute corresponding endpoint from the last completed date.
                _, _, old_start, old_end = periods(end)[index]
                now = accumulate(days, start, end+timedelta(days=1), ZERO())
                before = accumulate(days, old_start, old_end+timedelta(days=1), ZERO())
        now_total, before_total = totals(now), totals(before)
        result.append({'title': title, 'start': start, 'end': end, 'basis':basis, 'previous_start': old_start,
                       'previous_end': old_end, 'current': now, 'previous': before,
                       'total': now_total, 'previous_total': before_total,
                       'growth': [percent(now_total[i], before_total[i]) if now_total and before_total else None for i in range(2)]})
    return result


def formatted(value, money=False):
    if value is None:
        return '—'
    if money:
        value = (value/D('1000000000')).quantize(D('0.01'), rounding=ROUND_HALF_UP)
        if value == 0: value = abs(value)
        text = f'{value:,.2f}'
    else:
        text = f'{value:,.0f}'
    return text.replace(',', '~').replace('.', ',').replace('~', '.')


def growth(value):
    if value is None:
        return '—'
    if abs(value) < D('0.05'):
        return '0,0%'
    return f'{value:+.1f}%'.replace('.', ',')


def render(data, slot, path):
    """A compact, exact header merged into the existing first daily photo."""
    from PIL import Image, ImageDraw, ImageFont
    image = Image.new('RGB', (2200, 650), 'white')
    draw = ImageDraw.Draw(image)
    navy, blue, muted = '#10294D', '#1469B7', '#65758A'
    fonts = Path(os.environ['TAOWORK_REPORT_ROOT']) / 'fonts'
    def font(size, bold=False):
        return ImageFont.truetype(str(fonts/('Arial Bold.ttf' if bold else 'Arial.ttf')),size)
    def text(value,x,y,size=29,bold=False,color=navy,anchor='la',max_width=None):
        while max_width and draw.textlength(value,font=font(size,bold))>max_width and size>20:
            size-=1
        draw.text((x,y),value,font=font(size,bold),fill=color,anchor=anchor)
    text('SO SÁNH NGÀY · THÁNG · QUÝ · LŨY KẾ NĂM',40,20,40,True)
    text('Cập nhật '+slot.strftime('%d/%m/%Y · %H:%M')+'  |  SL: sản phẩm  |  DT: tỷ đồng  |  Quý dương lịch',40,76,25,color=muted)
    widths=[500,270,270,210,300,300,270]
    headers=['Kỳ so sánh','SL trước','SL này','% SL','DT trước','DT này','% DT']
    x=40
    for width,label in zip(widths,headers):
        draw.rectangle((x,125,x+width,186),fill=blue)
        text(label,x+width/2,140,29,True,'white','ma');x+=width
    for index,p in enumerate(data):
        y=186+index*104
        draw.rectangle((40,y,2160,y+104),fill='#F0F6FC' if index%2==0 else 'white')
        a,b=p['total'] or [None,None],p['previous_total'] or [None,None]
        title=['NGÀY','THÁNG','QUÝ','LŨY KẾ NĂM'][index]
        title+=(' · '+slot.strftime('%H:%M') if index==0 else ' · đến hết '+p['end'].strftime('%d/%m'))
        if p['end']<p['start']:
            title=['NGÀY','THÁNG','QUÝ','LŨY KẾ NĂM'][index]+' · chưa có ngày chốt'
        text(title,56,y+12,29,True)
        def date_span(start,end):
            return start.strftime('%d/%m')+('–'+end.strftime('%d/%m') if start!=end else '')+'/'+end.strftime('%y')
        dates=date_span(p['start'],p['end'])+' / '+date_span(p['previous_start'],p['previous_end'])
        if p['end']<p['start']:dates='Kỳ mới bắt đầu hôm nay'
        text(dates,56,y+55,23,color=muted,max_width=470)
        cells=[formatted(b[0]),formatted(a[0]),growth(p['growth'][0]),formatted(b[1],True),formatted(a[1],True),growth(p['growth'][1])]
        x=40+widths[0]
        for col,(width,cell) in enumerate(zip(widths[1:],cells),start=1):
            color=navy
            if col in (3,6):
                value=p['growth'][0 if col==3 else 1]
                color=muted if value is None or abs(value)<D('0.05') else '#16834A' if value>0 else '#D3313D'
            text(cell,x+width-18,y+31,31,True,color,'ra',max_width=width-32)
            draw.line((x,y,x,y+104),fill='#D8E3EE');x+=width
        draw.line((40,y+104,2160,y+104),fill='#D8E3EE')
    text('Khoảng ngày: kỳ này / kỳ trước · Ngày so cùng giờ; các kỳ dài so số đã chốt · “—”: chưa đủ dữ liệu',40,614,24,color=muted)
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    image.save(path,'JPEG',quality=90,subsampling=0,optimize=True);image.close()
    return path


def build(root, report, metadata, slot, directory):
    data = overview(root, report, metadata, slot)
    path = render(data,slot,Path(directory)/'04_So_Sanh_Bo_Sung.jpg')
    from report_comparison import save_json
    save_json(path.with_suffix('.json'), {'slot':slot.isoformat(),'scope':'Mới','vat': '1.08','unit':'tỷ đồng','periods':json.loads(json.dumps(data,default=str,ensure_ascii=False))})
    return path
