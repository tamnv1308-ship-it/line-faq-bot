"""Explicit setup only; importing app never changes Telegram webhook/settings."""
import argparse
import json
import os
from urllib.parse import urlsplit

from telegram_bridge import Client, TelegramError, settings


def main():
    parser=argparse.ArgumentParser(description='Kiểm tra/kết nối bot Telegram đã tạo bằng BotFather.')
    parser.add_argument('--register',action='store_true',help='Đăng ký webhook sau khi đã cấu hình máy chủ.')
    args=parser.parse_args();cfg=settings()
    if not cfg['ready']:parser.error('Thiếu TELEGRAM_ENABLED, BOT_TOKEN, BOT_USERNAME hoặc WEBHOOK_SECRET. Không in các khóa bí mật.')
    client=Client()
    try:
        me=client.call('getMe',{})
        if (not me.get('is_bot') or str(me.get('id'))!=cfg['bot_id'] or
                str(me.get('username','')).lower()!=cfg['username'].lower()):
            parser.error('Token không khớp tên bot Telegram được cấu hình. Chưa thay đổi webhook.')
        base=(os.getenv('REPORT_PUBLIC_BASE_URL') or os.getenv('RENDER_EXTERNAL_URL') or '').rstrip('/')
        parsed=urlsplit(base)
        if parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.query or parsed.fragment or parsed.path:
            parser.error('REPORT_PUBLIC_BASE_URL phải là địa chỉ HTTPS gốc của máy chủ bot.')
        url=base+'/telegram/webhook';before=client.call('getWebhookInfo',{})
        if args.register:
            if before.get('url') and before['url']!=url:
                parser.error('Bot đang nối tới máy chủ khác. Chưa đổi webhook; kiểm tra bot được chọn trước.')
            client.call('setWebhook',dict(url=url,secret_token=cfg['secret'],
                allowed_updates=['message','callback_query'],max_connections=4,drop_pending_updates=False))
            client.call('setMyCommands',{'commands':[
                {'command':'taoco','description':'Gửi form yêu cầu CO'},
                {'command':'congcu','description':'Mở hướng dẫn Công cụ Táo'},
                {'command':'co','description':'Tra cứu mã CO'},
                {'command':'gom','description':'Giỏ nháp riêng của Tâm'},
                {'command':'tongket','description':'Tổng kết dành cho Tâm'}]})
        after=client.call('getWebhookInfo',{})
        print(json.dumps({'bot':'@'+me['username'],'webhook_matches':after.get('url')==url,
            'pending_updates':after.get('pending_update_count',0),
            'webhook_has_error':bool(after.get('last_error_date')),
            'group_configured':bool(cfg['group']),'telegram_intake_active':cfg['active'],
            'registered':args.register},ensure_ascii=False,indent=2))
    except TelegramError as error:
        parser.error('Chưa kết nối được Telegram (HTTP '+str(error.code)+'). Không thay đổi kênh nhận LINE.')


if __name__=='__main__':main()
