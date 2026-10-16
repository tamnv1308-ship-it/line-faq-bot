"""Observe the web page's own create request; never send or retry a CO."""
import re
from decimal import Decimal, InvalidOperation
from mwg_api_worker import CREATE_URL

CONFLICT='Kết quả MWG không nhất quán; cần đối soát.'

def identity(row, remote=False):
    keys=('FROMSTOREID','TOSTOREID','PRODUCTID','QUANTITY') if remote else ('source','destination','product','quantity')
    def whole(value):
        try:number=Decimal(str(value))
        except InvalidOperation:raise ValueError('Invalid identity') from None
        if not number.is_finite() or number<=0 or number!=number.to_integral_value():
            raise ValueError('Invalid identity')
        return str(int(number))
    return whole(row[keys[0]]),whole(row[keys[1]]),str(row[keys[2]]).strip(),whole(row[keys[3]])


def parse_created_rows(body, records):
    rows=body.get('Data') if isinstance(body,dict) else None
    if not isinstance(rows,list):raise ValueError('Missing result rows')
    wanted=[identity(r) for r in records]
    if len(set(wanted))!=len(wanted):raise ValueError('Ambiguous input rows')
    found={}
    for row in rows:
        key=identity(row,True)
        if key not in wanted or key in found:raise ValueError('Result identity mismatch')
        raw=str(row.get('STORECHANGEORDERID') or '').strip()
        error=str(row.get('ERRORNOTE') or '').strip()
        co=raw if re.fullmatch(r'[0-9A-Z]+CO[0-9]+',raw) else ''
        state='unknown'
        if co and row.get('ISERROR') is False and not error:state='succeeded'
        elif not raw and row.get('ISERROR') is True and error:state='failed'
        if state=='unknown':error='Phản hồi MWG chưa xác định kết quả; cần đối soát. '+error[:250]
        found[key]=dict(co=co,error=error[:350],state=state)
    return [found.get(key,dict(co='',error='MWG chưa trả kết quả dòng này; cần đối soát.',state='unknown')) for key in wanted]


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
        self.rows=None;self.done=False;self.problem=None
        self.handlers=(('request',self.request),('requestfinished',self.finished),('requestfailed',self.failed))
        for event,handler in self.handlers:page.on(event,handler)

    def request(self,request):
        if request.method=='POST' and request.url.split('?',1)[0].rstrip('/').lower()==CREATE_URL.lower():
            self.requests.append(request)
            if len(self.requests)>1:
                self.rows=None;self.problem='MWG gửi nhiều lượt tạo cho cùng thao tác; cần đối soát.'

    def finished(self,request):
        if request not in self.requests:return
        self.done=True
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
            self.done=True;self.problem='Kết nối MWG ngắt khi tạo CO; cần đối soát, không tạo lại.'

    def close(self):
        for event,handler in self.handlers:
            try:self.page.remove_listener(event,handler)
            except Exception:pass
