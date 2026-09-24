"""Shared batch wire format and customer-facing results (no product IDs)."""
import json
import re

def message_chunks(text):
    chunks=[]; current=[]; size=0
    for char in text:
        units=2 if ord(char)>0xffff else 1
        if size+units>4500:
            chunks.append(''.join(current));current=[];size=0
        current.append(char);size+=units
    if current:chunks.append(''.join(current))
    if len(chunks)>5:
        raise ValueError('Kết quả quá dài để gửi trong một lượt LINE.')
    return chunks

def items(payload):
    return payload.get('items') or [payload]

def preview_names(payload, result):
    names=json.loads(result) if 'items' in payload else [result]
    if not isinstance(names,list) or len(names)!=len(items(payload)):
        raise ValueError('Sai số dòng tên sản phẩm.')
    if any(not isinstance(name,str) or not name.strip() or len(name)>300 for name in names):
        raise ValueError('Tên sản phẩm không hợp lệ.')
    return [name.strip() for name in names]

def decode_results(payload, result):
    rows=json.loads(result)
    if not isinstance(rows,list) or len(rows)!=len(items(payload)):
        raise ValueError('Sai số dòng kết quả.')
    for row in rows:
        if not isinstance(row,dict) or set(row)!={'co','error'}:
            raise ValueError('Kết quả không hợp lệ.')
        if not all(isinstance(row[k],str) for k in ('co','error')):
            raise ValueError('Kết quả không hợp lệ.')
        if row['co'] and not re.fullmatch(r'[0-9A-Z]+CO[0-9]+',row['co']):
            raise ValueError('Mã CO không hợp lệ.')
    return rows

def result_text(job):
    payload=json.loads(job['payload']); data=items(payload)
    try:
        rows=decode_results(payload,job['result'] or '')
    except (ValueError,TypeError):
        success=job['state']=='succeeded'
        rows=[{'co':job['result'] if success else '', 'error':'' if success else (job['result'] or 'Chưa có kết quả.')} for _ in data]
    count=sum(bool(row['co']) for row in rows)
    blocks=[f"Kết quả CO — {job['id']}: {count}/{len(data)} có mã CO"]
    for n,(item,row) in enumerate(zip(data,rows),1):
        icon='✅' if row['co'] and not row['error'] else '⚠️' if row['co'] or job['state']=='unknown' else '❌'
        block=f"{icon} {n}. {item['source']} → {item['destination']}\n{item.get('product_name','Chưa lấy được tên sản phẩm từ MWG')}\nSố lượng: {item['quantity']}"
        if row['co']:block+='\nCO: '+row['co']
        if row['error']:block+='\n'+row['error']
        blocks.append(block)
    if job['state']=='unknown':
        blocks.append('Có dòng chưa rõ kết quả. Kiểm tra MWG trước khi tạo lại; không gửi lại các dòng đã có mã CO.')
    return '\n\n'.join(blocks)
