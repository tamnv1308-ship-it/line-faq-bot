import random

from zoneinfo import ZoneInfo
from apscheduler.schedulers.background import BackgroundScheduler
from flask import Flask, request, abort

from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.webhooks import MessageEvent, TextMessageContent
from linebot.v3.messaging import (
    Configuration,
    ApiClient,
    MessagingApi,
    ReplyMessageRequest,
    PushMessageRequest,
    TextMessage,
)

import config
import sheets


app = Flask(__name__)

configuration = Configuration(
    access_token=config.CHANNEL_ACCESS_TOKEN
)

handler = WebhookHandler(
    config.CHANNEL_SECRET
)

seen_chat_ids = set()
seen_user_ids = set()

GREETING_MESSAGES = [
    "👋 Dạ, em nghe đây.\n\nMình cần em hỗ trợ tra cứu gì ạ?",
    "🙋 Em đây ạ.\n\nMình muốn tìm thông tin nào nè?",
    "✨ Dạ có em.\n\nMình gõ keyword để em tìm giúp nhé.",
    "🌟 Em sẵn sàng đây.\n\nMình cần tra cứu nội dung gì ạ?",
    "📩 Dạ, em có mặt.\n\nGõ lệnh hoặc keyword, em hỗ trợ mình ngay.",
]

HELP_OPENINGS = [
    f"🤖 {config.BOT_NAME} xin chào.",
    f"📚 Dạ, đây là phần hướng dẫn của {config.BOT_NAME}.",
    "📝 Em gửi mình các lệnh đang sử dụng được nhé.",
    "🔎 Mình có thể dùng các lệnh sau để tra cứu nhanh.",
]

HELP_CLOSINGS = [
    "💬 Mình cứ gửi câu lệnh, em tìm giúp ngay.",
    "⚡ Gõ đúng keyword là em trả lời liền ạ.",
    "🌈 Em luôn sẵn sàng hỗ trợ trong group.",
]

LIST_OPENINGS = [
    "📚 Danh sách keyword hiện có đây ạ.",
    "🔎 Em tìm được các keyword này.",
    "🗂️ Mình có thể tra cứu bằng những keyword bên dưới.",
]

ANSWER_OPENINGS = [
    "✅ Em tìm được thông tin này.",
    "📌 Dạ, nội dung mình cần đây ạ.",
    "💬 Em gửi mình câu trả lời nhé.",
    "🔍 Thông tin tra cứu của mình đây.",
]

NOT_FOUND_MESSAGES = [
    "😕 Em chưa tìm thấy keyword này.",
    "📭 Keyword này hiện chưa có trong dữ liệu của em.",
    "🔎 Em chưa thấy nội dung phù hợp với keyword này.",
    "📝 Có thể keyword này chưa được thêm vào danh sách.",
]


def send_all_reminders():
    for reminder in config.REMINDERS:
        try:
            with ApiClient(configuration) as api_client:
                MessagingApi(api_client).push_message(
                    PushMessageRequest(
                        to=reminder["group_id"],
                        messages=[
                            TextMessage(text=reminder["message"])
                        ]
                    )
                )

            app.logger.warning(
                "Đã gửi nhắc: %s",
                reminder["group_id"]
            )

        except Exception as e:
            app.logger.error(
                "Lỗi gửi group %s: %s",
                reminder["group_id"],
                e
            )


scheduler = BackgroundScheduler(
    timezone=ZoneInfo("Asia/Ho_Chi_Minh")
)

scheduler.add_job(
    send_all_reminders,
    trigger="cron",
    hour=9,
    minute=0,
    id="morning_reminder",
    replace_existing=True,
    max_instances=1
)

scheduler.start()


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


def reply_text(reply_token, text):
    try:
        with ApiClient(configuration) as api_client:
            MessagingApi(api_client).reply_message(
                ReplyMessageRequest(
                    reply_token=reply_token,
                    messages=[
                        TextMessage(text=text)
                    ]
                )
            )

    except Exception as e:
        app.logger.error("Reply Error: %s", e)


@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    user_text = event.message.text.strip()
    user_text_lower = user_text.lower()

    # Tự ghi ID group/room vào Render Logs, không trả lời group
    chat_id = (
        getattr(event.source, "group_id", None)
        or getattr(event.source, "room_id", None)
    )

    if chat_id and chat_id not in seen_chat_ids:
        app.logger.warning("NEW CHAT ID: %s", chat_id)
        seen_chat_ids.add(chat_id)

    user_id = getattr(event.source, "user_id", None)

    if user_id and user_id not in seen_user_ids:
        app.logger.warning("NEW USER ID: %s", user_id)
        seen_user_ids.add(user_id)

    if user_text_lower in [
        "bot ơi",
        "bot oi",
        "ê bot",
        "hey bot",
    ]:
        text = random.choice(GREETING_MESSAGES)
        text += (
            f"\n\n💡 Gõ {config.BOT_PREFIX}help để xem hướng dẫn "
            f"hoặc {config.BOT_PREFIX}<keyword> để tra cứu."
        )

        reply_text(event.reply_token, text)
        return

    if not user_text.startswith(config.BOT_PREFIX):
        return

    command = user_text[len(config.BOT_PREFIX):].strip()
    command_lower = command.lower()

    # Lệnh nội bộ: chỉ QTV được dùng, người khác sẽ không nhận phản hồi
    admin_commands = [
        "list",
        "reload",
        "sendall",
    ]

    if (
        command_lower in admin_commands
        and event.source.user_id not in config.ADMIN_USER_IDS
    ):
        return

    # HELP
    if command_lower in ["help", ""]:
        text = f"""
{random.choice(HELP_OPENINGS)}

━━━━━━━━━━━━━━
📌 CÁC LỆNH HIỆN CÓ
━━━━━━━━━━━━━━

🔎 {config.BOT_PREFIX}<keyword>
Tra cứu câu trả lời theo keyword

{random.choice(HELP_CLOSINGS)}
""".strip()

    # LIST: chỉ QTV
    elif command_lower == "list":
        try:
            data = sheets.load_sheet()

            if not data:
                text = "📭 Hiện tại em chưa thấy keyword nào trong dữ liệu."
            else:
                keys = sorted(data.keys())

                text = random.choice(LIST_OPENINGS)
                text += "\n\n━━━━━━━━━━━━━━\n"
                text += "\n".join(f"• {key}" for key in keys)
                text += "\n━━━━━━━━━━━━━━"

        except Exception as e:
            text = f"⚠️ Em chưa đọc được dữ liệu.\nChi tiết: {e}"

    # RELOAD: chỉ QTV
    elif command_lower == "reload":
        try:
            sheets.reload()
            text = "✅ Dữ liệu đã được cập nhật xong rồi."

        except Exception as e:
            text = f"⚠️ Em chưa thể cập nhật dữ liệu.\nChi tiết: {e}"

    # SEND ALL: chỉ QTV
    elif command_lower == "sendall":
        send_all_reminders()
        text = "✅ Đã gửi thông báo đến các group đã thiết lập."

    # SEARCH KEYWORD
    else:
        try:
            result = sheets.search(command)

            if result is None:
                text = random.choice(NOT_FOUND_MESSAGES)
                text += (
                    f"\n\n🔍 Keyword mình vừa tìm: {command}"
                    "\n\n💡 Mình thử kiểm tra lại cách viết keyword nhé."
                )
            else:
                text = random.choice(ANSWER_OPENINGS)
                text += f"\n\n{result}"

        except Exception as e:
            text = f"⚠️ Em gặp lỗi khi tra cứu.\nChi tiết: {e}"

    reply_text(event.reply_token, text)


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=5000,
        debug=False
    )
