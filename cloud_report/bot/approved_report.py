import os
"""Three photos in the 20:05 format, with live-month numbers and whole billions."""
from datetime import timedelta
from decimal import Decimal as D, getcontext
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
from mobile_report import money

from period_model_comparison import history, empty, merge, sum_days, combined_rows
from period_overview import previous_month, formatted, growth
from report_comparison import parse_time, numeric_data, validate_data, save_json
from report_photos import render_table_photos, validate_photos

LAYOUT = 'three_images_aligned_v1'
CALCULATION = 'day_week_month_live_all_categories_v4'
PRESENTATION = 'format_2005_live_month_v1'


def selected(data):
    """Retain every sale; known Watch bands belong to accessories, not Watch."""
    if data is None:
        return None
    result = empty()
    for name, item in data['models'].items():
        if 'watch band' in name.casefold() or name.casefold().startswith('dây'):
            item = dict(item, category=5)
        merge(result, {'models': {name: item}})
    validate_data(result)
    return result


def compare(root, report, metadata, slot, days=None):
    getcontext().prec = max(getcontext().prec, 64)
    exported = parse_time(metadata['exported_at_vn'])
    day = slot.date()
    if (report['report_date'] != day.isoformat() or exported.date() != day
            or not 0 <= (exported-slot).total_seconds() < 600):
        raise ValueError('Sai ngày hoặc mốc so sánh')
    current = numeric_data(report)
    validate_data(current)
    if days is None:
        days = history(root, day)
    monday = day-timedelta(days=day.weekday())
    specs = [
        ('NGÀY', day, day-timedelta(days=1), day-timedelta(days=1)),
        ('TUẦN', monday, monday-timedelta(days=7), day-timedelta(days=7)),
    ]
    result = []
    for title, start, old_start, old_end in specs:
        now = sum_days(days, start, day-timedelta(days=1))
        if now is not None:
            merge(now, current)
        # Previous periods use complete calendar days, irrespective of export time.
        # The current day stays live so /layso still reports the latest sales.
        before = sum_days(days, old_start, old_end)
        result.append({'title': title, 'start': str(start), 'end': str(day),
                       'previous_start': str(old_start), 'previous_end': str(old_end),
                       'basis': 'calendar_days_current_partial', 'slot': slot.isoformat(),
                       'current': selected(now), 'previous': selected(before)})
    # User-approved live MTD: completed earlier days + today's export exactly once.
    start = day.replace(day=1)
    old_end = previous_month(day)
    old_start = old_end.replace(day=1)
    now = sum_days(days, start, day-timedelta(days=1))
    if now is not None:
        merge(now, current)
    result.append({'title': 'THÁNG', 'start': str(start), 'end': str(day),
                   'previous_start': str(old_start), 'previous_end': str(old_end),
                   'basis': 'calendar_days_current_partial', 'slot': slot.isoformat(),
                   'current': selected(now),
                   'previous': selected(sum_days(days, old_start, old_end))})
    return result


def display_rows(periods):
    rows = combined_rows(periods)
    accessory_names = {name for p in periods for side in ('current', 'previous')
                       for name, item in (p[side] or {'models': {}})['models'].items()
                       if item['category'] == 5}
    rows = [r for r in rows if r['kind'] != 'model' or
            (r['label'] not in accessory_names and any(v is not None and v != 0
             for p in r['periods'] for side in ('current', 'previous') for v in p[side]))]
    rows[0]['label'] = 'TỔNG TOÀN BỘ'
    return rows


def span(period, prefix=''):
    if parse_time(period[prefix+'end']) < parse_time(period[prefix+'start']):
        return '0 ngày đã chốt'
    a = parse_time(period[prefix+'start']).strftime('%d/%m')
    b = parse_time(period[prefix+'end']).strftime('%d/%m')
    return a if a == b else a+'–'+b


def date_label(period):
    suffix = ('Trọn ngày' if period['basis'] == 'closed_days'
              else 'Kỳ trước trọn ngày · Kỳ này đang cập nhật')
    return span(period, 'previous_')+' / '+span(period)+' · '+suffix


def render(periods, path):
    rows = display_rows(periods)
    slot = parse_time(periods[0]['slot'])
    MARGIN, NAME_W, COL_W, ROW_H, TOP = 30, 480, 210, 56, 320
    WIDTH = 2*MARGIN + NAME_W + 18*COL_W
    HEIGHT = TOP + len(rows)*ROW_H + 78
    im = Image.new('RGB', (WIDTH, HEIGHT), 'white')
    draw = ImageDraw.Draw(im)
    INK, MUTED, GRID = '#112B47', '#5B6C7F', '#D8DFE7'
    font_dir = Path(os.environ['TAOWORK_REPORT_ROOT']) / 'fonts'
    fonts = {}
    def font(size, bold=False):
        key = (size, bold)
        if key not in fonts:
            fonts[key] = ImageFont.truetype(str(font_dir/('Arial Bold.ttf' if bold else 'Arial.ttf')), size)
        return fonts[key]

    def text(s, x, y, size=32, bold=False, color=INK, anchor='lm', max_width=None):
        while max_width and draw.textlength(s, font=font(size,bold))>max_width and size>22:
            size-=1
        f = font(size, bold)
        if max_width is not None and draw.textlength(s, font=f)>max_width:
            raise RuntimeError('Nội dung vượt chiều rộng cột: '+s)
        draw.text((x, y), s, font=f, fill=color, anchor=anchor)

    text('SO SÁNH NGÀY / TUẦN / THÁNG THEO MODEL', MARGIN, 42, 48, True)
    text(slot.strftime('%H:%M · %d/%m/%Y')+'   |   SL: sản phẩm   |   Doanh thu: tỷ đồng', MARGIN, 98, 31, color=MUTED)

    head_top = 140
    draw.rectangle((MARGIN, head_top, MARGIN+NAME_W, TOP), fill='#FFC000')
    text('NHÓM / MODEL', MARGIN+NAME_W/2, 231, 34, True, anchor='mm')
    titles = ['HÔM QUA / HÔM NAY', 'TUẦN TRƯỚC / TUẦN NÀY', 'THÁNG TRƯỚC / THÁNG NÀY']
    date_labels = [date_label(p) for p in periods]
    sub_labels = [('Hôm qua', 'Hôm nay'), ('Tuần trước', 'Tuần này'), ('Tháng trước', 'Tháng này')]

    for i in range(3):
        x = MARGIN+NAME_W+i*6*COL_W
        draw.rectangle((x, head_top, x+6*COL_W, 232), fill='#FFC000')
        text(titles[i], x+3*COL_W, 168, 34, True, anchor='mm')
        text(date_labels[i], x+3*COL_W, 210, 29, anchor='mm', max_width=6*COL_W-28)
        for k, label in enumerate(('SỐ LƯỢNG', 'DOANH THU · TỶ ĐỒNG')):
            mx = x+k*3*COL_W
            draw.rectangle((mx, 232, mx+3*COL_W, 275), fill='#E4EDF7' if k==0 else '#FCE8CC')
            text(label, mx+1.5*COL_W, 253, 28, True, anchor='mm')
            for c, sub in enumerate((*sub_labels[i], '% tăng/giảm')):
                cx = mx+c*COL_W
                draw.rectangle((cx, 275, cx+COL_W, TOP), fill='#FFF1BD' if c==1 else '#F2F5F9')
                text(sub, cx+COL_W/2, 298, 26, True, anchor='mm', max_width=COL_W-14)

    for ri, row in enumerate(rows):
        y = TOP+ri*ROW_H
        is_total = row['kind']=='total'
        is_category = row['kind']=='category'
        bold = is_total or is_category
        fill = '#FFE36B' if is_total else '#F8CBAD' if is_category else '#F3F6FA' if ri%2 else 'white'
        draw.rectangle((MARGIN, y, WIDTH-MARGIN, y+ROW_H), fill=fill)
        text(row['label'], MARGIN+14, y+ROW_H/2, 32, bold, max_width=NAME_W-28)
        for pi, period in enumerate(row['periods']):
            for metric in range(2):
                start = MARGIN+NAME_W+(pi*6+metric*3)*COL_W
                values = [money(period['previous'][metric]) if metric==1 else formatted(period['previous'][metric]),
                          money(period['current'][metric]) if metric==1 else formatted(period['current'][metric]),
                          growth(period['growth'][metric])]
                for ci, value in enumerate(values):
                    x = start+ci*COL_W
                    if ci==1 and not bold:
                        draw.rectangle((x, y, x+COL_W, y+ROW_H), fill='#FFF8DF')
                    color = INK
                    if ci==0 and not bold: color = '#40546C'
                    if ci==2:
                        g = period['growth'][metric]
                        color = MUTED if g is None or abs(g)<D('0.05') else '#13804C' if g>0 else '#C82F3C'
                    if value=='—':color=MUTED
                    text(value, x+COL_W-14, y+ROW_H/2, 31 if ci==2 else 32,
                         bold or ci==1, color, 'rm', COL_W-28)
        draw.line((MARGIN, y+ROW_H, WIDTH-MARGIN, y+ROW_H), fill=GRID, width=1)
        if bold:draw.line((MARGIN, y, WIDTH-MARGIN, y), fill='#CCAF90' if is_category else '#B39A37', width=2)

    bottom = TOP+len(rows)*ROW_H
    for j in range(19):
        x=MARGIN+NAME_W+j*COL_W
        major=j%6==0
        mid=j%3==0
        draw.line((x, head_top if major else 232 if mid else 275, x, bottom),
                  fill='#8495A8' if major else '#B6C3D1' if mid else GRID,
                  width=3 if major else 2 if mid else 1)
    draw.rectangle((MARGIN, head_top, WIDTH-MARGIN, bottom), outline='#A8B5C5', width=2)
    text('—: chưa đủ dữ liệu hoặc không tính được %. Tháng: lũy kế có số hôm nay. Tổng gồm cả phụ kiện.', MARGIN, HEIGHT-46, 27, color=MUTED)


    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if WIDTH+HEIGHT > 9800:
        scale = 9800/(WIDTH+HEIGHT)
        resized = im.resize((int(WIDTH*scale), int(HEIGHT*scale)), Image.Resampling.LANCZOS)
        im.close()
        im = resized
    im.save(path, 'JPEG', quality=85, subsampling=0, optimize=True)
    im.close()
    validate_photos([path])
    return path


def build(root, report, metadata, slot, directory):
    directory = Path(directory)
    periods = compare(root, report, metadata, slot)
    comparison = render(periods, directory/'04_Ngay_Tuan_Thang.jpg')
    photos = [comparison]
    for prefix in ('01_', '02_'):
        tables = [t for t in report['tables'] if t['stem'].startswith(prefix)]
        if len(tables) != 1:
            raise RuntimeError('Thiếu hoặc trùng bảng vùng/model đã duyệt')
        photos.extend(render_table_photos(tables[0], single_image=True))
    validate_photos(photos, expected=3)
    daily = periods[0]
    comparison_data = {'slot': slot.isoformat(), 'basis': daily['basis'],
                       'baseline_available': daily['previous'] is not None,
                       'previous_date': daily['previous_end'],
                       'today_total': daily['current']['total'],
                       'yesterday_total': daily['previous']['total'] if daily['previous'] else None}
    save_json(directory/'approved-report.json', {'schema': 4, 'layout': LAYOUT, 'calculation': CALCULATION, 'presentation': PRESENTATION,
              'slot': slot.isoformat(), 'periods': periods,
              'rows': len(display_rows(periods)), 'photos': [str(p) for p in photos]})
    return {'photos': [str(p) for p in photos], 'comparison': comparison_data}
