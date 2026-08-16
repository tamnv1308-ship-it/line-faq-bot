import os


CHANNEL_ACCESS_TOKEN = os.getenv("CHANNEL_ACCESS_TOKEN", "")
CHANNEL_SECRET = os.getenv("CHANNEL_SECRET", "")

GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID", "")
GOOGLE_SERVICE_ACCOUNT = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "")

# Tự lấy link Render nếu có. Nếu report không gửi được ảnh,
# tạo Environment Variable REPORT_PUBLIC_BASE_URL trên Render.
REPORT_PUBLIC_BASE_URL = os.getenv(
    "REPORT_PUBLIC_BASE_URL",
    os.getenv("RENDER_EXTERNAL_URL", ""),
).rstrip("/")

BOT_PREFIX = "!"
CACHE_TIME = 300
BOT_NAME = "LINE FAQ BOT"

# Tab cũ dùng để tra keyword và tab DATA dùng để làm report.
FAQ_SHEET_NAME = os.getenv("FAQ_SHEET_NAME", "FAQ")
REPORT_SHEET_NAME = "DATA"

GROUPS = {
    "bot": "Ca6ebad8571ec436ed0cc4a68729d22c0",
    "test": "C4f38e1a465a6dd1b0a3cd5c175f84c62",
    "dcn": "GROUP_ID_DA_NANG",
}

JOIN_LINKS = {
    "bot": "https://line.me/ti/g/CR9UsaW2kq",
    "test": "https://line.me/ti/g/CR9UsaW2kq",
    "dn": "LINK_MOI_GROUP_DA_NANG",
}

ADMIN_USER_IDS = [
    "U60751d1a57eb4707a3dff9c06f3240a4",
    "Ud29d838c51efaecd363ff5bc9ffa2a4c",
    "U810ef43dc32d6cb1c3bb332f7aabad4c",
    "Ua7faef12dfde3213c23d01c34dfede91",
    "Uf557568065b6debd6aa5c1ced009cbd6",
]

REMINDER_SCHEDULES = [
    {
        "id": "morning",
        "hour": 8,
        "minute": 0,
        "reminders": [
            {
                "group_id": GROUPS["bot"],
                "message": (
                    "☀️ Chào buổi sáng mọi người, hẹ hẹ hẹ.\n"
                    "Chúc cả group một ngày chạy deadline té địt nhớ !!!."
                ),
            },
        ],
    },
    {
        "id": "night",
        "hour": 22,
        "minute": 0,
        "reminders": [
            {
                "group_id": GROUPS["bot"],
                "message": "🌙 Con đỗn Boa, thoát nhóm ra vào lại nhá nhanh lên nàoo!.",
            },
        ],
    },
]
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
# Lịch gửi ảnh report. Giờ theo Việt Nam.
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
