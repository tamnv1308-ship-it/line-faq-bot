"""Read explicitly labelled transfer details; never infer IDs from mentions."""
import re
import unicodedata

ALIASES = {
    'source': ['kho xuat', 'ma kho xuat', 'kho chuyen', 'ma kho chuyen'],
    'destination': ['kho nhan hang', 'kho nhan', 'kho nhap', 'ma kho nhan', 'ma kho nhap'],
    'product': ['ma san pham', 'san pham', 'ma sp', 'ma code', 'msp', 'sku', 'sp', 'code'],
    'quantity': ['so luong', 'sl'],
    'note': ['ghi chu', 'note'],
    'status': ['trang thai san pham', 'trang thai'],
}
LABELS = {'source': 'Kho xuất', 'destination': 'Kho nhận',
          'product': 'Mã sản phẩm', 'quantity': 'Số lượng'}
LOOKUP = {alias: key for key, aliases in ALIASES.items() for alias in aliases}
LABEL = '|'.join(re.escape(a).replace(r'\ ', r'[ \t]+') for a in sorted(LOOKUP,key=len,reverse=True))
# Restrict labels to line/semicolon/pipe boundaries, not numbers inside prose or @mentions.
FIELD = re.compile(r'(?:^|[;|])[ \t]*(?:(?:[-*•]|[0-9]+[.)])[ \t]*)?('+LABEL+r')(?=[ \t]*(?:[:：=]|[0-9])|[ \t]*$)[ \t]*(?:[:：=][ \t]*)?',re.I)


def fold(text):
    return ''.join(c for c in unicodedata.normalize('NFD',text.lower().replace('đ','d'))
                   if unicodedata.category(c) != 'Mn')


def normalize_status(value):
    value=re.sub(r'^\s*\d+\s*[-–]\s*','',value)
    key=' '.join(re.sub(r'[()]',' ',fold(value)).split())
    return {'moi':'Mới','da su dung':'Đã sử dụng','moi giam gia':'Mới giảm giá',
            'trung bay':'Trưng bày','loi moi':'Lỗi (mới)','loi dsd':'Lỗi (ĐSD)',
            'loi da su dung':'Lỗi (ĐSD)'}.get(key)


def parts(text):
    # NFC keeps folded indices aligned with the original Vietnamese text.
    text=unicodedata.normalize('NFC',text).replace('\u00a0',' ')
    for line in text.splitlines():
        matches=list(FIELD.finditer(fold(line)))
        if not matches:
            # A standalone 13-digit product code is also a field, including in batches.
            if re.fullmatch(r'[0-9]{13}', line.strip()):
                yield 'product', line.strip()
                continue
            if line.strip():
                yield None,line.strip()
            continue
        prefix=line[:matches[0].start()].strip(' ;|')
        if prefix:
            yield None,prefix
        for i,match in enumerate(matches):
            end=matches[i+1].start() if i+1<len(matches) else len(line)
            key=LOOKUP[re.sub(r'[ \t]+',' ',match.group(1).lower())]
            value=line[match.end():end].strip()
            # SP also labels a product name in pasted requests. Only numeric SP is an ID.
            if re.sub(r'[ \t]+',' ',match.group(1).lower()) in {'sp','san pham'} and not re.match(r'^[0-9]',value):
                yield None,value
            else:
                yield key,value


def is_transfer_message(text):
    # Notes alone are ordinary conversation, not a transfer request.
    return any(key in LABELS for key,value in parts(text))


def parse_form(text):
    if len(text)>10000:
        raise ValueError('Tin nhắn quá dài; vui lòng gửi mỗi yêu cầu trong một tin nhắn ngắn hơn.')
    values={}; notes=[]
    def set_status(value):
        status=normalize_status(value)
        if status is None:
            raise ValueError('Trạng thái không hợp lệ: '+value+'. Chưa tạo CO.')
        if 'status' in values and values['status']!=status:
            raise ValueError('Có nhiều trạng thái khác nhau; vui lòng chỉ ghi một trạng thái.')
        values['status']=status
    for key,value in parts(text):
        if key is None:
            normalized=fold(value).lstrip('-*• ').strip()
            explicit=re.match(r'^trang thai(?: san pham)?\s*[:=]?\s+(.+)$',normalized)
            if explicit:
                set_status(explicit.group(1))
                continue
            if normalize_status(value):
                set_status(value)
                continue
            if (re.match(r'^(?:ql|qlst)\s+cho\s+hang\b',normalized)
                    or re.match(r'^dm\s+xac\s+nhan\b',normalized)):
                notes.append(value)
            continue
        if key=='note':
            explicit=re.match(r'^trang thai(?: san pham)?\s*[:=]?\s*(.+)$',fold(value))
            if explicit or normalize_status(value):
                set_status(explicit.group(1) if explicit else value)
            if value:
                notes.append(value)
            continue
        if key=='status':
            if key in values:
                raise ValueError('Trạng thái xuất hiện nhiều lần.')
            set_status(value)
            continue
        if key in values:
            raise ValueError(f'{LABELS[key]} xuất hiện nhiều lần. Chỉ gửi một yêu cầu trong mỗi tin nhắn.')
        if key=='quantity':
            match=re.fullmatch(r'([0-9]{1,6})(?:\s*(?:cai|chiec|may|san pham|sp))?',fold(value))
        elif key in {'source', 'destination'}:
            # Warehouse names may follow the code without a dash. Require a letter
            # first so numeric lists and slash-separated alternatives stay invalid.
            match=re.fullmatch(r'([0-9]{1,30})(?:\s+[-–—]\s+[^\n]+|\s+[^\W\d_][^\n]*)?',value)
            if match and re.match(r'^(?:hoac|va|or|and)\b',fold(value[match.end(1):].strip())):
                match=None
        else:
            # Optional " - warehouse/product description" is display context, never part of the ID.
            match=re.fullmatch(r'([0-9]{1,30})(?:\s+[-–—]\s+[^\n]+)?',value)
        if not match:
            raise ValueError(f'{LABELS[key]} chưa rõ hoặc có nhiều giá trị. Gửi dạng "{LABELS[key]}: mã/số".')
        values[key]=match.group(1)
    if 'quantity' not in values:
        values['quantity']='1'
        values['quantity_defaulted']=True
    missing=[label for key,label in LABELS.items() if key not in values]
    if missing:
        raise ValueError('Thiếu '+', '.join(missing)+'. Bổ sung vào tin nhắn và gửi lại toàn bộ yêu cầu; bot chưa tạo lệnh.')
    if values['source']==values['destination']:
        raise ValueError('Kho xuất và kho nhận phải khác nhau.')
    values['quantity']=int(values['quantity'])
    if not 1<=values['quantity']<=100000:
        raise ValueError('Số lượng phải là số nguyên từ 1 đến 100000.')
    values['note']='\n'.join(notes)
    values.setdefault('status','Mới')
    if len(values['note'])>500:
        raise ValueError('Ghi chú vượt 500 ký tự. Rút gọn nội dung phụ và gửi lại; bot không tự cắt bỏ.')
    return values


def parse_request(text):
    """Split complete records at a repeated field or an explicit separator."""
    if len(text)>10000:
        raise ValueError('Tin nhắn quá dài (tối đa 10000 ký tự).')
    groups=[]; lines=[]; seen=set()
    for line in unicodedata.normalize('NFC',text).splitlines():
        keys={key for key,value in parts(line) if key in LABELS}
        separator=bool(line.strip()) and bool(re.fullmatch(r'[\\\s=\-_*]{3,}',line))
        if (separator and seen) or (keys & seen):
            if not {'source','destination','product'}<=seen:
                raise ValueError('Một dòng yêu cầu chưa đủ kho xuất, kho nhận và mã sản phẩm; không tự ghép với yêu cầu kế tiếp.')
            groups.append('\n'.join(lines));lines=[];seen=set()
        if not separator:
            lines.append(line);seen.update(keys)
    if seen:
        groups.append('\n'.join(lines))
    if not groups:
        return parse_form(text)
    if len(groups)>7:
        raise ValueError('Tối đa 7 yêu cầu trong một tin nhắn.')
    items=[parse_form(group) for group in groups]
    if len(items)==1:
        return items[0]
    if len({item['status'] for item in items})!=1:
        raise ValueError('Các dòng trong cùng file phải cùng trạng thái sản phẩm. Gửi riêng các trạng thái khác nhau.')
    identities=[(str(int(item['source'])),str(int(item['destination'])),item['product'],item['quantity']) for item in items]
    if len(set(identities))!=len(identities):
        raise ValueError('Có dòng trùng kho xuất, kho nhận, mã sản phẩm và số lượng. Bỏ dòng trùng rồi gửi lại.')
    return {'items':items,'status':items[0]['status'],'batch_version':1}
