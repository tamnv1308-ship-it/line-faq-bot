import os
"""Export through the authenticated MWG endpoints used by its report UI."""
import argparse
import importlib.util
import json
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from mwg_auth import session_lock, refresh_if_due, read_state, local_tokens, NoRedirect, LoginRequired

ORIGIN = 'https://baocao.dienmayxanh.com'
VN = ZoneInfo('Asia/Ho_Chi_Minh')


def emit(event, **fields):
    print(json.dumps(dict(event=event, **fields), ensure_ascii=False), flush=True)


def api(path, body=None):
    if not path.startswith('/kb-api/'):
        raise RuntimeError('Đường dẫn MWG không hợp lệ')
    with session_lock():
        refresh_if_due()
        token = local_tokens(read_state())['access_token']
    context = ssl.create_default_context()
    if importlib.util.find_spec('certifi'):
        import certifi
        context = ssl.create_default_context(cafile=certifi.where())
    request = urllib.request.Request(ORIGIN + path,
        data=json.dumps(body).encode() if body is not None else None,
        headers={'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json',
                 'X-Request-ID': str(uuid.uuid4()), 'Origin': ORIGIN})
    opener = urllib.request.build_opener(NoRedirect(), urllib.request.HTTPSHandler(context=context))
    try:
        with opener.open(request, timeout=45) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            raise LoginRequired('MWG yêu cầu đăng nhập hoặc cấp quyền lại') from None
        raise RuntimeError('MWG từ chối yêu cầu: HTTP ' + str(exc.code)) from None
    except (OSError, ValueError):
        raise RuntimeError('Chưa kết nối được máy chủ báo cáo MWG') from None


def export_body(day, stores, templates):
    choices = [item for item in templates if item.get('name') == 'BI MỖI NGÀY']
    if len(choices) != 1 or choices[0].get('mode') != 'flat':
        raise RuntimeError('Không xác định duy nhất mẫu BI MỖI NGÀY')
    ids = list(dict.fromkeys(str(item['id']) for item in stores))
    if not ids:
        raise RuntimeError('Không lấy được danh sách siêu thị được phép báo cáo')
    return {'FROMDATE': int(day.strftime('%Y%m%d')), 'TODATE': int(day.strftime('%Y%m%d')),
            'RSMIDS': None, 'AMIDS': None, 'STOREIDS': ','.join(ids),
            'MAINGROUPIDS': '13,16,22,23,244,364', 'SUBGROUPIDS': None,
            'BRANDIDS': '136', 'INVENTORYSTATUSIDS': '1', 'OUTPUTTYPEIDS': None,
            'PRODUCTIDS': None, 'TEMPLATE_ID': choices[0]['id']}


def export_file(day, destination, inventory_status_ids='1', main_group_ids='13,16,22,23,244,364'):
    templates = api('/kb-api/reports/export-templates?report_key=margin-daily').get('templates', [])
    stores = api('/kb-api/common/filter-store-getbyasmlist', {
        'KEYWORD': '', 'PAGEINDEX': 1, 'PAGESIZE': 10000000, 'PERKEY': '',
        'AMIDS': None, 'RSMIDS': None, 'AsUser': None, 'COMPANYIDLIST': None, 'CHAINIDLIST': None})
    if not stores.get('success'):
        raise RuntimeError('MWG chưa trả danh sách siêu thị hợp lệ')
    body = export_body(day, stores.get('data', []), templates)
    body['INVENTORYSTATUSIDS'] = inventory_status_ids
    allowed_groups={'13','16','22','23','244','364'}
    if not main_group_ids or not set(main_group_ids.split(',')) <= allowed_groups:
        raise RuntimeError('Ngành hàng xuất không thuộc phạm vi Apple đã cấu hình')
    body['MAINGROUPIDS'] = main_group_ids
    requested = datetime.now(VN)
    created = api('/kb-api/reports/export/margin-daily', body)
    job_id = created.get('job_id')
    if not isinstance(job_id, str) or not job_id.isalnum():
        raise RuntimeError('MWG chưa xác nhận tác vụ xuất file')
    emit('export_queued', job_id=job_id, report_date=day.isoformat())
    deadline = time.monotonic() + 600
    while time.monotonic() < deadline:
        status = api('/kb-api/reports/export/status/' + job_id)
        if status.get('job_id') != job_id:
            raise RuntimeError('Kết quả MWG không thuộc tác vụ vừa xuất')
        if status.get('state') == 'done':
            break
        if status.get('state') == 'error':
            raise RuntimeError('MWG báo tác vụ xuất file thất bại')
        time.sleep(2)
    else:
        raise RuntimeError('MWG chưa xuất xong sau 10 phút')
    exported = datetime.fromisoformat(status['done_at']).astimezone(VN)
    if abs((exported - requested).total_seconds()) > 720:
        raise RuntimeError('Thời điểm file MWG không khớp yêu cầu mới')
    result = api('/kb-api/reports/export/download/' + job_id)
    url = result.get('downloadUrl', '')
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username:
        raise RuntimeError('Địa chỉ tải file MWG không hợp lệ')
    try:
        # Signed download URLs receive no bearer token or browser cookies.
        with urllib.request.urlopen(url, timeout=60) as response:
            content = response.read()
    except (OSError, ValueError):
        raise RuntimeError('Không tải được file MWG vừa xuất') from None
    if not content.startswith(b'PK'):
        raise RuntimeError('MWG trả nội dung không phải Excel')
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(content)
    destination.with_suffix('.export.json').write_text(json.dumps({
        'source_rows': status.get('result_rows'), 'exported_at_vn': exported.isoformat(),
        'job_id': job_id, 'filename': status.get('filename'),
        'source_mode': 'authenticated_mwg_api'}, ensure_ascii=False))
    emit('downloaded', report_date=day.isoformat(), source_rows=status.get('result_rows'))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--date', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    try:
        export_file(datetime.strptime(args.date, '%Y-%m-%d').date(), Path(args.output))
    except LoginRequired:
        emit('login_required', message='Phiên MWG cần đăng nhập lại')
        sys.exit(12)
    except Exception as exc:
        emit('fetch_failed', message=str(exc) if isinstance(exc, RuntimeError) else type(exc).__name__)
        sys.exit(1)
