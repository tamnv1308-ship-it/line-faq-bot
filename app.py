import random

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


GREETING_MESSAGES = [
    "Dạ, em nghe đây.\n\nMình cần em hỗ trợ tra cứu gì ạ?",
    "Em đây ạ.\n\nMình muốn tìm thông tin nào nè?",
    "Dạ có em.\n\nMình gõ keyword để em tìm giúp nhé.",
    "Em sẵn sàng đây.\n\nMình cần tra cứu nội dung gì ạ?",
    "Dạ, em có mặt.\n\nGõ lệnh hoặc keyword, em hỗ trợ mình ngay.",
]

HELP_OPENINGS = [
    f"{config.BOT_NAME} xin chào.",
    f"Dạ, đây là phần hướng dẫn của {config.BOT_NAME}.",
    f"Em gửi mình các lệnh đang sử dụng được nhé.",
    f"Mình có thể dùng các lệnh sau để tra cứu nhanh.",
]

HELP_CLOSINGS = [
    "Mình cứ gửi câu lệnh, em tìm giúp ngay.",
    "Gõ đúng keyword là em trả lời liền ạ.",
    "Nếu chưa biết tìm gì, mình thử gõ !list nhé.",
    "Em luôn sẵn sàng hỗ trợ trong group.",
]

LIST_OPENINGS = [
    "Danh sách keyword hiện có đây ạ.",
    "Em tìm được các keyword này.",
    "Mình có thể tra cứu bằng những keyword bên dưới.",
    "Đây là các nội dung bot đang hỗ trợ.",
]

ANSWER_OPENINGS = [
    "Em tìm được thông tin này.",
    "Dạ, nội dung mình cần đây ạ.",
    "Em gửi mình câu trả lời nhé.",
    "Thông tin tra cứu của mình đây.",
    "Em đã tìm thấy nội dung phù hợp.",
]

NOT_FOUND_MESSAGES = [
    "Em chưa tìm thấy keyword này.",
    "Keyword này hiện chưa có trong dữ liệu của em.",
    "Em chưa thấy nội dung phù hợp với keyword này.",
    "Có thể keyword này chưa được thêm vào Google Sheet.",
]

RELOAD_MESSAGES = [
    "Dữ liệu đã được cập nhật xong rồi.",
    "Em đã tải lại dữ liệu mới nhất.",
    "Reload hoàn tất rồi ạ.",
    "Dữ liệu từ Google Sheet đã được cập nhật.",
]


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

    # Khi mọi người gọi bot trực tiếp
    if user_text_lower in [
        "bot ơi",
        "bot oi",
        "ê bot",
        "lol bot",
        "di bot",
        "đĩ bot",
        "bot đâu",
        "bot dau",
    ]:
        text = random.choice(GREETING_MESSAGES)
        text += (
            f"\n\nGõ {config.BOT_PREFIX}help để xem hướng dẫn "
            f"hoặc {config.BOT_PREFIX}<keyword> để tra cứu."
        )

        reply_text(event.reply_token, text)
        return

    # Bỏ qua các tin nhắn không phải lệnh bot
    if not user_text.startswith(config.BOT_PREFIX):
        return

    command = user_text[len(config.BOT_PREFIX):].strip()
    command_lower = command.lower()

    # HELP
    if command_lower in ["help", ""]:
        text = f"""
{random.choice(HELP_OPENINGS)}

CÁC LỆNH HIỆN CÓ

{config.BOT_PREFIX}list
Xem toàn bộ keyword hiện có

{config.BOT_PREFIX}reload
Cập nhật lại dữ liệu từ Google Sheet

{config.BOT_PREFIX}<keyword>
Tra cứu câu trả lời theo keyword

VÍ DỤ

{config.BOT_PREFIX}wifi
{config.BOT_PREFIX}airpods
{config.BOT_PREFIX}macbook

{random.choice(HELP_CLOSINGS)}
""".strip()

    # LIST
    elif command_lower == "list":
        try:
            data = sheets.load_sheet()

            if not data:
                text = random.choice([
                    "Hiện tại em chưa thấy keyword nào trong dữ liệu.",
                    "Google Sheet đang chưa có keyword để em hiển thị.",
                    "Em chưa tìm thấy keyword nào, mình kiểm tra lại Sheet nhé.",
                ])

            else:
                keys = sorted(data.keys())

                text = random.choice(LIST_OPENINGS)
                text += "\n\n"
                text += "\n".join(f"• {key}" for key in keys)
                text += (
                    f"\n\nVí dụ: {config.BOT_PREFIX}{keys[0]}"
                )

        except Exception as e:
            text = f"Em chưa đọc được dữ liệu.\nChi tiết: {e}"

    # RELOAD
    elif command_lower == "reload":
        try:
            sheets.reload()

            text = random.choice(RELOAD_MESSAGES)
            text += (
                f"\n\nMình thử tra cứu lại bằng "
                f"{config.BOT_PREFIX}<keyword> nhé."
            )

        except Exception as e:
            text = f"Em chưa thể cập nhật dữ liệu.\nChi tiết: {e}"

    # SEARCH KEYWORD
    else:
        try:
            result = sheets.search(command)

            if result is None:
                text = random.choice(NOT_FOUND_MESSAGES)
                text += (
                    f"\n\nKeyword mình vừa tìm là: {command}"
                    f"\n\nMình thử kiểm tra lại cách viết, "
                    f"hoặc gõ {config.BOT_PREFIX}list để xem "
                    f"danh sách keyword nhé."
                )

            else:
                text = random.choice(ANSWER_OPENINGS)
                text += f"\n\n{result}"

        except Exception as e:
            text = f"Em gặp lỗi khi tra cứu.\nChi tiết: {e}"

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
