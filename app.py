import os
import random
import secrets
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from flask import Flask, abort, request, send_from_directory
from PIL import Image, ImageDraw, ImageFont

from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    ApiClient,
    Configuration,
    ImageMessage,
    MessagingApi,
    PushMessageRequest,
    ReplyMessageRequest,
    TextMessage,
)
from linebot.v3.webhooks import MessageEvent, TextMessageContent

import config
import sheets


app = Flask(__name__)

configuration = Configuration(access_token=config.CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(config.CHANNEL_SECRET)

REPORT_DIRECTORY = Path("report_images")
REPORT_DIRECTORY.mkdir(exist_ok=True)

VIETNAM_TZ = ZoneInfo("Asia/Ho_Chi_Minh")

GREETING_MESSAGES = [
    "👋 Dạ, em nghe đây. Mình cần em hỗ trợ gì ạ?",
    "🙋 Em đây ạ. Mình muốn tìm thông tin nào nè?",
]

NOT_FOUND_MESSAGES = [
    "😕 Em chưa tìm thấy keyword này.",
    "📭 Keyword này hiện chưa có trong dữ liệu của em.",
]


def push_to_group(group_id, text):
    try:
        with ApiClient(configuration) as api_client:
            MessagingApi(api_client).push_message(
                PushMessageRequest(
                    to=group_id,
                    messages=[TextMessage(text=text)],
                )
            )
        return True, None

    except Exception as error:
        app.logger.error("Lỗi gửi LINE: %s", error)
        return False, str(error)


def push_image_to_group(group_id, image_url):
    try:
        with ApiClient(configuration) as api_client:
            MessagingApi(api_client).push_message(
                PushMessageRequest(
                    to=group_id,
                    messages=[
                        ImageMessage(
                            original_content_url=image_url,
                            preview_image_url=image_url,
                        )
                    ],
                )
            )
        return True, None

    except Exception as error:
        app.logger.error("Lỗi gửi ảnh LINE: %s", error)
        return False, str(error)


def reply_text(reply_token, text):
    try:
        with ApiClient(configuration) as api_client:
            MessagingApi(api_client).reply_message(
                ReplyMessageRequest(
                    reply_token=reply_token,
                    messages=[TextMessage(text=text)],
                )
            )
    except Exception as error:
        app.logger.error("Lỗi reply LINE: %s", error)


def format_number(value):
    return f"{value:,.0f}".replace(",", ".")


def get_font(size, bold=False):
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
        if bold
        else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf",
    ]

    for font_path in candidates:
        try:
            return ImageFont.truetype(font_path, size)
        except OSError:
            continue

    return ImageFont.load_default()


def create_report_image():
    report = sheets.get_sales_report()
    now = datetime.now(VIETNAM_TZ)

    width = 1500
    row_height = 88
    top_height = 240
    bottom_height = 110
    height = top_height + row_height * 7 + bottom_height

    image = Image.new("RGB", (width, height), "#F5F7FB")
    draw = ImageDraw.Draw(image)

    title_font = get_font(46, bold=True)
    subtitle_font = get_font(27)
    header_font = get_font(25, bold=True)
    body_font = get_font(27)
    footer_font = get_font(22)

    navy = "#12263F"
    blue = "#0068FF"
    white = "#FFFFFF"
    line = "#D8E0EA"
    text = "#172B4D"

    draw.rectangle((0, 0, width, top_height), fill=navy)
    draw.text((65, 52), "BÁO CÁO BÁN HÀNG", font=title_font, fill=white)

    time_text = now.strftime("Ngày %d/%m/%Y - %H:%M")
    draw.text((65, 122), time_text, font=subtitle_font, fill="#D8E8FF")

    columns = [
        ("Nhóm hàng", 65, 470),
        ("Tổng cột V", 500, 730),
        ("Tổng cột AI", 770, 1080),
        ("TB giá bán", 1120, 1425),
    ]

    header_y = top_height
    draw.rectangle((0, header_y, width, header_y + row_height), fill=blue)

    for label, start_x, _ in columns:
        draw.text(
            (start_x, header_y + 27),
            label,
            font=header_font,
            fill=white,
        )

    y = header_y + row_height
    for index, (name, values) in enumerate(report["groups"].items()):
        background = white if index % 2 == 0 else "#EDF3FA"
        draw.rectangle((0, y, width, y + row_height), fill=background)
        draw.line((0, y + row_height, width, y + row_height), fill=line, width=1)

        draw.text((65, y + 27), name, font=body_font, fill=text)

        quantity = format_number(values["quantity"])
        revenue = format_number(values["revenue"])
        average = format_number(values["average_price"])

        draw.text((730, y + 27), quantity, font=body_font, fill=text, anchor="ra")
        draw.text((1080, y + 27), revenue, font=body_font, fill=text, anchor="ra")
        draw.text((1425, y + 27), average, font=body_font, fill=text, anchor="ra")

        y += row_height

    footer = (
        f"Đã lọc {report['skipped_status']} dòng trạng thái nội bộ/chuyển kho"
        f" · Bỏ {report['skipped_duplicate']} dòng trùng cột Q"
    )
    draw.text((65, y + 38), footer, font=footer_font, fill="#52667A")

    filename = (
        f"report_{now.strftime('%Y%m%d_%H%M%S')}_"
        f"{secrets.token_urlsafe(12)}.png"
    )
    output_path = REPORT_DIRECTORY / filename
    image.save(output_path, "PNG", optimize=True)

    return filename


def clean_old_report_images():
    expiry = time.time() - 7 * 24 * 60 * 60

    for image_path in REPORT_DIRECTORY.glob("*.png"):
        try:
            if image_path.stat().st_mtime < expiry:
                image_path.unlink()
        except OSError:
            pass


def send_sales_report(group_id):
    if not config.REPORT_PUBLIC_BASE_URL:
        raise ValueError(
            "Thiếu REPORT_PUBLIC_BASE_URL trên Render."
        )

    clean_old_report_images()
    filename = create_report_image()

    image_url = (
        f"{config.REPORT_PUBLIC_BASE_URL}/report-images/{filename}"
    )
    success, error = push_image_to_group(group_id, image_url)

    if not success:
        raise RuntimeError(error)

    return image_url


def send_reminders(reminders):
    for reminder in reminders:
        push_to_group(reminder["group_id"], reminder["message"])


def run_scheduled_report(group_id):
    try:
        image_url = send_sales_report(group_id)
        app.logger.warning("Đã gửi report: %s", image_url)
    except Exception as error:
        app.logger.exception("Không gửi được report: %s", error)


scheduler = BackgroundScheduler(timezone=VIETNAM_TZ)

for schedule in config.REMINDER_SCHEDULES:
    scheduler.add_job(
        send_reminders,
        trigger="cron",
        hour=schedule["hour"],
        minute=schedule["minute"],
        args=[schedule["reminders"]],
        id=f"reminder_{schedule['id']}",
        replace_existing=True,
        max_instances=1,
    )

for schedule in config.REPORT_SCHEDULES:
    scheduler.add_job(
        run_scheduled_report,
        trigger="cron",
        hour=schedule["hour"],
        minute=schedule["minute"],
        args=[schedule["group_id"]],
        id=f"report_{schedule['id']}",
        replace_existing=True,
        max_instances=1,
    )

scheduler.start()


@app.route("/")
def home():
    return "LINE FAQ BOT is running."


@app.route("/report-images/<filename>")
def report_image(filename):
    return send_from_directory(REPORT_DIRECTORY, filename)


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
    user_id = getattr(event.source, "user_id", None)

    if user_text.lower() in {"bot ơi", "bot oi", "e bot"}:
        reply_text(event.reply_token, random.choice(GREETING_MESSAGES))
        return

    if not user_text.startswith(config.BOT_PREFIX):
        return

    command = user_text[len(config.BOT_PREFIX):].strip()
    command_lower = command.lower()
    command_name = command_lower.split(maxsplit=1)[0] if command_lower else ""

    admin_commands = {"reload", "test", "testreport", "sendall"}

    if (
        command_name in admin_commands
        and user_id not in config.ADMIN_USER_IDS
    ):
        return

    if command_lower in {"", "help"}:
        text = (
            f"🤖 {config.BOT_NAME}\n\n"
            f"🔎 {config.BOT_PREFIX}<keyword>: tra cứu\n"
            f"📊 {config.BOT_PREFIX}testreport: gửi thử report"
        )

    elif command_lower == "reload":
        sheets.reload()
        text = "✅ Đã cập nhật lại dữ liệu FAQ."

    elif command_lower == "sendall":
        for schedule in config.REMINDER_SCHEDULES:
            send_reminders(schedule["reminders"])
        text = "✅ Đã gửi các thông báo đã thiết lập."

    elif command_lower == "testreport":
        try:
            image_url = send_sales_report(config.GROUPS["bot"])
            text = f"✅ Đã gửi report thử vào group BOT.\n{image_url}"
        except Exception as error:
            text = f"⚠️ Không gửi được report.\n{error}"

    elif command_name == "test":
        parts = command.split(maxsplit=1)
        if len(parts) < 2:
            text = "⚠️ Gõ: !test <mã khung giờ>"
        else:
            schedule_id = parts[1].lower()
            schedule = next(
                (
                    item
                    for item in config.REMINDER_SCHEDULES
                    if item["id"] == schedule_id
                ),
                None,
            )

            if schedule is None:
                text = "⚠️ Không tìm thấy khung giờ."
            else:
                send_reminders(schedule["reminders"])
                text = f"✅ Đã gửi thử khung {schedule_id}."

    else:
        result = sheets.search(command)

        if result is None:
            text = (
                f"{random.choice(NOT_FOUND_MESSAGES)}\n\n"
                f"🔍 Keyword: {command}"
            )
        else:
            text = f"✅ Em tìm được thông tin:\n\n{result}"

    reply_text(event.reply_token, text)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
REPORT_PUBLIC_BASE_URL = os.getenv(
    "REPORT_PUBLIC_BASE_URL",
    os.getenv("RENDER_EXTERNAL_URL", ""),
).rstrip("/")

FAQ_SHEET_NAME = "FAQ"
REPORT_SHEET_NAME = "DATA"

REPORT_SCHEDULES = [
    {
        "id": "report_1000",
        "hour": 10,
        "minute": 0,
        "group_id": GROUPS["bot"],
    },
    {
        "id": "report_1500",
        "hour": 15,
        "minute": 0,
        "group_id": GROUPS["bot"],
    },
    {
        "id": "report_2200",
        "hour": 22,
        "minute": 0,
        "group_id": GROUPS["bot"],
    },
]
