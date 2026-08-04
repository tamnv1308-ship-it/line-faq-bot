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


GREETING_MESSAGES = [
    "👋 Dạ, em nghe đây.\n\nMình cần em hỗ trợ tra cứu gì ạ?",
    "🙋 Em đây ạ.\n\nMình muốn tìm thông tin nào nè?",
    "✨ Dạ có em.\n\nMình gõ keyword để em tìm giúp nhé.",
    "🌟 Em sẵn sàng đây.\n\nMình cần tra cứu nội dung gì ạ?",
]

HELP_OPENINGS = [
    f"🤖 {config.BOT_NAME} xin chào.",
    f"📚 Dạ, đây là phần hướng dẫn của {config.BOT_NAME}.",
    "📝 Em gửi mình các lệnh đang sử dụng được nhé.",
]

HELP_CLOSINGS = [
    "💬 Mình cứ gửi câu lệnh, em tìm giúp ngay.",
    "⚡ Gõ đúng keyword là em trả lời liền ạ.",
    "🌈 Em luôn sẵn sàng hỗ trợ trong group.",
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
]


def push_to_group(group_id, text):
    try:
        with ApiClient(configuration) as api_client:
            MessagingApi(api_client).push_message(
                PushMessageRequest(
                    to=group_id,
                    messages=[
                        TextMessage(text=text)
                    ]
                )
            )

        return True, None

    except Exception as e:
        return False, str(e)


def send_all_reminders():
    for reminder in config.REMINDERS:
        success, error = push_to_group(
            reminder["group_id"],
            reminder["message"]
        )

        if success:
            app.logger.warning(
                "Đã gửi nhắc: %s",
                reminder["group_id"]
            )
        else:
            app.logger.error(
                "Lỗi gửi group %s: %s",
                reminder["group_id"],
                error
            )


scheduler = BackgroundScheduler(
    timezone=ZoneInfo("Asia/Ho_Chi_Minh")
)

scheduler.add_job(
    send_all_reminders,
    trigger="cron",
    hour=8,
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

    chat_id = (
        getattr(event.source, "group_id", None)
        or getattr(event.source, "room_id", None)
    )

    if chat_id and chat_id not in seen_chat_ids:
        app.logger.warning("NEW CHAT ID: %s", chat_id)
        seen_chat_ids.add(chat_id)

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
    command_name = command_lower.split(maxsplit=1)[0] if command_lower else ""

    admin_commands = [
        "list",
        "reload",
        "sendall",
        "send",
        "say",
    ]

    user_id = getattr(event.source, "user_id", None)

    if (
        command_name in admin_commands
        and user_id not in config.ADMIN_USER_IDS
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

    # LỆNH NỘI BỘ: GỬI TẤT CẢ GROUP
    elif command_lower == "sendall":
        send_all_reminders()
        text = "✅ Đã gửi thông báo đến các group đã thiết lập."

    # LỆNH NỘI BỘ: GỬI KEYWORD SANG GROUP KHÁC
    elif command_name == "send":
        parts = command.split(maxsplit=2)

        if len(parts) < 3:
            text = (
                "⚠️ Cú pháp chưa đúng.\n\n"
                f"{config.BOT_PREFIX}send <mã group> <keyword>"
            )
        else:
            group_key = parts[1].lower()
            keyword = parts[2]

            group_id = config.GROUPS.get(group_key)
            result = sheets.search(keyword)

            if not group_id:
                text = f"⚠️ Không tìm thấy mã group: {group_key}"

            elif result is None:
                text = f"⚠️ Không tìm thấy keyword: {keyword}"

            else:
                success, error = push_to_group(group_id, result)

                if success:
                    text = (
                        f"✅ Đã gửi keyword '{keyword}' "
                        f"đến group '{group_key}'."
                    )
                else:
                    text = f"⚠️ Gửi tin không thành công.\n{error}"

    # LỆNH NỘI BỘ: GỬI NỘI DUNG TỰ VIẾT SANG GROUP KHÁC
    elif command_name == "say":
        payload = command[3:].strip()
        group_key, separator, message = payload.partition("|")

        group_key = group_key.strip().lower()
        message = message.strip()

        if not separator or not group_key or not message:
            text = (
                "⚠️ Cú pháp chưa đúng.\n\n"
                f"{config.BOT_PREFIX}say <mã group> | <nội dung>"
            )
        else:
            group_id = config.GROUPS.get(group_key)

            if not group_id:
                text = f"⚠️ Không tìm thấy mã group: {group_key}"

            else:
                success, error = push_to_group(group_id, message)

                if success:
                    text = (
                        f"✅ Đã gửi nội dung đến group "
                        f"'{group_key}'."
                    )
                else:
                    text = f"⚠️ Gửi tin không thành công.\n{error}"

    # LỆNH NỘI BỘ: LIST
    elif command_lower == "list":
        try:
            data = sheets.load_sheet()

            if not data:
                text = "📭 Hiện tại chưa có keyword nào."
            else:
                text = "📚 Danh sách keyword\n\n"
                text += "\n".join(
                    f"• {key}" for key in sorted(data.keys())
                )

        except Exception as e:
            text = f"⚠️ Không đọc được dữ liệu.\n{e}"

    # LỆNH NỘI BỘ: RELOAD
    elif command_lower == "reload":
        try:
            sheets.reload()
            text = "✅ Dữ liệu đã được cập nhật."

        except Exception as e:
            text = f"⚠️ Không thể cập nhật dữ liệu.\n{e}"

    # TRA KEYWORD BÌNH THƯỜNG
    else:
        try:
            result = sheets.search(command)

            if result is None:
                text = random.choice(NOT_FOUND_MESSAGES)
                text += (
                    f"\n\n🔍 Keyword mình vừa tìm: {command}"
                    "\n\n💡 Mình thử kiểm tra lại cách viết nhé."
                )
            else:
                text = random.choice(ANSWER_OPENINGS)
                text += f"\n\n{result}"

        except Exception as e:
            text = f"⚠️ Em gặp lỗi khi tra cứu.\n{e}"

    reply_text(event.reply_token, text)


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=5000,
        debug=False
    )
