import time
import gspread
import json

from google.oauth2.service_account import Credentials
from gspread.exceptions import WorksheetNotFound
from config import GOOGLE_SHEET_ID
from config import GOOGLE_SERVICE_ACCOUNT
from config import CACHE_TIME

scope = [
    "https://www.googleapis.com/auth/spreadsheets"
]

credentials = Credentials.from_service_account_info(
    json.loads(GOOGLE_SERVICE_ACCOUNT),
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
    # ==============================
# USERS SHEET
# ==============================

def get_users_sheet():

    sheet = client.open_by_key(GOOGLE_SHEET_ID)

    try:
        return sheet.worksheet("Users")

    except WorksheetNotFound:

        ws = sheet.add_worksheet(
            title="Users",
            rows=1000,
            cols=2
        )

        ws.update("A1:B1", [["DisplayName", "UserId"]])

        return ws


def save_user(display_name, user_id):

    if not display_name or not user_id:
        return

    ws = get_users_sheet()

    rows = ws.get_all_records()

    for idx, row in enumerate(rows, start=2):

        if row.get("UserId") == user_id:

            ws.update(
                f"A{idx}:B{idx}",
                [[display_name, user_id]]
            )

            return

    ws.append_row([display_name, user_id])


def get_user_id(display_name):

    ws = get_users_sheet()

    rows = ws.get_all_records()

    for row in rows:

        if row["DisplayName"].strip().lower() == display_name.strip().lower():

            return row["UserId"]

    return None
