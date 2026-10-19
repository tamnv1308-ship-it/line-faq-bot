"""Import-only API probe. No CO creation endpoint or automatic retry."""
import json
from pathlib import Path
from mwg_result_contract import row_identity, expected_identities

ORIGIN = 'https://inventorytransfers.mwgroup.vn'
IMPORT_URL = ORIGIN + '/StoreChangeOrderManually/ImportExcel'


def match_import_rows(body, expected):
    if not isinstance(body, dict) or body.get('Success') is not True:
        raise ValueError('MWG từ chối nhập file hoặc phiên đăng nhập đã hết hạn.')
    data = body.get('Data')
    if not isinstance(data, dict):
        raise ValueError('Phản hồi nhập file không đúng cấu trúc.')
    rows = data.get('Data')
    if isinstance(rows, str):
        rows = json.loads(rows)
    if not isinstance(rows, list) or len(rows) != len(expected):
        raise ValueError('Số dòng MWG trả về không khớp yêu cầu.')
    wanted = expected_identities(expected)
    wanted_set = set(wanted)
    found = {}
    for row in rows:
        key = row_identity(row, True)
        if key not in wanted_set or key in found:
            raise ValueError('Dữ liệu MWG trả về không khớp yêu cầu.')
        found[key] = row
    return [found[key] for key in wanted]


def import_row_errors(body, expected):
    """Return each matched row's business error without rejecting healthy rows."""
    errors=[]
    for row in match_import_rows(body,expected):
        error=str(row.get('ERRORNOTE') or '').strip()
        if error:errors.append(error[:500])
        elif row.get('ISERROR') is not False:errors.append('MWG báo lỗi dòng nhập nhưng chưa trả lý do rõ ràng.')
        elif not str(row.get('PRODUCTNAME') or '').strip():errors.append('MWG chưa trả tên sản phẩm cho dòng này.')
        else:errors.append('')
    return errors


def validate_import(body, expected):
    rows=match_import_rows(body,expected)
    for row in rows:
        if row.get('ISERROR') is not False or row.get('ERRORNOTE'):
            raise ValueError('MWG báo lỗi dòng nhập: ' + str(row.get('ERRORNOTE') or 'Không rõ lỗi')[:500])
        if not row.get('PRODUCTNAME'):
            raise ValueError('MWG chưa trả tên sản phẩm.')
    return rows


def probe_import(request, token, excel_path, expected, status_id='1'):
    """request must be the authenticated worker context.request; token stays in memory.

    Caller supplies the currently selected, verified MWG status ID. This probe
    must run while idle; it does not update the UI or mark a job prepared.
    """
    if not token:
        raise ValueError('Thiếu mã xác thực MWG; chưa gửi file.')
    expected_identities(expected)
    path = Path(excel_path)
    response = request.post(IMPORT_URL, multipart={
        'INVENTORYSTATUSID': str(status_id), 'STORECHANGETYPEID': '1',
        'STORECHANGEORDERTYPEID': '0', 'BRANDID': '1,2,16', 'CONTENT': '',
        '__RequestVerificationToken': token,
        'fileUpload': {'name': path.name,
                       'mimeType': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                       'buffer': path.read_bytes()},
    }, timeout=60000, max_redirects=0, max_retries=0)
    if response.status != 200:
        raise ValueError('Nhập API không thành công (HTTP %s); chưa tạo CO.' % response.status)
    try:
        body = response.json()
    except Exception:
        raise ValueError('MWG không trả JSON; cần kiểm tra phiên đăng nhập.') from None
    return validate_import(body, expected)
