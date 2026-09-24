"""Mac worker. Browser adapter requires an on-site acceptance test before deployment."""
import argparse
import fcntl
import json
import os
import re
import time
import urllib.request
from pathlib import Path
from co_results import items

URL = 'https://inventorytransfers.mwgroup.vn/storechangeordermanually'
ROOT = Path(__file__).resolve().parent / '.co-mac'
TEMPLATE = Path(__file__).resolve().parent / 'templates' / 'StoreChangeOrderTGDD_template.xlsx'

def progress(job, stage):
    # Do not log tokens, form notes, or customer data.
    ROOT.mkdir(exist_ok=True)
    line=time.strftime('%Y-%m-%d %H:%M:%S')+' '+job['id']+' '+stage
    print(line,flush=True)
    with (ROOT/'worker-progress.log').open('a') as stream:
        stream.write(line+'\n')

def upload_excel(page, output):
    # Use the site's import button so its preparation handlers run before upload.
    with page.expect_file_chooser(timeout=15000) as chooser:
        page.get_by_role('button',name=re.compile('Nhập Excel mẫu')).click()
    chooser.value.set_files(str(output))

def concurrent_rejection(alerts, data):
    for message in alerts:
        normalized=' '.join(message.split())
        pair=r'\[\s*'+re.escape(data['source'])+r'\s*-\s*'+re.escape(data['product'])+r'\s*\]'
        if ('Đang có Kho + MSP đang tạo YCCK' in normalized and
                'không được phép cùng lúc tránh vượt tồn' in normalized and
                re.search(pair,normalized)):
            return message[:2500]
    return None

def api(route, data):
    base = os.environ['CO_BOT_URL'].rstrip('/')
    if not base.startswith('https://'):
        raise RuntimeError('CO_BOT_URL must use HTTPS')
    req = urllib.request.Request(base+'/co/worker/'+route, data=None if data is None else json.dumps(data).encode(),
        headers={'Content-Type':'application/json', 'Authorization':'Bearer '+os.environ['CO_WORKER_TOKEN']})
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.load(response)

def report(job, state, result=''):
    record = {'id':job['id'], 'lease':job['lease'], 'state':state, 'result':result}
    pending = ROOT/'pending.json'
    tmp = ROOT/'pending.tmp'
    with tmp.open('w') as f:
        json.dump(record, f); f.flush(); os.fsync(f.fileno())
    tmp.replace(pending)
    api('result', record)
    pending.unlink()

def fill_template(source, target, data):
    from openpyxl import load_workbook
    wb = load_workbook(source)
    ws = wb.active
    if [ws.cell(1,c).value for c in range(1,6)] != ['Kho xuất','Kho nhận hàng','Mã sản phẩm','Số lượng','Ghi chú']:
        raise RuntimeError('Cấu trúc mẫu Excel đã thay đổi.')
    if any(c.value is not None for row in ws.iter_rows(min_row=2) for c in row):
        raise RuntimeError('Mẫu có dữ liệu sẵn; dừng để tránh nhập nhầm.')
    records=items(data)
    last_row=len(records)+1
    if ws.max_row>last_row:
        ws.delete_rows(last_row+1,ws.max_row-last_row)
    for row_number in list(ws.row_dimensions):
        if row_number>last_row:
            del ws.row_dimensions[row_number]
    for row_number,record in enumerate(records,2):
        for col,key in enumerate(['source','destination','product','quantity','note'],1):
            cell=ws.cell(row_number,col); cell.value=record[key]
            if isinstance(record[key],str):
                cell.data_type='s'
                cell.number_format='@'
    wb.save(target)

def table_with(page, header):
    return page.get_by_role('table').filter(has=page.get_by_role('columnheader',name=header,exact=True))

def data_rows(table):
    result=[]
    for row in table.get_by_role('row').all():
        cells=row.get_by_role('cell').all_text_contents()
        if cells and any(value.strip() for value in cells):
            result.append((row,cells))
    return result

def match_rows(rows, records):
    if len(rows)!=len(records):
        return None
    matched=[]; used=set()
    for data in records:
        candidates=[]
        for index,(_,cells) in enumerate(rows):
            if index in used or len(cells)!=11:
                continue
            if (cells[3].strip()==data['product'] and cells[5].strip()==str(data['quantity'])
                    and cells[7].strip()==data['note']
                    and all(re.match(r'^'+re.escape(value)+r'(?:\s*-|\s*$)',actual.strip())
                            for value,actual in [(data['source'],cells[1]),(data['destination'],cells[2])])):
                candidates.append((index,cells))
        if len(candidates)!=1:
            return None
        index,cells=candidates[0]; used.add(index); matched.append(cells)
    return matched

def cancel_import(page):
    cancel=page.get_by_text('Hủy',exact=True)
    if cancel.is_visible():
        cancel.click()

def select_brands(page):
    desired={'1 - thegioididong','2 - dienmayxanh','16 - TopZone'}
    control=page.locator('input[role="listbox"]')
    control.wait_for(state='visible',timeout=15000)
    control.click()
    page.wait_for_timeout(700)
    owns=(control.get_attribute('aria-owns') or '').split()
    if not owns:
        raise RuntimeError('Danh sách thương hiệu chưa sẵn sàng; chưa nhập file.')
    choices=page.locator('[id="'+owns[-1]+'"]')
    for label in desired:
        choices.get_by_role('option',name=label,exact=True).wait_for(state='attached',timeout=15000)
    for option in choices.get_by_role('option').all():
        label=option.inner_text().strip()
        selected='k-state-selected' in (option.get_attribute('class') or '').split()
        if selected != (label in desired):
            if not option.is_visible():
                control.click()
                page.wait_for_timeout(500)
            option.click()
            page.wait_for_timeout(700)
    page.wait_for_timeout(1000)
    selected={text.strip() for text in choices.locator('.k-state-selected').all_text_contents()}
    if selected != desired:
        raise RuntimeError('Không chọn đúng ba thương hiệu TGDD, DMX, TopZone.')
    control.press('Escape')
    page.wait_for_timeout(500)

def select_product_status(page, status):
    labels={'Mới':'1 - Mới','Đã sử dụng':'2 - Đã sử dụng','Mới giảm giá':'8 - Mới (Giảm giá)'}
    if status not in labels:
        raise RuntimeError('Trạng thái yêu cầu không hợp lệ; chưa nhập file.')
    control=page.get_by_role('combobox',name='Vui lòng chọn trạng thái sản phẩm',exact=True)
    control.wait_for(state='visible',timeout=15000)
    if control.input_value().strip()==labels[status]:
        return
    control.press('Alt+ArrowDown')
    page.get_by_role('option',name=labels[status],exact=True).click()
    page.wait_for_timeout(700)
    if control.input_value().strip()!=labels[status]:
        raise RuntimeError('Không xác nhận được trạng thái '+status+'; chưa nhập file.')

def prepare_import_controls(page, job):
    # Run only before a new import, never while holding a row for confirmation.
    control=page.get_by_role('combobox',name='Vui lòng chọn trạng thái sản phẩm',exact=True)
    for attempt in range(3):
        control.wait_for(state='visible',timeout=15000)
        for _ in range(6):
            if control.input_value().strip():
                break
            page.wait_for_timeout(500)
        if control.input_value().strip():
            progress(job,'select_brands')
            select_brands(page)
            # Brand loading may clear the status widget again.
            if control.input_value().strip():
                progress(job,'select_product_status')
                select_product_status(page,job['payload'].get('status','Mới'))
                return
        if attempt<2:
            progress(job,'reload_blank_product_status')
            page.reload(wait_until='domcontentloaded',timeout=30000)
            page.get_by_role('button',name='Tạo CO',exact=True).wait_for(timeout=30000)
    raise RuntimeError('Ô trạng thái sản phẩm vẫn trống sau 3 lần kiểm tra và tải lại MWG; chưa nhập file, chưa tạo CO. Vui lòng thử lại khi trang tải đầy đủ.')

def process(page, job, prepared_id=None):
    submitting=False
    alerts=[]
    records=items(job['payload'])
    outcomes=[{'co':'','error':''} for _ in records]
    def on_dialog(dialog):
        alerts.append(dialog.message)
        if dialog.type=='alert':
            dialog.accept()
        else:
            dialog.dismiss()
    page.on('dialog',on_dialog)
    try:
        reuse=job.get('mode')=='create' and prepared_id==job['id']
        if job.get('mode')=='create' and job['payload'].get('product_name') and not reuse:
            raise RuntimeError('Trang chờ xác nhận không còn trong phiên bot này; chưa tạo CO. Gửi lại yêu cầu để nhập file mới.')
        if reuse:
            progress(job,'reuse_imported_row')
            if page.url.split('?',1)[0].split('#',1)[0].rstrip('/')!=URL:
                raise RuntimeError('Trang MWG đã thay đổi khi chờ xác nhận; chưa tạo CO.')
        else:
            progress(job,'reload_before_request')
            if page.url.split('?',1)[0].split('#',1)[0].rstrip('/')==URL:
                page.reload(wait_until='domcontentloaded',timeout=30000)
            else:
                page.goto(URL,wait_until='domcontentloaded',timeout=30000)
            page.get_by_role('button',name='Tạo CO',exact=True).wait_for(timeout=30000)
            prepare_import_controls(page,job)
            progress(job,'prepare_local_template')
            if not TEMPLATE.is_file():
                raise RuntimeError('Thiếu mẫu Excel lưu trên Mac; cần cập nhật templates/StoreChangeOrderTGDD_template.xlsx. Chưa tạo CO.')
            folder=ROOT/job['id']; folder.mkdir(exist_ok=True)
            output=folder/'StoreChangeOrderTGDD_upload.xlsx'
            fill_template(TEMPLATE,output,job['payload'])
            progress(job,'upload_excel')
            alerts.clear()
            upload_excel(page,output)
            popup=page.get_by_text('Dữ liệu trong tập tin excel',exact=True)
            import_deadline=time.monotonic()+60
            while not popup.is_visible():
                if alerts:
                    raise RuntimeError('MWG báo lỗi khi nhập Excel: '+'; '.join(alerts)[-1800:])
                if time.monotonic()>=import_deadline:
                    raise RuntimeError('MWG chưa trả kết quả nhập Excel sau 60 giây; bot chưa bấm Tạo CO.')
                page.wait_for_timeout(250)
            errors=[]
            for row in table_with(page,'Xóa').get_by_role('row').all()[1:]:
                cells=row.get_by_role('cell').all_text_contents()
                if len(cells)>=9 and cells[8].strip():
                    errors.append(cells[8].strip())
            progress(job,'accept_import')
            if errors:
                cancel_import(page)
                report(job,'failed','; '.join(dict.fromkeys(errors))[:2500]); return
            page.get_by_text('Đồng ý',exact=True).click()
            popup.wait_for(state='hidden',timeout=15000)
        table=table_with(page,'Mã yêu cầu chuyển kho')
        deadline=time.monotonic()+10
        rows=data_rows(table)
        while not rows and time.monotonic()<deadline:
            page.wait_for_timeout(250)
            rows=data_rows(table)
        matched=match_rows(rows,records)
        if matched is None:
            raise RuntimeError('Dữ liệu trên trang không khớp đủ '+str(len(records))+' dòng yêu cầu; chưa tạo CO.')
        for cells in matched:
            if cells[9].strip() or cells[10].strip():
                raise RuntimeError('Trang đã có mã CO hoặc lỗi; dừng để kiểm tra.')
        names=[cells[4].strip() for cells in matched]
        if not all(names):
            raise RuntimeError('MWG chưa trả đủ tên sản phẩm; chưa tạo CO.')
        if job.get('mode')=='preview':
            report(job,'preview_ready',json.dumps(names,ensure_ascii=False) if 'items' in job['payload'] else names[0])
            return job['id']
        for data,name in zip(records,names):
            if data.get('product_name') and name!=data['product_name']:
                raise RuntimeError('Tên sản phẩm trên MWG khác bản đã xác nhận; chưa tạo CO.')
        data=job['payload']
        if reuse:
            status_labels={'Mới':'1 - Mới','Đã sử dụng':'2 - Đã sử dụng','Mới giảm giá':'8 - Mới (Giảm giá)'}
            actual=page.get_by_role('combobox',name='Vui lòng chọn trạng thái sản phẩm',exact=True).input_value().strip()
            if actual!=status_labels[data.get('status','Mới')]:
                raise RuntimeError('Trạng thái sản phẩm đã thay đổi khi chờ xác nhận; chưa tạo CO.')
            control=page.locator('input[role="listbox"]')
            owns=(control.get_attribute('aria-owns') or '').split()
            selected=set() if not owns else {x.strip() for x in page.locator('[id="'+owns[-1]+'"] .k-state-selected').all_text_contents()}
            if selected!={'1 - thegioididong','2 - dienmayxanh','16 - TopZone'}:
                raise RuntimeError('Thương hiệu đã thay đổi khi chờ xác nhận; chưa tạo CO.')
        report(job,'submitting')
        submitting=True
        progress(job,'submit_co')
        alerts.clear()
        page.get_by_role('button',name='Tạo CO',exact=True).click()
        deadline=time.monotonic()+60
        while time.monotonic()<deadline:
            current=match_rows(data_rows(table),records)
            if current is not None:
                for index,cells in enumerate(current):
                    co=cells[9].strip(); error=cells[10].strip()
                    if co or error:
                        outcomes[index]={'co':co,'error':error[:350]}
                if all(row['co'] or row['error'] for row in outcomes):
                    state='unknown' if any(row['co'] and row['error'] for row in outcomes) else 'succeeded' if any(row['co'] for row in outcomes) else 'failed'
                    report(job,state,json.dumps(outcomes,ensure_ascii=False)); return
            if len(records)==1:
                rejection=concurrent_rejection(alerts,records[0])
                if rejection:
                    report(job,'failed',rejection); return
            page.wait_for_timeout(300)
        raise RuntimeError('Chưa thấy mã CO hoặc lỗi sau khi tạo; cần kiểm tra thủ công.')
    except Exception as error:
        progress(job,'exception_'+type(error).__name__)
        if (ROOT/'pending.json').exists():
            raise # Preserve undelivered outcome, including successful CO codes.
        message=str(error).splitlines()[0][:1800]
        if alerts:
            message+=' | '+'; '.join(alerts)[-500:]
        if 'phiên làm việc đã hết hạn' in message.lower():
            message=('Phiên đăng nhập MWG trên Mac đã hết hạn. '
                     'Dừng bot bằng Ctrl+C, mở lại Chay-bot-Mac.command và đăng nhập MWG '
                     'trong cửa sổ Chrome của bot, rồi nhấn Enter tại Terminal. '
                     'Sau đó gửi lại form và xác nhận. Không cần đổi thông tin kho hoặc sản phẩm.')
        elif 'has been closed' in message:
            message=('Chrome của bot đã đóng hoặc mất kết nối. Giữ cửa sổ Chrome của bot mở. '
                     + ('Cần kiểm tra MWG trước khi gửi lại vì đã bắt đầu bước tạo CO.' if submitting else
                        'Chưa tạo CO; hãy gửi lại form và xác nhận yêu cầu mới.'))
        elif 'strict mode violation' in message:
            message='Bot gặp lỗi chọn thành phần trên trang MWG; chưa hoàn tất thao tác. Cần kiểm tra bot trước khi gửi lại.'
        if not submitting:
            try:
                cancel_import(page)
            except Exception:
                pass
        if submitting:
            for outcome in outcomes:
                if not outcome['co'] and not outcome['error']:
                    outcome['error']='Chưa rõ kết quả; cần đối soát MWG. '+message[:250]
            report(job,'unknown',json.dumps(outcomes,ensure_ascii=False))
        else:
            report(job,'failed',message)
    finally:
        page.remove_listener('dialog',on_dialog)

def open_browser(pw):
    # The bundled CfT archive lacks valid macOS signing resources on this Mac.
    # Use the installed signed Chrome and preserve the original bot login profile.
    if not Path('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome').is_file():
        raise RuntimeError('Không tìm thấy Google Chrome trong Applications. Chưa nhận yêu cầu CO.')
    context=pw.chromium.launch_persistent_context(
        str(ROOT/'browser'),channel='chrome',headless=False,accept_downloads=True)
    return context, context.pages[0] if context.pages else context.new_page()

def refresh_idle(page):
    # Preserve the current result page when reconciliation is still required.
    if (ROOT/'pending.json').exists():
        return False
    states=api('status',None)['states']
    if any(states.get(state,0) for state in ('running','submitting','unknown','preview_running')):
        return False
    page.reload(wait_until='domcontentloaded',timeout=30000)
    print('Đã tải lại trang MWG sau 5 phút khi rảnh.',flush=True)
    return True

def ensure_browser(pw, context, page):
    if not page.is_closed():
        return context, page
    # A closed tab can leave the context alive. A closed window cannot.
    try:
        return context, context.new_page()
    except Exception as error:
        if 'has been closed' not in str(error):
            raise
        return open_browser(pw)

def main():
    env_file=Path(__file__).resolve().parent/'.env'
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            key,sep,value=line.partition('=')
            if sep and key in {'CO_BOT_URL','CO_WORKER_TOKEN'}:
                os.environ.setdefault(key,value.strip())
    parser=argparse.ArgumentParser()
    parser.add_argument('--login',action='store_true')
    parser.add_argument('--live',action='store_true')
    args=parser.parse_args()
    if not (args.login or args.live):
        parser.error('Dùng --login để đăng nhập; --live để xử lý tác vụ đã xác nhận.')
    os.umask(0o077); ROOT.mkdir(exist_ok=True)
    lock=open(ROOT/'worker.lock','w'); fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    os.environ['PLAYWRIGHT_BROWSERS_PATH']=str(Path(__file__).resolve().parent/'.pw-browsers')
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        context,page=open_browser(pw)
        if args.login:
            page.goto(URL)
            input('Nếu MWG chưa đăng nhập, hãy đăng nhập trong cửa sổ này. Xong nhấn Enter để tiếp tục: ')
        if args.live:
            print('Bắt đầu chờ yêu cầu từ LINE trong cùng cửa sổ Chrome. Giữ Chrome và Terminal mở.', flush=True)
            pending=ROOT/'pending.json'
            if pending.exists():
                record=json.loads(pending.read_text()); api('result',record); pending.unlink()
                if record['state']=='submitting':
                    raise RuntimeError('Có tác vụ dở ở bước tạo. Kiểm tra MWG trước khi chạy lại.')
            refresh_at=time.monotonic()+300
            prepared_id=None
            while True:
                context,page=ensure_browser(pw,context,page)
                job=api('claim',{'preview_protocol':1,'prepared_id':prepared_id,'batch_protocol':1})
                if job and job.get('release_preview'):
                    prepared_id=None
                    refresh_at=time.monotonic()+300
                    continue
                if job:
                    prepared_id=process(page,job,prepared_id)
                    refresh_at=time.monotonic()+300
                elif not prepared_id and time.monotonic()>=refresh_at:
                    try:
                        refresh_idle(page)
                    except Exception as error:
                        print('Không tải lại được trang MWG: '+type(error).__name__,flush=True)
                    refresh_at=time.monotonic()+300
                time.sleep(1 if prepared_id else 2)
        context.close()

if __name__=='__main__':
    main()
