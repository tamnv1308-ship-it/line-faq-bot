"""Read explicitly labelled transfer details; never infer IDs from mentions."""
import re
import unicodedata

ALIASES = {
    'source': ['kho xuat', 'ma kho xuat'],
    'destination': ['kho nhan hang', 'kho nhan', 'kho nhap', 'ma kho nhan', 'ma kho nhap'],
    'product': ['ma san pham', 'ma sp', 'msp', 'sku'],
    'quantity': ['so luong', 'sl'],
    'note': ['ghi chu', 'note'],
}
LABELS = {'source': 'Kho xuất', 'destination': 'Kho nhận',
          'product': 'Mã sản phẩm', 'quantity': 'Số lượng'}
LOOKUP = {alias: key for key, aliases in ALIASES.items() for alias in aliases}
LABEL = '|'.join(re.escape(a).replace(r'\ ', r'[ \t]+') for a in sorted(LOOKUP,key=len,reverse=True))
# Restrict labels to line/semicolon/pipe boundaries, not numbers inside prose or @mentions.
FIELD = re.compile(r'(?:^|[;|])[ \t]*(?:[-*•][ \t]*)?('+LABEL+r')(?=[ \t]*(?:[:：=]|[0-9])|[ \t]*$)[ \t]*(?:[:：=][ \t]*)?',re.I)


def fold(text):
    return ''.join(c for c in unicodedata.normalize('NFD',text.lower().replace('đ','d'))
                   if unicodedata.category(c) != 'Mn')


def parts(text):
    # NFC keeps folded indices aligned with the original Vietnamese text.
    text=unicodedata.normalize('NFC',text).replace('\u00a0',' ')
    for line in text.splitlines():
        matches=list(FIELD.finditer(fold(line)))
        if not matches:
            if line.strip():
                yield None,line.strip()
            continue
        prefix=line[:matches[0].start()].strip(' ;|')
        if prefix:
            yield None,prefix
        for i,match in enumerate(matches):
            end=matches[i+1].start() if i+1<len(matches) else len(line)
            key=LOOKUP[re.sub(r'[ \t]+',' ',match.group(1).lower())]
            yield key,line[match.end():end].strip()


def is_transfer_message(text):
    # Notes alone are ordinary conversation, not a transfer request.
    return any(key in LABELS for key,value in parts(text))


def parse_form(text):
    if len(text)>10000:
        raise ValueError('Tin nhắn quá dài; vui lòng gửi mỗi yêu cầu trong một tin nhắn ngắn hơn.')
    values={}; notes=[]
    for key,value in parts(text):
        if key is None or key=='note':
            if value:
                notes.append(value)
            continue
        if key in values:
            raise ValueError(f'{LABELS[key]} xuất hiện nhiều lần. Chỉ gửi một yêu cầu trong mỗi tin nhắn.')
        if key=='quantity':
            match=re.fullmatch(r'([0-9]{1,6})(?:\s*(?:cai|chiec|may|san pham|sp))?',fold(value))
        else:
            # Optional " - warehouse/product description" is display context, never part of the ID.
            match=re.fullmatch(r'([0-9]{1,30})(?:\s+[-–—]\s+[^\n]+)?',value)
        if not match:
            raise ValueError(f'{LABELS[key]} chưa rõ hoặc có nhiều giá trị. Gửi dạng "{LABELS[key]}: mã/số".')
        values[key]=match.group(1)
    missing=[label for key,label in LABELS.items() if key not in values]
    if missing:
        raise ValueError('Thiếu '+', '.join(missing)+'. Bổ sung vào tin nhắn và gửi lại toàn bộ yêu cầu; bot chưa tạo lệnh.')
    if values['source']==values['destination']:
        raise ValueError('Kho xuất và kho nhận phải khác nhau.')
    values['quantity']=int(values['quantity'])
    if not 1<=values['quantity']<=100000:
        raise ValueError('Số lượng phải là số nguyên từ 1 đến 100000.')
    values['note']='\n'.join(notes)
    if len(values['note'])>500:
        raise ValueError('Ghi chú vượt 500 ký tự. Rút gọn nội dung phụ và gửi lại; bot không tự cắt bỏ.')
    return values
