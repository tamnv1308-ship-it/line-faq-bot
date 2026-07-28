import time

from flask import Flask, request, abort

from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.webhooks import MessageEvent, TextMessageContent
from linebot.v3.messaging import (
    Configuration,
    ApiClient,
    MessagingApi,
    ReplyMessageRequest,
    TextMessage,
)

import config
import sheets


app = Flask(__name__)

configuration = Configuration(
    access_token=config.CHANNEL_ACCESS_TOKEN
)

handler = WebhookHandler(config.CHANNEL_SECRET)

# Không gọi LINE + Google Sheet liên tục cho cùng một người
user_save_cache = {}
USER_SAVE_CACHE_TIME = 6 * 60 * 60


@app.route("/")
def home():
    return "LINE FAQ BOT is running."


@app.route("/callback", methods=["POST"])
def callback():
    signature = request.headers.get("X-Line-Signature")
    body = request.get_data(as_text=True)

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)

    return "OK"


def save_user_if_needed(event):
    """Lưu thông tin user, nhưng không lưu lặp lại liên tục."""
    try:
        user_id = event.source.user_id
        now = time.time()

        if now - user_save_cache.get(user_id, 0) < USER_SAVE_CACHE_TIME:
            return

        with ApiClient(configuration) as api_client:
            bot = MessagingApi(api_client)

            # Dùng cho group LINE
            group_id = getattr(event.source, "group_id", None)
            room_id = getattr(event.source, "room_id", None)

            if group_id:
                profile = bot.get_group_member_profile(group_id, user_id)
            elif room_id:
                profile = bot.get_room_member_profile(room_id, user_id)
            else:
                profile = bot.get_profile(user_id)

            sheets.save_user(profile.display_name, user_id)
            user_save_cache[user_id] = now

    except Exception as e:
        print("Save User Error:", e)


@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    user_text = event.message.text.strip()

    # Bot chỉ xử lý lệnh bắt đầu bằng !
    if not user_text.startswith(config.BOT_PREFIX):
        return

    command = user_text[len(config.BOT_PREFIX):].strip()
    command_lower = command.lower()
    text = ""

    if command_lower == "help":
        text = f"""
{config.BOT_NAME}

Các lệnh hỗ trợ

{config.BOT_PREFIX}help
Hiển thị hướng dẫn

{config.BOT_PREFIX}list
Danh sách tất cả keyword

{config.BOT_PREFIX}reload
Reload dữ liệu từ Google Sheet

{config.BOT_PREFIX}<keyword>
Tra cứu nội dung

Ví dụ

{config.BOT_PREFIX}wifi
{config.BOT_PREFIX}airpods
{config.BOT_PREFIX}macbook
""".strip()

    elif command_lower == "list":
        try:
            data = sheets.load_sheet()

            if not data:
                text = "Chưa có keyword."
            else:
                keys = sorted(data.keys())
                text = "Danh sách keyword\n\n"
                text += "\n".join(f"• {key}" for key in keys)

        except Exception as e:
            text = f"Lỗi:\n{e}"

    elif command_lower == "reload":
        try:
            sheets.reload()
            text = "Đã reload dữ liệu thành công."

        except Exception as e:
            text = f"Lỗi:\n{e}"

    else:
        try:
            result = sheets.search(command)

            if result is None:
                text = (
                    f"Không tìm thấy keyword:\n{command}\n\n"
                    f"Xem danh sách bằng lệnh {config.BOT_PREFIX}list"
                )
            else:
                text = result

        except Exception as e:
            text = f"Lỗi:\n{e}"

    # Trả lời trước để người trong group không phải chờ
    try:
        with ApiClient(configuration) as api_client:
            MessagingApi(api_client).reply_message(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text=text)]
                )
            )

    except Exception as e:
        print("Reply Error:", e)
        return

    # Lưu sau khi đã gửi câu trả lời
    save_user_if_needed(event)


if __name__ == "__main__":
    print("======================")
    print(config.BOT_NAME)
    print("Server is starting...")
    print("======================")

    app.run(
        host="0.0.0.0",
        port=5000,
        debug=False
    )
