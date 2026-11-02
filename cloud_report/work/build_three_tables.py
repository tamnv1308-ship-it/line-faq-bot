import os
from pathlib import Path
from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP
import re, json, argparse
from datetime import datetime, date
from openpyxl import load_workbook
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.colors import HexColor
from pypdf import PdfReader, PdfWriter
from report_product_labels import watch_labels, case_labels, source_fallback_labels

ROOT=Path(os.environ['TAOWORK_REPORT_ROOT'])
parser=argparse.ArgumentParser()
parser.add_argument('--input',type=Path,default=ROOT/'inputs/bi_moi_ngay_20261014_225541.xlsx')
parser.add_argument('--out',type=Path,default=ROOT/'outputs/baocao_3_bang_model')
parser.add_argument('--date',default='2026-10-14')
parser.add_argument('--snapshot',default='22:55')
parser.add_argument('--abbreviations',type=Path,default=ROOT/'inputs/ten_viet_tat.xlsx')
parser.add_argument('--checks',type=Path,default=ROOT/'work/three_tables_model_checks.json')
parser.add_argument('--combined',type=Path,default=ROOT/'outputs/Apple_Bao_Cao_3_Bang.pdf')
parser.add_argument('--metrics-only',action='store_true')
args=parser.parse_args()
REPORT_DATE=date.fromisoformat(args.date)
REPORT_DATE_TEXT=REPORT_DATE.strftime('%d/%m/%Y')
OUT=args.out
OUT.mkdir(parents=True,exist_ok=True)
SOURCE=args.input
FONT=Path(os.environ['TAOWORK_REPORT_ROOT']) / 'fonts'
pdfmetrics.registerFont(TTFont('ArialVN',str(FONT/'Arial.ttf')))
pdfmetrics.registerFont(TTFont('ArialVN-Bold',str(FONT/'Arial Bold.ttf')))
wb=load_workbook(SOURCE,read_only=True,data_only=True)
detail_sheets=[s for s in wb.sheetnames if s.startswith('GiaVonLaiGopHangNgay_')]
assert detail_sheets,'Không tìm thấy sheet dữ liệu BI MỖI NGÀY'
expected_headers=['MÃ SẢN PHẨM','TÊN SẢN PHẨM','LÀ HTX BÁN HÀNG?','TÊN TÌNH TRẠNG SP','HÃNG SẢN XUẤT','NGÀNH HÀNG','KÊNH BÁN HÀNG','MÃ SIÊU THỊ','SIÊU THỊ','TÊN THƯƠNG HIỆU','TỈNH/THÀNH','KHU VỰC RSM','NGÀY','THÁNG','SỐ LƯỢNG (SUM)','DOANH THU (SUM)','LÃI GỘP (SUM)']
data=[]
for sheet in detail_sheets:
    values=iter(wb[sheet].values)
    headers=next(values)
    assert list(headers[:17])==expected_headers,'Cấu trúc mẫu MWG đã thay đổi'
    data.extend(r for r in values if r[0] is not None)
def source_date(value):
    if isinstance(value,datetime):return value.date()
    if isinstance(value,date):return value
    return datetime.strptime(str(value).strip(),'%Y/%m/%d').date()
assert all(source_date(r[12])==REPORT_DATE and r[4]=='Apple' and r[3]=='Mới' for r in data),'Ngày/hãng/trạng thái không đúng bộ lọc'
assert set(r[9] for r in data)<={'Thế Giới Di Động','Điện Máy Xanh','TopZone'}
assert all(r[6] in ['Kênh Offline','Kênh Online'] for r in data),'Có kênh bán chưa được nhận diện'
D=Decimal
from report_numbers import configure_precision
configure_precision(value for row in data for value in (row[14], row[15]))
FACTOR=D('1.08')
ZERO=(D(0),D(0))

def add(a,b):return tuple(x+y for x,y in zip(a,b))
def amt(r):return (D(str(r[14])),D(str(r[15]))*FACTOR)
def total(rs):
    out=ZERO
    for r in rs:out=add(out,amt(r))
    return out
TOTAL=total(data)
assert all(D(str(r[14]))==D(str(r[14])).to_integral_value() for r in data),'Số lượng không nguyên'
if 'Sheet1' in wb:
    pivot_rows=[r for r in wb['Sheet1'].values if r[0] in ['Grand Total','Tổng cộng','Tổng']]
    if pivot_rows:
        pivot=pivot_rows[-1]
        assert D(str(pivot[1]))==TOTAL[0]
        assert abs(TOTAL[1]-D(str(pivot[2]))*FACTOR)<D('0.01')
def integer(n):return f'{int(n):,}'.replace(',','.')
def decimal(n,places=2):
    q=D(1).scaleb(-places)
    n=D(n).quantize(q,rounding=ROUND_HALF_UP)
    if n==0:n=abs(n)
    return f'{n:,.{places}f}'.replace(',','~').replace('.',',').replace('~','.')
def revenue_text(v):return decimal(v/D('1000000000'),places=0)
def formatted(v):return [integer(v[0]),revenue_text(v[1]),decimal(v[0]/TOTAL[0]*100 if TOTAL[0] else D(0))+'%']
def channel(r):return 'tz' if r[9]=='TopZone' else 'mwg'

def raw_keys(r):
    n=' '.join(r[1].split())
    if r[5]=='Điện thoại':
        m=re.match(r'Điện thoại (iPhone.*?) (\d+(?:GB|TB))\b',n)
        assert m,n
        return m[1],f'{m[1]} {m[2]}'
    if r[5]=='Laptop':
        m=re.match(r'Macbook (Air|Neo|Pro) (\d+) inch (.*?) (\d+)GB - (\d+(?:GB|TB))\b',n)
        assert m,n
        fam=f'MacBook {m[1]} {m[2]} {m[3]}'
        return fam,f'{fam} {m[4]}GB/{m[5]}'
    if r[5]=='IT':
        m=re.match(r'(Mac Mini .*?) (\d+)GB - (\d+(?:GB|TB))\b',n)
        assert m,n
        return m[1],f'{m[1]} {m[2]}GB/{m[3]}'
    if r[5]=='Tablet':
        m=re.match(r'Máy tính bảng (iPad.*?) (Wifi(?: Cellular)?) (\d+(?:GB|TB))\b',n)
        assert m,n
        return m[1],f'{m[1]} {m[3]} '+('Cellular' if 'Cellular' in m[2] else 'Wi-Fi')
    if r[5]=='Wearable':
        m=re.match(r'(Apple Watch .*?) (\d+)mm (GPS(?: Cellular)?)\b',n)
        assert m,n
        return m[1],f'{m[1]} {m[2]}mm {m[3]}'
    if 'AirPods' in n:
        x=n[n.index('AirPods'):]
        model=re.split(r' Trắng| Starlight| Xanh| Cam| cổng',x)[0]
        return 'AirPods',model
    prefixes=[('Adapter','Sạc Apple'),('Cáp','Cáp Apple'),('Ốp lưng','Ốp lưng'),('Bút','Apple Pencil'),('Tai nghe','EarPods'),('Bàn phím','Bàn phím Apple'),('Bàn di','Trackpad'),('Chuột','Magic Mouse'),('Bao da','Bao da iPad'),('Thiết bị','AirTag'),('Ví','Ví MagSafe'),('Dây','Dây đeo')]
    for p,f in prefixes:
        if n.startswith(p):return f,n
    raise ValueError('Chưa phân nhóm: '+n)

def clean_name(value):
    text=' '.join(str(value or '').split())
    text=re.sub(r'\bMacbook\b','MacBook',text,flags=re.I)
    text=re.sub(r'\biPad 11\b(?! M\d)','iPad A16',text)
    return text

def product_code(value):
    return str(value).strip().removesuffix('.0').zfill(13)

abbreviation_book=load_workbook(args.abbreviations,read_only=True,data_only=True)
abbreviations={};abbreviation_conflicts=[]
# Sheet1 is the main dictionary; later sheets only fill missing product codes.
for sheet in abbreviation_book:
    for row in list(sheet.values)[1:]:
        if not row[1] or not row[2]:continue
        code=product_code(row[1]);labels=tuple(clean_name(value) for value in row[3:6])
        if not all(labels):continue
        if code in abbreviations and abbreviations[code]!=labels:
            abbreviation_conflicts.append(code)
        abbreviations.setdefault(code,labels)

def parsed_fallback_labels(r):
    name=' '.join(r[1].split())
    bare=re.sub(r'\s+[A-Z0-9]{5,}(?:[A-Z/]+)?$','',name)
    if r[5]=='Wearable':
        return watch_labels(bare)
    if 'AirPods' in name:
        family=re.search(r'AirPods (?:Pro \d+|Max \d+|\d+)\b',name)[0]
        config=family+(' Wireless' if 'sạc không dây' in name else '')
        color=bare.split(family,1)[1].strip() if 'Max' in family else ''
        return family,config,config+(' '+color if color else '')
    if name.startswith('Ốp lưng'):
        return case_labels(bare)
    if name.startswith('Adapter'):
        config=re.sub(r'\s+Trắng$','',bare.replace('Adapter sạc Apple','Adapter sạc'))
        return 'Adapter Sạc',config,config
    if 'AirTag 2' in name:return 'AirTag 2','AirTag 2','AirTag 2 Trắng'
    if name.startswith('Ví'):
        detail=bare.replace('Ví Magsafe Apple FineWoven','Magsafe FineWoven Wallet')
        return 'Magsafe FineWoven Wallet','Magsafe FineWoven Wallet',detail
    if name.startswith('Dây đeo'):
        detail=bare.replace(' Apple','')
        config='Dây đeo '+('cổ tay' if 'cổ tay' in name else 'chéo')+' TechWoven'
        return 'Dây đeo',config,detail
    if name.startswith('Cáp Apple Thunderbolt'):
        detail=bare.replace('Cáp Apple','Cáp')
        return 'Cáp chuyển','Cáp Thunderbolt 5 Pro',detail
    family,configuration=raw_keys(r)
    detail=re.sub(r'^(Điện thoại |Máy tính bảng )','',bare)
    return family,configuration,detail

name_parse_fallback_codes=[]
def fallback_labels(r):
    try:
        return parsed_fallback_labels(r)
    except (AssertionError, ValueError, IndexError, AttributeError):
        name_parse_fallback_codes.append(product_code(r[0]))
        # Product-name variations must not drop sales or stop all four reports.
        return source_fallback_labels(r[1],r[5])

report_labels={};unmapped_codes=[]
for r in data:
    code=product_code(r[0])
    if code in report_labels:continue
    if code in abbreviations:
        report_labels[code]=abbreviations[code]
    else:
        report_labels[code]=tuple(clean_name(x) for x in fallback_labels(r))
        unmapped_codes.append(code)

def keys(r):return report_labels[product_code(r[0])][:2]

from report_order import natural_key, model_order

def metric_record():return {'all':ZERO,'mwg':ZERO,'tz':ZERO}
def accumulate(rec,r):
    v=amt(r)
    rec['all']=add(rec['all'],v);c=channel(r);rec[c]=add(rec[c],v)
def cells(rec):
    return sum((formatted(rec[k]) for k in ['all','mwg','tz']),[])
families=defaultdict(metric_record)
models=defaultdict(metric_record)
products=defaultdict(metric_record)
product_names={}
source_names={}
family_category={}
grand=metric_record()
for r in data:
    family,model=keys(r)
    family_category[family]={'Điện thoại':0,'Tablet':1,'Laptop':2,'IT':2,'Wearable':3}.get(r[5],4 if 'AirPods' in r[1] else 5)
    accumulate(families[family],r);accumulate(models[(family,model)],r)
    accumulate(products[(family,r[0])],r);product_names[r[0]]=report_labels[product_code(r[0])][2]
    source_names[r[0]]=' '.join(r[1].split())
    accumulate(grand,r)
assert grand['all']==TOTAL
assert add(grand['mwg'],grand['tz'])==TOTAL
for bucket in [models,products]:
    assert sum(v['all'][0] for v in bucket.values())==TOTAL[0]
    assert sum(v['all'][1] for v in bucket.values())==TOTAL[1]
family_order=sorted(families,key=lambda f:(family_category[f],model_order(f,family_category[f])))

def summary_model(r):
    return keys(r)[0]

CATEGORY_NAMES=['iPhone','iPad','Mac','Watch','AirPods','Phụ kiện tiện ích']
summary_models=defaultdict(metric_record)
summary_categories=defaultdict(metric_record)
summary_category={}
for r in data:
    line=summary_model(r);category=family_category[keys(r)[0]]
    accumulate(summary_models[line],r);accumulate(summary_categories[category],r)
    summary_category[line]=category
for metric in ['all','mwg','tz']:
    for index in [0,1]:
        assert sum(v[metric][index] for v in summary_models.values())==grand[metric][index]
summary_order=sorted(summary_models,key=lambda name:(summary_category[name],model_order(name,summary_category[name])))
summary_rows=[]
for category,label in enumerate(CATEGORY_NAMES):
    for name in summary_order:
        if summary_category[name]==category:
            summary_rows.append({'kind':'data','cells':[name]+cells(summary_models[name])})
    summary_rows.append({'kind':'subtotal','cells':['TỔNG '+label]+cells(summary_categories[category])})
summary_rows.append({'kind':'total','cells':['TỔNG']+cells(grand)})

def configuration_order(name):
    # In Mac names, RAM precedes the storage after '-' or '/'.
    mac=re.search(r'\b(\d+)\s*GB\s*[-/]\s*(\d+)\s*(TB|GB)\b',name,re.I)
    capacity=mac if mac else re.search(r'\b(\d+)\s*(TB|GB)\b',name,re.I)
    if mac:
        ram=D(mac[1]);storage=D(mac[2])*(1024 if mac[3].upper()=='TB' else 1)
    elif capacity:
        ram=D(0);storage=D(capacity[1])*(1024 if capacity[2].upper()=='TB' else 1)
    else:
        watch_size=re.search(r'\b(\d+)\s*mm\b',name,re.I)
        ram=D(0);storage=D(watch_size[1]) if watch_size else D('Infinity')
    watts=tuple(D(w) for w in re.findall(r'\b(\d+(?:\.\d+)?)\s*W\b',name,re.I))
    # Unknown charging power follows the explicitly named wattages.
    return storage,ram,watts or (D('Infinity'),)

def detail_rows(bucket,product=False,category=None):
    result=[]
    for family in family_order:
        if category is not None and family_category[family]!=category:continue
        entries=[(k,v) for k,v in bucket.items() if k[0]==family]
        entries.sort(key=lambda kv:(configuration_order(source_names[kv[0][1]] if product else kv[0][1]),natural_key(product_names[kv[0][1]] if product else kv[0][1]),kv[0][1]))
        for key,rec in entries:
            name=product_names[key[1]] if product else key[1]
            result.append({'kind':'data','cells':[name]+cells(rec)})
        result.append({'kind':'subtotal','cells':[family]+cells(families[family])})
    result.append({'kind':'total','cells':['TỔNG']+cells(grand if category is None else summary_categories[category])})
    return result

NORTH=['Đông Tây Bắc','Đồng Bằng Sông Hồng','Hà Nội +','Trung Bộ']
SOUTH=['Đông Cao Nguyên','Duyên Hải','Hồ Chí Minh','Tây Nam Bộ']
unknown_regions=sorted({r[11] for r in data if r[6]=='Kênh Offline'
                        and r[11].removeprefix('Vùng ') not in {*NORTH,*SOUTH}})
region_rows=[]
miens=[]
for name,regions in [('MIỀN BẮC',NORTH),('MIỀN NAM',SOUTH)]:
    start=len(region_rows)
    reg_total=ZERO
    for region in regions:
        v=total(r for r in data if r[6]=='Kênh Offline' and r[11]=='Vùng '+region)
        reg_total=add(reg_total,v)
        region_rows.append({'kind':'data','cells':['',region]+formatted(v)})
    region_rows.append({'kind':'mien','cells':['',name]+formatted(reg_total)})
    miens.append((name,start,len(regions)))
# MWG sometimes returns Offline stores without an assigned RSM region.
# Show their actual source label separately; never drop them or guess a miền.
for region in unknown_regions:
    v=total(r for r in data if r[6]=='Kênh Offline' and r[11]==region)
    region_rows.append({'kind':'data','cells':['',region.removeprefix('Vùng ')]+formatted(v)})
offline=total(r for r in data if r[6]=='Kênh Offline')
assigned=total(r for r in data if r[6]=='Kênh Offline' and r[11] not in unknown_regions)
unassigned=total(r for r in data if r[6]=='Kênh Offline' and r[11] in unknown_regions)
assert add(assigned,unassigned)==offline
online=total(r for r in data if r[6]=='Kênh Online')
region_rows.append({'kind':'online','cells':['','ONLINE']+formatted(online)})
region_rows.append({'kind':'total','cells':['','TỔNG']+formatted(TOTAL)})
assert sum(D(str(r[14])) for r in data if r[6]=='Kênh Offline')+online[0]==TOTAL[0]

comparison_data={'total':[str(x) for x in grand['all']], 'models':{name:{'category':summary_category[name],'values':[str(x) for x in summary_models[name]['all']], 'order_key':list(model_order(name,summary_category[name]))} for name in summary_order}}
if args.metrics_only:
    args.checks.parent.mkdir(parents=True,exist_ok=True)
    args.checks.write_text(json.dumps({'report_date':args.date,'source_rows':len(data),'comparison_data':comparison_data},ensure_ascii=False,indent=2))
    raise SystemExit(0)

YELLOW='#FFC000';ORANGE='#F8CBAD';GREEN='#E2EFDA';CYAN='#00C8E8';TOTAL_YELLOW='#FFF000'
GRID='#1B1B1B';BLACK='#101010';RED='#DB180E'
def draw_text(c,txt,x,y,w,h,bold=False,size=17,align='left',color=BLACK):
    font='ArialVN-Bold' if bold else 'ArialVN'
    assert pdfmetrics.stringWidth(txt,font,size)<=w-12,('Text overflow',txt,w,pdfmetrics.stringWidth(txt,font,size))
    c.setFont(font,size);c.setFillColor(HexColor(color))
    baseline=y+(h-size)/2+size*.22
    if align=='right':c.drawRightString(x+w-6,baseline,txt)
    elif align=='center':c.drawCentredString(x+w/2,baseline,txt)
    else:c.drawString(x+6,baseline,txt)
def rect(c,x,y,w,h,fill=None):
    c.setStrokeColor(HexColor(GRID));c.setLineWidth(.6)
    if fill:c.setFillColor(HexColor(fill))
    c.rect(x,y,w,h,stroke=1,fill=1 if fill else 0)
def create_table(stem,title,rows,widths,regional=False,scoped_total=None):
    display_total=TOTAL if scoped_total is None else scoped_total
    summary_model_table=stem.startswith('02')
    margin=18;rh=25;head_h=30;title_h=122;bottom=80 if summary_model_table else 58
    header_total=head_h if regional else head_h*2
    width=sum(widths)+margin*2;height=title_h+header_total+len(rows)*rh+bottom
    path=OUT/(stem+'.pdf');c=canvas.Canvas(str(path),pagesize=(width,height))
    c.setTitle(title+' - '+REPORT_DATE_TEXT);c.setAuthor('NH Apple')
    c.setFont('ArialVN-Bold',26);c.drawString(margin,height-32,title)
    c.setFont('ArialVN',16);c.drawString(margin,height-56,'Ngày '+REPORT_DATE_TEXT+' | Cập nhật '+args.snapshot+' | Apple - Hàng mới | DT nguồn x 1,08')
    c.drawString(margin,height-79,'ĐVT doanh thu: tỷ đồng | Tỷ trọng SL tính trên '+integer(TOTAL[0])+' SP.')
    c.setFont('ArialVN-Bold',18)
    c.drawString(margin,height-103,('TỔNG DOANH THU: ' if scoped_total is None else 'DOANH THU NHÓM: ')+revenue_text(display_total[1])+' tỷ đồng | SỐ LƯỢNG: '+integer(display_total[0])+' SP')
    x0=margin;top=height-title_h
    if regional:
        x=x0
        for text,w in zip(['MIỀN','VÙNG','SỐ LƯỢNG','DT (tỷ)','TỶ TRỌNG'],widths):
            rect(c,x,top-head_h,w,head_h,YELLOW);draw_text(c,text,x,top-head_h,w,head_h,True,17,'center');x+=w
    else:
        rect(c,x0,top-header_total,widths[0],header_total,YELLOW)
        draw_text(c,'SẢN PHẨM' if stem.startswith('03') else 'MODEL',x0,top-header_total,widths[0],header_total,True,18,'center')
        x=x0+widths[0]
        for label in ['TỔNG','TGDĐ/ĐMX','TOPZONE']:
            w=sum(widths[1:4]);rect(c,x,top-head_h,w,head_h,YELLOW)
            draw_text(c,label,x,top-head_h,w,head_h,True,18,'center')
            for text,ww in zip(['SL','DT (tỷ)','Tỷ trọng'],widths[1:4]):
                rect(c,x,top-header_total,ww,head_h,YELLOW);draw_text(c,text,x,top-header_total,ww,head_h,True,17,'center');x+=ww
    data_top=top-header_total
    for i,row in enumerate(rows):
        y=data_top-(i+1)*rh;x=x0;k=row['kind']
        fill={'subtotal':ORANGE,'mien':GREEN,'online':CYAN,'total':TOTAL_YELLOW}.get(k)
        for j,(text,w) in enumerate(zip(row['cells'],widths)):
            rect(c,x,y,w,rh,fill)
            draw_text(c,text,x,y,w,rh,k!='data',17,'left' if j<(2 if regional else 1) else 'right',RED if k=='total' and j>=(2 if regional else 1) else BLACK)
            x+=w
    if regional:
        for name,start,n in miens:
            y=data_top-(start+n)*rh;h=n*rh
            c.setFillColor(HexColor('#FFFFFF'));c.rect(x0,y,widths[0],h,fill=1,stroke=0)
            rect(c,x0,y,widths[0],h);draw_text(c,name,x0,y,widths[0],h,True,17,'center')
    c.setFont('ArialVN',15);c.setFillColor(HexColor(BLACK))
    if regional:
        c.drawString(margin,35,'Các vùng/miền chỉ gồm Offline; Online tách riêng. Cộng đủ hai phần mới ra tổng.')
    elif summary_model_table:
        c.drawString(margin,57,'Tên model theo cột Tên viết tắt 1; mỗi model gộp các dung lượng và màu. Sắp theo dòng và đời máy từ thấp lên cao.')
        c.drawString(margin,35,'Hàng màu cam là tổng nhóm; không cộng lại vào các dòng model. Tỷ trọng là tỷ trọng số lượng trên toàn hệ thống.')
    else:
        c.drawString(margin,35,'Giữ nguyên dấu số liệu. Hàng màu cam là tổng nhóm; không cộng lại vào các dòng chi tiết.')
    c.drawString(margin,14,('Chưa có giao dịch trong file MWG tại thời điểm xuất. Các chỉ tiêu hiển thị 0.' if not data else 'Nguồn: BI MỖI NGÀY, MWG | TGDD/DMX gộp hai thương hiệu; TopZone tách riêng.'))
    c.showPage();c.save()
    text=PdfReader(path).pages[0].extract_text()
    assert integer(display_total[0]) in text and revenue_text(display_total[1]) in text
    assert 'tỷ đồng' in text and 'ĐVT doanh thu: ĐỒNG' not in text
    return {'stem':stem,'title':title,'width':width,'height':height,'rows':len(rows),'pdf':str(path),
            'mobile_rows':rows,'mobile_unit':'billion_vnd_rounded',
            'mobile_regions':miens if regional else []}

tables=[create_table('01_Vung_Mien','SỐ BÁN THEO VÙNG / MIỀN',region_rows,[150,360,150,200,160],True),
        create_table('02_Model','SỐ BÁN THEO DÒNG MODEL',summary_rows,[300,105,200,110,105,200,110,105,200,110])]
category_slugs=['iPhone','iPad','Mac','Watch','AirPods','Phu_Kien']
for category,label in enumerate(CATEGORY_NAMES):
    detail_table_rows=detail_rows(products,True,category)
    detail_name_width=max(520,int(max(pdfmetrics.stringWidth(row['cells'][0],'ArialVN-Bold' if row['kind']!='data' else 'ArialVN',17) for row in detail_table_rows)+31)//20*20)
    table=create_table('03_'+str(category+1).zfill(2)+'_'+category_slugs[category],
        'CHI TIẾT SỐ BÁN - '+label.upper(),detail_table_rows,
        [detail_name_width,105,200,110,105,200,110,105,200,110],scoped_total=summary_categories[category]['all'])
    table.update(category=label,category_index=category,
        totals=[str(x) for x in summary_categories[category]['all']],
        product_codes=sorted({product_code(key[1]) for key in products if family_category[key[0]]==category}))
    tables.append(table)
assert sum(D(table['totals'][0]) for table in tables[2:])==TOTAL[0]
assert sum(D(table['totals'][1]) for table in tables[2:])==TOTAL[1]
assert sum(len(table['product_codes']) for table in tables[2:])==len({product_code(key[1]) for key in products})

combined=args.combined
combined.parent.mkdir(parents=True,exist_ok=True)
writer=PdfWriter()
for table in tables:
    writer.append(table['pdf'])
writer.write(combined)
writer.close()
assert len(PdfReader(combined).pages)==len(tables)
summary={'comparison_data':comparison_data,'report_date':args.date,'snapshot':args.snapshot,'source_rows':len(data),'products':len(products),'model_rows':len(summary_models),'configuration_rows':len(models),'families':len(families),'grand_total':cells(grand),'online':formatted(online),'tables':tables,'summary_models':{name:cells(summary_models[name]) for name in summary_order},'abbreviation_matching':{'name_parse_fallback_codes':name_parse_fallback_codes,'matched':len(report_labels)-len(unmapped_codes),'source_name_fallback':len(unmapped_codes),'unmapped_codes':unmapped_codes,'duplicate_codes_using_main_sheet':sorted(set(abbreviation_conflicts)&set(report_labels))}}
args.checks.parent.mkdir(parents=True,exist_ok=True)
args.checks.write_text(json.dumps(summary,ensure_ascii=False,indent=2))
print(json.dumps(summary,ensure_ascii=False,indent=2))
