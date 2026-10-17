"""Owner-only forwarded text drafts. No worker sees a draft until explicit send."""
import hashlib
import json
import re
import secrets
import time

from tao_compose import parse_editable, validate_rows, queue_payload
from transfer_parser import fold, is_transfer_message

VERSION = 2
SENT = object()


class ReplyText(str):
    """Trusted reply actions travel separately from forwarded/user-authored text."""
    def __new__(cls, text, actions=()):
        value = super().__new__(cls, text)
        value.quick_actions = tuple(actions)
        return value


def is_forward_command(text):
    return bool(re.match(r'^!gom(?:\s|$)', fold(text.strip())))


def schema(db):
    db.execute('''CREATE TABLE IF NOT EXISTS co_forward_drafts (
        owner TEXT PRIMARY KEY, chat TEXT NOT NULL, id TEXT NOT NULL,
        state TEXT NOT NULL, revision INTEGER NOT NULL, payload TEXT NOT NULL,
        edit_index INTEGER NOT NULL, receipt TEXT NOT NULL,
        started REAL NOT NULL, updated REAL NOT NULL)''')


def cleanup(db, cutoff):
    # Retire content on the same 30-day retention schedule as the CO history.
    # Keep the mode closed to live intake: an old forwarding session must never
    # silently turn into immediate CO intake because its content was purged.
    db.execute("UPDATE co_forward_drafts SET payload='[]',receipt='',state='paused',"
               "edit_index=-1,revision=revision+1 WHERE updated<? AND state IN ('collecting','sent')", (cutoff,))


class ForwardDrafts:
    def __init__(self, queue, owner, finalize_note, max_rows=7):
        self.queue = queue
        self.owner = owner
        self.finalize_note = finalize_note
        self.max_rows = max_rows

    def _new(self, db, chat, stamp):
        now = time.time()
        db.execute('''INSERT INTO co_forward_drafts
            (owner,chat,id,state,revision,payload,edit_index,receipt,started,updated)
            VALUES(?,?,?,'collecting',1,'[]',-1,'',?,?)
            ON CONFLICT(owner) DO UPDATE SET chat=excluded.chat,id=excluded.id,
            state=excluded.state,revision=excluded.revision,payload=excluded.payload,
            edit_index=-1,receipt='',started=excluded.started,updated=excluded.updated''',
            (self.owner, chat, secrets.token_hex(5), stamp, now))
        return self._read(db)

    def _read(self, db):
        row = db.execute('SELECT * FROM co_forward_drafts WHERE owner=?', (self.owner,)).fetchone()
        return dict(row) if row else None

    def _save(self, db, draft, **changes):
        draft.update(changes)
        draft['revision'] += 1
        draft['updated'] = time.time()
        db.execute('''UPDATE co_forward_drafts SET state=?,revision=?,payload=?,edit_index=?,
            receipt=?,updated=? WHERE owner=?''',
            tuple(draft[k] for k in ('state','revision','payload','edit_index','receipt','updated')) + (self.owner,))

    def _action(self, draft, verb, index=None):
        text = f"!gom {verb} {draft['id']} {draft['revision']}"
        return text + (f' {index}' if index is not None else '')

    def _review(self, draft):
        entries = json.loads(draft['payload'])
        rows = [row for entry in entries for row in entry['rows']]
        return entries, validate_rows(rows, self.max_rows) if rows else None


    def snapshot(self, draft):
        """Public owner-only draft data. Row references are valid for one revision."""
        result={'id':draft['id'] if draft else None, 'revision':draft['revision'] if draft else 0,
                'state':draft['state'] if draft else 'off', 'updated':draft['updated'] if draft else None,
                'receipt':draft['receipt'] if draft else '', 'edit_index':draft['edit_index'] if draft else -1,
                'rows':[], 'messages':0, 'global_errors':[], 'warnings':[], 'can_send':False,
                'max_rows':self.max_rows}
        if not draft or draft['state']!='collecting':return result
        entries,review=self._review(draft);result['messages']=len(entries)
        offset=0
        for index,entry in enumerate(entries):
            for row_index,row in enumerate(entry['rows']):
                result['rows'].append({'entry':index,'row':row_index,'values':row,
                    'errors':review['errors'][offset], 'entry_error':entry.get('error','')})
                offset+=1
            if not entry['rows']:
                result['rows'].append({'entry':index,'row':None,
                    'values':dict(source='',destination='',product='',quantity='1',status='Mới',note=''),
                    'errors':{},'entry_error':entry.get('error') or 'Tin chưa có dòng hợp lệ. Sửa hoặc bỏ tin này.'})
        if review:
            result['global_errors']=review['global_errors'];result['warnings']=review['warnings']
        result['can_send']=bool(review and review['valid'] and not any(e.get('error') for e in entries)
                                and draft['edit_index']<0)
        return result

    def change_row(self, db, draft, entry_index, row_index, values=None, remove=False):
        entries=json.loads(draft['payload'])
        if type(entry_index) is not int or not 0<=entry_index<len(entries):
            raise ValueError('Không tìm thấy tin cần sửa. Tải lại giỏ nháp.')
        entry=entries[entry_index];rows=entry['rows']
        if rows:
            if type(row_index) is not int or not 0<=row_index<len(rows):raise ValueError('Dòng không hợp lệ.')
        elif row_index is not None:raise ValueError('Dòng không hợp lệ.')
        if remove:
            if rows:rows.pop(row_index)
            if not rows:entries.pop(entry_index)
        else:
            review=validate_rows([values],self.max_rows)
            # Invalid values remain editable drafts; submit validates the whole basket.
            if rows:rows[row_index]=review['rows'][0]
            else:rows.append(review['rows'][0])
            entry['error']=''
        self._save(db,draft,payload=json.dumps(entries,ensure_ascii=False),edit_index=-1)

    def submit(self, db, draft, name, reply_token=None, chat=None):
        entries,review=self._review(draft)
        if not review or not review['valid'] or any(e.get('error') for e in entries):
            raise ValueError('Sửa hoặc bỏ các dòng lỗi trước khi gửi. Chưa đưa vào hàng chờ.')
        if draft['edit_index']>=0:raise ValueError('Đang sửa tin trên LINE. Hoàn tất sửa hoặc bấm Thôi sửa trước khi gửi.')
        payload=queue_payload(review)
        self.finalize_note(payload,name)
        payload['request_count']=len(entries)
        payload['forward_draft']={'id':draft['id'],'messages':len(entries)}
        # In the same queue transaction: append/drop/send cannot race. The
        # fixed submission key and no 10-second merge protect double taps.
        job=self.queue.draft('forward:'+draft['id'],self.owner,chat or draft['chat'],payload,
            check_product=True,reply_token=reply_token,require_online=True,
            check_duplicates=True,gather_seconds=0,_db=db)
        if job['state']=='skipped':receipt=job['result']
        else:receipt=f"Đã gửi {len(entries)} tin trong yêu cầu {job['id']}.\nĐang lấy dữ liệu MWG để gửi thông tin xác nhận. Chưa tạo CO."
        self._save(db,draft,state='sent',receipt=receipt,edit_index=-1)
        return job

    def _show(self, draft, notice='', detailed=True):
        if not draft or draft['state'] == 'off':
            return ReplyText((notice+'\n\n' if notice else '')+
                'Gom nháp đang tắt. Gửi !gom để bật trước khi chuyển tiếp tin.', [('Bắt đầu gom','!gom')])
        if draft['state'] == 'sent':
            return ReplyText((notice+'\n\n' if notice else '') + draft['receipt'] +
                '\n\nChế độ gom vẫn bật. Tin mới sẽ vào bản nháp mới, không tự gửi.',
                [('Gom tiếp','!gom'),('Tắt gom','!gom tat')])
        if draft['state'] == 'paused':
            return ReplyText('Nội dung nháp cũ đã hết thời gian lưu. Gửi !gom để bắt đầu gom lại; chưa nhận yêu cầu CO.',
                             [('Bắt đầu gom','!gom'),('Tắt gom','!gom tat')])
        entries, review = self._review(draft)
        lines = ['📥 GOM NHÁP — CHỈ TÂM', notice] if notice else ['📥 GOM NHÁP — CHỈ TÂM']
        count = len(review['rows']) if review else 0
        lines.append(f"{len(entries)} tin · {count}/{self.max_rows} dòng · Chưa gửi yêu cầu")
        if draft['edit_index'] >= 0:
            lines.append(f"✏️ Đang sửa tin {draft['edit_index']+1}. Gửi lại toàn bộ nội dung tin đó để thay thế.")
        offset = 0
        for index, entry in enumerate(entries, 1):
            if detailed:
                lines.append(f'\nTin {index}')
                for row, errors in zip(entry['rows'], (review or {}).get('errors',[])[offset:]):
                    lines.append(f"{row['source'] or '?'} → {row['destination'] or '?'} | MSP {row['product'] or '?'}\n"
                                 f"SL: {row['quantity']} · {row['status']}" +
                                 (f"\nNote: {row['note']}" if row['note'] else ''))
                    if errors:lines.append('⚠️ '+'; '.join(errors.values()))
                if entry.get('error'):lines.append('⚠️ '+entry['error'])
            offset += len(entry['rows'])
        if review:
            lines += ['⚠️ '+x for x in review['global_errors']]
            lines += ['⚠️ Dòng '+str(x['row']+1)+': '+x['message'] for x in review['warnings']]
        lines.append('\nChuyển tiếp thêm tin văn bản vào đây. Note từng dòng được giữ riêng.\n'
                     'Người yêu cầu: Tâm; bot không tự lấy tên người gửi tin gốc.\n'
                     'Chỉ lấy dữ liệu MWG sau khi bấm Gửi yêu cầu. Sau đó vẫn cần Xác nhận trong 1 phút.')
        actions = [('Xem nháp','!gom xem')]
        valid = review and review['valid'] and not any(e.get('error') for e in entries)
        if entries:
            if valid and draft['edit_index'] < 0:actions.append(('Gửi yêu cầu',self._action(draft,'gui')))
            actions += [('Sửa tin',self._action(draft,'sua')),('Bỏ tin',self._action(draft,'bo'))]
        actions.append(('Hủy nháp',self._action(draft,'huy')))
        if draft['edit_index'] >= 0:actions.append(('Thôi sửa',self._action(draft,'thoisua')))
        lines.append('\nLệnh xem lại: !gom xem · Thoát chế độ gom: !gom tat')
        return ReplyText('\n'.join(lines), actions)

    def _menu(self, draft, verb):
        entries = json.loads(draft['payload'])
        label = 'Sửa' if verb == 'sua' else 'Bỏ'
        return ReplyText(f'{label} tin nào trong bản nháp?\nChọn số tin ở các nút bên dưới.',
            [(f'{label} tin {n}',self._action(draft,verb,n)) for n in range(1,len(entries)+1)] +
            [('Xem nháp','!gom xem')])

    def process(self, event, requester_name):
        """Return None to preserve normal dispatch; never reply while DB is locked."""
        text = event.message.text.strip()
        command = is_forward_command(text)
        owner = getattr(event.source,'user_id',None)
        private = not (getattr(event.source,'group_id',None) or getattr(event.source,'room_id',None))
        if owner != self.owner or not private:
            return 'Chỉ Tâm 258330 được dùng gom nháp trong tin nhắn riêng với bot.' if command else None
        # Existing bot/CO commands keep their own authorization and confirmation.
        if not command and not is_transfer_message(text) and (text.startswith('!') or re.fullmatch(
                r'(?:(?:XACNHAN|HUY|SUA|XEM)\s+\S+|BOT\s+(?:ON|OFF|STATUS)|LISTADM|KETQUA)',text,re.I)):
            return None
        event_id = getattr(event,'webhook_event_id',None) or 'message:'+str(event.message.id)
        digest = hashlib.sha256(('forward:'+owner+':'+event_id).encode()).hexdigest()
        stamp = getattr(event,'timestamp',None)
        stamp = stamp/1000 if isinstance(stamp,(float,int)) and not isinstance(stamp,bool) else time.time()
        # Resolve the display name outside the transaction; failed sends preserve the draft.
        name = None
        bits = fold(text).split() if command else []
        if len(bits)>=2 and bits[1]=='gui' and requester_name:
            try:name=requester_name(event)
            except Exception:pass
        with self.queue.db() as db:
            draft = self._read(db)
            if db.execute('SELECT 1 FROM co_event_tombstones WHERE digest=?',(digest,)).fetchone():
                return self._show(draft,'Tin hoặc thao tác này đã được ghi nhận; không thêm lần nữa.')
            if not command and (not draft or draft['state']=='off'):
                if draft and stamp < draft['started']:
                    return self._show(draft,'Tin cũ đến trễ; không gửi yêu cầu CO.')
                return None
            if draft and stamp < draft['started']:
                return self._show(draft,'Tin thuộc phiên trước đến trễ; không thay đổi bản nháp hiện tại.')
            # Errors returned as text commit their event receipt but never enqueue.
            try:
                result = self._command(db,draft,bits,stamp,event,name) if command else self._append(db,draft,text,stamp)
            except ValueError as error:
                result = self._show(self._read(db),str(error))
            db.execute('INSERT INTO co_event_tombstones(digest) VALUES(?) ON CONFLICT(digest) DO NOTHING',(digest,))
            return result

    def _append(self, db, draft, text, stamp):
        if draft['state']=='paused':return self._show(draft)
        if draft['state']=='sent':draft=self._new(db,draft['chat'],stamp)
        if not text or len(text)>10000:raise ValueError('Mỗi tin nháp tối đa 10000 ký tự. Chưa thêm tin này.')
        entry = {'rows':[], 'error':''}
        try:entry['rows']=parse_editable(text)['rows']
        except ValueError as error:entry['error']=str(error)
        entries=json.loads(draft['payload'])
        index=draft['edit_index']
        if index>=0:entries[index]=entry
        else:entries.append(entry)
        if len(entries)>self.max_rows or sum(len(e['rows']) for e in entries)>self.max_rows:
            raise ValueError(f'Bản nháp tối đa {self.max_rows} dòng/tin. Tin vừa gửi chưa được thêm; hãy gửi hoặc bỏ bớt bản nháp trước.')
        self._save(db,draft,payload=json.dumps(entries,ensure_ascii=False),edit_index=-1)
        return self._show(draft,f"Đã {'sửa tin '+str(index+1) if index>=0 else 'thêm tin '+str(len(entries))} vào nháp.")

    def _command(self, db, draft, bits, stamp, event, name):
        verb=bits[1] if len(bits)>1 else 'bat'
        if verb in ('bat','on') and len(bits)<=2:
            if not draft or draft['state'] in ('off','sent','paused'):
                from telegram_bridge import event_chat
                draft=self._new(db,event_chat(event),stamp)
            return self._show(draft,'Đã bật gom nháp. Các tin gửi vào chat này sẽ chưa tạo yêu cầu CO.')
        if verb=='xem' and len(bits)==2:return self._show(draft)
        if verb in ('tat','off') and len(bits)==2:
            if draft:
                self._save(db,draft,state='off',payload='[]',edit_index=-1,receipt='')
                db.execute('UPDATE co_forward_drafts SET started=? WHERE owner=?',(stamp,self.owner))
            return self._show(None,'Đã tắt gom và hủy nháp chưa gửi. Các yêu cầu đã gửi giữ nguyên. Tin CO mới sẽ được xử lý theo cách bình thường.')
        if verb not in ('gui','sua','bo','huy','thoisua'):
            return self._show(draft,'Dùng !gom để bật · !gom xem để xem nháp · !gom tat để thoát.')
        if not draft or draft['state'] in ('off','paused'):return self._show(draft)
        if len(bits)==2:return self._show(draft,'Bấm nút bên dưới cho bản nháp hiện tại.')
        if len(bits) not in (4,5) or bits[2]!=draft['id'] or bits[3]!=str(draft['revision']):
            return self._show(draft,'Nút cũ đã hết hiệu lực vì bản nháp thay đổi. Xem lại và dùng nút mới.')
        if draft['state']=='sent':return self._show(draft)
        entries, review=self._review(draft)
        if verb=='huy' and len(bits)==4:
            self._save(db,draft,state='off',payload='[]',edit_index=-1,receipt='')
            db.execute('UPDATE co_forward_drafts SET started=? WHERE owner=?',(stamp,self.owner))
            return self._show(None,'Đã hủy nháp và tắt gom. Chưa gửi yêu cầu, chưa tạo CO. Yêu cầu đã gửi trước đó giữ nguyên.')
        if verb=='thoisua' and len(bits)==4:
            self._save(db,draft,edit_index=-1)
            return self._show(draft,'Đã thôi sửa; nội dung cũ được giữ nguyên.')
        if verb in ('sua','bo'):
            if not entries:return self._show(draft,'Bản nháp chưa có tin.')
            if len(bits)==4:return self._menu(draft,verb)
            if not bits[4].isdigit() or not 1<=int(bits[4])<=len(entries):raise ValueError('Số tin không hợp lệ.')
            index=int(bits[4])-1
            if verb=='sua':self._save(db,draft,edit_index=index)
            else:
                entries.pop(index)
                self._save(db,draft,payload=json.dumps(entries,ensure_ascii=False),edit_index=-1)
            return self._show(draft,'Đã bỏ tin khỏi nháp.' if verb=='bo' else '')
        if verb=='gui' and len(bits)==4:
            if not review or not review['valid'] or any(e.get('error') for e in entries):
                return self._show(draft,'Sửa hoặc bỏ các tin lỗi trước khi gửi. Chưa đưa vào hàng chờ.')
            if draft['edit_index']>=0:return self._show(draft,'Hoàn tất sửa tin hoặc bấm Thôi sửa trước khi gửi.')
            from telegram_bridge import event_chat
            job=self.submit(db,draft,name,event.reply_token,chat=event_chat(event))
            # Reserve this reply token for the normal MWG preview; !gom xem can
            # retrieve the receipt meanwhile, without forcing a paid push.
            return SENT if job['state']!='skipped' else self._show(draft)
        return self._show(draft,'Lệnh gom chưa đúng. Dùng các nút của bản nháp hiện tại.')


def install(queue, owner, finalize_note, reply, requester_name, max_rows=7):
    store=ForwardDrafts(queue,owner,finalize_note,max_rows) if queue else None
    def handle(event):
        if not store:
            if not is_forward_command(event.message.text):return False
            reply(event.reply_token,'Chức năng CO chưa được cấu hình.');return True
        result=store.process(event,requester_name)
        if result is not None and result is not SENT:reply(event.reply_token,result)
        return result is not None
    return handle
