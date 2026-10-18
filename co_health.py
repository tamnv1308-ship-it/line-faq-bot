"""Server-side readiness derived from UI progress, not heartbeat alone."""
import math
import time

READINESS_VERSION = 2
PROGRESS_TTL = 60
LABELS = {
    'ready': 'Sẵn sàng', 'processing': 'Đang xử lý',
    'awaiting_confirmation': 'Đang chờ xác nhận', 'loading': 'Đang tải MWG',
    'loading_slow': 'MWG tải chậm / đang chờ dữ liệu',
    'login': 'Chờ đăng nhập MWG', 'blocked': 'Bị kẹt / cần kiểm tra',
    'reconnecting': 'Đang kết nối lại', 'stopping': 'Đang dừng',
    'stopped': 'Đã tắt', 'unverified': 'Chưa kiểm tra MWG',
    'offline': 'Mac offline hoặc mất kết nối',
}
WORKING = {'ready', 'processing', 'awaiting_confirmation'}


def validate_health(value):
    if not isinstance(value, dict) or value.get('state') not in LABELS:
        raise ValueError('Invalid worker health')
    age = value.get('progress_age_seconds')
    if isinstance(age, bool) or not isinstance(age, (int, float)) or not math.isfinite(age) or not 0 <= age <= 86400:
        raise ValueError('Invalid progress age')
    return value['state'], age


def readiness(db, now=None):
    now = time.time() if now is None else now
    control = db.execute('SELECT enabled,heartbeat FROM co_control WHERE id=1').fetchone()
    health = db.execute('SELECT state,progress_at FROM co_worker_health WHERE id=1').fetchone()
    online = now - control['heartbeat'] <= 30
    state = health['state'] if health else 'unverified'
    age = max(0, now - health['progress_at']) if health else 86400
    if not online:
        state = 'stopped' if state == 'stopped' else 'offline'
    elif state in WORKING and age > PROGRESS_TTL:
        state = 'blocked'
    ready = online and state in WORKING and age <= PROGRESS_TTL
    return {'online': online, 'worker_state': state, 'worker_label': LABELS[state],
            'progress_age_seconds': round(age, 1), 'mwg_ready': ready,
            'accepting': bool(control['enabled'] and ready)}
