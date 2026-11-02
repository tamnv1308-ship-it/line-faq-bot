import os
"""Week/month/MTD replacements for the daily model-comparison photos."""
import calendar
import hashlib
import json
import re
import sqlite3
from datetime import date, timedelta
from decimal import Decimal as D, getcontext
from pathlib import Path

from period_overview import category, formatted, growth, previous_month
from report_comparison import CATEGORIES, numeric_data, parse_time, validate_data, percent, save_json
from report_order import model_order
from report_product_labels import watch_labels, case_labels, source_fallback_labels


def empty():
    return {'total':['0','0'],'models':{}}


def add_to(data, label, group, qty, revenue):
    item=data['models'].setdefault(label,{'category':group,'values':['0','0']})
    if item['category']!=group:
        raise ValueError('Model thuộc nhiều nhóm: '+label)
    for i,value in enumerate((qty,revenue)):
        item['values'][i]=str(D(item['values'][i])+value)
        data['total'][i]=str(D(data['total'][i])+value)


def merge(a,b):
    for name,item in b['models'].items():
        add_to(a,name,item['category'],*(D(x) for x in item['values']))
    return a


def normalize(name):
    name=re.sub(r'\bMacbook\b','MacBook',' '.join(name.split()),flags=re.I)
    return re.sub(r'\biPad 11\b(?! M\d)','iPad A16',name)


def labels_from_workbook(path):
    from openpyxl import load_workbook
    result={}
    wb=load_workbook(path,read_only=True,data_only=True)
    try:
        for sheet in wb:
            for row in sheet.iter_rows(min_row=2,values_only=True):
                if len(row)>3 and row[1] and row[3]:
                    result.setdefault(str(row[1]).removesuffix('.0').zfill(13),normalize(str(row[3])))
    finally:wb.close()
    return result


def fallback(name,industry):
    name=normalize(name)
    if industry=='Điện thoại':
        m=re.search(r'(iPhone.*?)\s+\d+(?:GB|TB)\b',name)
        if m:return m[1]
    if industry=='Tablet':
        m=re.search(r'(iPad.*?)\s+(?:Wifi|Wi-Fi|\d+(?:GB|TB))\b',name,re.I)
        if m:return m[1]
    if industry=='Laptop':
        m=re.match(r'(MacBook (?:Air|Neo|Pro) \d+) inch (.*?) \d+GB\b',name,re.I)
        if m:return m[1]+' '+m[2]
    if industry=='IT':
        m=re.match(r'(Mac (?:Mini|mini|Studio).*?|iMac.*?) \d+GB\b',name)
        if m:return m[1]
    if industry=='Wearable':return watch_labels(name)[0]
    if 'AirPods' in name:
        m=re.search(r'AirPods (?:Pro(?: \d+)?|Max(?: \d+)?|\d+)',name)
        if m:return m[0]
    if name.startswith('Ốp lưng'):return case_labels(name)[0]
    for prefix,label in [('Adapter','Adapter Sạc'),('Cáp','Cáp sạc'),('Bút','Apple Pencil'),('Tai nghe','Earpods'),('Bàn phím','Bàn phím Apple'),('Bàn di','Trackpad'),('Chuột','Mouse'),('Bao da','Ốp iPad'),('Thiết bị','AirTag'),('Ví','Ví MagSafe'),('Dây','Dây đeo')]:
        if name.startswith(prefix):return label
    return source_fallback_labels(name,industry)[0]


def history(root,day):
    getcontext().prec=max(getcontext().prec,64)
    dictionary_path=root/'inputs/ten_viet_tat.xlsx'
    mapping=labels_from_workbook(dictionary_path)
    with sqlite3.connect('file:'+str(root/'.private/sales-history.sqlite3')+'?mode=ro',uri=True,timeout=10) as db:
        db.execute('BEGIN')
        coverage=db.execute('SELECT day,industry,source_id,final,as_of FROM coverage WHERE day<? ORDER BY day,industry',(day.isoformat(),)).fetchall()
        digest=hashlib.sha256(json.dumps(coverage).encode()+dictionary_path.read_bytes()).hexdigest()
        cache=root/'.private/period-model-cache.json'
        if cache.exists():
            saved=json.loads(cache.read_text())
            if saved.get('schema')==2 and saved.get('digest')==digest:return saved['days']
        selected={}
        for stamp,industry,source_id,final,as_of in coverage:
            if final:selected.setdefault(stamp,set()).add(industry)
        result={stamp:empty() for stamp,groups in selected.items() if len(groups)==6}
        products={}
        query='''SELECT f.day,f.industry,f.product,p.name,f.quantity,f.revenue_raw
            FROM coverage c JOIN facts f ON f.source_id=c.source_id AND f.day=c.day AND f.industry=c.industry
            JOIN products p ON p.code=f.product
            WHERE c.day<? AND c.final=1 AND f.status='Mới' '''
        for stamp,industry,code,name,qty,revenue in db.execute(query,(day.isoformat(),)):
            if stamp not in result:continue
            key=(industry,code)
            if key not in products:
                group={'Điện thoại':0,'Tablet':1,'Laptop':2,'IT':2,'Wearable':3}.get(industry,4 if 'AirPods' in name else 5)
                products[key]=(mapping.get(code) or fallback(name,industry),group)
            label,group=products[key]
            add_to(result[stamp],label,group,D(qty),D(revenue)*D('1.08'))
    for value in result.values():validate_data(value)
    save_json(cache,{'schema':2,'digest':digest,'days':result})
    return result


def sum_days(days,start,end):
    result=empty()
    while start<=end:
        value=days.get(start.isoformat())
        if value is None:return None
        merge(result,value);start+=timedelta(days=1)
    return result


def ranges(day):
    monday=day-timedelta(days=day.weekday())
    month_end=day.replace(day=1)-timedelta(days=1)
    prior_end=month_end.replace(day=1)-timedelta(days=1)
    return [
        ('TUẦN',monday-timedelta(days=7),monday-timedelta(days=1),monday-timedelta(days=14),monday-timedelta(days=8)),
        ('THÁNG',month_end.replace(day=1),month_end,prior_end.replace(day=1),prior_end),
        ('LŨY KẾ THÁNG',day.replace(day=1),day,previous_month(day).replace(day=1),previous_month(day)),
    ]


def snapshot_data(root,slot,exported,day):
    path=root/'.private/sales-snapshots'/day.isoformat()/(slot.strftime('%H%M')+'.json')
    try:
        saved=json.loads(path.read_text());old=parse_time(saved['slot']);actual=parse_time(saved['exported_at'])
        if (saved.get('schema')!=1 or saved.get('revenue_vat_applied') is not True
                or saved.get('report_date')!=day.isoformat() or old.date()!=day
                or old.time()!=slot.time() or not 0<=(actual-old).total_seconds()<600
                or abs((actual-old).total_seconds()-(exported-slot).total_seconds())>180):return None
        validate_data(saved['data']);return saved['data']
    except (OSError,ValueError,KeyError,TypeError,AssertionError):return None


def compare(root,report,metadata,slot,days=None):
    exported=parse_time(metadata['exported_at_vn'])
    if report['report_date']!=slot.date().isoformat() or not 0<=(exported-slot).total_seconds()<600:
        raise ValueError('Sai mốc so sánh')
    if days is None:days=history(root,slot.date())
    result=[]
    for index,(title,start,end,old_start,old_end) in enumerate(ranges(slot.date())):
        if index<2:
            current=sum_days(days,start,end);previous=sum_days(days,old_start,old_end)
        else:
            current=sum_days(days,start,end-timedelta(days=1))
            if current is not None:merge(current,numeric_data(report))
            previous=sum_days(days,old_start,old_end-timedelta(days=1))
            endpoint=snapshot_data(root,slot,exported,old_end)
            previous=merge(previous,endpoint) if previous is not None and endpoint is not None else None
        for value in (current,previous):
            if value is not None:validate_data(value)
        result.append({'title':title,'start':str(start),'end':str(end),'previous_start':str(old_start),'previous_end':str(old_end),
                       'basis':'same_clock' if index==2 else 'full_period','slot':slot.isoformat(),'current':current,'previous':previous})
    return result


def rows(period):
    now,before=period['current'],period['previous']
    def values(data,group=None,name=None):
        if data is None:return [None,None]
        if name is not None:return [D(x) for x in data['models'].get(name,{'values':['0','0']})['values']]
        if group is None:return [D(x) for x in data['total']]
        return [sum((D(item['values'][i]) for item in data['models'].values() if item['category']==group),D(0)) for i in range(2)]
    def row(label,kind,group=None,name=None):
        a,b=values(now,group,name),values(before,group,name)
        return {'label':label,'kind':kind,'current':a,'previous':b,'growth':[percent(a[i],b[i]) if a[i] is not None and b[i] is not None else None for i in range(2)]}
    result=[row('TỔNG','total')]
    union=dict(before['models']) if before else {};union.update(now['models'] if now else {})
    for group,label in enumerate(CATEGORIES):
        result.append(row(label,'category',group))
        for name in sorted((name for name,item in union.items() if item['category']==group),key=lambda n:model_order(n,group)):
            result.append(row(name,'model',group,name))
    return result


def combined_rows(periods):
    """One shared model order, including models present in any compared period."""
    models={}
    for period in periods:
        for side in ('current','previous'):
            for name,item in (period[side] or {'models':{}})['models'].items():
                if name in models and models[name]!=item['category']:
                    raise ValueError('Model khác nhóm giữa các kỳ: '+name)
                models[name]=item['category']
    keys=[('total','TỔNG')]
    for group,label in enumerate(CATEGORIES):
        keys.append(('category',label))
        keys.extend(('model',name) for name in sorted((n for n,g in models.items() if g==group),key=lambda n:model_order(n,group)))
    tables=[{(r['kind'],r['label']):r for r in rows(p)} for p in periods]
    result=[]
    for kind,label in keys:
        metrics=[]
        for period,table in zip(periods,tables):
            item=table.get((kind,label))
            if item is None:
                a=[D(0),D(0)] if period['current'] is not None else [None,None]
                b=[D(0),D(0)] if period['previous'] is not None else [None,None]
                item={'current':a,'previous':b,'growth':[percent(a[i],b[i]) if a[i] is not None and b[i] is not None else None for i in range(2)]}
            metrics.append(item)
        result.append({'label':label,'kind':kind,'periods':metrics})
    return result


def render_combined(periods,directory):
    from PIL import Image,ImageDraw,ImageFont
    assert len(periods)==3
    font_dir=Path(os.environ['TAOWORK_REPORT_ROOT']) / 'fonts'
    fonts={}
    def font(n,b=False):
        key=(n,b)
        if key not in fonts:fonts[key]=ImageFont.truetype(str(font_dir/('Arial Bold.ttf' if b else 'Arial.ttf')),n)
        return fonts[key]
    table=combined_rows(periods)
    parts=[table[i:i+34] for i in range(0,len(table),34)]
    paths=[]
    for part,items in enumerate(parts):
        width=2000;left=24;name_w=500;cell_w=242;top=270;row_h=66
        height=top+len(items)*row_h+42
        image=Image.new('RGB',(width,height),'white');draw=ImageDraw.Draw(image)
        def text(s,x,y,size=26,bold=False,color='#101010',anchor='la',max_width=None):
            while max_width and draw.textlength(s,font=font(size,bold))>max_width and size>17:size-=1
            if max_width and draw.textlength(s,font=font(size,bold))>max_width:raise ValueError('Tên model quá dài: '+s)
            draw.text((x,y),s,font=font(size,bold),fill=color,anchor=anchor)
        slot=parse_time(periods[0]['slot'])
        text('SO SÁNH TUẦN · THÁNG · LŨY KẾ THÁNG',left,20,36,True)
        text('Cập nhật '+slot.strftime('%d/%m/%Y · %H:%M')+' | DT: tỷ đồng | Số kỳ này; % so với kỳ trước | Mới',left,73,24,color='#667085')
        draw.rectangle((left,120,left+name_w,top),fill='#FFC000',outline='#D5B44A')
        text('NHÓM / MODEL',left+name_w/2,179,28,True,anchor='ma')
        for index,period in enumerate(periods):
            x=left+name_w+index*cell_w*2
            draw.rectangle((x,120,x+cell_w*2,226),fill='#FFC000',outline='#D5B44A')
            text(period['title'],x+cell_w,130,28,True,anchor='ma')
            def span(prefix):
                a=date.fromisoformat(period[prefix+'start']);b=date.fromisoformat(period[prefix+'end'])
                return a.strftime('%d/%m')+'–'+b.strftime('%d/%m/%y')
            text(span(''),x+cell_w,169,23,anchor='ma')
            text('so với '+span('previous_'),x+cell_w,196,21,anchor='ma',color='#545454')
            for metric,label in enumerate(('SL','DT (tỷ)')):
                draw.rectangle((x+metric*cell_w,226,x+(metric+1)*cell_w,top),fill='#FFF2CC',outline='#D8DDE3')
                text(label,x+(metric+.5)*cell_w,234,25,True,anchor='ma')
        for line,row in enumerate(items):
            y=top+line*row_h
            fill='#FFF000' if row['kind']=='total' else '#F8CBAD' if row['kind']=='category' else ('#FFFFFF' if line%2 else '#F8FAFC')
            draw.rectangle((left,y,left+name_w,y+row_h),fill=fill,outline='#D8DDE3')
            text(row['label'],left+12,y+20,26,row['kind']!='model',max_width=name_w-24)
            for index,item in enumerate(row['periods']):
                for metric in range(2):
                    x=left+name_w+(index*2+metric)*cell_w
                    draw.rectangle((x,y,x+cell_w,y+row_h),fill=fill,outline='#D8DDE3')
                    text(formatted(item['current'][metric],metric==1),x+cell_w-14,y+7,27,True,anchor='ra',max_width=cell_w-28)
                    v=item['growth'][metric]
                    color='#667085' if v is None or abs(v)<D('0.05') else '#16834A' if v>0 else '#D3313D'
                    text(growth(v),x+cell_w-14,y+38,22,True,color,'ra',cell_w-28)
        note='—: chưa đủ dữ liệu cùng mốc' if any(p['previous'] is None for p in periods) else 'Tuần / tháng: trọn kỳ · Lũy kế tháng: đến giờ báo cáo'
        text(note,left,height-31,20,color='#667085')
        text(str(part+1)+'/'+str(len(parts)),width-24,height-31,20,color='#667085',anchor='ra')
        path=Path(directory)/('04_Tuan_Thang_LuyKe-'+str(part+1).zfill(2)+'.jpg')
        image.save(path,'JPEG',quality=90,subsampling=0,optimize=True);image.close()
        assert path.stat().st_size<10*1024*1024 and width+height<10000
        paths.append(str(path))
    return paths


def build(root,report,metadata,slot,directory):
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    periods=compare(root,report,metadata,slot)
    paths=render_combined(periods,directory)
    save_json(directory/'period-model-comparison.json',{'schema':2,'layout':'combined','periods':periods,'photos':paths})
    return paths
