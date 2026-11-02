import os
"""Display models for revenue tracking; never infer a generation from a SKU.

Names supplied here are already normalized by revenue_report. Storage, colour
and radio variants roll up; Mac/iPad screen sizes and explicitly named chips
remain distinct. Unknown names stay in a labelled residual, preserving totals.
"""
import re

MODEL_RULE = 'calendar-model-matrix-v1'


def screen(name, *, mac=False):
    match = re.search(r'\b(\d{2}(?:\.\d)?)\s*(?:inch\b|["″])', name)
    if not match:
        return ''
    value = match[1]
    if mac:
        value = str(int(float(value)))
    return value + '″'


def chip(name):
    match = re.search(r'\b(m\d+|a\d{2})(?:\s+(pro|max|ultra))?\b', name)
    if not match:
        return ''
    return match[1].upper() + (' ' + match[2].title() if match[2] else '')


def model_name(group, detail, name, detail_name):
    if group == 'iphone':
        match = re.search(r'\biphone\s+(\d{1,2}[ec]?(?:\s+(?:pro max|pro|plus|mini))?|duo|air|se(?:\s+\d{4})?)\b', name)
        if match:
            return 'iPhone ' + re.sub(r'(\d)([EC])\b', lambda m:m[1]+m[2].lower(), match[1].title())
    elif group == 'ipad':
        match = re.search(r'\bipad(?:\s+(air|pro|mini))?\b', name)
        if match:
            base = 'iPad' + (' ' + ('mini' if match[1]=='mini' else match[1].title()) if match[1] else '')
            processor = chip(name)
            size = screen(name)
            named_size = re.search(r'\bipad\s+(?:air|pro)\s+(11|12\.9|13)\b', name)
            if not size and named_size:
                size = named_size[1] + '″'
            generation = re.search(r'\bipad(?:\s+(?:air|pro|mini))?\s+(\d{1,2})\b', name)
            if processor:
                return ' '.join(x for x in [base, size, processor] if x)
            if size:
                year = re.search(r'\b(20\d{2})\b', name)
                return base + ' ' + size + (' ('+year[1]+')' if year else '')
            if generation:
                return ' '.join(x for x in [base, generation[1], size if size.rstrip('″') != generation[1] else ''] if x)
    elif group == 'mac':
        for word, base in [('macbook neo', 'MacBook Neo'), ('macbook air', 'MacBook Air'),
                           ('macbook pro', 'MacBook Pro'), ('mac mini', 'Mac mini'),
                           ('mac studio', 'Mac Studio'), ('imac', 'iMac')]:
            if word in name:
                processor = chip(name)
                if processor:
                    return ' '.join(x for x in [base, screen(name, mac=True), processor] if x)
        if 'studio display' in name:
            return 'Studio Display'
    elif group == 'watch':
        match = re.search(r'\bwatch\s+(?:series\s*|s)(\d+)\b', name)
        if match:
            return 'Watch S' + match[1]
        match = re.search(r'\bwatch\s+(se|ultra)(?:\s+(\d{1,4}))?\b', name)
        if match:
            return 'Watch ' + ('SE' if match[1] == 'se' else 'Ultra') + (' ' + match[2] if match[2] else '')
    elif group == 'airpods':
        match = re.search(r'\bairpods\s*(pro|max)?(?:\s*(?:gen\s*)?(\d))?\b', name)
        if match:
            base = 'AirPods' + (' ' + match[1].title() if match[1] else '')
            if match[2]:
                base += ' ' + match[2]
            elif not match[1]:
                return 'AirPods · chưa rõ thế hệ'
            return base
    elif group == 'accessories':
        # Retain the established accessory families rather than guess hardware
        # models from compatible-device names printed on cases and chargers.
        return detail_name
    return detail_name + ' · chưa tách model'
