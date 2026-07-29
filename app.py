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

handler = WebhookHandler(
    config.CHANNEL_SECRET
)


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
        print("Reply Error:", e)


@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    user_text = event.message.text.strip()
    user_text_lower = user_text.lower()

    # Bot chỉ phản hồi khi được gọi đúng câu này
    if user_text_lower in [
        "bot ơi",
        "bot oi",
        "ê bot",
        "hey bot",
    ]:
        reply_text(
            event.reply_token,
            f"Dạ, em nghe đây.\n\nGõ {config.BOT_PREFIX}help để xem các lệnh."
        )
        return

    # Tin nhắn không phải lệnh thì bỏ qua
    if not user_text.startswith(config.BOT_PREFIX):
        return

    command = user_text[len(config.BOT_PREFIX):].strip()
    command_lower = command.lower()

    # HELP
    if command_lower in ["help", ""]:
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

    # LIST
    elif command_lower == "list":
        try:
            data = sheets.load_sheet()

            if not data:
                text = "Chưa có keyword."

            else:
                keys = sorted(data.keys())

                text = "Danh sách keyword\n\n"
                text += "\n".join(
                    f"• {key}" for key in keys
                )

        except Exception as e:
            text = f"Lỗi:\n{e}"

    # RELOAD
    elif command_lower == "reload":
        try:
            sheets.reload()
            text = "Đã reload dữ liệu thành công."

        except Exception as e:
            text = f"Lỗi:\n{e}"

    # SEARCH KEYWORD
    else:
        try:
            result = sheets.search(command)

            if result is None:
                text = (
                    f"Không tìm thấy keyword:\n{command}\n\n"
                    f"Gõ {config.BOT_PREFIX}list để xem danh sách keyword."
                )

            else:
                text = result

        except Exception as e:
            text = f"Lỗi:\n{e}"

    reply_text(event.reply_token, text)


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
