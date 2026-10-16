"""Editable intake drafts. Parsing never enqueues or silently drops a row."""
import html
import re

from transfer_parser import parts, clean_copied_text, fold, normalize_status, LABELS, transfer_key
from destination_policy import BLOCKED

STATUSES = ('Mới','Đã sử dụng','Mới giảm giá','Trưng bày','Lỗi (mới)','Lỗi (ĐSD)')
FIELDS = ('source','destination','product','quantity','status','note')


def validate_rows(values, max_rows=7):
    if not isinstance(values,list) or not 1<=len(values)<=50:
        raise ValueError('Cần từ 1 đến 7 dòng yêu cầu. Mỗi lần tách tối đa 50 dòng để sửa.')
    rows=[];errors=[];warnings=[];seen={}
    for index,value in enumerate(values):
        if not isinstance(value,dict):raise ValueError('Dữ liệu dòng yêu cầu không hợp lệ.')
        row={};bad={}
        for key in FIELDS:
            raw=value.get(key,'')
            if not isinstance(raw,str) or len(raw)>10000:
                raise ValueError('Các ô phải là văn bản, tối đa 10000 ký tự.')
            row[key]=clean_copied_text(raw).strip()
        for key in ('source','destination'):
            if not re.fullmatch(r'[0-9]{1,30}',row[key]):bad[key]='Nhập mã kho bằng chữ số.'
        if not re.fullmatch(r'[0-9]{13}',row['product']):bad['product']='Mã sản phẩm phải đủ 13 chữ số, giữ nguyên số 0 đầu.'
        if not re.fullmatch(r'[0-9]{1,6}',row['quantity']) or not 1<=int(row['quantity'])<=100000:
            bad['quantity']='Nhập số nguyên từ 1 đến 100000.'
        status=normalize_status(row['status'])
        if not status:bad['status']='Chọn một trạng thái sản phẩm hợp lệ.'
        else:row['status']=status
        if len(row['note'])>500:bad['note']='Note tối đa 500 ký tự, bao gồm thông tin liên hệ được thêm khi gửi.'
        if not bad.get('source') and not bad.get('destination'):
            if int(row['source'])==int(row['destination']):bad['destination']='Kho nhận phải khác kho xuất.'
            blocked=BLOCKED.get(str(int(row['destination'])))
            if blocked:bad['destination']=f"{blocked['name']} thuộc nhóm {blocked['group']}; không nhận tạo CO."
        if not any(key in bad for key in ('source','destination','product','quantity')):
            key=transfer_key(row)
            if key in seen:warnings.append({'row':index,'message':f'Trùng dòng {seen[key]+1}; bot sẽ bỏ dòng trùng khi gửi.'})
            else:seen[key]=index
        rows.append(row);errors.append(bad)
    global_errors=[]
    if len(rows)>max_rows:global_errors.append(f'Mỗi file tối đa {max_rows} dòng. Xóa bớt dòng trước khi gửi.')
    if len({row['status'] for row,bad in zip(rows,errors) if 'status' not in bad})>1:
        global_errors.append('Các dòng trong một file phải cùng trạng thái sản phẩm. Gửi riêng từng trạng thái.')
    return dict(rows=rows,errors=errors,warnings=warnings,global_errors=global_errors,
                valid=not any(errors) and not global_errors)


def parse_editable(text):
    if not isinstance(text,str) or not text.strip() or len(text)>10000:
        raise ValueError('Dán tin nhắn cần tạo CO, tối đa 10000 ký tự.')
    groups=[];lines=[];seen=set()
    for line in clean_copied_text(html.unescape(text)).splitlines():
        fields=list(parts(line))
        keys={key for key,value in fields if key in LABELS}
        separator=bool(line.strip()) and bool(re.fullmatch(r'[\\\s=\-_*]{3,}',line))
        if (separator and seen) or keys & seen:
            groups.append(lines);lines=[];seen=set()
        if not separator:lines.extend(fields);seen.update(keys)
    if lines or not groups:groups.append(lines)
    rows=[]
    for group in groups:
        raw={};notes=[]
        for key,value in group:
            normalized=fold(value).lstrip('-*• ').strip()
            if key is None:
                explicit=re.match(r'^trang thai(?: san pham)?\s*[:=]?\s+(.+)$',normalized)
                if explicit or normalize_status(value):key='status';value=explicit.group(1) if explicit else value
                elif re.match(r'^(?:(?:ql|qlst)\s+cho\s+hang|dm\s+xac\s+nhan)\b',normalized):notes.append(value)
                else:continue
            if key=='note':
                notes.append(value)
                explicit=re.match(r'^trang thai(?: san pham)?\s*[:=]?\s*(.+)$',fold(value))
                if explicit or normalize_status(value):key='status';value=explicit.group(1) if explicit else value
                else:continue
            # Keep ambiguous values visible and invalid rather than picking one.
            raw[key]=(raw[key]+' / '+value) if key in raw else value
        for key in ('source','destination'):
            value=raw.get(key,'')
            match=re.fullmatch(r'([0-9]{1,30})(?:\s*[-–—]\s*[^\W\d_][^\n]*|\s+[^\W\d_][^\n]*)?',value)
            if match and not re.match(r'^(?:hoac|va|or|and)\b',fold(value[match.end(1):].strip())):
                raw[key]=match.group(1)
        product=re.fullmatch(r'([0-9]{1,30})(?:\s+[-–—]\s+[^\n]+)?',raw.get('product',''))
        if product:raw['product']=product.group(1)
        quantity=re.fullmatch(r'([0-9]{1,6})(?:\s*(?:cai|chiec|may|san pham|sp))?',fold(raw.get('quantity','1')))
        if quantity:raw['quantity']=quantity.group(1)
        raw.setdefault('quantity','1');raw.setdefault('status','Mới')
        raw['note']='\n'.join(notes)
        rows.append({key:raw.get(key,'') for key in FIELDS})
    return validate_rows(rows)


def queue_payload(review):
    if not review['valid']:raise ValueError('Sửa các ô đang báo lỗi trước khi gửi.')
    rows=[dict(row,quantity=int(row['quantity'])) for row in review['rows']]
    return rows[0] if len(rows)==1 else dict(items=rows,status=rows[0]['status'],batch_version=1)
