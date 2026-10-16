"""Import-only API probe. No CO creation endpoint or automatic retry."""
import json
from decimal import Decimal, InvalidOperation
from pathlib import Path

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
    def identity(row, api=False):
        keys = ('FROMSTOREID','TOSTOREID','PRODUCTID','QUANTITY') if api else ('source','destination','product','quantity')
        def whole(value):
            try:number=Decimal(str(value))
            except InvalidOperation:raise ValueError('Mã kho hoặc số lượng không hợp lệ.') from None
            if not number.is_finite() or number<=0 or number!=number.to_integral_value():
                raise ValueError('Mã kho hoặc số lượng không hợp lệ.')
            return str(int(number))
        return (whole(row[keys[0]]),whole(row[keys[1]]),str(row[keys[2]]),whole(row[keys[3]]))
    wanted = {identity(row): row for row in expected}
    if len(wanted) != len(expected):
        raise ValueError('Yêu cầu có dòng trùng.')
    found = {}
    for row in rows:
        key = identity(row, True)
        if key not in wanted or key in found:
            raise ValueError('Dữ liệu MWG trả về không khớp yêu cầu.')
        found[key] = row
    return [found[identity(row)] for row in expected]


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
    path = Path(excel_path)
    response = request.post(IMPORT_URL, multipart={
        'INVENTORYSTATUSID': str(status_id), 'STORECHANGETYPEID': '1',
        'STORECHANGEORDERTYPEID': '0', 'BRANDID': '1,2,16', 'CONTENT': '',
        '__RequestVerificationToken': token,
        'fileUpload': {'name': path.name,
                       'mimeType': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                       'buffer': path.read_bytes()},
    }, timeout=60000, max_redirects=0)
    if response.status != 200:
        raise ValueError('Nhập API không thành công (HTTP %s); chưa tạo CO.' % response.status)
    try:
        body = response.json()
    except Exception:
        raise ValueError('MWG không trả JSON; cần kiểm tra phiên đăng nhập.') from None
    return validate_import(body, expected)
