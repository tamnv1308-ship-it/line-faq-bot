import os
"""Product boundaries shared by overview and detailed revenue reports."""
import re
import unicodedata

GROUPING_RULE = 'apple-6-watch-bands-accessories-v2'


def is_watch_band(name):
    """Recognize standalone straps, not a watch sold with a Sport Band/Loop."""
    value = unicodedata.normalize('NFKD', str(name or '').casefold()).replace('đ', 'd')
    value = re.sub(r'\s+', ' ', ''.join(c for c in value if not unicodedata.combining(c))).strip()
    if not re.search(r'\bwatch\b|\bdong ho\b', value):
        return False
    if re.match(r'^day (?:deo\b|dong ho\b)', value):
        return True
    if re.match(r'^(?:dong ho(?: thong minh)? )?(?:apple )?watch (?:series\s*\d+|s\d+|se|ultra|\d+)\b', value):
        return False
    if re.match(r'^(?:dong ho(?: thong minh)? )?(?:apple )?watch\b', value) and re.search(r'\bgps\b|\bcellular\b', value):
        return False
    return bool(re.search(r'\b(?:band|strap|loop)\b', value))


def is_airpods(name):
    value = unicodedata.normalize('NFKD', str(name or '').casefold())
    value = ''.join(c for c in value if not unicodedata.combining(c))
    return bool(re.search(r'\bairpods\b', value))


def product_group(industry, name):
    if industry == 'Wearable' and is_watch_band(name):
        return 'accessories'
    if industry == 'Phụ kiện tiện ích':
        return 'airpods' if is_airpods(name) else 'accessories'
    return {'Điện thoại':'iphone', 'Tablet':'ipad', 'Laptop':'mac',
            'IT':'mac', 'Wearable':'watch'}[industry]
