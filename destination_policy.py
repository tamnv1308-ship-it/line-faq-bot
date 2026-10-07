"""Destination restrictions from SHOP MẸ - KHÔNG KD ICT, Sheet1 B2:D75."""
import json
from pathlib import Path

def load_destinations():
    # Render mounts the private policy separately from the public repository.
    private = Path('/etc/secrets/blocked_destinations.json')
    path = private if private.is_file() else Path(__file__).with_name('blocked_destinations.json')
    data = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(data, dict) or not data:
        raise ValueError('Missing destination restriction policy')
    for code, shop in data.items():
        if not code.isdigit() or str(int(code)) != code or not isinstance(shop, dict) or not shop.get('name') or shop.get('group') not in {'Shop mẹ', 'Không kinh doanh ICT'}:
            raise ValueError('Invalid destination restriction policy')
    return data


BLOCKED = load_destinations()


class BlockedDestination(ValueError):
    pass


def check_destinations(payload):
    rejected = []
    for index, item in enumerate(payload.get('items') or [payload], 1):
        code = str(int(str(item['destination']).strip()))
        shop = BLOCKED.get(code)
        if shop:
            rejected.append(f"Dòng {index}: Kho nhận {code} - {shop['name']} thuộc nhóm {shop['group']}.")
    if rejected:
        raise BlockedDestination('⚠️ Không nhận yêu cầu tạo CO.\n' + '\n'.join(rejected) +
                                 '\nĐã hủy toàn bộ yêu cầu trong tin nhắn này; không tạo CO, không đưa vào hàng chờ xác nhận. Vui lòng sửa kho nhận và gửi lại.')
