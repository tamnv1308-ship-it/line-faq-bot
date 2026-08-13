import os

CHANNEL_ACCESS_TOKEN = os.getenv("CHANNEL_ACCESS_TOKEN", "")
CHANNEL_SECRET = os.getenv("CHANNEL_SECRET", "")

GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID", "")
GOOGLE_SERVICE_ACCOUNT = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "")

BOT_PREFIX = "!"
CACHE_TIME = 300
BOT_NAME = "LINE FAQ BOT"

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
                "group_id": "Ca6ebad8571ec436ed0cc4a68729d22c0",
                "message": "☀️ Chào buổi sáng mọi người, hẹ hẹ hẹ.\nChúc cả group một ngày chạy deadline té địt nhớ !!!.",
            },
        ],
    },
    {
        "id": "night",
        "hour": 22,
        "minute": 0,
        "reminders": [
            {
                "group_id": "Ca6ebad8571ec436ed0cc4a68729d22c0",
                "message": "🌙 Con đỗn Boa, thoát nhóm ra vào lại nhá nhanh lên nàoo!.",
            },
        ],
    },
]
