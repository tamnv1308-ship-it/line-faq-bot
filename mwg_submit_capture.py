"""Observe the web page's own create request; never send or retry a CO."""
from mwg_api_worker import CREATE_URL
from mwg_result_contract import row_identity as identity, parse_created_rows

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


class CreateCapture:
    def __init__(self,page,records):
        self.page=page;self.records=records;self.requests=[]
        self.rows=None;self.done=False;self.problem=None;self.inflight=set()
        self.handlers=(('request',self.request),('requestfinished',self.finished),('requestfailed',self.failed))
        for event,handler in self.handlers:page.on(event,handler)

    def request(self,request):
        if request.method=='POST' and request.url.split('?',1)[0].rstrip('/').lower()==CREATE_URL.lower():
            self.requests.append(request)
            self.inflight.add(request);self.done=False
            if len(self.requests)>1:
                self.rows=None;self.problem='MWG gửi nhiều lượt tạo cho cùng thao tác; cần đối soát.'

    def finished(self,request):
        if request not in self.requests:return
        self.inflight.discard(request);self.done=not self.inflight
        if len(self.requests)!=1:return
        try:
            response=request.response()
            if response.status!=200:
                self.problem='MWG trả HTTP '+str(response.status)+' ở bước tạo CO; cần đối soát.'
                return
            self.rows=parse_created_rows(response.json(),self.records)
        except Exception as error:
            # Never include response bodies, tokens or cookies in diagnostics.
            self.problem='Chưa đối chiếu được phản hồi tạo CO ('+type(error).__name__+'); cần đối soát.'

    def failed(self,request):
        if request in self.requests:
            self.inflight.discard(request);self.done=not self.inflight
            self.problem='Kết nối MWG ngắt khi tạo CO; cần đối soát, không tạo lại.'

    def close(self):
        for event,handler in self.handlers:
            try:self.page.remove_listener(event,handler)
            except Exception:pass
