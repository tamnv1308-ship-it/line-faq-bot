"""Read the private store directory for confirmation labels only."""
import base64
import json
import os
import zlib
from functools import lru_cache
from pathlib import Path

REGIONS = {'Hà Nội +', 'Hồ Chí Minh', 'Đông Tây Bắc', 'Đồng Bằng Sông Hồng',
           'Trung Bộ', 'Duyên Hải', 'Đông Cao Nguyên', 'Tây Nam Bộ'}

@lru_cache(maxsize=1)
def stores():
    try:
        packed = os.getenv('CO_STORES_ZLIB')
        if packed:
            return json.loads(zlib.decompress(base64.b64decode(packed)))
        return json.loads(Path(os.getenv('CO_STORES_PATH', '/var/data/co_stores.json')).read_text())
    except (ValueError, OSError, zlib.error):
        return {}

def region(code):
    value = stores().get(str(int(code)), {}).get('region', '').strip()
    if value.startswith('Vùng '):
        value = value[5:]
    return value if value in REGIONS else None

def region_label(item):
    source, destination = region(item['source']), region(item['destination'])
    if not source or not destination:
        missing = ', '.join(label for label, value in [('kho xuất', source), ('kho nhận', destination)] if not value)
        return 'unknown', f'❓ CHƯA XÁC ĐỊNH VÙNG — {missing} chưa có dữ liệu trong 8 vùng.'
    if source == destination:
        return 'same', f'✅ CÙNG VÙNG: {source}'
    return 'different', f'⚠️ KHÁC VÙNG: {source} → {destination}'
