from flask import Flask, request, abort
from linebot.v3.messaging import MessagingApiBlob

from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.webhooks import MessageEvent, TextMessageContent


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

    # =========================
    # SAVE USER
    # =========================
    try:

        user_id = event.source.user_id

        with ApiClient(configuration) as api_client:

            line_bot_api = MessagingApi(api_client)

            profile = line_bot_api.get_profile(user_id)

            sheets.save_user(
                profile.display_name,
                user_id
            )

    except Exception as e:
        print("Save User:", e)

    # ===== Từ đây mới là code cũ =====

    if not user_text.startswith(config.BOT_PREFIX):
        return

    command = user_text[len(config.BOT_PREFIX):].strip()
