import os

CHANNEL_ACCESS_TOKEN = os.getenv("CHANNEL_ACCESS_TOKEN", "")
CHANNEL_SECRET = os.getenv("CHANNEL_SECRET", "")

GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID", "")
GOOGLE_SERVICE_ACCOUNT = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "")

BOT_PREFIX = "!"
CACHE_TIME = 300
BOT_NAME = "LINE FAQ BOT"
REMINDERS = [
    {
        "group_id": "Ca6ebad8571ec436ed0cc4a68729d22c0",
        "message": "Chào buổi sáng Group 1.\nChúc mọi người một ngày hiệu quả.",
    },
    {
        "group_id": "Ca6ebad8571ec436ed0cc4a68729d22c0",
        "message": "Chào buổi sáng Group 2.\nNội dung riêng của group 2.",
    },
    {
        "group_id": "Ca6ebad8571ec436ed0cc4a68729d22c0",
        "message": "Nội dung riêng của group 3.",
    },
    {
        "group_id": "Ca6ebad8571ec436ed0cc4a68729d22c0",
        "message": "Nội dung riêng của group 4.",
    },
    
    {
        "group_id": "Ca6ebad8571ec436ed0cc4a68729d22c0",
        "message": "Nội dung riêng của group 5.",
    },
    
    {
        "group_id": "Ca6ebad8571ec436ed0cc4a68729d22c0",
        "message": "Nội dung riêng của group 6.",
    },
    
    {
        "group_id": "Ca6ebad8571ec436ed0cc4a68729d22c0",
        "message": "Nội dung riêng của group 7.",
    },
    
    {
        "group_id": "Ca6ebad8571ec436ed0cc4a68729d22c0",
        "message": "Nội dung riêng của group 8.",
    },
        
]

ADMIN_USER_IDS = [
    "U60751d1a57eb4707a3dff9c06f3240a4"
]
