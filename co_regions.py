"""Read the private store directory for confirmation labels only."""
import base64
import json
import os
import zlib
from functools import lru_cache
from pathlib import Path
from co_store_directory import override_path

REGIONS = {'Hà Nội +', 'Hồ Chí Minh', 'Đông Tây Bắc', 'Đồng Bằng Sông Hồng',
           'Trung Bộ', 'Duyên Hải', 'Đông Cao Nguyên', 'Tây Nam Bộ'}

@lru_cache(maxsize=2)
def _file_stores(path,stamp,size,inode,override):
    payload=json.loads(Path(path).read_text())
    mapping=payload['stores'] if override else payload
    if not isinstance(mapping,dict) or any(not isinstance(row,dict) for row in mapping.values()):
        raise ValueError('Danh mục shop không hợp lệ.')
    return mapping

@lru_cache(maxsize=1)
def _packed_stores(packed):
    return json.loads(zlib.decompress(base64.b64decode(packed)))

def stores():
    try:
        path=override_path()
        if path.exists():
            stat=path.stat()
            return _file_stores(str(path),stat.st_mtime_ns,stat.st_size,stat.st_ino,True)
        packed = os.getenv('CO_STORES_ZLIB')
        if packed:
            return _packed_stores(packed)
        path=Path(os.getenv('CO_STORES_PATH', '/var/data/co_stores.json'));stat=path.stat()
        return _file_stores(str(path),stat.st_mtime_ns,stat.st_size,stat.st_ino,False)
    except (ValueError, OSError, zlib.error, KeyError, TypeError):
        return {}

def clear_store_cache():
    _file_stores.cache_clear();_packed_stores.cache_clear()

def cluster_label(item):
    mapping=stores()
    source={g['id']:g for g in mapping.get(str(int(item['source'])),{}).get('clusters',[])}
    destination={g['id']:g for g in mapping.get(str(int(item['destination'])),{}).get('clusters',[])}
    shared=sorted(source.keys() & destination.keys())
    return '⚠️ CÙNG CỤM: '+', '.join(source[g]['name'] for g in shared) if shared else ''

def cluster_condition(item):
    mapping=stores()
    source={g['id']:g for g in mapping.get(str(int(item['source'])),{}).get('clusters',[])}
    destination={g['id']:g for g in mapping.get(str(int(item['destination'])),{}).get('clusters',[])}
    if not source or not destination:
        missing=', '.join(label for label,groups in (('kho xuất',source),('kho nhận',destination)) if not groups)
        return '❌ Cụm: Chưa có dữ liệu '+missing
    shared=sorted(source.keys() & destination.keys())
    if shared:
        return '✅ Cùng cụm: '+', '.join(source[g]['name'] for g in shared)
    return '❌ Khác cụm'

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
