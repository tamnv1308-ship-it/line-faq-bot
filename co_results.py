"""Shared batch wire format and customer-facing results (no product IDs)."""
import json
import re
from transfer_parser import duplicate_notice, row_error_notice

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
    if result.startswith('{'):
        names=[r['product_name'] for r in preview_details(payload,result)]
    else:
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
        if not isinstance(row,dict) or set(row) not in ({'co','error'},{'co','error','state'}):
            raise ValueError('Kết quả không hợp lệ.')
        if not all(isinstance(row[k],str) for k in row):
            raise ValueError('Kết quả không hợp lệ.')
        if row['co'] and not re.fullmatch(r'[0-9A-Z]+CO[0-9]+',row['co']):
            raise ValueError('Mã CO không hợp lệ.')
        if 'state' in row and (row['state'] not in {'succeeded','failed','unknown'}
                or (row['state']=='failed' and (row['co'] or not row['error']))
                or (row['state']=='succeeded' and (not row['co'] or row['error']))):
            raise ValueError('Trạng thái dòng không khớp kết quả.')
    return rows


def protected_items(job, stock_only=False):
    """Legacy unknown evidence stays protected; only explicit row results release it."""
    payload=json.loads(job['payload']);data=items(payload)
    if job['state']!='unknown':return data
    try:rows=decode_results(payload,job['result'] or '')
    except (ValueError,TypeError):return data
    return [item for item,row in zip(data,rows) if row.get('state')!='failed'
            and not (stock_only and row['co'] and not row['error'])]


def filtered_preview(payload, result):
    """Validate exclusions before accepting a smaller, explicitly confirmed batch."""
    body=json.loads(result);excluded=body.get('excluded',[])
    if not isinstance(excluded,list):raise ValueError('Sai danh sách dòng lỗi.')
    data=items(payload);seen=set();errors=[]
    for row in excluded:
        if (not isinstance(row,dict) or set(row)!={'index','error'}
                or type(row['index']) is not int or not 0<=row['index']<len(data)
                or row['index'] in seen or not isinstance(row['error'],str)
                or not row['error'].strip() or len(row['error'])>500):
            raise ValueError('Dòng lỗi nhập MWG không hợp lệ.')
        seen.add(row['index'])
        errors.append(dict((key,data[row['index']][key]) for key in ('source','destination','product','quantity')))
        errors[-1]['error']=row['error']
    kept=[row for index,row in enumerate(data) if index not in seen]
    if not kept:raise ValueError('Không còn dòng hợp lệ để xác nhận.')
    updated=dict(payload)
    if excluded:
        updated['items']=kept
        updated['skipped_errors']=payload.get('skipped_errors',[])+errors
    details=preview_details(updated,result)
    return updated,details

def result_text(job):
    payload=json.loads(job['payload']); data=items(payload)
    try:
        rows=decode_results(payload,job['result'] or '')
    except (ValueError,TypeError):
        success=job['state']=='succeeded'
        rows=[{'co':job['result'] if success else '', 'error':'' if success else (job['result'] or 'Chưa có kết quả.')} for _ in data]
    count=sum(bool(row['co']) for row in rows)
    blocks=[f"Kết quả CO — {job['id']}: {count}/{len(data)} có mã CO"]
    skipped=duplicate_notice(payload.get('skipped_duplicates',[]))
    if skipped:blocks.append(skipped)
    rejected=row_error_notice(payload.get('skipped_errors',[]))
    if rejected:blocks.append(rejected)
    for n,(item,row) in enumerate(zip(data,rows),1):
        icon='✅' if row['co'] and not row['error'] else '⚠️' if row['co'] or row.get('state',job['state'])=='unknown' else '❌'
        product=item.get('product_name') or 'MSP: '+item['product']+' (MWG chưa trả tên)'
        block=f"{icon} {n}. {item['source']} → {item['destination']}\n{product}\nSố lượng: {item['quantity']}"
        if row['co']:block+='\nCO: '+row['co']
        if row['error']:block+='\n'+row['error']
        blocks.append(block)
    if job['state']=='unknown':
        blocks.append('Có dòng chưa rõ kết quả. Kiểm tra MWG trước khi tạo lại; không gửi lại các dòng đã có mã CO.')
    return '\n\n'.join(blocks)


def note_group_text(job):
    """Only confirmed successful rows; no historical backfill or guessed COs."""
    payload=json.loads(job['payload']); data=items(payload)
    try:
        rows=decode_results(payload,job['result'] or '')
    except (ValueError,TypeError):
        if len(data)!=1 or job['state']!='succeeded' or not re.fullmatch(r'[0-9A-Z]+CO[0-9]+',job['result'] or ''):
            return ''
        rows=[{'co':job['result'],'error':''}]
    blocks=[]
    for item,row in zip(data,rows):
        if row['co'] and not row['error']:
            blocks.append(f"Tên sản phẩm: {item.get('product_name','Chưa lấy được tên sản phẩm từ MWG')}\nCO: {row['co']}\nSố lượng: {item['quantity']}")
    if not blocks:
        return ''
    return f"Đã tạo CO — {job['id']}\nNgười yêu cầu: {payload.get('requester_name') or job['owner']}\n\n"+'\n\n'.join(blocks)


def preview_details(payload,result):
    data=json.loads(result)
    rows=data.get('rows') if isinstance(data,dict) else None
    if not isinstance(rows,list) or len(rows)!=len(items(payload)):
        raise ValueError('Sai số dòng thông tin MWG.')
    for item,row in zip(items(payload),rows):
        if not isinstance(row,dict) or any(not isinstance(row.get(k),str) or not row[k].strip() or len(row[k])>500 for k in ('product_name','source_name','destination_name')):
            raise ValueError('Thông tin MWG không hợp lệ.')
        for key in ('source','destination'):
            match=re.match(r'^(\d+)\b',row[key+'_name'].strip())
            if not match or int(match.group(1))!=int(item[key]):
                raise ValueError('Mã kho MWG không khớp.')
    return rows


def line_text_messages(text):
    messages=[{'type':'text','text':part} for part in message_chunks(text)]
    from co_forward import ReplyText
    if isinstance(text,ReplyText) and text.quick_actions:
        messages[-1]['quickReply']={'items':[{'type':'action','action':{'type':'message','label':label,'text':command}}
            for label,command in text.quick_actions]}
        return messages
    match=re.match(r'^Xác nhận tạo CO — ([0-9a-f]{10})\b',text,re.IGNORECASE)
    if not match and text.startswith('🏅 ') and '\nMời ' in text:
        match=re.search(r'(?m)^XACNHAN ([0-9a-f]{10})\nHUY \1\n\n(?:⏳ )?Hiệu lực: (?:1|5) phút$',text)
    if match:
        jid=match.group(1)
        messages[-1]['quickReply']={'items':[{'type':'action','action':{'type':'message','label':label,'text':command}} for label,command in
            [('Xác nhận','XACNHAN '+jid),('Hủy','HUY '+jid)]]}
    return messages
