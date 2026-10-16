"""Authenticated MWG API path; memory-only preparation and single-shot creation."""
import json
import re
from mwg_import_api import ORIGIN, probe_import

CREATE_URL=ORIGIN+'/StoreChangeOrderManually/CreateGroupCO'

def identity(row, remote=False):
    keys=('FROMSTOREID','TOSTOREID','PRODUCTID','QUANTITY') if remote else ('source','destination','product','quantity')
    return (str(int(row[keys[0]])),str(int(row[keys[1]])),str(row[keys[2]]),int(row[keys[3]]))

def fingerprint(records,status):
    return (status,tuple((identity(r),r.get('note','')) for r in records))

def outcomes(body,records):
    # HTTP 200 / Success true alone never proves creation.
    rows=body.get('Data') if isinstance(body,dict) else None
    if not isinstance(rows,list):
        raise ValueError('MWG không trả danh sách kết quả; cần đối soát trước khi tạo lại.')
    wanted=[identity(r) for r in records]
    mapped={}
    for row in rows:
        key=identity(row,True)
        if key not in wanted or key in mapped:
            raise ValueError('Kết quả MWG không khớp yêu cầu; cần đối soát.')
        co=str(row.get('STORECHANGEORDERID') or '').strip()
        error=str(row.get('ERRORNOTE') or '').strip()
        valid=bool(re.fullmatch(r'[0-9]+CO[0-9]+',co))
        if valid and row.get('ISERROR') is False and not error:
            mapped[key]=({'co':co,'error':''},False)
        elif not co and row.get('ISERROR') is True and error:
            mapped[key]=({'co':'','error':error[:350]},False)
        else:
            mapped[key]=({'co':co if valid else '', 'error':'Chưa rõ kết quả MWG; cần đối soát. '+error[:250]},True)
    result=[];unknown=False
    for key in wanted:
        row,uncertain=mapped.get(key,({'co':'','error':'MWG chưa trả kết quả dòng này; cần đối soát.'},True))
        result.append(row);unknown|=uncertain
    return ('unknown' if unknown else 'succeeded' if any(r['co'] for r in result) else 'failed'),result


def create(request,token,rows):
    data=[{k:r[k] for k in ('FROMSTOREID','TOSTOREID','INVENTORYSTATUSID','PRODUCTID','QUANTITY','NOTE','STORECHANGEORDERTYPEID','CONTENT','ISURGENT')} for r in rows]
    for r in data:
        r['INVENTORYSTATUSID']=int(r['INVENTORYSTATUSID'])
        r['ISURGENT']=int(r['ISURGENT'] or 0)
    payload={k:False for k in ('ISLOCKGOODSEVENT','ISMAINTENANCEPARTS_LIFETIME','ISNONBUSINESSIT','ISNONBUSINESSLOGISTICS','ISSTORECHANGEORDERBYPASSSTOCK')}
    payload['Json']=json.dumps(data,ensure_ascii=False)
    response=request.post(CREATE_URL,data=payload,headers={'X-Xsrf-Token':token,'Clientcompanyid':'1','Clientlanguage':'2','Clienturl':ORIGIN+'/storechangeordermanually','Groupbrandcompanyid':'1','Origin':ORIGIN,'Referer':ORIGIN+'/storechangeordermanually'},timeout=60000,max_redirects=0,max_retries=0)
    if response.status!=200:
        raise ValueError('MWG trả HTTP '+str(response.status)+' sau khi gửi tạo; cần đối soát.')
    return response.json()


class ApiWorker:
    def __init__(self):
        self.prepared=None

    def process(self,page,job,prepared_id,worker):
        records=worker.items(job['payload'])
        status=worker.normalize_status(job['payload'].get('status','Mới'))
        sent=False
        try:
            if job.get('mode')=='preview':
                self.prepared=None
                worker.progress(job,'api_prepare')
                page.goto(worker.URL,wait_until='domcontentloaded',timeout=30000)
                worker.prepare_import_controls(page,job)
                label=page.get_by_role('combobox',name='Vui lòng chọn trạng thái sản phẩm',exact=True).input_value()
                match=re.match(r'^\s*(\d+)\s*-',label)
                if not match or worker.normalize_status(label)!=status:
                    raise ValueError('Chưa xác minh được trạng thái MWG; chưa nhập file.')
                token=page.locator('input[name="__RequestVerificationToken"]').first.input_value(timeout=5000)
                folder=worker.ROOT/job['id'];folder.mkdir(exist_ok=True)
                output=folder/'StoreChangeOrderTGDD_upload.xlsx'
                worker.fill_template(worker.TEMPLATE,output,job['payload'])
                worker.progress(job,'api_import')
                rows=probe_import(page.context.request,token,output,records,match.group(1))
                for r,e in zip(rows,records):
                    if str(r.get('INVENTORYSTATUSID'))!=match.group(1) or (r.get('NOTE') or '')!=e.get('note',''):
                        raise ValueError('Trạng thái hoặc ghi chú sau nhập không khớp.')
                self.prepared=(job['id'],fingerprint(records,status),rows,token,page)
                worker.report(job,'preview_ready',json.dumps({'rows':[{'product_name':r['PRODUCTNAME'],'source_name':str(r['FROMSTOREID'])+' - '+r['FROMSTORENAME'],'destination_name':str(r['TOSTOREID'])+' - '+r['TOSTORENAME']} for r in rows]},ensure_ascii=False))
                return job['id']
            cached=self.prepared
            if job.get('mode')!='create' or not cached or prepared_id!=job['id'] or cached[0]!=job['id'] or cached[1]!=fingerprint(records,status) or cached[4] is not page:
                raise ValueError('Phiên chuẩn bị API không còn hoặc dữ liệu đã đổi; chưa tạo CO. Gửi yêu cầu mới.')
            for r,e in zip(cached[2],records):
                if e.get('product_name')!=r['PRODUCTNAME']:
                    raise ValueError('Tên sản phẩm khác bản xác nhận; chưa tạo CO.')
            worker.report(job,'submitting')
            sent=True
            self.prepared=None # Consume before sending; never replay on network errors.
            worker.progress(job,'api_submit_co')
            body=create(page.context.request,cached[3],cached[2])
            state,result=outcomes(body,records)
            worker.report(job,state,json.dumps(result,ensure_ascii=False))
        except Exception as error:
            self.prepared=None
            if (worker.ROOT/'pending.json').exists():
                raise
            # Do not leak browser request headers or tokens through exception text.
            message=str(error)[:500] if isinstance(error,ValueError) else 'Lỗi kết nối API MWG ('+type(error).__name__+').'
            if sent:
                worker.report(job,'unknown',json.dumps([{'co':'','error':'Cần đối soát MWG; không tự tạo lại. '+message} for _ in records],ensure_ascii=False))
            else:
                worker.report(job,'failed',message+' Chưa tạo CO.',before_submit=True)
