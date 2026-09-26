from co_results import message_chunks
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
import co_flow


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
                    messages=[TextMessage(text=part) for part in message_chunks(text)],
                )
            )
        return True, None

    except Exception as error:
        app.logger.error("Lỗi gửi LINE: %s", error)
        if 'monthly limit' in str(error).lower():
            return False, 'LINE đã hết hạn mức gửi tin tháng. Kiểm tra gói tin nhắn trong LINE Official Account; lệnh chưa gửi được.'
        if getattr(error,'status',None)==429:
            return False, 'LINE đang giới hạn gửi tin (429). Chờ rồi thử lại; chưa gửi thành công.'
        return False, 'Không gửi được tin tới LINE. Kiểm tra bot còn trong nhóm và quyền gửi tin; xem log để biết lỗi.'


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
                    messages=[TextMessage(text=part) for part in message_chunks(text)],
                )
            )
        return True
    except Exception:
        app.logger.error("Không gửi được reply LINE.")
        return False


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

def push_co_result(chat, text, retry_key):
    import urllib.request
    import urllib.error
    import json
    payload = json.dumps({'to': chat, 'messages': [{'type': 'text', 'text': part} for part in message_chunks(text)]}).encode()
    req = urllib.request.Request('https://api.line.me/v2/bot/message/push', data=payload,
        headers={'Authorization': 'Bearer ' + config.CHANNEL_ACCESS_TOKEN,
                 'Content-Type': 'application/json', 'X-Line-Retry-Key': retry_key})
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            return response.status == 200
    except urllib.error.HTTPError as error:
        return error.code == 409 and bool(error.headers.get('X-Line-Accepted-Request-Id'))
    except Exception:
        app.logger.warning('CO result delivery failed; will retry.')
        return False

handle_co, notify_co = co_flow.install(app, reply_text, push_co_result, config.ADMIN_USER_IDS,
    requester_name=lambda event: source_name(
        'group_user' if getattr(event.source,'group_id',None) else 'room_user' if getattr(event.source,'room_id',None) else 'user',
        getattr(event.source,'group_id',None) or getattr(event.source,'room_id',None), event.source.user_id))
scheduler.add_job(notify_co, 'interval', seconds=1, id='co_result_notifications', max_instances=1)
scheduler.start()


@app.route("/")
def home():
    return "LINE FAQ BOT is running."


@app.get("/health")
def health():
    return {"status": "ok"}, 200


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


_source_name_cache = {}


def source_name(kind, chat_id, user_id=None):
    key = (kind, chat_id, user_id)
    cached = _source_name_cache.get(key)
    if cached and cached[0] > time.monotonic():
        return cached[1]
    name = "Không lấy được tên"
    ttl = 60
    try:
        with ApiClient(configuration) as api_client:
            bot = MessagingApi(api_client)
            if kind == "group":
                result = bot.get_group_summary(chat_id, _request_timeout=2)
                name = result.group_name
            elif kind == "group_user":
                result = bot.get_group_member_profile(chat_id, user_id, _request_timeout=2)
                name = result.display_name
            elif kind == "room_user":
                result = bot.get_room_member_profile(chat_id, user_id, _request_timeout=2)
                name = result.display_name
            else:
                result = bot.get_profile(user_id, _request_timeout=2)
                name = result.display_name
        ttl = 3600
    except Exception:
        pass  # IDs remain available even when LINE cannot return a name.
    name = " ".join(str(name).split())
    if len(_source_name_cache) >= 512:
        _source_name_cache.pop(next(iter(_source_name_cache)))
    _source_name_cache[key] = (time.monotonic() + ttl, name)
    return name


def log_message_source(event):
    source = event.source
    group_id = getattr(source, "group_id", None)
    room_id = getattr(source, "room_id", None)
    user_id = getattr(source, "user_id", None)
    group_name = source_name("group", group_id) if group_id else (
        "Chat phòng" if room_id else "Chat riêng"
    )
    kind = "group_user" if group_id else "room_user" if room_id else "user"
    user_name = source_name(kind, group_id or room_id, user_id) if user_id else "Không có User ID"
    app.logger.warning(
        "GROUP: %s | GROUP ID: %s | ROOM ID: %s | USER: %s | USER ID: %s",
        group_name, group_id or "-", room_id or "-", user_name, user_id or "-",
    )


@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    log_message_source(event)
    if (co_flow.admin_command(event.message.text) or not event.message.text.strip().startswith(config.BOT_PREFIX)) and handle_co(event):
        return
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

    admin_commands = {"reload", "test", "testreport", "sendall", "say", "list"}

    if (
        command_name in admin_commands
        and user_id not in config.ADMIN_USER_IDS
    ):
        reply_text(event.reply_token,'Lệnh này chỉ dành cho tài khoản ADM đã được cấp quyền.')
        return

    if command_lower in {"", "help"}:
        text = (
            f"🤖 {config.BOT_NAME}\n\n"
            f"🔎 {config.BOT_PREFIX}<keyword>: tra cứu\n"
            f"📊 {config.BOT_PREFIX}testreport: gửi thử report"
        )

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



# Phiên bản báo cáo Apple: tồn kho, sức bán, doanh thu và cảnh báo.
def create_report_image():
    report = sheets.get_apple_dashboard()
    now = datetime.now(VIETNAM_TZ)
    width, row_height, top_height, bottom_height = 1700, 88, 240, 115
    height = top_height + row_height * (len(report["groups"]) + 1) + bottom_height
    image = Image.new("RGB", (width, height), "#F5F7FB")
    draw = ImageDraw.Draw(image)
    title_font = get_font(44, bold=True)
    subtitle_font = get_font(25)
    header_font = get_font(23, bold=True)
    body_font = get_font(25)
    footer_font = get_font(20)
    navy, blue, white, line, text = "#12263F", "#0068FF", "#FFFFFF", "#D8E0EA", "#172B4D"

    draw.rectangle((0, 0, width, top_height), fill=navy)
    draw.text((58, 50), "APPLE — TỒN KHO & BÁN HÀNG", font=title_font, fill=white)
    draw.text((58, 120), now.strftime("Cập nhật %d/%m/%Y - %H:%M"), font=subtitle_font, fill="#D8E8FF")
    draw.text((58, 160), f"Tồn kho: {report['inventory_updated_at']}", font=subtitle_font, fill="#D8E8FF")

    columns = [("Nhóm Apple", 58), ("Tồn", 650), ("SL bán", 865), ("Doanh thu", 1110), ("Cảnh báo", 1510)]
    y = top_height
    draw.rectangle((0, y, width, y + row_height), fill=blue)
    for label, x in columns:
        draw.text((x, y + 27), label, font=header_font, fill=white)
    y += row_height

    for index, item in enumerate(report["groups"]):
        background = white if index % 2 == 0 else "#EDF3FA"
        draw.rectangle((0, y, width, y + row_height), fill=background)
        draw.line((0, y + row_height, width, y + row_height), fill=line, width=1)
        alert_color = "#C62828" if item["alert"] != "Bình thường" else "#1B7F3A"
        draw.text((58, y + 27), item["group"], font=body_font, fill=text)
        draw.text((790, y + 27), format_number(item["inventory"]), font=body_font, fill=text, anchor="ra")
        draw.text((1005, y + 27), format_number(item["quantity"]), font=body_font, fill=text, anchor="ra")
        draw.text((1375, y + 27), format_number(item["revenue"]), font=body_font, fill=text, anchor="ra")
        draw.text((1510, y + 27), item["alert"], font=body_font, fill=alert_color)
        y += row_height

    draw.text((58, y + 36), "Cảnh báo Tồn cao: tồn >= 30 và lớn hơn 10 lần SL bán.", font=footer_font, fill="#52667A")
    filename = f"apple_dashboard_{now.strftime('%Y%m%d_%H%M%S')}_{secrets.token_urlsafe(12)}.png"
    image.save(REPORT_DIRECTORY / filename, "PNG", optimize=True)
    return filename
