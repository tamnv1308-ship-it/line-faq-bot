"""Validated private store data, persisted outside the public source checkout."""
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path

VERSION = 1


def override_path():
    custom=os.getenv('CO_STORES_OVERRIDE_PATH')
    if custom:
        return Path(custom)
    database=os.getenv('CO_DB_PATH','')
    if database and Path(database).is_absolute():
        return Path(database).with_name('co_store_directory.json')
    return Path('/var/data/co_store_directory.json')


def validate(payload):
    if not isinstance(payload,dict) or payload.get('version')!=VERSION:
        raise ValueError('Sai phiên bản danh mục shop.')
    source=payload.get('source')
    source_hash=payload.get('source_sha256')
    rows=payload.get('stores')
    if not isinstance(source,str) or not 1<=len(source)<=100 or not isinstance(source_hash,str) or not re.fullmatch('[0-9a-f]{64}',source_hash):
        raise ValueError('Thiếu nguồn danh mục hợp lệ.')
    if not isinstance(rows,dict) or not 1<=len(rows)<=10000:
        raise ValueError('Danh mục shop rỗng hoặc quá lớn.')
    text_fields={'name','region','province','province_old','ward','district_old','channel','record_type'}
    groups={}
    for code,row in rows.items():
        if not isinstance(code,str) or not re.fullmatch('[1-9][0-9]{0,5}',code) or not isinstance(row,dict):
            raise ValueError('Mã shop không hợp lệ.')
        if set(row)-text_fields-{'clusters'} or not {'name','region','province'}<=set(row):
            raise ValueError('Sai trường thông tin shop.')
        if any(not isinstance(row[k],str) or len(row[k])>600 for k in set(row)&text_fields):
            raise ValueError('Thông tin shop không hợp lệ.')
        clusters=row.get('clusters',[])
        if not isinstance(clusters,list) or len(clusters)>10:
            raise ValueError('Danh sách cụm không hợp lệ.')
        seen=set()
        for cluster in clusters:
            if not isinstance(cluster,dict) or set(cluster)!={'id','name','base'}:
                raise ValueError('Sai thông tin cụm.')
            if any(not isinstance(cluster[k],str) or not 1<=len(cluster[k])<=100 for k in cluster):
                raise ValueError('Thông tin cụm rỗng hoặc quá dài.')
            if not re.fullmatch('[1-9][0-9]{0,5}',cluster['base']) or cluster['base'] not in rows or cluster['id'] in seen:
                raise ValueError('ST base không hợp lệ hoặc cụm bị trùng.')
            seen.add(cluster['id'])
            identity=(cluster['name'],cluster['base'])
            if groups.setdefault(cluster['id'],identity)!=identity:
                raise ValueError('Tên cụm/ST base mâu thuẫn giữa các shop.')
    for group,(_,base) in groups.items():
        if group not in {g['id'] for g in rows[base].get('clusters',[])}:
            raise ValueError('ST base chưa có quan hệ với cụm tham chiếu.')
    encoded=json.dumps(payload,ensure_ascii=False,separators=(',',':')).encode()
    if len(encoded)>3000000:
        raise ValueError('Danh mục vượt 3 MB.')
    return encoded


def metadata(payload):
    rows=payload['stores']
    encoded=json.dumps(payload,ensure_ascii=False,separators=(',',':')).encode()
    return dict(version=payload['version'],source=payload['source'],source_sha256=payload['source_sha256'],
                digest=hashlib.sha256(encoded).hexdigest(),stores=len(rows),
                detail_stores=sum(row.get('record_type','detail')=='detail' for row in rows.values()),
                clusters=len({g['id'] for row in rows.values() for g in row.get('clusters',[])}))


def write(payload):
    encoded=validate(payload)
    path=override_path();path.parent.mkdir(parents=True,exist_ok=True)
    temporary=None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent,prefix='.co-directory-',delete=False) as stream:
            temporary=Path(stream.name)
            stream.write(encoded);stream.flush();os.fsync(stream.fileno())
        # Retain one prior snapshot for rollback, without publishing either copy.
        if path.exists():
            previous=path.with_suffix('.previous.json')
            with previous.open('wb') as stream:
                os.chmod(previous,0o600)
                stream.write(path.read_bytes());stream.flush();os.fsync(stream.fileno())
        os.replace(temporary,path)
    finally:
        if temporary and temporary.exists():temporary.unlink()
    return metadata(payload)


def status():
    try:
        return metadata(json.loads(override_path().read_text()))
    except (OSError,ValueError,KeyError,TypeError):
        return {'version':VERSION,'loaded':False}
