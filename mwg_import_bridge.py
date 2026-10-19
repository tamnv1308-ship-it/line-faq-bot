"""Import via authenticated API, then run MWG's existing import-success handler.

Never calls a CO creation endpoint. Fallback is allowed only before an upload.
The normal worker still verifies/accepts the popup and checks the main table.
"""
import json
import uuid
from pathlib import Path

from mwg_import_api import IMPORT_URL, ORIGIN, match_import_rows

VERSION = 1
IMPORT_TIMEOUT_MS = 15000


class BridgeUnavailable(RuntimeError):
    """No request was sent and no UI upload handler was invoked."""


class ImportResponse:
    status = 200

    def __init__(self, body):
        self.body = body

    def json(self):
        return self.body


# Source: the observed StoreChangeOrderManuallyController Kendo upload handlers.
# Upload prepares model-derived parameters/headers; success opens its own popup.
# No Angular model/table is fabricated and CreateGroupCO is never invoked here.
PREFLIGHT = r'''() => {
  const el = document.querySelector('#fileUpload');
  const widget = el && window.jQuery && window.jQuery(el).data('kendoUpload');
  if (!widget || typeof widget.trigger !== 'function' ||
      typeof widget.options.upload !== 'function' ||
      typeof widget.options.success !== 'function' ||
      typeof widget.options.error !== 'function') return null;
  return {url: new URL(widget.options.async.saveUrl, location.href).href};
}'''
BEGIN = r'''arg => {
  const el = document.querySelector('#fileUpload');
  const widget = el && window.jQuery(el).data('kendoUpload');
  if (!widget || window.__taoImportBridgeV1) throw new Error('Import bridge busy');
  if (new URL(widget.options.async.saveUrl, location.href).href !== arg.url)
    throw new Error('Import endpoint changed');
  const event = {files: [{name:arg.name,extension:'.xlsx',size:arg.size,uid:arg.id}],
                 operation:'upload'};
  window.__taoImportBridgeV1 = {id:arg.id,widget,event};
  if (widget.trigger('upload',event)) throw new Error('Upload was rejected');
  return {data:event.data,headers:event.headers};
}'''
FINISH = r'''arg => {
  const current=window.__taoImportBridgeV1;
  const el=document.querySelector('#fileUpload');
  if (!current || current.id!==arg.id || !el ||
      window.jQuery(el).data('kendoUpload')!==current.widget)
    throw new Error('Import page changed');
  // Consume first: the imported response cannot be injected twice.
  delete window.__taoImportBridgeV1;
  current.widget.trigger('success', {...current.event, response:arg.body,
    XMLHttpRequest:{status:200,statusText:'OK',responseText:JSON.stringify(arg.body)}});
  return true;
}'''
ABORT = r'''id => {
  const current=window.__taoImportBridgeV1;
  if (!current || current.id!==id) return;
  delete window.__taoImportBridgeV1;
  current.widget.trigger('error',{...current.event,XMLHttpRequest:{status:0}});
}'''


def parameters(value, status_id):
    if not isinstance(value, dict) or not isinstance(value.get('data'), dict):
        raise ValueError('MWG chưa trả tham số nhập file.')
    raw=value['data']; headers=value.get('headers')
    if not isinstance(headers,dict):raise ValueError('Thiếu xác thực nhập file MWG.')
    token=headers.get('X-XSRF-TOKEN')
    if not isinstance(token,str) or not token or '\r' in token or '\n' in token:
        raise ValueError('Thiếu xác thực nhập file MWG.')
    if str(raw.get('INVENTORYSTATUSID')) != str(status_id):
        raise ValueError('Trạng thái MWG đã thay đổi; chưa nhập file.')
    if str(raw.get('STORECHANGETYPEID'))!='1' or str(raw.get('STORECHANGEORDERTYPEID'))!='0':
        raise ValueError('Loại chuyển kho MWG không đúng; chưa nhập file.')
    if set(str(raw.get('BRANDID','')).split(',')) != {'1','2','16'}:
        raise ValueError('Thương hiệu MWG không đúng; chưa nhập file.')
    content=raw.get('CONTENT')
    if content not in ('',None):
        raise ValueError('Ô Nội dung MWG đang có dữ liệu khác; chưa nhập file.')
    return ({key:str(raw[key]) if raw[key] is not None else '' for key in
             ('INVENTORYSTATUSID','STORECHANGETYPEID','STORECHANGEORDERTYPEID','BRANDID','CONTENT')},
            {'X-XSRF-TOKEN':token})


def validate_rows(body, records, status_id):
    rows=match_import_rows(body,records)
    for row,expected in zip(rows,records):
        # Business-error rows retain their reason and are filtered by the worker.
        if row.get('ISERROR') is not False or row.get('ERRORNOTE'):continue
        if str(row.get('INVENTORYSTATUSID'))!=str(status_id):
            raise ValueError('Trạng thái sau nhập không khớp yêu cầu.')
        if (row.get('NOTE') or '')!=expected.get('note',''):
            raise ValueError('Ghi chú sau nhập không khớp yêu cầu.')
        if str(row.get('STORECHANGEORDERTYPEID'))!='0' or str(row.get('ISURGENT') or 0)!='0':
            raise ValueError('Loại chuyển kho sau nhập không khớp yêu cầu.')
    # MWG's own success callback JSON.parse's this field.
    if not isinstance(body['Data']['Data'],str):
        body=dict(body,Data=dict(body['Data'],Data=json.dumps(rows,ensure_ascii=False)))
    return body


def import_preview(page, output, records, status_id, on_start=lambda:None):
    path=Path(output)
    if path.suffix.lower()!='.xlsx' or not path.is_file():
        raise ValueError('File nhập không hợp lệ; chưa gửi MWG.')
    if page.url.split('?',1)[0].split('#',1)[0].rstrip('/')!=ORIGIN+'/storechangeordermanually':
        raise BridgeUnavailable('Chưa ở trang nhập file MWG.')
    try:capability=page.evaluate(PREFLIGHT)
    except Exception:raise BridgeUnavailable('Chưa đọc được thành phần nhập file.') from None
    if not isinstance(capability,dict) or capability.get('url','').lower()!=IMPORT_URL.lower():
        raise BridgeUnavailable('Thành phần nhập file chưa tương thích.')
    attempt=uuid.uuid4().hex
    try:
        on_start()
        context=page.evaluate(BEGIN,{'id':attempt,'url':capability['url'],'name':path.name,'size':path.stat().st_size})
        data,headers=parameters(context,status_id)
        response=page.context.request.post(IMPORT_URL,multipart=dict(data,fileUpload={
            'name':path.name,'mimeType':'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            'buffer':path.read_bytes()}),headers=headers,timeout=IMPORT_TIMEOUT_MS,max_redirects=0,max_retries=0)
        try:
            if response.status!=200:raise ValueError('Nhập file API MWG lỗi HTTP '+str(response.status)+'.')
            try:body=response.json()
            except Exception:raise ValueError('MWG chưa trả dữ liệu nhập file hợp lệ; kiểm tra phiên đăng nhập.') from None
            body=validate_rows(body,records,status_id)
        finally:
            response.dispose()
        page.evaluate(FINISH,{'id':attempt,'body':body})
        return ImportResponse(body)
    except Exception as error:
        try:page.evaluate(ABORT,attempt)
        except Exception:pass
        # No retries/fallback after BEGIN: never hide an uncertain import outcome.
        if isinstance(error,ValueError):raise
        raise RuntimeError('Không hoàn tất nhập file API MWG ('+type(error).__name__+'); chưa tạo CO.') from None
