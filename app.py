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


@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):

    user_text = event.message.text.strip()

    if not user_text.startswith(config.BOT_PREFIX):
        return

    command = user_text[len(config.BOT_PREFIX):].strip()

    if command == "":
        return

    command_lower = command.lower()

    with ApiClient(configuration) as api_client:

        line_bot_api = MessagingApi(api_client)

        # =========================
        # HELP
        # =========================
        if command_lower == "help":

            text = (
                "📚 LINE FAQ BOT\n\n"
                "!help - Hiển thị hướng dẫn\n"
                "!list - Danh sách keyword\n"
                "!reload - Tải lại Google Sheet\n"
                "!<keyword> - Tra cứu thông tin"
            )

            if not text or text.strip() == "":
    text = "Không có dữ liệu trả về."
            line_bot_api.reply_message(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[
                        TextMessage(text=text)
                    ]
                )
            )

            return

        # =========================
        # LIST
        # =========================
        if command_lower == "list":

            data = sheets.load_sheet()

            keys = sorted(data.keys())

            if len(keys) == 0:
                text = "Hiện chưa có keyword nào."
            else:
                text = "📋 Danh sách Keyword\n\n"
                text += "\n".join(f"• {k}" for k in keys)

            line_bot_api.reply_message(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[
                        TextMessage(text=text)
                    ]
                )
            )

            return

        # =========================
        # RELOAD
        # =========================
        if command_lower == "reload":

            sheets.reload()

            line_bot_api.reply_message(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[
                        TextMessage(
                            text="✅ Google Sheet đã được tải lại."
                        )
                    ]
                )
            )

            return

        # =========================
        # SEARCH
        # =========================
        answer = sheets.search(command)

        if answer is None:

            text = (
                "❌ Không tìm thấy thông tin.\n\n"
                "Gõ !list để xem danh sách keyword."
            )

        else:

            text = answer

        line_bot_api.reply_message(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[
                    TextMessage(text=text)
                ]
            )
        )


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=8000,
        debug=True
    )
