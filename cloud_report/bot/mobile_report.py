import os
"""Portrait reports from the original numbers; no network, rounding only for display."""
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
from report_photos import validate_photos

WIDTH, MARGIN, ROW = 960, 24, 64
INK, MUTED, LINE = '#152941', '#50657d', '#dce4ee'
NAVY, BLUE = '#142b49', '#245bd6'
FONT_DIR = Path(os.environ['TAOWORK_REPORT_ROOT']) / 'fonts'


def money(value):
    if value is None:
        return '—'
    value = (Decimal(value)/Decimal('1000000000')).quantize(Decimal(1), rounding=ROUND_HALF_UP)
    if value == 0:
        value = abs(value)
    return f'{value:,.0f}'.replace(',', '.')


def number(value):
    return '—' if value is None else f'{Decimal(value):,.0f}'.replace(',', '.')


def percent(value):
    if value is None:
        return '—'
    if abs(value) < Decimal('0.05'):
        return '0,0%'
    return f'{value:+.1f}%'.replace('.', ',')


class Sheet:
    def __init__(self, height):
        self.image = Image.new('RGB', (WIDTH, height), '#ffffff')
        self.draw = ImageDraw.Draw(self.image)
        self.fonts = {}

    def font(self, size, bold):
        key = (size, bold)
        if key not in self.fonts:
            self.fonts[key] = ImageFont.truetype(str(FONT_DIR/('Arial Bold.ttf' if bold else 'Arial.ttf')), size)
        return self.fonts[key]

    def text(self, value, x, y, width, size=34, bold=False, color=INK, align='left'):
        value = str(value)
        while size > 23 and self.draw.textlength(value, font=self.font(size, bold)) > width-20:
            size -= 1
        if self.draw.textlength(value, font=self.font(size, bold)) > width-20:
            raise ValueError('Nội dung quá dài cho ảnh điện thoại: '+value)
        anchor = 'rm' if align == 'right' else 'mm' if align == 'center' else 'lm'
        point = x+width-10 if align == 'right' else x+width/2 if align == 'center' else x+10
        self.draw.text((point, y), value, font=self.font(size, bold), fill=color, anchor=anchor)

    def bar(self, y, height, color):
        self.draw.rectangle((MARGIN, y, WIDTH-MARGIN, y+height), fill=color)

    def heading(self, title, slot, note):
        self.text(title, MARGIN, 45, WIDTH-2*MARGIN, 48, True)
        self.text(slot.strftime('%H:%M · %d/%m/%Y')+'  |  SL: SP · DT: tỷ đồng', MARGIN, 98, WIDTH-2*MARGIN, 31, color=MUTED)
        self.text(note, MARGIN, 142, WIDTH-2*MARGIN, 29, color=MUTED)

    def save(self, path):
        image = self.image
        if sum(image.size) > 9800:
            ratio = 9800/sum(image.size)
            image = image.resize(tuple(int(v*ratio) for v in image.size), Image.Resampling.LANCZOS)
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        image.save(path, 'JPEG', quality=90, subsampling=0, optimize=True)
        if image is not self.image:
            image.close()
        self.image.close()
        validate_photos([path])
        return path


def render_comparison(periods, rows, path):
    from report_comparison import parse_time
    from approved_report import span
    # Each metric has its own line, allowing four readable columns on a phone.
    row_h = 88
    sheet = Sheet(180 + len(periods)*(154 + len(rows)*row_h + 26) + 66)
    slot = parse_time(periods[0]['slot'])
    sheet.heading('SO SÁNH NGÀY · TUẦN · THÁNG', slot, 'Kỳ này có số hôm nay · Kỳ trước lấy trọn ngày tương ứng')
    widths = [312,200,200,200]
    y = 180
    for pi, period in enumerate(periods):
        sheet.bar(y, 66, NAVY)
        sheet.text(period['title'], MARGIN+8, y+33, 160, 39, True, '#ffffff')
        label = span(period, 'previous_')+'  →  '+span(period)
        sheet.text(label, MARGIN+170, y+33, WIDTH-2*MARGIN-180, 30, color='#ffffff', align='right')
        y += 66
        sheet.bar(y, 88, '#e7edf7')
        x = MARGIN
        for ci, (label, width) in enumerate(zip(['NHÓM / MODEL','TRƯỚC','KỲ NÀY','TĂNG/GIẢM'], widths)):
            sheet.text(label,x,y+26,width,30,True,align='left' if ci==0 else 'right')
            x += width
        sheet.text('Dòng trên: Số lượng (SP) · Dòng dưới: Doanh thu (tỷ)', MARGIN, y+65, WIDTH-2*MARGIN, 28, color=MUTED)
        y += 88
        for ri, row in enumerate(rows):
            total = row['kind'] == 'total'
            bold = total or row['kind'] == 'category'
            fill = NAVY if total else '#dfebff' if bold else '#f5f7fb' if ri%2 else '#ffffff'
            sheet.bar(y, row_h, fill)
            label = 'Phụ kiện' if row['label']=='Phụ kiện tiện ích' else row['label']
            # Wrap long model names instead of shrinking every cell to fit one line.
            label_lines = [label]
            if sheet.draw.textlength(label,font=sheet.font(36,bold)) > widths[0]-20:
                words=label.split(); middle=max(1,len(words)//2)
                label_lines=[' '.join(words[:middle]),' '.join(words[middle:])]
            for li, line in enumerate(label_lines):
                yy=y+row_h/2 if len(label_lines)==1 else y+25+li*38
                sheet.text(line,MARGIN,yy,widths[0],36,bold,'#ffffff' if total else INK)
            p = row['periods'][pi]
            for ci, side in enumerate(['previous','current','growth']):
                x=MARGIN+widths[0]+ci*200
                for metric in (0,1):
                    value=p[side][metric]
                    if side=='growth':
                        text=percent(value)
                    else:
                        text=(number(value)+' SP' if metric==0 else money(value)+' tỷ') if value is not None else '—'
                    color='#ffffff' if total else BLUE if side=='current' else INK if metric==0 else MUTED
                    if not total and side=='growth':
                        color=MUTED if value is None or abs(value)<Decimal('0.05') else '#13714a' if value>0 else '#b53244'
                    sheet.text(text,x,y+25+metric*38,200,36,bold or side=='current',color,'right')
            sheet.draw.line((MARGIN, y+row_h, WIDTH-MARGIN, y+row_h), fill=LINE)
            y += row_h
        y += 26
    sheet.text('Tổng gồm phụ kiện · DT làm tròn tỷ · —: thiếu số đối chiếu', MARGIN, y+26, WIDTH-2*MARGIN, 28, color=MUTED)
    return sheet.save(path)


def source_sections(table):
    """Reshape validated source rows without recomputing or dropping a cell."""
    rows = table.get('mobile_rows')
    if not isinstance(rows, list) or len(rows) != table.get('rows') or table.get('mobile_unit') != 'billion_vnd_rounded':
        raise ValueError('Thiếu dữ liệu chuẩn cho ảnh điện thoại; cần dựng lại từ file MWG.')
    if table['stem'].startswith('01_'):
        if any(len(row['cells']) != 5 or row['cells'][0] for row in rows):
            raise ValueError('Sai cột vùng/miền')
        return [('VÙNG / MIỀN', [{'kind': r['kind'], 'cells': r['cells'][1:]} for r in rows])]
    if table['stem'].startswith('02_'):
        if any(len(row['cells']) != 10 for row in rows):
            raise ValueError('Sai cột model')
        return [(title, [{'kind': r['kind'], 'cells': [r['cells'][0]]+r['cells'][1+i*3:4+i*3]} for r in rows])
                for i,title in enumerate(['TOÀN HỆ THỐNG', 'TGDD / ĐMX', 'TOPZONE'])]
    raise ValueError('Không nhận diện được bảng điện thoại')


def render_source_table(table, report, slot, path):
    sections = source_sections(table)
    regional = table['stem'].startswith('01_')
    row_h = 76 if regional else ROW
    height = 180 + sum(116+len(rows)*row_h+26 for _, rows in sections) + 66
    sheet = Sheet(height)
    title = 'SỐ BÁN THEO VÙNG / MIỀN' if regional else 'SỐ BÁN THEO MODEL'
    sheet.heading(title, slot, 'Tổng: '+report['grand_total'][0]+' SP  ·  '+report['grand_total'][1]+' tỷ đồng, gồm VAT')
    widths = [432,160,160,160]
    y = 180
    for title, rows in sections:
        sheet.bar(y, 64, NAVY)
        sheet.text(title, MARGIN+8, y+32, WIDTH-2*MARGIN-16, 38, True, '#ffffff')
        y += 64
        sheet.bar(y, 52, '#e7edf7')
        x = MARGIN
        for ci,(value,width) in enumerate(zip(['Vùng / Miền' if regional else 'Model','SL','DT (tỷ)','% SL'],widths)):
            sheet.text(value,x,y+26,width,32,True,align='left' if ci==0 else 'right');x+=width
        y += 52
        for ri,row in enumerate(rows):
            bold = row['kind'] != 'data'
            total = row['kind'] == 'total'
            sheet.bar(y,row_h,NAVY if total else '#dfebff' if bold else '#f5f7fb' if ri%2 else '#ffffff')
            x = MARGIN
            for ci,(value,width) in enumerate(zip(row['cells'],widths)):
                sheet.text(value,x,y+row_h/2,width,38,bold,'#ffffff' if total else BLUE if ci==1 else INK,'left' if ci==0 else 'right')
                x += width
            sheet.draw.line((MARGIN,y+row_h,WIDTH-MARGIN,y+row_h),fill=LINE)
            y += row_h
        y += 26
    note = 'Vùng/miền: Offline · Online tách riêng · Tổng gồm cả hai' if regional else 'Tỷ trọng SL trên tổng hệ thống · Không cộng lại dòng tổng nhóm'
    sheet.text(note,MARGIN,y+26,WIDTH-2*MARGIN,28,color=MUTED)
    return sheet.save(path)
