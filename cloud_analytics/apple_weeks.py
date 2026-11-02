import os
"""Apple weeks anchored to the user's checked Qúy calendar, not ISO weeks."""
from datetime import date, timedelta
from pathlib import Path
import json

APPLE_WEEK_RULE = 'apple-week-sales-v1'
CALENDAR_PATH = Path(os.getenv('TAOWORK_DATA_DIR', '/var/data/taowork')) / 'settings/apple-calendar.json'


def load_calendar(path=CALENDAR_PATH):
    data = json.loads(path.read_text())
    if data.get('schema') != 1 or data.get('week_starts_on') != 'Sunday':
        raise ValueError('Invalid Apple calendar')
    seen = set()
    previous_end = None
    for item in data['quarters']:
        start, end = date.fromisoformat(item['start']), date.fromisoformat(item['end'])
        identity = f"Q{item['quarter']}Y{item['year'] % 100}"
        if (item['id'] != identity or identity in seen or item['quarter'] not in range(1, 5)
                or item['weeks'] not in (13, 14) or start.weekday() != 6
                or end != start + timedelta(days=item['weeks'] * 7 - 1)
                or previous_end is not None and start != previous_end + timedelta(days=1)):
            raise ValueError('Invalid Apple quarter boundaries')
        seen.add(identity)
        previous_end = end
    if not seen:
        raise ValueError('Empty Apple calendar')
    return data


def build_apple_weeks(cutoff, complete, keys, total, calendar=None):
    calendar = calendar or load_calendar()
    if not any(q['start'] <= cutoff.isoformat() <= q['end'] for q in calendar['quarters']):
        raise ValueError('Apple calendar does not cover the sales cutoff')

    def period(first, last):
        through = min(last, cutoff)
        elapsed = max(0, (through - first).days + 1)
        covered = sum((first + timedelta(days=i)).isoformat() in complete for i in range(elapsed))
        state = ('future' if not elapsed else 'missing' if covered != elapsed
                 else 'partial' if through < last else 'complete')
        valid = state in ('partial', 'complete')
        return {'start': first.isoformat(), 'end': last.isoformat(),
                'through': through.isoformat() if elapsed else None,
                'elapsed_days': elapsed, 'covered_days': covered,
                'calendar_days': (last - first).days + 1, 'state': state,
                'values': {key: {
                    'revenue': float(total('system', key, first, through)) if valid else None,
                    'quantity': int(total('system', key, first, through, quantity=True)) if valid else None
                } for key in keys}}

    quarters = []
    for item in calendar['quarters']:
        if item['start'] > cutoff.isoformat() or item['end'] < min(complete):
            continue
        start, end = date.fromisoformat(item['start']), date.fromisoformat(item['end'])
        weeks = []
        for index in range(item['weeks']):
            first = start + timedelta(days=index * 7)
            weeks.append({'id': f"Q{item['quarter']}W{index + 1}Y{item['year'] % 100}",
                          'week': index + 1, **period(first, first + timedelta(days=6))})
        quarters.append({**item, 'weeks': weeks, 'total': period(start, end)})
    return {'rule': APPLE_WEEK_RULE, 'source': calendar['source'], 'quarters': quarters}
