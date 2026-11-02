import os
"""Rasterize exact report tables into readable Telegram photos, preserving every row."""
import math
from pathlib import Path


def photo_sections(table):
    """Top-origin bands; long tables split only between whole data rows."""
    stem = table['stem']
    if stem.startswith('04'):
        header, row_h, footer = 164, 27, 22
    else:
        header, row_h, footer = 122 + (30 if stem.startswith('01') else 60), 25, (80 if stem.startswith('02') else 58)
    width, height, rows = table['width'], table['height'], table['rows']
    if abs(header + row_h * rows + footer - height) > .1:
        raise RuntimeError('Bố cục bảng đã thay đổi; chưa chuyển được ảnh an toàn')
    # Bound the long side so Telegram compression does not shrink tiny table text.
    if height <= width * 1.6:
        return [(0, rows)]
    per_image = max(1, math.floor((width * 1.3 - header - footer - 28) / row_h))
    return [(start, min(rows, start + per_image)) for start in range(0, rows, per_image)]


def render_table_photos(table, single_image=False):
    import pypdfium2 as pdfium
    from PIL import Image, ImageDraw
    source = Path(table['pdf'])
    sections = photo_sections(table)
    if single_image:
        sections = [(0, table['rows'])]
    paths = []
    with pdfium.PdfDocument(source) as document:
        if len(document) != 1:
            raise RuntimeError('Bảng báo cáo phải có đúng một trang')
        page = document[0]
        width, height = page.get_size()
        if abs(width-table['width']) > 1 or abs(height-table['height']) > 1:
            raise RuntimeError('Kích thước bảng và ảnh không khớp')
        scale = min(2, 2200 / width)
        if single_image:
            scale = min(scale, 9800 / (width + height))
        row_h = 27 if table['stem'].startswith('04') else 25
        footer = 22 if table['stem'].startswith('04') else (80 if table['stem'].startswith('02') else 58)
        header = height - table['rows'] * row_h - footer
        def band(top, bottom):
            bitmap = page.render(scale=scale, crop=(0, max(0,height-bottom), 0, top))
            result = bitmap.to_pil().convert('RGB').copy()
            bitmap.close()
            return result
        for index, (start, end) in enumerate(sections):
            if len(sections) == 1:
                image = band(0, height)
            else:
                pieces = [band(0, header), band(header+start*row_h, header+end*row_h), band(height-footer, height)]
                image = Image.new('RGB', (max(p.width for p in pieces), sum(p.height for p in pieces)+28), 'white')
                y = 0
                for piece in pieces:
                    image.paste(piece, (0,y)); y += piece.height; piece.close()
                ImageDraw.Draw(image).text((20,y+7), str(index+1)+'/'+str(len(sections)), fill='black')
            path = source.with_name(source.stem + '-anh-' + str(index+1).zfill(2) + '.jpg')
            image.save(path, 'JPEG', quality=85, subsampling=0, optimize=True)
            w,h=image.size;image.close()
            if w+h > 10000 or max(w,h)/min(w,h)>20 or path.stat().st_size >= 10*1024*1024:
                raise RuntimeError('Ảnh vượt giới hạn Telegram; chưa gửi báo cáo')
            paths.append(path)
    return paths


def validate_photos(paths, expected=None):
    from PIL import Image
    if not paths or (expected is not None and len(paths) != expected):
        raise RuntimeError('Bộ báo cáo mới phải có đúng 3 ảnh')
    for path in paths:
        path = Path(path)
        if not path.is_file() or path.stat().st_size >= 10*1024*1024:
            raise RuntimeError('Thiếu ảnh hoặc ảnh vượt giới hạn Telegram')
        with Image.open(path) as image:
            w, h = image.size
            image.verify()
        if w+h > 10000 or max(w,h)/min(w,h) > 20:
            raise RuntimeError('Ảnh vượt kích thước Telegram')
    return paths


def report_photos(report):
    if 'delivery_photos' in report:
        return validate_photos([Path(p) for p in report['delivery_photos']], expected=3)
    replacements = report.get('period_comparison_photos')
    if replacements is not None:
        paths = [Path(p) for p in replacements]
        if not paths or any(not p.is_file() or p.stat().st_size>=10*1024*1024 for p in paths):
            raise RuntimeError('Thiếu ảnh so sánh tuần/tháng/lũy kế')
        return paths + [path for table in report['tables'] if not table['stem'].startswith('04') for path in render_table_photos(table)]
    paths = [path for table in report['tables'] for path in render_table_photos(table)]
    header = report.get('comparison_header_photo')
    if header:
        from PIL import Image
        if not paths or not report['tables'][0]['stem'].startswith('04'):
            raise RuntimeError('Bảng so sánh phải đứng đầu bộ ảnh')
        with Image.open(paths[0]) as original, Image.open(header) as top:
            height = round(top.height * original.width / top.width)
            with top.resize((original.width,height),Image.Resampling.LANCZOS) as resized:
                result = Image.new('RGB',(original.width,original.height+height),'white')
                result.paste(resized,(0,0));result.paste(original,(0,height))
            target=paths[0].with_name(paths[0].stem+'-mo-rong.jpg')
            if sum(result.size)>10000 or max(result.size)/min(result.size)>20:
                result.close();raise RuntimeError('Ảnh so sánh mở rộng vượt kích thước Telegram')
            result.save(target,'JPEG',quality=90,subsampling=0,optimize=True);result.close()
            if target.stat().st_size>=10*1024*1024:
                raise RuntimeError('Ảnh so sánh mở rộng quá lớn')
            paths[0]=target
    return paths


def album_sizes(count):
    if count < 2:
        raise RuntimeError('Báo cáo phải có ít nhất hai ảnh')
    sizes=[]
    while count:
        size=min(10,count)
        if count-size==1:size-=1
        sizes.append(size);count-=size
    return sizes
