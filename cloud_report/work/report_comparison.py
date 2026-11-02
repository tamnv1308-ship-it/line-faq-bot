import os
"""Daily comparisons use saved, timely snapshots, never a retrospective full day."""
import json
import os
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from zoneinfo import ZoneInfo

from report_order import model_order
from report_numbers import configure_precision

VN = ZoneInfo('Asia/Ho_Chi_Minh')
CATEGORIES = ['iPhone', 'iPad', 'Mac', 'Watch', 'AirPods', 'Phụ kiện tiện ích']
ZERO = (Decimal(0), Decimal(0))


def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.tmp')
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
    os.replace(temporary, path)


def parse_time(value):
    stamp = datetime.fromisoformat(value)
    return stamp.replace(tzinfo=VN) if stamp.tzinfo is None else stamp.astimezone(VN)


def category_of(name):
    if name.startswith('iPhone'): return 0
    if name.startswith('iPad') and 'Keyboard' not in name: return 1
    if name.startswith(('MacBook', 'Mac Mini', 'Mac mini', 'iMac', 'Mac Studio')): return 2
    if 'Watch' in name: return 3
    if name.startswith('AirPods'): return 4
    return 5


def legacy_number(value):
    return Decimal(str(value).replace('.', '').replace(',', '.'))


def numeric_data(report):
    if 'comparison_data' in report:
        return report['comparison_data']
    # Old renderer checks contain full VND strings after VAT, not scaled values.
    models = {}
    for name, cells in report['summary_models'].items():
        category = category_of(name)
        models[name] = {'category': category,
                        'values': [str(legacy_number(cells[0])), str(legacy_number(cells[1]))],
                        'order_key': list(model_order(name, category))}
    return {'total': [str(legacy_number(report['grand_total'][i])) for i in (0, 1)], 'models': models}


def validate_data(data):
    configure_precision([*data['total'], *(v for item in data['models'].values() for v in item['values'])])
    totals = tuple(Decimal(v) for v in data['total'])
    assert len(totals) == 2 and all(v.is_finite() for v in totals)
    sums = [Decimal(0), Decimal(0)]
    for item in data['models'].values():
        assert item['category'] in range(6)
        values = [Decimal(v) for v in item['values']]
        assert len(values) == 2 and all(v.is_finite() for v in values)
        assert values[0] == values[0].to_integral_value()
        for i in range(2): sums[i] += values[i]
    assert tuple(sums) == totals, 'Tổng model không khớp tổng báo cáo'


def make_snapshot(report, metadata, slot):
    slot = slot.astimezone(VN)
    exported = parse_time(metadata['exported_at_vn'])
    if report['report_date'] != slot.date().isoformat():
        raise ValueError('Ngày báo cáo không khớp mốc')
    if exported.date() != slot.date() or not 0 <= (exported - slot).total_seconds() < 600:
        raise ValueError('Không phải bản chụp đúng mốc; không dùng làm dữ liệu so sánh')
    if metadata.get('source_rows') is not None and metadata['source_rows'] != report['source_rows']:
        raise ValueError('Số dòng không khớp file MWG')
    data = numeric_data(report)
    validate_data(data)
    return {'schema': 1, 'report_date': report['report_date'], 'slot': slot.isoformat(),
            'exported_at': exported.isoformat(), 'source_rows': report['source_rows'],
            'revenue_vat_applied': True, 'data': data}


def snapshot_path(history, slot):
    slot = slot.astimezone(VN)
    return history / slot.date().isoformat() / (slot.strftime('%H%M') + '.json')


def store_snapshot(history, snapshot):
    path = snapshot_path(history, parse_time(snapshot['slot']))
    if path.exists():
        try:
            previous = json.loads(path.read_text())
            validate_data(previous['data'])
            previous_slot = parse_time(previous['slot'])
            offset = (parse_time(previous['exported_at'])-previous_slot).total_seconds()
            if (previous.get('schema') == 1 and previous['slot'] == snapshot['slot']
                    and previous.get('revenue_vat_applied') is True and 0 <= offset < 600
                    and parse_time(previous['exported_at']) <= parse_time(snapshot['exported_at'])):
                return previous
        except (ValueError, KeyError, TypeError, AssertionError):
            pass
    save_json(path, snapshot)
    return snapshot


def _previous_snapshot(history, current):
    slot = parse_time(current['slot']) - timedelta(days=1)
    path = snapshot_path(history, slot)
    if not path.exists(): return None
    previous = json.loads(path.read_text())
    if (previous.get('schema') != 1 or previous.get('slot') != slot.isoformat()
            or previous.get('report_date') != slot.date().isoformat()
            or previous.get('revenue_vat_applied') is not True):
        return None
    exported = parse_time(previous['exported_at'])
    if not 0 <= (exported - slot).total_seconds() < 600: return None
    # Do not compare a report several minutes later in one day with an earlier one.
    offset_today = (parse_time(current['exported_at']) - parse_time(current['slot'])).total_seconds()
    if abs((exported - slot).total_seconds() - offset_today) > 180: return None
    validate_data(previous['data'])
    return previous


def previous_snapshot(history, current):
    try:
        return _previous_snapshot(history, current)
    except (ValueError, KeyError, TypeError, AssertionError):
        return None


def percent(today, yesterday):
    if yesterday is None: return None
    if yesterday == 0: return Decimal(0) if today == 0 else None
    return (today - yesterday) / abs(yesterday) * 100


def values(data, name=None, category=None):
    if data is None: return None
    if name is not None:
        return tuple(Decimal(v) for v in data['models'].get(name, {'values': ZERO})['values'])
    if category is not None:
        selected = [item for item in data['models'].values() if item['category'] == category]
        return tuple(sum((Decimal(item['values'][i]) for item in selected), Decimal(0)) for i in range(2))
    return tuple(Decimal(v) for v in data['total'])


def comparison_rows(current, previous):
    now = current['data']; before = previous['data'] if previous else None
    def row(label, kind, category=None, name=None):
        a, b = values(now, name, category), values(before, name, category)
        return {'label': label, 'kind': kind, 'today': a, 'yesterday': b,
                'change': tuple(percent(a[i], b[i] if b else None) for i in range(2))}
    result = [row('TỔNG', 'total')]
    union = dict(before['models']) if before else {}
    union.update(now['models'])
    for category, label in enumerate(CATEGORIES):
        result.append(row(label, 'category', category=category))
        names = sorted((name for name, item in union.items() if item['category'] == category),
                       key=lambda name: model_order(name, category))
        for name in names: result.append(row(name, 'model', name=name))
    return result


def number(value):
    if value is None: return '-'
    rounded = value.quantize(Decimal(1), rounding=ROUND_HALF_UP)
    return f'{rounded:,.0f}'.replace(',', '.')


def change_text(value):
    if value is None: return '-'
    if abs(value) < Decimal('0.05'): return '0,0%'
    return (f'{value:+.1f}' + '%').replace('.', ',')


def billion(value):
    if value is None: return '-'
    rounded = (Decimal(value)/Decimal('1000000000')).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    if rounded == 0: rounded = abs(rounded)
    return f'{rounded:,.2f}'.replace(',', '~').replace('.', ',').replace('~', '.')


def render_comparison(current, previous, path):
    from reportlab.pdfgen import canvas
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.lib.colors import HexColor
    font_dir = Path(os.environ['TAOWORK_REPORT_ROOT']) / 'fonts'
    for face, filename in [('Compare', 'Arial.ttf'), ('CompareBold', 'Arial Bold.ttf')]:
        if face not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont(face, str(font_dir / filename)))
    rows = comparison_rows(current, previous)
    widths = [max(270, max(pdfmetrics.stringWidth(r['label'], 'CompareBold', 16) for r in rows) + 30),
              105, 105, 115, 190, 190, 115]
    margin = 20; row_h = 27; header_h = 32; title_h = 100
    width = sum(widths) + margin * 2
    height = title_h + header_h * 2 + len(rows) * row_h + 22
    path.parent.mkdir(parents=True, exist_ok=True)
    c = canvas.Canvas(str(path), pagesize=(width, height))
    c.setTitle('SO SÁNH HÔM QUA / HÔM NAY'); c.setAuthor('NH Apple')
    c.setFillColor(HexColor('#101010')); c.setFont('CompareBold', 25)
    c.drawString(margin, height-33, 'SO SÁNH HÔM QUA / HÔM NAY')
    slot = parse_time(current['slot']); old_day = slot - timedelta(days=1)
    c.setFont('Compare', 16)
    c.drawString(margin, height-59, 'Lũy kế đến '+slot.strftime('%H:%M')+' | '+old_day.strftime('%d/%m/%Y')+' so với '+slot.strftime('%d/%m/%Y'))
    c.setFont('Compare', 14)
    c.setFillColor(HexColor('#667085' if previous else '#9A6700'))
    c.drawString(margin, height-82, ('Hôm qua '+parse_time(previous['exported_at']).strftime('%H:%M')+' | Hôm nay '+parse_time(current['exported_at']).strftime('%H:%M')) if previous else 'Hôm qua: chưa có dữ liệu cùng mốc')
    def cell(text, x, y, w, h, bold=False, fill='#FFFFFF', color='#101010', align='right', size=16):
        c.setFillColor(HexColor(fill)); c.setStrokeColor(HexColor('#CBD2DA')); c.setLineWidth(.5)
        c.rect(x, y, w, h, stroke=1, fill=1)
        face = 'CompareBold' if bold else 'Compare'
        assert pdfmetrics.stringWidth(text, face, size) <= w-14, ('Overflow', text)
        c.setFillColor(HexColor(color)); c.setFont(face, size)
        baseline = y + (h-size)/2 + size*.22
        if align == 'center': c.drawCentredString(x+w/2, baseline, text)
        elif align == 'left': c.drawString(x+8, baseline, text)
        else: c.drawRightString(x+w-8, baseline, text)
    top = height-title_h
    cell('NHÓM / MODEL', margin, top-header_h*2, widths[0], header_h*2, True, '#FFC000', align='center')
    x = margin+widths[0]
    for label, parts in [('SỐ LƯỢNG', widths[1:4]), ('DOANH THU (tỷ đồng)', widths[4:])]:
        cell(label, x, top-header_h, sum(parts), header_h, True, '#FFC000', align='center', size=17)
        for name, w in zip(['Hôm qua', 'Hôm nay', '+/- %'], parts):
            cell(name, x, top-header_h*2, w, header_h, True, '#FFF2CC', align='center', size=15)
            x += w
    for index, row in enumerate(rows):
        y = top-header_h*2-(index+1)*row_h
        fill = '#FFF000' if row['kind']=='total' else '#F8CBAD' if row['kind']=='category' else '#FFFFFF' if index%2 else '#F8FAFC'
        b = row['yesterday']; a = row['today']
        texts = [row['label'], number(b[0] if b else None), number(a[0]), change_text(row['change'][0]),
                 billion(b[1] if b else None), billion(a[1]), change_text(row['change'][1])]
        x = margin
        for column, (text, w) in enumerate(zip(texts, widths)):
            color = '#101010'; background = fill
            if column in (3,6):
                value = row['change'][0 if column==3 else 1]
                color = '#15803D' if value is not None and value>0 else '#D92D20' if value is not None and value<0 else '#667085'
                if value is not None and value != 0: background = '#EDF9EF' if value>0 else '#FFF1F0'
            cell(text, x, y, w, row_h, row['kind']!='model' or column in (3,6), background,
                 color, 'left' if column==0 else 'right')
            x += w
    c.showPage(); c.save()
    return {'stem': '04_So_Sanh', 'title': 'SO SÁNH HÔM QUA / HÔM NAY', 'pdf': str(path),
            'rows': len(rows), 'width': width, 'height': height, 'baseline_available': previous is not None}


def attach_comparison(report, metadata, slot, history, directory):
    current = make_snapshot(report, metadata, slot)
    store_snapshot(history, current)
    previous = previous_snapshot(history, current)
    table = render_comparison(current, previous, directory / '04_So_Sanh.pdf')
    report['tables'] = [table] + report['tables']
    report['comparison'] = {'slot': slot.isoformat(), 'baseline_available': previous is not None,
                            'previous_date': (slot-timedelta(days=1)).date().isoformat(),
                            'today_total': current['data']['total'],
                            'yesterday_total': previous['data']['total'] if previous else None}
    save_json(directory / 'comparison.json', {'current': current, 'previous': previous})
    return report
