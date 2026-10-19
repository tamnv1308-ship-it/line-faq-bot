"""Authenticated MWG API path; memory-only preparation and single-shot creation."""
import json
import re
from mwg_import_api import ORIGIN, probe_import
from mwg_result_contract import row_identity as identity, expected_identities, parse_created_rows
from co_reconciliation_hold import enforce as enforce_reconciliation_hold

CREATE_URL=ORIGIN+'/StoreChangeOrderManually/CreateGroupCO'

def fingerprint(records,status):
    return (status,tuple((identity(r),r.get('note','')) for r in records))

def outcomes(body,records):
    # HTTP 200 / Success true alone never proves creation.
    result=parse_created_rows(body,records)
    unknown=any(row['state']=='unknown' for row in result)
    # The existing queue uses succeeded for a resolved batch with at least one
    # CO; retain explicit per-row failure states for accurate UI/protection.
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
            expected_identities(records)
            enforce_reconciliation_hold(worker.ROOT,job['id'],records)
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
                worker.report(job,'unknown',json.dumps([{'co':'','error':'Cần đối soát MWG; không tự tạo lại. '+message,'state':'unknown'} for _ in records],ensure_ascii=False))
            else:
                worker.report(job,'failed',message+' Chưa tạo CO.',before_submit=True)
