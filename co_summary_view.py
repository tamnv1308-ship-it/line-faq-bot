"""Deterministic dashboard image, rendered on the server without Chrome."""
import json, re, math, secrets
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
from co_results import items, decode_results


def details(jobs, stores, tz):
    groups={k:defaultdict(set) for k in ('people','source','destination','region','province','product')}
    quantities={k:Counter() for k in groups}; requests=Counter();labels={}; hourly=defaultdict(set);recent=[];seen=set()
    for j in sorted(jobs,key=lambda r:(r.get('created',0),r.get('id',''))):
        p=json.loads(j['payload']);rows=items(p);person=j['owner'];requests[person]+=1
        labels[('people',person)]=p.get('requester_name') or 'Chưa có tên'
        stamp=datetime.fromtimestamp(j.get('created',0),tz)
        try:results=decode_results(p,j.get('result') or '')
        except (ValueError,TypeError):
            co=j.get('result') or ''
            valid=len(rows)==1 and j['state']=='succeeded' and re.fullmatch(r'[0-9A-Z]+CO[0-9]+',co)
            results=[{'co':co if valid else '', 'error':''} for _ in rows]
        for item,result in zip(rows,results):
            success=bool(result['co']) and not result['error'];qty=int(item['quantity'])
            state='Thành công' if success else 'Chưa rõ' if j['state'] in ('unknown','succeeded') else 'Lỗi' if result['error'] or j['state']=='failed' else 'Đã hủy/hết hạn' if j['state'] in ('cancelled','expired') else 'Đang chờ'
            recent.append(dict(time=stamp.strftime('%d/%m %H:%M'),person=labels[('people',person)],source=str(item['source']),destination=str(item['destination']),product=item.get('product_name') or 'Chưa có tên sản phẩm',quantity=qty,co=result['co'] or '—',state=state))
            if not success:continue
            key=(result['co'],item['source'],item['destination'],item['product'],qty)
            if key in seen:continue
            seen.add(key);hourly[stamp.hour].add(result['co'])
            source=stores.get(str(item['source']),{})
            keys=dict(people=person,source=str(item['source']),destination=str(item['destination']),region=source.get('region','Chưa phân vùng'),province=source.get('province','Chưa phân vùng'),product=item['product'])
            for group,value in keys.items():groups[group][value].add(result['co']);quantities[group][value]+=qty
            labels[('product',item['product'])]=item.get('product_name') or 'Chưa có tên sản phẩm'
            for side in ('source','destination'):
                code=str(item[side]);labels[(side,code)]=stores.get(code,{}).get('name') or item.get(side+'_name') or 'Chưa có tên kho'
    # A CO can span multiple lines: count it once in the hourly series.
    assigned=set();hours=[]
    for h in range(24):
        codes=hourly[h]-assigned;assigned.update(hourly[h]);hours.append(len(codes))
    ranked={k:sorted([(v,len(codes),quantities[k][v]) for v,codes in table.items()],key=lambda r:(-r[1],r[0]))[:5] for k,table in groups.items()}
    return dict(ranked=ranked,labels=labels,requests=requests,hours=hours,recent=list(reversed(recent))[:5])


def draw_dashboard(jobs,stores,start,end,directory,stats,tz):
    info=details(jobs,stores,tz)
    W,H=2400,1900;im=Image.new('RGB',(W,H),'#f2f6fa');d=ImageDraw.Draw(im)
    navy='#102b50';ink='#122e51';muted='#657b94';green='#07976b';line='#e2eaf2';red='#e55367';amber='#edab34'
    fonts=[('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf','/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'),('/System/Library/Fonts/Supplemental/Arial.ttf','/System/Library/Fonts/Supplemental/Arial Bold.ttf')]
    normal,bold=next(pair for pair in fonts if Path(pair[0]).exists());cache={}
    def font(size,b=False):
        key=(size,b)
        if key not in cache:cache[key]=ImageFont.truetype(bold if b and Path(bold).exists() else normal,size)
        return cache[key]
    def text(x,y,s,size=26,color=ink,b=False,anchor=None):d.text((x,y),str(s),font=font(size,b),fill=color,anchor=anchor)
    def fit(s,width,size=25,b=False):
        s=str(s)
        if d.textlength(s,font=font(size,b))<=width:return s
        while s and d.textlength(s+'…',font=font(size,b))>width:s=s[:-1]
        return s.rstrip()+'…'
    def card(x,y,w,h):d.rounded_rectangle((x,y,x+w,y+h),radius=14,fill='white',outline=line,width=2)
    def badge(x,y,n):
        color='#ffe3a2' if n==1 else '#e9f0f7';d.ellipse((x,y,x+32,y+32),fill=color);text(x+16,y+16,n,20,ink,True,'mm')
    # A compact brand rail, not simulated clickable navigation.
    d.rectangle((0,0,112,H),fill=navy);text(56,53,'CO',36,'white',True,'mm')
    for yy in (175,260,345):
        d.rounded_rectangle((34,yy,78,yy+38),6,outline='#a9c3df',width=3)
        d.line((44,yy+28,44,yy+17,55,yy+17,55,yy+10,66,yy+10),fill='#a9c3df',width=3)
    text(56,H-46,'7D',25,'#a9c3df',True,'mm')
    d.rectangle((112,0,W,94),fill='white');text(150,23,'APPLE BOT',44,navy,True);text(438,29,'|  Tổng kết CO • '+str((end-start).days)+' ngày',37,navy)
    text(2348,35,'BÁO CÁO RIÊNG • TÂM 258330',23,muted,False,'ra')
    card(150,111,2200,65)
    dates=start.strftime('%d/%m/%Y')+' — '+(end-timedelta(days=1)).strftime('%d/%m/%Y')
    text(176,129,dates,25,ink,True);text(670,129,'Tất cả vùng  /  Tất cả tỉnh, thành  /  Tất cả kênh',24,muted)
    text(2322,129,'Giờ Việt Nam',24,muted,False,'ra')
    cards=[('Tổng yêu cầu',stats['requests'],navy),('Mã CO thành công',stats['co'],green),('SL sản phẩm',stats['quantity'],navy),('Dòng lỗi',stats['failed'],red),('Dòng đang chờ',stats['pending'],amber),('Dòng chưa rõ',stats['unknown'],amber)]
    cw=(2200-5*16)//6
    for i,(label,value,color) in enumerate(cards):
        x=150+i*(cw+16);card(x,194,cw,147);d.ellipse((x+20,213,x+58,251),fill='#eaf3f6');text(x+75,218,label,24,muted);text(x+26,261,value,47,color,True)
    # Hourly successful CO trend. Uses recorded request time, never invents completion latency.
    card(150,359,1434,310);text(178,378,'CO thành công theo giờ ghi nhận',30,ink,True)
    text(178,420,'Gộp các ngày trong kỳ • Mỗi mã CO tính một lần',21,muted)
    left,right,top,bottom=213,1534,470,620;values=info['hours'];maximum=max(4,max(values));maximum=math.ceil(maximum/4)*4
    for i in range(5):
        y=bottom-i*(bottom-top)/4;d.line((left,y,right,y),fill=line,width=2);text(left-18,y,str(int(maximum*i/4)),20,muted,False,'rm')
    pts=[(left+h*(right-left)/23,bottom-v/maximum*(bottom-top)) for h,v in enumerate(values)]
    if sum(values):d.polygon([(left,bottom)]+pts+[(right,bottom)],fill='#dcf3e9')
    d.line(pts,fill=green,width=4)
    for h in range(24):
        if h%3==0 or h==23:text(pts[h][0],636,f'{h:02}h',19,muted,False,'ma')
        if values[h]:d.ellipse((pts[h][0]-5,pts[h][1]-5,pts[h][0]+5,pts[h][1]+5),fill=green)
    if not sum(values):text(870,538,'Chưa có CO thành công',25,muted,False,'mm')
    # Outcome denominator is transfer rows, not request count or distinct CO count.
    card(1602,359,748,310);text(1628,378,'Kết quả xử lý theo dòng',30,ink,True)
    outcomes=[('Thành công',stats['success_rows'],green),('Lỗi',stats['failed'],red),('Đang chờ',stats['pending'],amber),('Chưa rõ',stats['unknown'],'#8b77ba'),('Hủy / hết hạn',stats['cancelled'],'#a3b1c1')]
    total=sum(v for _,v,_ in outcomes);box=(1640,452,1840,652);angle=-90
    if not total:d.ellipse(box,fill=line)
    for label,count,color in outcomes:
        if count:d.pieslice(box,start=angle,end=angle+360*count/total,fill=color);angle+=360*count/total
    d.ellipse((1683,495,1797,609),fill='white');text(1740,544,total,32,ink,True,'mm');text(1740,578,'dòng',19,muted,False,'mm')
    for i,(label,count,color) in enumerate(outcomes):
        y=450+i*40;d.ellipse((1870,y+7,1885,y+22),fill=color);text(1900,y,label,23);text(2316,y,f'{count}  ·  {count/total*100:.1f}%' if total else '0',23,muted,False,'ra')
    # Six compact Top 5 panels in a three-column grid.
    titles={'people':'TOP 5 người yêu cầu','source':'TOP 5 kho xuất','destination':'TOP 5 kho nhận','region':'TOP 5 vùng xuất','province':'TOP 5 tỉnh/thành xuất','product':'TOP 5 sản phẩm'}
    for n,(kind,title) in enumerate(titles.items()):
        x=150+(n%3)*740;y=687+(n//3)*346;w=720;card(x,y,w,328);text(x+22,y+18,title,28,ink,True)
        d.rounded_rectangle((x+16,y+63,x+w-16,y+102),7,fill='#edf3f8')
        text(x+28,y+71,'#',20,muted,True)
        is_geo=kind in ('region','province');namewidth=420 if is_geo else 390
        namehead={'people':'Người yêu cầu','source':'Mã kho · Tên kho','destination':'Mã kho · Tên kho','region':'Vùng','province':'Tỉnh/thành','product':'Sản phẩm'}[kind]
        text(x+70,y+71,namehead,20,muted,True)
        if kind=='people':text(x+575,y+71,'Yêu cầu',20,muted,True,'ra')
        elif not is_geo:text(x+575,y+71,'SL',20,muted,True,'ra')
        text(x+684,y+71,'CO',20,muted,True,'ra')
        rows=info['ranked'][kind]
        if not rows:text(x+28,y+159,'Chưa có dữ liệu thành công',25,muted)
        for i,(key,count,qty) in enumerate(rows):
            yy=y+111+i*41;badge(x+25,yy,i+1)
            label=info['labels'].get((kind,key),key)
            if kind in ('source','destination'):label=key+' · '+label
            if kind=='region':label=label.removeprefix('Vùng ')
            if kind=='province':label=label.removeprefix('Thành phố ').removeprefix('Tỉnh ')
            text(x+70,yy+3,fit(label,namewidth,22),22)
            if is_geo:
                barx=x+510;d.rounded_rectangle((barx,yy+10,barx+114,yy+25),4,fill='#edf3f8');d.rounded_rectangle((barx,yy+10,barx+max(2,114*count/rows[0][1]),yy+25),4,fill=green)
            else:text(x+575,yy+3,info['requests'][key] if kind=='people' else qty,22,ink,False,'ra')
            text(x+684,yy+3,count,22,green,True,'ra')
            if i<4:d.line((x+20,yy+37,x+w-20,yy+37),fill=line)
    # Latest records, with explicit no-data display and no mock interactions.
    card(150,1380,2200,365);text(178,1398,'Chi tiết CO gần đây',30,ink,True);text(2320,1407,'5 dòng gần nhất trong kỳ',23,muted,False,'ra')
    cols=[(176,170,'Giờ ghi nhận'),(360,280,'Người yêu cầu'),(660,370,'Kho xuất → Kho nhận'),(1050,570,'Sản phẩm'),(1644,90,'SL'),(1754,310,'Mã CO'),(2090,230,'Kết quả')]
    d.rounded_rectangle((170,1451,2330,1494),6,fill='#edf3f8')
    for x,width,label in cols:text(x+5,1460,label,22,muted,True)
    recent=info['recent']
    if not recent:text(180,1531,'Chưa có yêu cầu trong khoảng ngày này.',27,muted)
    for i,row in enumerate(recent):
        yy=1508+i*43;vals=[row['time'],row['person'],row['source']+' → '+row['destination'],row['product'],row['quantity'],row['co'],row['state']]
        for (x,width,_),value in zip(cols,vals):text(x+5,yy,fit(value,width-15,22),22,green if value=='Thành công' else red if value=='Lỗi' else ink)
        d.line((170,yy+36,2330,yy+36),fill=line)
    text(150,1764,'Top 5 xếp theo mã CO thành công • SL: số sản phẩm • Vùng/tỉnh theo kho xuất • Kho thiếu danh mục: Chưa phân vùng',23,muted)
    text(150,1804,'Một CO có thể có nhiều dòng. Biểu đồ dùng giờ ghi nhận yêu cầu, không phải thời điểm MWG tạo xong.',23,muted)
    text(150,1844,'!tongket: hôm nay • !tongket 7ngay: 7 ngày • Chỉ dữ liệu BOT đã ghi nhận',22,muted);text(2350,1844,'Cập nhật '+datetime.now(tz).strftime('%H:%M %d/%m/%Y'),22,muted,False,'ra')
    directory.mkdir(parents=True,exist_ok=True);name=secrets.token_hex(24)+'.png';im.save(directory/name,optimize=True);return name
