import os

CHANNEL_ACCESS_TOKEN = os.getenv("CHANNEL_ACCESS_TOKEN", "")
CHANNEL_SECRET = os.getenv("CHANNEL_SECRET", "")

GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID", "")
GOOGLE_SERVICE_ACCOUNT = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "")

BOT_PREFIX = "!"
CACHE_TIME = 300
BOT_NAME = "LINE FAQ BOT"
REMINDER_GROUP_ID = "Ca6ebad8571ec436ed0cc4a68729d22c0"

REMINDER_TEXT = """
Chào buổi sáng mọi người.

Chúc cả group một ngày thật nhiều năng lượng và làm việc hiệu quả.
Có gì cần tra cứu, mọi người cứ gọi em nhé.
""".strip()
