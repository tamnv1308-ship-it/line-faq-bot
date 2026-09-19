"""Mac worker. Browser adapter requires an on-site acceptance test before deployment."""
import argparse
import fcntl
import json
import os
import re
import time
import urllib.request
from pathlib import Path

URL = 'https://inventorytransfers.mwgroup.vn/storechangeordermanually'
ROOT = Path(__file__).resolve().parent / '.co-mac'

def api(route, data):
    base = os.environ['CO_BOT_URL'].rstrip('/')
    if not base.startswith('https://'):
        raise RuntimeError('CO_BOT_URL must use HTTPS')
    req = urllib.request.Request(base+'/co/worker/'+route, data=json.dumps(data).encode(),
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
    for col,key in enumerate(['source','destination','product','quantity','note'],1):
        cell=ws.cell(2,col); cell.value=data[key]
        if isinstance(data[key],str):
            cell.data_type='s'
    wb.save(target)

def table_with(page, header):
    return page.get_by_role('table').filter(has=page.get_by_role('columnheader',name=header,exact=True))

def cancel_import(page):
    cancel=page.get_by_text('Hủy',exact=True)
    if cancel.is_visible():
        cancel.click()

def select_brands(page):
    desired={'1 - thegioididong','2 - dienmayxanh','16 - TopZone'}
    control=page.locator('input[role="listbox"]')
    control.click()
    owns=control.get_attribute('aria-owns').split()
    choices=page.locator('[id="'+owns[-1]+'"]')
    for option in choices.get_by_role('option').all():
        label=option.inner_text().strip()
        selected='k-state-selected' in (option.get_attribute('class') or '').split()
        if selected != (label in desired):
            if not option.is_visible():
                control.click()
            option.click()
    selected=set(choices.locator('.k-state-selected').all_text_contents())
    if selected != desired:
        raise RuntimeError('Không chọn đúng ba thương hiệu TGDD, DMX, TopZone.')
    page.get_by_text('Nội dung',exact=True).click()

def process(page, job):
    submitting=False
    alerts=[]
    def on_dialog(dialog):
        alerts.append(dialog.message)
        if dialog.type=='alert':
            dialog.accept()
        else:
            dialog.dismiss()
    page.on('dialog',on_dialog)
    try:
        page.goto(URL,wait_until='domcontentloaded')
        page.get_by_role('button',name='Tạo CO',exact=True).wait_for(timeout=30000)
        select_brands(page)
        with page.expect_download() as info:
            page.get_by_role('link',name=re.compile('Tải excel mẫu')).click()
        download=info.value
        if not download.suggested_filename.startswith('StoreChangeOrderTGDD'):
            raise RuntimeError('Tên mẫu tải xuống không đúng StoreChangeOrderTGDD*.')
        folder=ROOT/job['id']; folder.mkdir(exist_ok=True)
        source=folder/'template.xlsx'; output=folder/'StoreChangeOrderTGDD_upload.xlsx'
        download.save_as(source)
        fill_template(source,output,job['payload'])
        with page.expect_file_chooser() as info:
            page.get_by_role('button',name=re.compile('Nhập Excel mẫu')).click()
        info.value.set_files(str(output))
        popup=page.get_by_text('Dữ liệu trong tập tin excel',exact=True)
        popup.wait_for(timeout=60000)
        errors=[]
        for row in table_with(page,'Xóa').get_by_role('row').all()[1:]:
            cells=row.get_by_role('cell').all_text_contents()
            if len(cells)>=9 and cells[8].strip():
                errors.append(cells[8].strip())
        page.get_by_text('Đồng ý',exact=True).click()
        if errors:
            cancel_import(page)
            report(job,'failed','; '.join(dict.fromkeys(errors))[:2500]); return
        popup.wait_for(state='hidden',timeout=15000)
        table=table_with(page,'Mã yêu cầu chuyển kho')
        rows=table.get_by_role('row').all()
        if len(rows)!=2:
            raise RuntimeError('Dữ liệu trước khi tạo không đúng một dòng đã xác nhận.')
        cells=rows[1].get_by_role('cell').all_text_contents(); data=job['payload']
        if len(cells)!=11 or cells[3].strip()!=data['product'] or cells[5].strip()!=str(data['quantity']) or cells[7].strip()!=data['note']:
            raise RuntimeError('Dữ liệu trên trang khác nội dung đã xác nhận.')
        for value,actual in [(data['source'],cells[1]),(data['destination'],cells[2])]:
            if not re.match(r'^'+re.escape(value)+r'(?:\s*-|\s*$)',actual.strip()):
                raise RuntimeError('Kho trên trang khác kho đã xác nhận.')
        if cells[9].strip() or cells[10].strip():
            raise RuntimeError('Trang đã có mã CO hoặc lỗi; dừng để kiểm tra.')
        report(job,'submitting')
        submitting=True
        page.get_by_role('button',name='Tạo CO',exact=True).click()
        deadline=time.monotonic()+60
        while time.monotonic()<deadline:
            cells=table.get_by_role('row').nth(1).get_by_role('cell').all_text_contents()
            if cells[9].strip() and not cells[10].strip():
                report(job,'succeeded',cells[9].strip()); return
            if cells[10].strip():
                report(job,'failed',cells[10].strip()[:2500]); return
            page.wait_for_timeout(500)
        raise RuntimeError('Chưa thấy mã CO hoặc lỗi sau khi tạo; cần kiểm tra thủ công.')
    except Exception as error:
        if (ROOT/'pending.json').exists():
            raise # Preserve undelivered outcome, including successful CO codes.
        message=str(error).splitlines()[0][:1800]
        if alerts:
            message+=' | '+'; '.join(alerts)[-500:]
        if not submitting:
            try:
                cancel_import(page)
            except Exception:
                pass
        report(job,'unknown' if submitting else 'failed',message)
    finally:
        page.remove_listener('dialog',on_dialog)

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
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        context=pw.chromium.launch_persistent_context(str(ROOT/'browser'),channel='chrome',headless=False,accept_downloads=True)
        page=context.pages[0] if context.pages else context.new_page()
        if args.login:
            page.goto(URL)
            input('Đăng nhập MWG. Xong nhấn Enter tại Terminal để lưu phiên: ')
        else:
            pending=ROOT/'pending.json'
            if pending.exists():
                record=json.loads(pending.read_text()); api('result',record); pending.unlink()
                if record['state']=='submitting':
                    raise RuntimeError('Có tác vụ dở ở bước tạo. Kiểm tra MWG trước khi chạy lại.')
            while True:
                job=api('claim',{})
                if job:
                    process(page,job)
                time.sleep(5)
        context.close()

if __name__=='__main__':
    main()
