"""Read-only, exact-SKU policy display; never authorizes or rejects a CO."""
import logging
import os
import re
import threading
import time
import unicodedata

SHEET_ID = '1tjw9BdOmRah0Km2g0XilwTPrIaEPAQZ6n2ijvG71lmA'
_lock = threading.Lock()
_cache = {}
_until = 0


def fold(value):
    value = unicodedata.normalize('NFD', str(value or '').strip().lower())
    return ''.join(c for c in value if unicodedata.category(c) != 'Mn').replace('đ', 'd')


def parse_rows(rows):
    result = {}
    for row in rows:
        if len(row) < 3:
            continue
        code = str(row[1]).strip()
        if not re.fullmatch(r'\d{13}', code) or not re.search(r'iphone\s*18\s*pro\b', fold(row[2])):
            continue
        values = [str(row[n]).strip() if len(row) > n else '' for n in (3, 4, 5)]
        # Conflicting duplicate SKU entries are not evidence of permission.
        if code in result and result[code] != values:
            result[code] = ['Chưa rõ (dữ liệu trùng khác nhau)'] * 3
        else:
            result[code] = values
    return result


def load_conditions():
    global _cache, _until
    with _lock:
        if time.monotonic() < _until:
            return _cache
        try:
            from sheets import get_client
            session = get_client().http_client.session
            response = session.get(
                'https://sheets.googleapis.com/v4/spreadsheets/' + os.getenv('CO_POLICY_SHEET_ID', SHEET_ID) + '/values/DATA!A1:F200',
                params={'valueRenderOption': 'FORMATTED_VALUE'}, timeout=(3, 5))
            response.raise_for_status()
            _cache = parse_rows(response.json().get('values', []))
            _until = time.monotonic() + 60
        except Exception:
            logging.getLogger(__name__).warning('CO policy unavailable; displaying unknown, not cached permissions.')
            _cache = {}
            _until = time.monotonic() + 15
        return _cache


def condition_text(item, policies=None):
    if not re.search(r'iphone\s*18\s*pro\b', fold(item.get('product_name', ''))):
        return ''
    values = (policies or {}).get(item['product'], ['', '', ''])
    lines = ['📋 Điều kiện']
    for label, value in zip(('Bán thường', 'Chiến giá', 'Chuyển kho'), values):
        normalized = fold(value)
        if normalized in {'mo', 'duoc', 'co', 'duoc phep', 'yes', 'true', '✅'}:
            lines.append('✅ ' + label)
        elif normalized in {'khoa', 'khong', 'khong duoc', 'khong duoc phep', 'no', 'false', '❌'}:
            lines.append('❌ ' + label)
        else:
            lines.append(label + ': ' + (value or 'Chưa rõ'))
    return '\n'.join(lines)
