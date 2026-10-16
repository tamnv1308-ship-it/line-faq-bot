"""Small durable diagnostics spool; no browser calls or synchronous network work."""
import json
import threading
import time
import uuid
from co_observability import WORKER_STAGES, classify
from worker_runtime import atomic_json


class Telemetry:
    def __init__(self, root):
        self.path=root/'telemetry-pending.json'
        self.lock=threading.RLock();self.active={};self.warned=False
        try:
            rows=json.loads(self.path.read_text())
            self.events=[r for r in rows if isinstance(r,dict) and r.get('at',0)>time.time()-30*86400][-1000:] if isinstance(rows,list) else []
        except (OSError,ValueError,TypeError):self.events=[]

    def save(self):
        try:atomic_json(self.path,self.events[-1000:])
        except Exception:
            if not self.warned:
                print('Chưa lưu được nhật ký đo thời gian; xử lý CO vẫn tiếp tục.',flush=True)
                self.warned=True

    def append(self, job, stage, outcome, duration=None, code=''):
        self.events.append(dict(event_id=uuid.uuid4().hex,job_id=job['id'],lease=job['lease'],
                                stage=stage,at=time.time(),duration_ms=duration,outcome=outcome,error_code=code))
        self.events=self.events[-1000:]

    def finish(self, job, error='', persist=True):
        with self.lock:
            previous=self.active.pop((job['id'],job['lease']),None)
            if previous:
                stage,started=previous
                self.append(job,stage,'error' if error else 'ok',round(max(0,time.monotonic()-started)*1000,2),classify(error) if error else '')
                if persist:self.save()

    def progress(self, job, stage):
        with self.lock:
            if stage.startswith('exception_'):
                self.finish(job,stage);return
            if stage not in WORKER_STAGES:return
            self.finish(job,persist=False)
            self.active[(job['id'],job['lease'])]=(stage,time.monotonic())
            self.append(job,stage,'start');self.save()

    def batch(self, job=None):
        with self.lock:
            fresh=[e for e in self.events if e['at']>time.time()-30*86400]
            if len(fresh)!=len(self.events):self.events=fresh;self.save()
            rows=self.events if job is None else [e for e in self.events if e['job_id']==job['id'] and e['lease']==job['lease']]
            return [dict(e) for e in rows[:40]]

    def delivery_error(self, job, error):
        with self.lock:
            status=getattr(error,'code',None)
            code='service_auth' if status in (401,403) else 'mismatch' if type(error).__name__=='ResultDeliveryBlocked' else 'timeout' if 'timeout' in type(error).__name__.lower() else 'network'
            # Do not copy exception text: network exceptions can contain URLs/tokens.
            self.append(job,'send_result','error',code=code);self.save()

    def acknowledge(self, ids):
        if not isinstance(ids,list):return
        with self.lock:
            known={x for x in ids if isinstance(x,str)}
            if known:
                self.events=[e for e in self.events if e['event_id'] not in known];self.save()
