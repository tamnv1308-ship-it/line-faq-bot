import json
import re
import time
from collections import OrderedDict

import gspread
from google.oauth2.service_account import Credentials

import config

SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
_client = None
_sheet_cache = None
_sheet_cache_time = 0

APPLE_GROUPS = [
    "iPhone", "iPad", "Mac", "Apple Watch", "AirPods", "Phụ kiện tiện ích",
]


def get_client():
    global _client
    if _client is not None:
        return _client
    if not config.GOOGLE_SERVICE_ACCOUNT:
        raise ValueError("Thiếu GOOGLE_SERVICE_ACCOUNT_JSON trên Render.")
    credentials = Credentials.from_service_account_info(
        json.loads(config.GOOGLE_SERVICE_ACCOUNT), scopes=SCOPES
    )
    _client = gspread.authorize(credentials)
    return _client


def get_spreadsheet():
    if not config.GOOGLE_SHEET_ID:
        raise ValueError("Thiếu GOOGLE_SHEET_ID trên Render.")
    return get_client().open_by_key(config.GOOGLE_SHEET_ID)


def load_sheet():
    """Đọc FAQ: cột A là keyword, cột B là câu trả lời."""
    global _sheet_cache, _sheet_cache_time
    if _sheet_cache is not None and time.time() - _sheet_cache_time < config.CACHE_TIME:
        return _sheet_cache
    rows = get_spreadsheet().worksheet(config.FAQ_SHEET_NAME).get_all_values()
    result = {}
    for row in rows[1:]:
        if len(row) >= 2 and row[0].strip() and row[1].strip():
            result[row[0].strip().lower()] = row[1].strip()
    _sheet_cache = result
    _sheet_cache_time = time.time()
    return result


def reload_sheet():
    global _sheet_cache, _sheet_cache_time
    _sheet_cache = None
    _sheet_cache_time = 0
    return load_sheet()


def search_answer(message):
    text = str(message or "").lower()
    for keyword, answer in load_sheet().items():
        if keyword in text:
            return answer
    return None


def parse_number(value):
    text = str(value or "").strip()
    if not text:
        return 0
    text = re.sub(r"[^0-9,.-]", "", text)
    if text.count(",") == 1 and text.count(".") >= 1:
        text = text.replace(",", "")
    elif text.count(",") > 1:
        text = text.replace(",", "")
    elif text.count(".") > 1:
        text = text.replace(".", "")
    try:
        return float(text.replace(",", ""))
    except ValueError:
        return 0


def product_group(product_name):
    return normalise_apple_group(product_name)


def normalise_apple_group(value):
    text = str(value or "").strip().lower()
    if "iphone" in text:
        return "iPhone"
    if "ipad" in text:
        return "iPad"
    if "apple watch" in text or text == "watch":
        return "Apple Watch"
    if "airpod" in text or "air pod" in text:
        return "AirPods"
    if "mac" in text:
        return "Mac"
    return "Phụ kiện tiện ích"


def get_sales_report():
    """Tổng hợp sheet DATA hiện có theo tên model Apple."""
    groups = OrderedDict((group, {"quantity": 0, "revenue": 0}) for group in APPLE_GROUPS)
    rows = get_spreadsheet().worksheet(config.REPORT_SHEET_NAME).get_all_values()
    seen_products = set()
    skipped_status = 0
    skipped_duplicate = 0
    for row in rows[1:]:
        status = row[7].strip().lower() if len(row) > 7 else ""
        if status in {"xuất bán nội bộ", "xuất chuyển kho"}:
            skipped_status += 1
            continue
        product = row[16].strip() if len(row) > 16 else ""
        if not product or product in seen_products:
            skipped_duplicate += 1
            continue
        seen_products.add(product)
        group = normalise_apple_group(product)
        groups[group]["quantity"] += parse_number(row[21] if len(row) > 21 else 0)
        groups[group]["revenue"] += parse_number(row[34] if len(row) > 34 else 0)
    for item in groups.values():
        item["quantity"] = int(item["quantity"])
        item["revenue"] = int(item["revenue"])
        item["average_price"] = int(item["revenue"] / item["quantity"]) if item["quantity"] else 0
    return {"groups": groups, "unique_products": len(seen_products), "skipped_status": skipped_status, "skipped_duplicate": skipped_duplicate}


def get_inventory_report():
    """Đọc bảng tồn: Cập nhật lúc | Nhóm Apple | Tồn có thể bán."""
    result = OrderedDict((group, 0) for group in APPLE_GROUPS)
    sheet_id = getattr(config, "INVENTORY_GOOGLE_SHEET_ID", "")
    sheet_name = getattr(config, "INVENTORY_SHEET_NAME", "Trang tính1")
    if not sheet_id:
        return {"groups": result, "updated_at": "Chưa kết nối bảng tồn"}
    rows = get_client().open_by_key(sheet_id).worksheet(sheet_name).get_all_values()
    if len(rows) < 2:
        return {"groups": result, "updated_at": "Chưa có dữ liệu tồn"}
    headers = [str(cell).strip().lower() for cell in rows[0]]
    try:
        group_index = headers.index("nhóm apple")
        stock_index = headers.index("tồn có thể bán")
    except ValueError as exc:
        raise ValueError("Bảng tồn cần có cột Nhóm Apple và Tồn có thể bán.") from exc
    time_index = headers.index("cập nhật lúc") if "cập nhật lúc" in headers else None
    updated_at = "Chưa có thời gian cập nhật"
    for row in rows[1:]:
        if len(row) <= max(group_index, stock_index):
            continue
        result[normalise_apple_group(row[group_index])] += parse_number(row[stock_index])
        if time_index is not None and len(row) > time_index and row[time_index]:
            updated_at = row[time_index]
    return {"groups": result, "updated_at": updated_at}


def get_apple_dashboard():
    sales = get_sales_report()
    inventory = get_inventory_report()
    dashboard = []
    high_multiplier = getattr(config, "INVENTORY_HIGH_MULTIPLIER", 10)
    for group in APPLE_GROUPS:
        sold = sales["groups"][group]["quantity"]
        revenue = sales["groups"][group]["revenue"]
        stock = int(inventory["groups"][group])
        if sold <= 0:
            alert = "Không có sức bán"
        elif stock >= 30 and stock > sold * high_multiplier:
            alert = "Tồn cao"
        else:
            alert = "Bình thường"
        dashboard.append({"group": group, "inventory": stock, "quantity": sold, "revenue": revenue, "alert": alert})
    return {"groups": dashboard, "inventory_updated_at": inventory["updated_at"], "unique_products": sales["unique_products"]}
