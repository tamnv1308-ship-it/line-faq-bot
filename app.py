from flask import Flask, request, abort

from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.webhooks import (
    MessageEvent,
    TextMessageContent,
)

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


@handler.add(
    MessageEvent,
    message=TextMessageContent
)
def handle_message(event):

    user_text = event.message.text.strip()

    # ==========================
    # SAVE USER
    # ==========================

    try:

        user_id = event.source.user_id

        with ApiClient(configuration) as api_client:

            bot = MessagingApi(api_client)

            profile = bot.get_profile(user_id)

            sheets.save_user(
                profile.display_name,
                user_id
            )

    except Exception as e:

        print("Save User:", e)

    if not user_text.startswith(config.BOT_PREFIX):
        return

    command = user_text[len(config.BOT_PREFIX):].strip()

    text = ""
        # ==========================
    # HELP
    # ==========================

    if command.lower() == "help":

        text = f"""
🤖 {config.BOT_NAME}

Các lệnh hỗ trợ

!help
Hiển thị hướng dẫn

!list
Danh sách tất cả keyword

!reload
Reload dữ liệu từ Google Sheet

!<keyword>
Tra cứu nội dung

Ví dụ

!wifi
!airpods
!macbook
""".strip()

    # ==========================
    # LIST
    # ==========================

    elif command.lower() == "list":

        try:

            data = sheets.load_sheet()

            if len(data) == 0:

                text = "Chưa có keyword."

            else:

                keys = sorted(data.keys())

                text = "📚 Danh sách keyword\n\n"

                text += "\n".join(
                    f"• {k}" for k in keys
                )

        except Exception as e:

            text = f"Lỗi:\n{e}"


    # ==========================
    # RELOAD
    # ==========================

    elif command.lower() == "reload":

        try:

            sheets.reload()

            text = "✅ Đã reload dữ liệu thành công."

        except Exception as e:

            text = f"Lỗi:\n{e}"
                # ==========================
    # SEARCH
    # ==========================

    else:

        try:

            result = sheets.search(command)

            if result is None:

                text = (
                    f"❌ Không tìm thấy keyword:\n"
                    f"{command}"
                )

            else:

                text = result

        except Exception as e:

            text = f"Lỗi:\n{e}"

    # ==========================
    # REPLY
    # ==========================

    try:

        with ApiClient(configuration) as api_client:

            MessagingApi(api_client).reply_message(

                ReplyMessageRequest(

                    reply_token=event.reply_token,

                    messages=[

                        TextMessage(
                            text=text
                        )

                    ]

                )

            )

    except Exception as e:

        print("Reply Error:", e)
        if __name__ == "__main__":

    print("==============================")
    print(config.BOT_NAME)
    print("Server is starting...")
    print("==============================")

    app.run(
        host="0.0.0.0",
        port=5000,
        debug=False
    )
