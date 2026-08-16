import json
import re
import time
from collections import OrderedDict

import gspread
from google.oauth2.service_account import Credentials

import config


SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets.readonly",
]

_client = None
_sheet_cache = None
_sheet_cache_time = 0


def get_client():
    global _client

    if _client is not None:
        return _client

    if not config.GOOGLE_SERVICE_ACCOUNT:
        raise ValueError("Thiếu GOOGLE_SERVICE_ACCOUNT_JSON trên Render.")

    service_info = json.loads(config.GOOGLE_SERVICE_ACCOUNT)
    credentials = Credentials.from_service_account_info(
        service_info,
        scopes=SCOPES,
    )
    _client = gspread.authorize(credentials)
    return _client


def get_spreadsheet():
    if not config.GOOGLE_SHEET_ID:
        raise ValueError("Thiếu GOOGLE_SHEET_ID trên Render.")

    return get_client().open_by_key(config.GOOGLE_SHEET_ID)


def load_sheet():
    """Đọc sheet FAQ cũ: cột A là keyword, cột B là câu trả lời."""
    global _sheet_cache, _sheet_cache_time

    now = time.time()
    if (
        _sheet_cache is not None
        and now - _sheet_cache_time < config.CACHE_TIME
    ):
        return _sheet_cache

    worksheet = get_spreadsheet().worksheet(config.FAQ_SHEET_NAME)
    rows = worksheet.get_all_values()

    result = {}
    for row in rows[1:]:
        if len(row) < 2:
            continue

        keyword = row[0].strip().lower()
        answer = row[1].strip()

        if keyword and answer:
            result[keyword] = answer

    _sheet_cache = result
    _sheet_cache_time = now
    return result


def reload():
    global _sheet_cache, _sheet_cache_time
    _sheet_cache = None
    _sheet_cache_time = 0
    return load_sheet()


def search(keyword):
    data = load_sheet()
    keyword = keyword.strip().lower()

    if keyword in data:
        return data[keyword]

    for key, answer in data.items():
        if keyword in key or key in keyword:
            return answer

    return None


def parse_number(value):
    """
    Dùng cho số lượng và tiền từ Google Sheet.
    Ví dụ: 1.200.000đ -> 1200000
    """
    if value is None:
        return 0

    text = str(value).strip()
    if not text:
        return 0

    cleaned = re.sub(r"[^\d-]", "", text)
    if cleaned in ("", "-"):
        return 0

    try:
        return int(cleaned)
    except ValueError:
        return 0


def product_group(product_name):
    """Phân loại bằng nội dung cột Q."""
    name = product_name.lower()

    if "iphone" in name:
        return "iPhone"
    if "ipad" in name:
        return "iPad"
    if "mac" in name:
        return "Mac"
    if "apple watch" in name:
        return "Apple Watch"
    if "airpods" in name or "air pods" in name:
        return "AirPods"

    return "Phụ kiện còn lại"


def get_sales_report():
    """
    DATA:
    - H: trạng thái
    - Q: tên hàng, dùng lọc trùng và phân nhóm
    - V: số lượng
    - AI: doanh thu
    """
    worksheet = get_spreadsheet().worksheet(config.REPORT_SHEET_NAME)
    rows = worksheet.get_all_values()

    groups = OrderedDict(
        [
            ("iPhone", {"quantity": 0, "revenue": 0}),
            ("iPad", {"quantity": 0, "revenue": 0}),
            ("Mac", {"quantity": 0, "revenue": 0}),
            ("Apple Watch", {"quantity": 0, "revenue": 0}),
            ("AirPods", {"quantity": 0, "revenue": 0}),
            ("Phụ kiện còn lại", {"quantity": 0, "revenue": 0}),
        ]
    )

    seen_products = set()
    skipped_status = 0
    skipped_duplicate = 0

    # Bỏ hàng tiêu đề: dòng 1
    for row in rows[1:]:
        # AI là cột 35, index 34
        padded = row + [""] * max(0, 35 - len(row))

        status_h = padded[7].strip()
        product_q = padded[16].strip()
        quantity_v = parse_number(padded[21])
        revenue_ai = parse_number(padded[34])

        if status_h in {"Xuất bán nội bộ", "Xuất chuyển kho"}:
            skipped_status += 1
            continue

        # Không có tên sản phẩm thì không thể lọc trùng/phân nhóm.
        if not product_q:
            continue

        duplicate_key = product_q.casefold()
        if duplicate_key in seen_products:
            skipped_duplicate += 1
            continue

        seen_products.add(duplicate_key)

        group_name = product_group(product_q)
        groups[group_name]["quantity"] += quantity_v
        groups[group_name]["revenue"] += revenue_ai

    for data in groups.values():
        quantity = data["quantity"]
        data["average_price"] = (
            round(data["revenue"] / quantity) if quantity else 0
        )

    return {
        "groups": groups,
        "unique_products": len(seen_products),
        "skipped_status": skipped_status,
        "skipped_duplicate": skipped_duplicate,
    }
