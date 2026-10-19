"""Local worker identity and cooperative shutdown; no process-name killing."""
import fcntl
import json
import os
import select
import signal
import sys
import threading
import time
import uuid
from pathlib import Path

# This is a controller-health alarm, not the CO response deadline. Slow MWG
# still pumps browser events and refreshes control progress below this limit.
CONTROL_STALE_SECONDS = 60


def atomic_json(path, value):
    tmp=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    try:
        with tmp.open('x') as stream:
            os.chmod(tmp,0o600)
            json.dump(value,stream,ensure_ascii=False)
            stream.flush();os.fsync(stream.fileno())
        tmp.replace(path)
    finally:
        tmp.unlink(missing_ok=True)


def read_json(path):
    try:return json.loads(path.read_text())
    except (OSError,ValueError):return {}


def lock_held(root):
    root.mkdir(exist_ok=True)
    with (root/'worker.lock').open('a') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:return True
        return False


def request_stop(root):
    # Target the current UUID. An old stop file cannot stop the next session.
    if not lock_held(root):return 'stopped'
    identity=read_json(root/'worker.json')
    if not identity.get('instance') or identity.get('state')=='stopped':return 'legacy'
    atomic_json(root/'stop-request.json',{'instance':identity['instance']})
    return 'requested'


class Runtime:
    def __init__(self,root):
        self.root=Path(root)
        self.instance=uuid.uuid4().hex
        self.mutex=threading.RLock()
        self.stop=threading.Event()
        self.state='loading';self.changed=time.monotonic()
        self.control_at=self.changed
        self.main_thread=threading.get_ident()
        self.driver_probe=None
        self.browser_generation=0
        self.browser_connected=None
        self.old_handlers={}
        self.managed=os.environ.get('CO_MANAGED_WORKER')=='1'

    def install(self):
        for kind in (signal.SIGTERM,signal.SIGINT,signal.SIGHUP):
            self.old_handlers[kind]=signal.getsignal(kind)
            signal.signal(kind,lambda *_:self.request_shutdown())
        self.persist()

    def request_shutdown(self):
        self.stop.set()
        self.set('stopping')

    def stopping(self):
        if self.managed and read_json(self.root/'service-control.json').get('enabled') is not True:
            self.request_shutdown()
        if read_json(self.root/'stop-request.json').get('instance')==self.instance:
            self.request_shutdown()
        return self.stop.is_set()

    def check_stop(self):
        if self.stopping():raise SystemExit(0)

    def set(self,state):
        with self.mutex:
            self.state='stopping' if self.stop.is_set() and state!='stopped' else state
            self.changed=time.monotonic()
            if threading.get_ident()==self.main_thread:self.control_at=self.changed

    def control_ok(self):
        # Only a main-thread operation can prove the controller made progress.
        if threading.get_ident()!=self.main_thread:return
        with self.mutex:self.control_at=time.monotonic()

    def watch_driver(self):
        from driver_health import own_driver_probe
        self.driver_probe=own_driver_probe()

    def browser_opened(self):
        with self.mutex:
            self.browser_generation+=1
            self.browser_connected=True
            return self.browser_generation

    def browser_closed(self,generation):
        with self.mutex:
            if generation==self.browser_generation:self.browser_connected=False

    def snapshot(self):
        self.stopping()
        driver=self.driver_probe.sample() if self.driver_probe is not None else None
        with self.mutex:
            age=min(86400,max(0,time.monotonic()-self.control_at))
            state=self.state
            if state not in {'stopping','stopped'}:
                if driver in {'dead','unverified'} or self.browser_connected is False:
                    state='driver_error'
                elif age>CONTROL_STALE_SECONDS and state not in {'login','reconnecting','unverified'}:
                    state='control_stalled'
            return {'state':state,'progress_age_seconds':age}

    def persist(self):
        value=self.snapshot()
        atomic_json(self.root/'worker.json',dict(value,pid=os.getpid(),instance=self.instance,updated=time.time()))

    def wait_login(self):
        print('Đăng nhập MWG trong Chrome của bot rồi nhấn Enter tại đây. Dùng Tat-BOT.command để dừng.',flush=True)
        self.set('login')
        while True:
            self.check_stop()
            ready,_,_=select.select([sys.stdin],[],[],0.5)
            if ready:
                if not sys.stdin.readline():raise SystemExit('Cửa sổ đăng nhập đã đóng; bot chưa nhận CO.')
                return

    def close(self):
        self.set('stopped')
        # Persist stopped directly: an outstanding stop request must not mask it.
        atomic_json(self.root/'worker.json',dict(state='stopped',pid=os.getpid(),instance=self.instance,
                                               updated=time.time(),progress_age_seconds=0))
        for kind,handler in self.old_handlers.items():signal.signal(kind,handler)
