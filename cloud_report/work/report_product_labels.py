import os
"""Conservative product labels retain new Watch case and band variants."""
import re


def case_labels(bare):
    match = re.search(r'iPhone (.+)$', bare)
    if not match:
        return ('Ốp iPad' if 'iPad' in bare else 'Ốp lưng'), bare, bare
    detail = match[1].replace(' MagSafe ', ' ')
    for before, after in [('Nhựa Trong','Clear Case'),('Silicone','Silicone Case'),
                          ('TechWoven','TechWoven Case'),('Folio','Folio Case')]:
        detail = detail.replace(before,after)
    config = re.match(r'.*?Case',detail)
    return 'Ốp iPhone', config[0] if config else detail, detail


def source_fallback_labels(name, category):
    bare=re.sub(r'\s+[A-Z0-9]{5,}(?:[A-Z/]+)?$','',' '.join(name.split()))
    if bare.startswith('Ốp lưng'): return case_labels(bare)
    if 'AirPods' in bare: family='AirPods - tên gốc'
    else:
        family={'Điện thoại':'iPhone - tên gốc','Tablet':'iPad - tên gốc',
                'Laptop':'Mac - tên gốc','IT':'Mac - tên gốc',
                'Wearable':'Watch - tên gốc'}.get(category,'Phụ kiện - tên gốc')
    return family,bare,bare


def watch_labels(bare):
    match = re.fullmatch(r'(Apple Watch .*?) (\d+)mm (GPS(?: Cellular)?) (.+?) vỏ (.+?) dây (.+)', bare)
    if match:
        family, size, network, case_color, material, band = match.groups()
        family = family.replace('Series ', 'S')
        config = family + (' Cellular' if 'Cellular' in network else '') + ' ' + size + 'mm'
        # Preserve existing short Silicone labels; keep other band types explicit.
        band = re.sub(r'^Silicone\s+', '', band)
        color = case_color + (' / ' + band if band != case_color else '')
        return family, config, config + ' ' + color
    # An unfamiliar naming layout must not discard a valid sales row.
    core = re.match(r'(Apple Watch.*?)\s+(\d+)mm\b', bare)
    family = core[1].replace('Series ', 'S') if core else 'Apple Watch'
    return family, bare, bare
