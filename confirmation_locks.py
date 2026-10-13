"""Confirmation expiry penalties and owner-only unlock selection, within queue transactions."""
import json
import math

POLICY_VERSION = 1


def lock_notice(db, owner, now, owner_id):
    if owner == owner_id:
        return ''
    row=db.execute('SELECT * FROM co_confirmation_locks WHERE owner=?',(owner,)).fetchone()
    if not row:
        return ''
    if row['strikes']>=3:
        return 'Tài khoản đã quá hạn xác nhận 3 lần và đang bị khóa nhận yêu cầu CO. Liên hệ Tâm 258330 Apple để mở khóa.'
    remaining=math.ceil(row['locked_until']-now)
    if remaining>0:
        return f"Bạn đang bị khóa nhận yêu cầu CO do quá hạn xác nhận lần {row['strikes']}. Còn {remaining} giây; hết thời gian này có thể gửi lại."
    return ''


def expire_drafts(db, now, owner_id):
    rows=db.execute("SELECT * FROM jobs WHERE state='draft' AND created<=? - CASE WHEN result='MWG_PREVIEW' AND notified=0 THEN 300 ELSE 60 END ORDER BY created,id",(now,)).fetchall()
    control=db.execute('SELECT enabled,heartbeat FROM co_control WHERE id=1').fetchone()
    online=control['enabled'] and now-control['heartbeat']<=30
    for job in rows:
        payload=json.loads(job['payload'])
        delivered=job['result']=='MWG_PREVIEW' and job['notified']==1
        message='Hết hạn xác nhận yêu cầu '+job['id']+'. Yêu cầu đã tự hủy, chưa tạo CO.'
        if delivered and payload.get('confirmation_lock_version')==POLICY_VERSION and online and job['owner']!=owner_id:
            previous=db.execute('SELECT strikes FROM co_confirmation_locks WHERE owner=?',(job['owner'],)).fetchone()
            strikes=min(3,(previous['strikes'] if previous else 0)+1)
            until=now+({1:60,2:180}.get(strikes,0))
            name=payload.get('requester_name') or 'Chưa có tên'
            db.execute('INSERT INTO co_confirmation_locks(owner,name,strikes,locked_until,last_job,updated) VALUES(?,?,?,?,?,?) ON CONFLICT(owner) DO UPDATE SET name=excluded.name,strikes=excluded.strikes,locked_until=excluded.locked_until,last_job=excluded.last_job,updated=excluded.updated',
                       (job['owner'],name,strikes,until,job['id'],now))
            message+='\n'+('Khóa nhận yêu cầu mới 1 phút (lần 1).' if strikes==1 else
                            'Khóa nhận yêu cầu mới 3 phút (lần 2).' if strikes==2 else
                            'Khóa nhận yêu cầu mới đến khi Tâm 258330 Apple mở khóa (lần 3).')
        db.execute("UPDATE jobs SET state='expired',lease=NULL,result=?,updated=?,notified=? WHERE id=? AND state='draft'",
                   (message,now,0 if delivered else 1,job['id']))
        db.execute('DELETE FROM preview_replies WHERE job_id=?',(job['id'],))


def unlock(db, owner, chat, event, selection, now, owner_id):
    if owner!=owner_id:
        return 'Chỉ Tâm 258330 Apple được xem danh sách và mở khóa yêu cầu CO.'
    old=db.execute('SELECT message FROM co_unlock_events WHERE event=?',(event,)).fetchone()
    if old:
        return old['message']
    if not selection:
        rows=db.execute('SELECT * FROM co_confirmation_locks WHERE strikes>=3 OR locked_until>? ORDER BY updated,owner LIMIT 50',(now,)).fetchall()
        db.execute('DELETE FROM co_unlock_choices WHERE owner=? AND chat=?',(owner,chat))
        blocks=['🔓 DANH SÁCH CẦN MỞ KHÓA']
        for position,row in enumerate(rows,1):
            db.execute('INSERT INTO co_unlock_choices(owner,chat,position,target,last_job,issued) VALUES(?,?,?,?,?,?)',
                       (owner,chat,position,row['owner'],row['last_job'],now))
            state='Chờ Tâm mở khóa' if row['strikes']>=3 else f"Còn {math.ceil(row['locked_until']-now)} giây"
            blocks.append(f"{position}. {row['name']}\nLần {row['strikes']} · {state}")
        message='\n\n'.join(blocks)+'\n\nGửi !mokhoa <số thứ tự>, ví dụ !mokhoa 2. Danh sách có hiệu lực 5 phút; mở khóa sẽ reset số lần về 0.' if rows else 'Không có tài khoản đang bị khóa nhận yêu cầu CO.'
    elif not selection.isascii() or not selection.isdigit() or not 1<=int(selection)<=50:
        message='Dùng !mokhoa để xem danh sách, rồi !mokhoa <số thứ tự> để mở.'
    else:
        choice=db.execute('SELECT * FROM co_unlock_choices WHERE owner=? AND chat=? AND position=?',(owner,chat,int(selection))).fetchone()
        current=db.execute('SELECT * FROM co_confirmation_locks WHERE owner=?',(choice['target'],)).fetchone() if choice else None
        if not choice or now-choice['issued']>=300 or not current or current['last_job']!=choice['last_job']:
            message='Danh sách đã hết hiệu lực hoặc trạng thái đã thay đổi. Gửi !mokhoa để lấy danh sách mới.'
        else:
            db.execute('DELETE FROM co_confirmation_locks WHERE owner=?',(choice['target'],))
            db.execute('DELETE FROM co_unlock_choices WHERE target=?',(choice['target'],))
            message=f"Đã mở khóa {current['name']}. Số lần quá hạn đã reset về 0; có thể gửi yêu cầu CO mới."
    db.execute('INSERT INTO co_unlock_events(event,message,created) VALUES(?,?,?)',(event,message,now))
    return message
