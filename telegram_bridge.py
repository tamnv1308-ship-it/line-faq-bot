"""Telegram transport for the existing CO queue; LINE remains the LIFF identity.

Disabled until configured. Linking requires both a private Telegram message and
an authenticated, CSRF-protected confirmation in LIFF. Never trust usernames,
forwarded senders, callback message authors, or Telegram group admin status as
CO owner/admin identity.
"""
import hashlib
import hmac
import json
import os
import re
import secrets
import time
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from co_results import line_text_messages


def settings():
    token = os.getenv('TELEGRAM_BOT_TOKEN', '')
    secret = os.getenv('TELEGRAM_WEBHOOK_SECRET', '')
    username = os.getenv('TELEGRAM_BOT_USERNAME', '').lstrip('@')
    group = os.getenv('TELEGRAM_CO_GROUP_ID', '')
    note_group = os.getenv('TELEGRAM_NOTE_GROUP_ID', '')
    group = group if re.fullmatch(r'-[1-9][0-9]*', group) else ''
    note_group = note_group if re.fullmatch(r'-[1-9][0-9]*', note_group) else ''
    ready = bool(os.getenv('TELEGRAM_ENABLED') == '1' and
                 re.fullmatch(r'[1-9][0-9]*:[A-Za-z0-9_-]{20,}', token) and
                 re.fullmatch(r'[A-Za-z0-9_-]{32,256}', secret) and
                 re.fullmatch(r'[A-Za-z0-9_]{5,32}', username))
    return dict(ready=ready, token=token, secret=secret, username=username,
                bot_id=token.split(':')[0], group=group, note_group=note_group,
                active=ready and bool(group) and os.getenv('CO_INTAKE_TRANSPORT', 'line') == 'telegram')


def is_chat(chat):
    return bool(re.fullmatch(r'tg:-?[1-9][0-9]*', str(chat)))


def member_groups():
    cfg = settings()
    return {'tg:'+cfg['group']} if cfg['ready'] and cfg['group'] else set()


def event_chat(event):
    return (getattr(event, 'delivery_chat', None) or getattr(event.source, 'group_id', None)
            or getattr(event.source, 'room_id', None) or event.source.user_id)


def schema(db):
    db.executescript('''
      CREATE TABLE IF NOT EXISTS co_telegram_links (
        line_user TEXT PRIMARY KEY, telegram_user TEXT UNIQUE NOT NULL,
        display_name TEXT NOT NULL, created REAL NOT NULL);
      CREATE TABLE IF NOT EXISTS co_telegram_link_requests (
        line_user TEXT PRIMARY KEY, digest TEXT UNIQUE NOT NULL, expires REAL NOT NULL,
        candidate TEXT NOT NULL, display_name TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS co_telegram_updates (
        bot_id TEXT NOT NULL, update_id TEXT NOT NULL, payload TEXT NOT NULL,
        state TEXT NOT NULL, lease REAL NOT NULL, attempts INTEGER NOT NULL,
        received REAL NOT NULL, PRIMARY KEY(bot_id,update_id));
      CREATE TABLE IF NOT EXISTS co_telegram_deliveries (
        delivery_key TEXT PRIMARY KEY, state TEXT NOT NULL, retry_at REAL NOT NULL,
        message_id TEXT NOT NULL, updated REAL NOT NULL);
      CREATE TABLE IF NOT EXISTS co_telegram_identities (
        telegram_user TEXT PRIMARY KEY, owner_id TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS co_telegram_seen_groups (
        bot_id TEXT NOT NULL, chat_id TEXT NOT NULL, title TEXT NOT NULL,
        seen REAL NOT NULL, PRIMARY KEY(bot_id,chat_id));
    ''')


class TelegramError(Exception):
    def __init__(self, code=0, retry_after=0):
        super().__init__('Telegram request failed')  # Never include the token/URL/body.
        self.code, self.retry_after = code, retry_after


class Client:
    def call(self, method, payload):
        cfg = settings()
        if not cfg['ready']:
            raise TelegramError()
        # Only fixed methods supplied by our own code reach this function.
        if method not in {'sendMessage', 'sendPhoto', 'answerCallbackQuery', 'getChatMember',
                          'getMe', 'getWebhookInfo', 'setWebhook', 'setMyCommands'}:
            raise ValueError('Unsupported Telegram method')
        req = Request('https://api.telegram.org/bot'+cfg['token']+'/'+method,
                      data=json.dumps(payload).encode(), headers={'Content-Type':'application/json'})
        try:
            with urlopen(req, timeout=6) as response:
                data = json.loads(response.read(256000))
        except HTTPError as error:
            try:data = json.loads(error.read(16000))
            except (ValueError, OSError):data = {}
            raise TelegramError(error.code, data.get('parameters', {}).get('retry_after', 0)) from None
        except (OSError, ValueError):
            raise TelegramError() from None
        if not isinstance(data, dict) or data.get('ok') is not True:
            raise TelegramError(data.get('error_code', 0) if isinstance(data, dict) else 0)
        return data.get('result')


class Bridge:
    def __init__(self, queue, client=None):
        self.queue, self.client = queue, client or Client()
        with queue.db() as db:schema(db)

    def linked(self, uid=None, telegram_user=None, db=None):
        if db is None:
            with self.queue.db() as connection:
                return self.linked(uid, telegram_user, connection)
        row = db.execute('SELECT * FROM co_telegram_links WHERE '+
                         ('line_user=?' if uid is not None else 'telegram_user=?'),
                         (uid if uid is not None else str(telegram_user),)).fetchone()
        return dict(row) if row else None

    def link_status(self, uid):
        cfg = settings()
        with self.queue.db() as db:
            linked = self.linked(uid, db=db)
            pending = db.execute('SELECT * FROM co_telegram_link_requests WHERE line_user=? AND expires>?',
                                 (uid, time.time())).fetchone()
        return dict(available=cfg['ready'], active=cfg['active'], username=cfg['username'],
                    linked={'id':linked['telegram_user'], 'name':linked['display_name']} if linked else None,
                    candidate={'id':pending['candidate'], 'name':pending['display_name'],
                               'expires':pending['expires']} if pending and pending['candidate'] else None)

    def begin_link(self, uid):
        if not settings()['ready']:raise ValueError('Chưa cấu hình bot Telegram.')
        token = secrets.token_urlsafe(24)
        with self.queue.db() as db:
            if self.linked(uid, db=db):raise ValueError('Tài khoản đã liên kết Telegram. Không tự đổi tài khoản đang có quyền.')
            db.execute('''INSERT INTO co_telegram_link_requests VALUES(?,?,?,'','')
                ON CONFLICT(line_user) DO UPDATE SET digest=excluded.digest,expires=excluded.expires,
                candidate='',display_name='' ''', (uid, hashlib.sha256(token.encode()).hexdigest(), time.time()+300))
        return 'https://t.me/'+settings()['username']+'?start=link_'+token

    def offer_link(self, token, sender):
        if not re.fullmatch(r'[A-Za-z0-9_-]{32}', token):raise ValueError('Mã liên kết không hợp lệ.')
        with self.queue.db() as db:
            row = db.execute('SELECT * FROM co_telegram_link_requests WHERE digest=? AND expires>?',
                             (hashlib.sha256(token.encode()).hexdigest(), time.time())).fetchone()
            tid = str(sender['id'])
            if not row or (row['candidate'] and row['candidate'] != tid):
                raise ValueError('Liên kết đã hết hạn hoặc đã dùng. Tạo liên kết mới trong LIFF.')
            if self.linked(telegram_user=tid, db=db):raise ValueError('Telegram này đã liên kết với một tài khoản.')
            name = ' '.join(str(sender.get(k) or '') for k in ('first_name','last_name')).strip()[:150]
            db.execute('UPDATE co_telegram_link_requests SET candidate=?,display_name=? WHERE line_user=?',
                       (tid, name or 'Thành viên Telegram', row['line_user']))
        return 'Đã nhận tài khoản Telegram. Quay lại Công cụ Táo (LIFF), kiểm tra tên/mã Telegram rồi bấm Xác nhận liên kết. Chưa cấp quyền.'

    def confirm_link(self, uid, candidate):
        with self.queue.db() as db:
            row = db.execute('SELECT * FROM co_telegram_link_requests WHERE line_user=? AND expires>?',
                             (uid, time.time())).fetchone()
            if not row or not row['candidate'] or row['candidate'] != str(candidate):
                raise ValueError('Thông tin liên kết đã đổi hoặc hết hạn. Vui lòng bắt đầu lại.')
            if self.linked(uid, db=db) or self.linked(telegram_user=candidate, db=db):
                raise ValueError('Tài khoản đã được liên kết. Không thay đổi quyền hiện có.')
            db.execute('INSERT INTO co_telegram_links VALUES(?,?,?,?)',
                       (uid, row['candidate'], row['display_name'], time.time()))
            db.execute('DELETE FROM co_telegram_link_requests WHERE line_user=?', (uid,))

    def destination(self, uid, group=False, db=None):
        link = self.linked(uid, db=db)
        if not link:raise ValueError('Liên kết Telegram trong Công cụ Táo trước khi gửi yêu cầu.')
        if group:
            gid = settings()['group']
            if not gid:raise ValueError('Chưa chọn nhóm Telegram được phép nhận CO.')
            return 'tg:'+gid
        return 'tg:'+link['telegram_user']

    def verify_member(self, uid, chat):
        link = self.linked(uid)
        if not link:raise ValueError('Chưa liên kết Telegram cho tài khoản này.')
        if chat != 'tg:'+settings()['group'] or chat not in member_groups():
            raise ValueError('Nhóm Telegram này chưa được cấp quyền.')
        try:member = self.client.call('getChatMember', {'chat_id':chat[3:], 'user_id':int(link['telegram_user'])})
        except TelegramError:raise ValueError('Chưa xác minh được thành viên Telegram. Thử lại sau.') from None
        if (str(member.get('user',{}).get('id')) != link['telegram_user'] or
                member.get('status') not in ('creator','administrator','member','restricted') or
                member.get('status')=='restricted' and not member.get('is_member')):
            raise ValueError('Tài khoản không còn trong nhóm Telegram được phép.')

    def send(self, chat, text, key, photo=False):
        if not is_chat(chat):return False
        messages = [{'text':text}] if photo else line_text_messages(text)
        if not photo:messages = [dict(messages[-1], text=str(text))] if messages else []
        # LINE chunks can be 5000 characters; Telegram permits 4096. Preserve
        # every character, including astral emojis (budget in UTF-16 units).
        parts = []
        for message in messages:
            current, units = '', 0
            for char in message['text']:
                size = 2 if ord(char)>65535 else 1
                if units+size>3900:parts.append({'text':current});current,units='',0
                current+=char;units+=size
            parts.append(dict(message, text=current))
        for index, message in enumerate(parts):
            digest = hashlib.sha256((chat+':'+key+':'+str(index)+':'+message['text']).encode()).hexdigest()
            with self.queue.db() as db:
                prior = db.execute('SELECT * FROM co_telegram_deliveries WHERE delivery_key=?', (digest,)).fetchone()
                if prior and prior['state']=='sent':continue
                if prior and prior['retry_at']>time.time():return False
                db.execute("INSERT INTO co_telegram_deliveries VALUES(?,'sending',?,'',?) ON CONFLICT(delivery_key) DO UPDATE SET state='sending',retry_at=excluded.retry_at,updated=excluded.updated",
                           (digest, time.time()+30, time.time()))
            payload = {'chat_id':chat[3:], 'photo' if photo else 'text':message['text']}
            if not photo:
                payload['link_preview_options']={'is_disabled':True}
                actions=message.get('quickReply',{}).get('items',[])
                buttons=[{'text':a['action']['label'],'callback_data':a['action']['text']} for a in actions
                         if len(a['action']['text'].encode())<=64]
                if buttons:payload['reply_markup']={'inline_keyboard':[buttons[n:n+2] for n in range(0,len(buttons),2)]}
            try:
                result = self.client.call('sendPhoto' if photo else 'sendMessage', payload)
                if not isinstance(result,dict) or not result.get('message_id'):raise TelegramError()
            except TelegramError as error:
                delay = max(30, min(3600, int(error.retry_after or 0)))
                with self.queue.db() as db:
                    db.execute("UPDATE co_telegram_deliveries SET state='retry',retry_at=? WHERE delivery_key=?",
                               (time.time()+delay,digest))
                return False
            with self.queue.db() as db:
                db.execute("UPDATE co_telegram_deliveries SET state='sent',message_id=?,updated=? WHERE delivery_key=?",
                           (str(result['message_id']),time.time(),digest))
        return True

    def reply(self, token, text, photo=False):
        match = re.fullmatch(r'tgr:(-?[1-9][0-9]*):([0-9]+)', str(token))
        if not match:return False
        if not self.send('tg:'+match[1], text, 'reply:'+token, photo):raise TelegramError()
        return True

    def process(self, update, handlers):
        cfg=settings();callback=update.get('callback_query')
        message=(callback or {}).get('message') if callback else update.get('message')
        if not isinstance(message,dict):return
        sender=(callback or {}).get('from') if callback else message.get('from')
        if not isinstance(sender,dict) or sender.get('is_bot') or type(sender.get('id')) is not int:return
        chat=message.get('chat',{});kind=chat.get('type');cid=chat.get('id')
        if type(cid) is not int or kind not in ('private','group','supergroup') or message.get('sender_chat'):return
        if kind=='private' and cid!=sender['id']:return
        # Record only group identity from an explicit setup command. This never
        # grants access, sends a reply to an unconfigured group, or saves chat text.
        setup_command=str(message.get('text','')).strip()
        if (not callback and kind!='private' and cid<0 and
                re.fullmatch(r'/start@'+re.escape(cfg['username']),setup_command,re.I) and
                type(message.get('date')) is int and -60<=time.time()-message['date']<=300):
            with self.queue.db() as db:
                db.execute('INSERT INTO co_telegram_seen_groups VALUES(?,?,?,?) '
                           'ON CONFLICT(bot_id,chat_id) DO UPDATE SET title=excluded.title,seen=excluded.seen',
                           (cfg['bot_id'],str(cid),str(chat.get('title',''))[:200],time.time()))
        if kind!='private' and str(cid) not in {cfg['group'],cfg['note_group']}:return
        # Topic threads need separate routing before they can be enabled.
        if message.get('is_topic_message'):return
        token='tgr:'+str(cid)+':'+str(update['update_id'])
        text=str(callback.get('data','') if callback else message.get('text','')).strip()
        if callback:
            if str(message.get('from',{}).get('id'))!=cfg['bot_id']:return
            if not re.fullmatch(r'(?:XACNHAN|HUY) [0-9a-f]{10}|!gom(?: [a-z0-9]+)*',text):return
            try:self.client.call('answerCallbackQuery',{'callback_query_id':callback['id']})
            except TelegramError:pass
        elif not text:return
        stamp=message.get('date')
        if not callback and (type(stamp) is not int or stamp>time.time()+60 or time.time()-stamp>300):
            self.reply(token,'Tin đã quá 5 phút khi bot nhận được. Gửi lại nếu vẫn cần xử lý; chưa tạo CO.');return
        # Slash aliases work with Telegram privacy mode without reading unrelated
        # group messages. Plain forms also work when the bot receives them.
        match=re.match(r'^/([a-z_]+)(?:@([A-Za-z0-9_]+))?(?:\s+([\s\S]*))?$',text,re.I)
        if match:
            command,mention,rest=match.groups();rest=rest or ''
            if mention and mention.lower()!=cfg['username'].lower():return
            aliases={'xacnhan':'XACNHAN','huy':'HUY','xem':'XEM','co':'!co','bot':'!bot',
                     'gom':'!gom','mokhoa':'!mokhoa','listadm':'!listadm','tongket':'!tongket','ketqua':'!ketqua'}
            if command.lower()=='taoco':text=rest
            elif command.lower() in aliases:text=(aliases[command.lower()]+' '+rest).strip()
            elif command.lower()=='start' and rest.startswith('link_'):
                if kind!='private':return
                try:answer=self.offer_link(rest[5:],sender)
                except ValueError as error:answer=str(error)
                self.reply(token,answer);return
            elif command.lower() in ('start','help','congcu'):
                self.reply(token,'Công cụ Táo · Telegram\nThành viên nhóm CO dùng ngay, không cần liên kết LIFF.\n'
                    '/taoco + nội dung form — gửi yêu cầu\n/xacnhan <mã> · /huy <mã>\n/co <mã CO> · /gom · /tongket\n'
                    'https://liff.line.me/'+os.getenv('TAO_LIFF_ID','2012056807-Wv492OLR'));return
        link=self.linked(telegram_user=sender['id'])
        if not link and (kind=='private' or str(cid)!=cfg['group']):
            self.reply(token,'Bot chỉ nhận yêu cầu của thành viên trong nhóm CO được phép. Tin nhắn riêng dành cho Tâm.');return
        # Pin the canonical identity so linking LIFF later cannot reset locks,
        # lose ownership of pending requests, or bypass duplicate protection.
        tid=str(sender['id'])
        with self.queue.db() as db:
            db.execute('INSERT INTO co_telegram_identities(telegram_user,owner_id) VALUES(?,?) '
                       'ON CONFLICT(telegram_user) DO NOTHING',
                       (tid,link['line_user'] if link else 'telegram:'+tid))
            identity=db.execute('SELECT owner_id FROM co_telegram_identities WHERE telegram_user=?',(tid,)).fetchone()['owner_id']
        name=(link['display_name'] if link else ' '.join(str(sender.get(k,'')).strip() for k in ('first_name','last_name')).strip())
        source=SimpleNamespace(user_id=identity,group_id='tg:'+str(cid) if kind!='private' else None,room_id=None)
        event=SimpleNamespace(source=source,delivery_chat='tg:'+str(cid),platform='telegram',
            requester_name=(name or 'Telegram '+tid)[:200],message=SimpleNamespace(text=text,id=str(message.get('message_id',0))),
            webhook_event_id='telegram:'+cfg['bot_id']+':'+str(update['update_id']),reply_token=token,
            timestamp=int((stamp if not callback else time.time())*1000))
        for handler in handlers:
            if handler(event):break

    def drain(self, handlers, logger):
        cfg=settings()
        if not cfg['ready']:return
        # Never call Telegram or the shared dispatcher while holding the queue lock.
        for _ in range(5):
            with self.queue.db() as db:
                row=db.execute("SELECT * FROM co_telegram_updates WHERE bot_id=? AND state!='done' AND lease<? AND attempts<8 ORDER BY received,update_id LIMIT 1",
                               (cfg['bot_id'],time.time())).fetchone()
                if not row:return
                db.execute("UPDATE co_telegram_updates SET state='processing',lease=?,attempts=attempts+1 WHERE bot_id=? AND update_id=?",
                           (time.time()+120,cfg['bot_id'],row['update_id']))
            try:self.process(json.loads(row['payload']),handlers)
            except Exception:
                logger.warning('Telegram update pending; retrying without creating a new event.')
                continue
            with self.queue.db() as db:
                db.execute("UPDATE co_telegram_updates SET state='done',payload='{}' WHERE bot_id=? AND update_id=?",
                           (cfg['bot_id'],row['update_id']))

    def cleanup(self):
        with self.queue.db() as db:
            db.execute('DELETE FROM co_telegram_seen_groups WHERE seen<?',(time.time()-3*86400,))
            db.execute('DELETE FROM co_telegram_link_requests WHERE expires<?',(time.time(),))
            db.execute("DELETE FROM co_telegram_updates WHERE state='done' AND received<?",(time.time()-30*86400,))
            # A stalled webhook is retained for inspection but not replayed forever.
            db.execute("UPDATE co_telegram_updates SET payload='{}',state='done' WHERE received<?",(time.time()-86400,))
            db.execute('DELETE FROM co_telegram_deliveries WHERE updated<?',(time.time()-30*86400,))


def install_webhook(app, bridge):
    from flask import abort, request
    @app.post('/telegram/webhook')
    def telegram_webhook():
        cfg=settings()
        if not bridge or not cfg['ready']:abort(503)
        supplied=request.headers.get('X-Telegram-Bot-Api-Secret-Token','')
        if not hmac.compare_digest(supplied,cfg['secret']):abort(403)
        if request.content_length is None or request.content_length>65536:abort(413)
        data=request.get_json(silent=True)
        if not isinstance(data,dict) or type(data.get('update_id')) is not int or data['update_id']<0:abort(400)
        # Persist before acknowledging. Retried deliveries use the same primary key.
        with bridge.queue.db() as db:
            db.execute("INSERT INTO co_telegram_updates VALUES(?,?,?,'pending',0,0,?) ON CONFLICT(bot_id,update_id) DO NOTHING",
                       (cfg['bot_id'],str(data['update_id']),json.dumps(data,ensure_ascii=False),time.time()))
        return {'ok':True}
