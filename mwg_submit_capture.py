"""Observe the web page's own create request; never send or retry a CO."""
import math
import time
import uuid
from mwg_api_worker import CREATE_URL
from mwg_result_contract import row_identity as identity, parse_created_rows, ResultContractError

CONFLICT='Kết quả MWG không nhất quán; cần đối soát.'

def merge_results(previous, received):
    """Never erase a CO or overwrite a known outcome with conflicting evidence."""
    if len(previous)!=len(received):raise ValueError('Result count mismatch')
    merged=[]
    for old,new in zip(previous,received):
        if old.get('error')==CONFLICT:
            merged.append(old)
        elif old.get('state') in {'succeeded','failed'} and old!=new:
            if new.get('state')=='unknown' and not new.get('co'):
                merged.append(old);continue
            merged.append(dict(co=old.get('co') or new.get('co',''),
                               error=CONFLICT,state='unknown'))
        elif old.get('co') and old['co']!=new.get('co'):
            merged.append(dict(co=old['co'],error=CONFLICT,state='unknown'))
        else:merged.append(new)
    return merged


def value_kind(value):
    if value is None:return 'null'
    if isinstance(value,bool):return 'boolean'
    if isinstance(value,dict):return 'object'
    if isinstance(value,list):return 'array'
    if isinstance(value,str):return 'string'
    if isinstance(value,(int,float)):return 'number'
    return 'other'


def response_shape(body):
    """Only types/counts/boolean flags: no rows, notes, messages or credentials."""
    summary={'body_type':value_kind(body)}
    if not isinstance(body,dict):return summary
    summary.update(data_present='Data' in body,success_type=value_kind(body.get('Success')),
                   message_present=isinstance(body.get('Message'),str) and bool(body['Message'].strip()))
    if isinstance(body.get('Success'),bool):summary['success']=body['Success']
    if 'Data' in body:summary['data_type']=value_kind(body['Data'])
    if isinstance(body.get('Data'),list):summary['row_count']=len(body['Data'])
    return summary


class CreateCapture:
    def __init__(self,page,records,on_diagnostic=None):
        self.page=page;self.records=records;self.requests=[]
        self.rows=None;self.done=False;self.problem=None;self.inflight=set()
        self.started_at=None;self.clicked_at=None;self.click_button=None
        self.click_key='__co_click_'+uuid.uuid4().hex
        self.on_diagnostic=on_diagnostic
        self.diagnostic={'version':1,'expected_rows':len(records)}
        self.handlers=(('request',self.request),('requestfinished',self.finished),('requestfailed',self.failed))
        for event,handler in self.handlers:page.on(event,handler)

    def arm_click(self,button):
        self.click_button=button
        try:
            button.evaluate('''(el,key)=>{
                const mark={at:null};
                mark.handler=e=>{if(e.isTrusted && mark.at===null)mark.at=performance.now();};
                el[key]=mark;el.addEventListener('click',mark.handler,{capture:true,once:true});
            }''',self.click_key,timeout=1000)
        except Exception:pass  # Fall back to the observed POST, never start during preparation.

    def result_deadline(self,seconds):
        elapsed=None
        try:
            elapsed=self.click_button.evaluate('''(el,key)=>{
                const mark=el[key];
                return mark && typeof mark.at==='number' ? (performance.now()-mark.at)/1000 : null;
            }''',self.click_key,timeout=1000)
        except Exception:pass
        if type(elapsed) in (float,int) and math.isfinite(elapsed) and elapsed>=0:
            self.clicked_at=time.monotonic()-elapsed
            basis='trusted_click'
        elif self.started_at is not None:
            self.clicked_at=self.started_at;basis='observed_post'
        else:
            basis='click_return'
        start=self.clicked_at if self.clicked_at is not None else time.monotonic()
        self.diagnostic.update(wait_seconds=seconds,timer_basis=basis,
                               click_age_at_wait_seconds=round(max(0,time.monotonic()-start),3))
        self.record()
        return start+seconds

    def record(self,code=None):
        if code is not None:self.diagnostic['code']=code
        self.diagnostic.update(request_count=len(self.requests),transport_finished=self.done)
        if self.on_diagnostic:
            try:self.on_diagnostic(dict(self.diagnostic))
            except Exception:pass  # A diagnostic write must never lose a CO result.

    def request(self,request):
        if request.method=='POST' and request.url.split('?',1)[0].rstrip('/').lower()==CREATE_URL.lower():
            self.requests.append(request)
            if self.started_at is None:self.started_at=time.monotonic()
            self.inflight.add(request);self.done=False
            if len(self.requests)>1:
                self.rows=None;self.problem='MWG gửi nhiều lượt tạo cho cùng thao tác; cần đối soát.'
                self.record('multiple_requests')

    def finished(self,request):
        if request not in self.requests:return
        self.inflight.discard(request);self.done=not self.inflight
        if len(self.requests)!=1:
            self.record('multiple_requests');return
        try:
            response=request.response()
            if type(response.status) is int:self.diagnostic['http_status']=response.status
            if response.status!=200:
                self.problem='MWG trả HTTP '+str(response.status)+' ở bước tạo CO; cần đối soát.'
                self.record('http_error')
                return
            try:body=response.json()
            except Exception:
                self.problem='MWG trả dữ liệu không đọc được ở bước tạo CO; chưa xác định kết quả, không tạo lại.'
                self.record('invalid_json');return
            self.diagnostic.update(response_shape(body))
            self.rows=parse_created_rows(body,self.records)
            if all(row['state'] in {'succeeded','failed'} for row in self.rows):
                self.record('verified')
            else:self.record('incomplete_rows')
        except ResultContractError as error:
            self.problem=str(error)
            self.record(error.code)
        except Exception:
            self.problem='Không đọc được phản hồi tạo CO của MWG; cần đối soát, không tạo lại.'
            self.record('response_unavailable')

    def failed(self,request):
        if request in self.requests:
            self.inflight.discard(request);self.done=not self.inflight
            self.problem='Kết nối MWG ngắt khi tạo CO; cần đối soát, không tạo lại.'
            self.record('network_failed' if len(self.requests)==1 else 'multiple_requests')

    def close(self):
        for event,handler in self.handlers:
            try:self.page.remove_listener(event,handler)
            except Exception:pass
        if self.click_button is not None:
            try:
                self.click_button.evaluate('''(el,key)=>{
                    const mark=el[key];if(mark)el.removeEventListener('click',mark.handler,true);
                    delete el[key];
                }''',self.click_key,timeout=1000)
            except Exception:pass
