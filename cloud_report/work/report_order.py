import os
"""Shared product-line and generation ordering for Apple reports."""
import re

def natural_key(name):
    return re.sub(r'\d+',lambda m:m[0].zfill(8),name.casefold())

def model_order(name,category):
    """Numeric generations within the user's explicit product-line hierarchy."""
    if category==0:
        match=re.search(r'iPhone (\d+)(e)?',name,re.I)
        if match:
            tier=0 if match[2] else 4 if 'Pro Max' in name else 3 if 'Pro' in name else 2 if 'Plus' in name else 1
            return (int(match[1]),tier,natural_key(name))
        return (0 if 'SE' in name else 1001 if 'Duo' in name else 1000,0,natural_key(name))
    if category==1:
        tier=3 if 'Pro' in name else 2 if 'Air' in name else 1 if 'Mini' in name else 0
        return tier,0,natural_key(name)
    if category==2:
        tier=0 if 'Neo' in name else 1 if 'Air' in name else 2 if 'MacBook Pro' in name else 3 if 'Mini' in name or 'mini' in name else 4
        return tier,0,natural_key(name)
    if category==3:
        tier=0 if 'SE' in name else 2 if 'Ultra' in name else 1
        generation=re.search(r'(?:SE\s*|S(?:eries)?\s*|Ultra\s*)(\d+)',name,re.I)
        return tier,int(generation[1]) if generation else 0,natural_key(name)
    if category==4:
        tier=2 if 'Max' in name else 1 if 'Pro' in name else 0
        generation=re.search(r'(\d+)',name)
        return tier,int(generation[1]) if generation else 0,natural_key(name)
    accessory_order=['Adapter Sạc','Cáp sạc','Cáp chuyển','Earpods','Apple Pencil','Mac Keyboard','iPad Keyboard','Mouse','AirTag 2','Airtag Key Ring','Ốp iPhone','Ốp iPad','Magsafe FineWoven Wallet','Dây đeo']
    return (accessory_order.index(name) if name in accessory_order else 99),0,natural_key(name)

