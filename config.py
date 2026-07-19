import os

# ============================
# LINE BOT
# ============================

CHANNEL_ACCESS_TOKEN = os.getenv("CHANNEL_ACCESS_TOKEN", "")

CHANNEL_SECRET = os.getenv("CHANNEL_SECRET", "")

# ============================
# GOOGLE SHEET
# ============================

GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID", "")

GOOGLE_SERVICE_ACCOUNT = "service_account.json"

# ============================
# BOT
# ============================

BOT_PREFIX = "!"

CACHE_TIME = 300

BOT_NAME = "LINE FAQ BOT"
