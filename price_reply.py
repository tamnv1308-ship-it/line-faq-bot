"""Serve verified Mac scan snapshots through LINE replies, only in NOTE."""
import hashlib
import hmac
import json
import math
import os
import re
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

NOTE_GROUP = 'C4f38e1a465a6dd1b0a3cd5c175f84c62'
TZ = ZoneInfo('Asia/Ho_Chi_Minh')
PAGE_SIZE = 10


def sync_key(worker_token):
    # This derived credential grants only access to price snapshots, not CO jobs.
    return hmac.new(worker_token.encode(), b'apple-price-report-sync:v1', hashlib.sha256).hexdigest()


def normalize(value):
    return ''.join(c for c in unicodedata.normalize('NFD', value.casefold().replace('đ', 'd'))
                   if unicodedata.category(c) != 'Mn')


def validate_snapshot(body):
    if not isinstance(body, dict) or body.get('version') != 1 or body.get('scope') != 'all_kdbt':
        raise ValueError('invalid_snapshot')
    checked = datetime.fromisoformat(body['checked'])
    if checked.tzinfo is None or checked.timestamp() > time.time() + 300:
        raise ValueError('invalid_timestamp')
    items = body['items']
    if not isinstance(items, list) or len(items) > 2000:
        raise ValueError('invalid_items')
    cleaned, keyed, own_prices, names = [], set(), {}, {}
    for item in items:
        if not isinstance(item, dict):
            raise ValueError('invalid_item')
        sku, name, retail = item['sku'], item['name'], item['retailer']
        if (not isinstance(sku, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', sku)
                or not isinstance(name, str) or not 1 <= len(name.strip()) <= 500
                or retail not in ('FPT', 'CPS')):
            raise ValueError('invalid_product')
        own, price = item['mw_price'], item['price']
        if any(type(v) is not int or not 100_000 <= v <= 500_000_000 for v in (own, price)):
            raise ValueError('invalid_price')
        if ((sku, retail) in keyed or own_prices.get(sku, own) != own
                or names.get(sku, name) != name):
            raise ValueError('conflicting_product')
        keyed.add((sku, retail)); own_prices[sku] = own; names[sku] = name
        cleaned.append(dict(sku=sku, name=' '.join(name.split()), retailer=retail,
                            mw_price=own, price=price, difference=price-own))
    return dict(version=1, scope='all_kdbt', checked=checked.astimezone(timezone.utc).isoformat(), items=cleaned)


def money(value):
    return f'{value:,}'.replace(',', '.') + 'đ'


def report_page(snapshot, argument=''):
    if not snapshot:
        raise ValueError('Chưa có báo cáo giá đã xác minh. Máy Mac cần hoàn tất một lượt quét và đồng bộ dữ liệu.')
    argument = argument.strip()
    page, query = 1, argument
    if argument.isdigit():
        page, query = int(argument), ''
    else:
        match = re.search(r'\s+/(\d+)$', argument)
        if match:
            page, query = int(match[1]), argument[:match.start()].strip()
    if len(query) > 120 or page < 1:
        raise ValueError('Dùng !gia, !gia 2 hoặc !gia air m5 để tìm sản phẩm.')
    groups = {}
    for item in snapshot['items']:
        if all(word in normalize(item['name'] + ' ' + item['sku']) for word in normalize(query).split()):
            groups.setdefault(item['sku'], []).append(item)
    ordered = sorted(groups.values(), key=lambda values: (min(i['difference'] for i in values), values[0]['name']))
    total = len(ordered)
    pages = max(1, math.ceil(total / PAGE_SIZE))
    if page > pages:
        raise ValueError(f'Báo cáo có {pages} trang. Gửi !gia để xem lại từ đầu.')
    return ordered, page, query, pages


def render_report(snapshot, argument=''):
    try:
        ordered, page, query, pages = report_page(snapshot, argument)
    except ValueError as exc:
        return str(exc)
    total = len(ordered)
    checked = datetime.fromisoformat(snapshot['checked']).astimezone(TZ)
    header = f'GIÁ APPLE SO VỚI MW\nCập nhật: {checked:%H:%M %d/%m/%Y} (giờ Việt Nam)\n{total} sản phẩm đã xác minh · Trang {page}/{pages}'
    if time.time() - checked.timestamp() > 18*3600:
        header += '\n⚠️ Bản quét đã quá 18 giờ. Giá hiện tại có thể thay đổi.'
    if not total:
        return header + '\n\n' + ('Không có sản phẩm khớp từ khóa trong bản quét này.' if query else 'Lượt quét này chưa có sản phẩm đủ giá để so sánh.')
    blocks = [header]
    for index, values in enumerate(ordered[(page-1)*PAGE_SIZE:page*PAGE_SIZE], (page-1)*PAGE_SIZE+1):
        first = values[0]
        lines = [f"{index}. {first['name']}", f"MW: {money(first['mw_price'])}"]
        for item in sorted(values, key=lambda i: ('FPT', 'CPS').index(i['retailer'])):
            delta = item['difference']
            relation = 'bằng MW' if delta == 0 else ('rẻ hơn MW ' if delta < 0 else 'cao hơn MW ') + money(abs(delta))
            lines.append(f"{item['retailer']}: {money(item['price'])} — {relation}")
        blocks.append('\n'.join(lines))
    if page < pages:
        command = f'!gia {query} /{page+1}' if query else f'!gia {page+1}'
        blocks.append('Xem tiếp: ' + command)
    blocks.append('Tìm mẫu: !gia air m5\nGiá từ lần quét ghi ở trên; ưu tiên hiển thị mẫu đối thủ rẻ hơn MW.')
    return '\n\n'.join(blocks)


def page_command(query, page):
    return f'!gia {query} /{page}' if query else f'!gia {page}'


def render_cards(snapshot, argument=''):
    """Native LINE cards. Errors/empty searches keep the short text response."""
    try:
        ordered, page, query, pages = report_page(snapshot, argument)
    except ValueError:
        return None
    if not ordered:
        return None
    checked = datetime.fromisoformat(snapshot['checked']).astimezone(TZ)
    stale = time.time() - checked.timestamp() > 18*3600
    total = len(ordered)

    def text(value, **style):
        return dict(type='text', text=value, wrap=True, **style)

    def box(contents, **style):
        return dict(type='box', layout='vertical', contents=contents, **style)

    def button(label, command):
        return dict(type='button', style='secondary', height='sm',
                    action=dict(type='message', label=label, text=command))

    navigation = []
    if page > 1:
        navigation.append(button('‹ Trang trước', page_command(query, page-1)))
    if page < pages:
        navigation.append(button('Trang tiếp ›', page_command(query, page+1)))
    if not navigation:
        navigation.append(button('Xem tất cả', '!gia'))
    bubbles = []
    start = (page-1)*PAGE_SIZE
    for index, values in enumerate(ordered[start:start+PAGE_SIZE], start+1):
        first = values[0]
        name = re.sub(r'\bMacbook\b', 'MacBook', first['name'], flags=re.I)
        part = re.search(r'\s+([A-Z0-9]{4,12}[A-Z]{2}/A|Z[A-Z0-9]{7,11})$', name, re.I)
        heading = [text(name[:part.start()] if part else name, size='lg', weight='bold', color='#172B4D')]
        if part:
            heading.append(text(part[1], size='xs', color='#69788D', margin='sm'))
        body = [*heading,
                box([text('MW · GIÁ ĐỐI CHIẾU', size='xs', weight='bold', color='#456A98'),
                     text(money(first['mw_price']), size='xxl', weight='bold', color='#172B4D', margin='sm')],
                    backgroundColor='#EDF3FA', cornerRadius='12px', paddingAll='14px', margin='lg')]
        for item in sorted(values, key=lambda i: ('FPT', 'CPS').index(i['retailer'])):
            delta = item['difference']
            color = '#C03932' if delta < 0 else '#946B10' if delta == 0 else '#087A60'
            relation = 'Bằng giá MW' if delta == 0 else ('↓ Rẻ hơn MW ' if delta < 0 else '↑ Cao hơn MW ') + money(abs(delta))
            retailer = 'FPT Shop' if item['retailer']=='FPT' else 'CellphoneS'
            body.append(box([
                dict(type='box', layout='baseline', contents=[
                    text(retailer, size='sm', color='#45546A', weight='bold', flex=2),
                    text(money(item['price']), size='md', color=color, weight='bold', flex=3, align='end')]),
                text(relation, size='xs', color=color, align='end', margin='xs')],
                margin='lg'))
        footer = [dict(type='separator', color='#E4EAF1'),
                  text(f'Cập nhật {checked:%H:%M · %d/%m/%Y} (VN)', size='xxs', color='#69788D', margin='md')]
        if stale:
            footer.append(text('Bản quét quá 18 giờ; giá có thể đã đổi.', size='xs', color='#B45309', margin='sm'))
        footer.extend([text('Vuốt ngang để xem sản phẩm khác →', size='xxs', color='#69788D', margin='sm'),
                       dict(type='box', layout='horizontal', spacing='sm', margin='md', contents=navigation)])
        bubbles.append(dict(type='bubble', size='mega',
            header=box([text(f'GIÁ APPLE  ·  {index}/{total}', size='xs', weight='bold', color='#FFFFFF'),
                        text(f'Trang {page}/{pages}', size='xxs', color='#D3DFEF', margin='xs')],
                       backgroundColor='#203E63', paddingAll='16px'),
            body=box(body, paddingAll='20px'), footer=box(footer, paddingAll='20px', paddingTop='0px')))
    # Respect LINE's 50 KB carousel cap even for unusually long Unicode names.
    messages, current = [], []
    alt = f'Giá Apple · Trang {page}/{pages} · {total} sản phẩm · Cập nhật {checked:%H:%M %d/%m}'
    def message(cards):
        return dict(type='flex', altText=alt, contents=dict(type='carousel', contents=cards))
    for bubble in bubbles:
        if current and len(json.dumps(message(current+[bubble]), ensure_ascii=False).encode()) > 48000:
            messages.append(message(current)); current=[]
        current.append(bubble)
    if current:
        messages.append(message(current))
    return messages


def install(app, reply, verify_note, reply_cards=None):
    from flask import request, abort, jsonify
    from co_flow import Queue
    path = os.environ.get('CO_DATABASE_URL') or os.environ.get('CO_DB_PATH', '')
    worker = os.environ.get('CO_WORKER_TOKEN', '')
    store = None
    if len(worker) >= 32 and (path.startswith(('postgresql://', 'postgres://')) or Path(path).is_absolute()):
        store = Queue(path)
        with store.db() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS price_reply_snapshot(id INTEGER PRIMARY KEY, checked TEXT NOT NULL, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS price_reply_events(event TEXT PRIMARY KEY, state TEXT NOT NULL, created REAL NOT NULL);
            ''')

    def auth():
        if store is None:
            abort(503)
        if not hmac.compare_digest(request.headers.get('Authorization', ''), 'Bearer ' + sync_key(worker)):
            abort(401)

    def read_snapshot():
        if store is None:
            return None
        with store.db() as db:
            row = db.execute('SELECT payload FROM price_reply_snapshot WHERE id=1').fetchone()
        return json.loads(row['payload']) if row else None

    @app.put('/price/report')
    def upload():
        auth()
        raw = request.stream.read(300001)
        if len(raw) > 300000:
            abort(413)
        try:
            snapshot = validate_snapshot(json.loads(raw))
        except (ValueError, TypeError, KeyError, OverflowError):
            abort(400)
        payload = json.dumps(snapshot, ensure_ascii=False, sort_keys=True)
        with store.db() as db:
            current = db.execute('SELECT checked,payload FROM price_reply_snapshot WHERE id=1').fetchone()
            if current and (snapshot['checked'] < current['checked'] or
                            (snapshot['checked'] == current['checked'] and payload != current['payload'])):
                abort(409)
            db.execute('''INSERT INTO price_reply_snapshot(id,checked,payload) VALUES(1,?,?)
                ON CONFLICT(id) DO UPDATE SET checked=excluded.checked,payload=excluded.payload''', (snapshot['checked'], payload))
        return jsonify(ok=True, checked=snapshot['checked'], products=len({i['sku'] for i in snapshot['items']}))

    @app.get('/price/status')
    def status():
        auth()
        snapshot = read_snapshot()
        with store.db() as db:
            last = db.execute("SELECT MAX(created) AS last FROM price_reply_events WHERE state='accepted'").fetchone()['last']
        return jsonify(ready=snapshot is not None, checked=snapshot['checked'] if snapshot else None,
                       products=len({i['sku'] for i in snapshot['items']}) if snapshot else 0, last_reply=last)

    def handle(event):
        match = re.fullmatch(r'!gi[aá](?:\s+(.*))?', event.message.text.strip(), re.I | re.S)
        if not match:
            return False
        # Do not reply or forward price data to CO, other groups, rooms or DMs.
        if getattr(event.source, 'group_id', None) != NOTE_GROUP:
            return True
        if not verify_note():
            app.logger.warning('Price reply skipped: NOTE identity could not be verified.')
            return True
        event_id = getattr(event, 'webhook_event_id', None) or getattr(event.message, 'id', None)
        if not event_id or not isinstance(event_id, str) or len(event_id) > 200:
            return True
        if store:
            with store.db() as db:
                if db.execute('SELECT state FROM price_reply_events WHERE event=?', (event_id,)).fetchone():
                    return True
                db.execute('INSERT INTO price_reply_events VALUES(?,?,?)', (event_id, 'sending', time.time()))
                db.execute('DELETE FROM price_reply_events WHERE created<?', (time.time()-7*86400,))
        try:
            snapshot = read_snapshot()
            cards = render_cards(snapshot, match[1] or '') if reply_cards else None
            if cards:
                sent = reply_cards(event.reply_token, cards) is True
            else:
                sent = reply(event.reply_token, render_report(snapshot, match[1] or '')) is True
        except Exception:
            app.logger.warning('Price reply failed; no push fallback used.')
            sent = False
        if store:
            with store.db() as db:
                if sent:
                    db.execute("UPDATE price_reply_events SET state='accepted' WHERE event=?", (event_id,))
                else:
                    db.execute('DELETE FROM price_reply_events WHERE event=?', (event_id,))
        return True
    return handle
