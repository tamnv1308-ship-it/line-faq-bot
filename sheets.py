import time
import gspread

from google.oauth2.service_account import Credentials

from config import GOOGLE_SHEET_ID
from config import GOOGLE_SERVICE_ACCOUNT
from config import CACHE_TIME

scope = [
    "https://www.googleapis.com/auth/spreadsheets.readonly"
]

credentials = Credentials.from_service_account_file(
    GOOGLE_SERVICE_ACCOUNT,
    scopes=scope
)

client = gspread.authorize(credentials)

_cache = {}
_last_update = 0


def load_sheet():

    global _cache
    global _last_update

    now = time.time()

    if now - _last_update < CACHE_TIME:
        return _cache

    sheet = client.open_by_key(GOOGLE_SHEET_ID)

    ws = sheet.sheet1

    rows = ws.get_all_records()

    data = {}

    for row in rows:

        keyword = str(row.get("Keyword", "")).strip().lower()

        answer = str(row.get("Answer", "")).strip()

        if keyword != "":
            data[keyword] = answer

    _cache = data

    _last_update = now

    return data


def search(keyword):

    keyword = keyword.lower()

    data = load_sheet()

    if keyword in data:
        return data[keyword]

    for key in data:

        if keyword in key:

            return data[key]

    return None


def reload():

    global _last_update

    _last_update = 0

    return load_sheet()
