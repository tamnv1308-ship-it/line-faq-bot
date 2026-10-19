"""Pure row matching shared by import, API results and browser observation.

No requests, authentication, browser access or retry logic lives here.
"""
import re
from decimal import Decimal, InvalidOperation


class ResultContractError(ValueError):
    """Fixed, non-sensitive diagnostic for an unverified MWG result."""
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def row_identity(row, remote=False):
    if not isinstance(row, dict):
        raise ResultContractError('row_type', 'Dữ liệu dòng MWG không hợp lệ; cần đối soát.')
    keys = ('FROMSTOREID', 'TOSTOREID', 'PRODUCTID', 'QUANTITY') if remote else (
        'source', 'destination', 'product', 'quantity')
    if any(key not in row for key in keys):
        raise ResultContractError('identity_missing', 'Thiếu trường đối chiếu dòng MWG; cần đối soát.')

    def whole(value):
        try:
            number = Decimal(str(value))
        except InvalidOperation:
            raise ResultContractError('store_quantity_invalid', 'Mã kho hoặc số lượng không hợp lệ.') from None
        if not number.is_finite() or number <= 0 or number != number.to_integral_value():
            raise ResultContractError('store_quantity_invalid', 'Mã kho hoặc số lượng không hợp lệ.')
        return str(int(number))

    product = row[keys[2]]
    # Never restore missing leading zeroes by guessing or converting a number.
    if not isinstance(product, str):
        raise ResultContractError('product_type', 'Mã sản phẩm phải là chuỗi giữ nguyên số 0 đầu.')
    product = product.strip()
    if not product or not product.isascii() or not product.isdigit():
        raise ResultContractError('product_format', 'Mã sản phẩm không hợp lệ.')
    return whole(row[keys[0]]), whole(row[keys[1]]), product, whole(row[keys[3]])


def expected_identities(records):
    if not isinstance(records, list) or not records:
        raise ResultContractError('request_empty', 'Yêu cầu không có dòng hàng hợp lệ.')
    wanted = [row_identity(row) for row in records]
    if len(set(wanted)) != len(wanted):
        raise ResultContractError('request_duplicate', 'Yêu cầu có dòng trùng; không thể đối chiếu duy nhất.')
    return wanted


def parse_created_rows(body, records):
    if not isinstance(body, dict):
        raise ResultContractError('body_type', 'MWG trả cấu trúc phản hồi không hợp lệ; chưa xác định được kết quả CO.')
    if 'Data' not in body:
        raise ResultContractError('data_missing', 'Phản hồi MWG thiếu bảng kết quả (Data); cần đối soát, không tạo lại.')
    rows = body['Data']
    if rows is None:
        raise ResultContractError('data_null', 'MWG trả bảng kết quả rỗng (Data=null); chưa xác định được CO. Giữ yêu cầu để đối soát, không tạo lại.')
    if not isinstance(rows, list):
        raise ResultContractError('data_type', 'MWG trả sai định dạng bảng kết quả; cần đối soát, không tạo lại.')
    wanted = expected_identities(records)
    wanted_set = set(wanted)
    found = {}
    for row in rows:
        key = row_identity(row, True)
        if key not in wanted_set or key in found:
            raise ResultContractError('row_mismatch', 'Kết quả MWG không khớp duy nhất với yêu cầu; cần đối soát.')
        raw = str(row.get('STORECHANGEORDERID') or '').strip()
        error = str(row.get('ERRORNOTE') or '').strip()
        # Keep the format already accepted by the browser path and queue.
        co = raw if re.fullmatch(r'[0-9A-Z]+CO[0-9]+', raw) else ''
        state = 'unknown'
        if co and row.get('ISERROR') is False and not error:
            state = 'succeeded'
        elif not raw and row.get('ISERROR') is True and error:
            state = 'failed'
        if state == 'unknown':
            error = 'Phản hồi MWG chưa xác định kết quả; cần đối soát. ' + error[:250]
        found[key] = dict(co=co, error=error[:350], state=state)
    return [found.get(key, dict(co='', error='MWG chưa trả kết quả dòng này; cần đối soát.',
                               state='unknown')) for key in wanted]
