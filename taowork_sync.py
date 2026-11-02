"""Read-only Mac report sync to the existing LINE service; no BOT imports/sends."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import ssl
import sys
import threading
import time
from urllib.parse import urlsplit
from urllib.request import Request, HTTPRedirectHandler, build_opener, HTTPSHandler

LINE_ROOT = Path('/Users/tamtam/Documents/Codex/2026-09-19/ch/outputs/line-faq-bot-mac')
SERVICE = 'https://line-faq-bot-d5wv.onrender.com'


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def credentials(root):
    values = {}
    for name in ('.env', '.env.local'):
        path = root / name
        if not path.exists():
            continue
        for line in path.read_text().splitlines():
            key, sep, value = line.partition('=')
            if sep and key.strip() in {'CO_BOT_URL', 'CO_WORKER_TOKEN'}:
                values[key.strip()] = value.strip().strip('"\'')
    # Never send this installed credential to a URL supplied by a web client.
    if values.get('CO_BOT_URL', '').rstrip('/') != SERVICE or len(values.get('CO_WORKER_TOKEN', '')) < 32:
        raise ValueError('Installed LINE connection does not match verified service')
    return values['CO_WORKER_TOKEN']


def collect():
    from business_analytics import load_business, DATABASE, fingerprint
    from revenue_report import load_revenue, TARGETS
    from apple_weeks import CALENDAR_PATH
    paths = [DATABASE, Path(str(DATABASE) + '-wal'), TARGETS, CALENDAR_PATH]
    before = fingerprint(paths)
    payload = {'schema': 1, 'analytics': load_business(), 'revenue': load_revenue()}
    if before != fingerprint(paths):
        raise ValueError('Report source changed during collection')
    return payload


def sync(dashboard, line=LINE_ROOT):
    sys.path.insert(0, str(dashboard / 'scripts'))
    token = credentials(line)
    payload = collect()
    raw = json.dumps(payload, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode()
    if len(raw) > 8 * 1024 * 1024:
        raise ValueError('Report too large')
    digest = hashlib.sha256(raw).hexdigest()
    # Read-only snapshot POST, not report.run, Telegram delivery or a CO request.
    request = Request(SERVICE + '/tao/dashboard/api/snapshot', data=raw,
                      headers={'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'})
    context = ssl.create_default_context()
    try:
        import certifi
        context.load_verify_locations(certifi.where())
    except ImportError:
        pass
    opener = build_opener(NoRedirect(), HTTPSHandler(context=context))
    with opener.open(request, timeout=30) as response:
        result = json.loads(response.read(4096))
    if result.get('sha256') != digest or result.get('schema') != 1:
        raise ValueError('Snapshot receipt mismatch')
    receipt = {'schema': 1, 'state': 'synced', 'received_at': result['received_at'],
               'sha256': digest, 'cutoff': payload['revenue']['cutoff']}
    state = dashboard / '.automation/cloud-sync-status.json'
    tmp = state.with_suffix('.tmp')
    tmp.write_text(json.dumps(receipt))
    tmp.chmod(0o600)
    os.replace(tmp, state)
    return receipt


def start(dashboard):
    config = dashboard / '.automation/cloud-sync.json'
    try:
        enabled = json.loads(config.read_text()).get('enabled') is True
    except (OSError, ValueError):
        enabled = False
    if not enabled:
        return None
    def loop():
        while True:
            try:
                sync(dashboard)
            except Exception as error:
                # Never log headers, tokens, URLs with parameters, or payloads.
                print('TáoWork cloud sync: ' + type(error).__name__, flush=True)
            time.sleep(60)
    worker = threading.Thread(target=loop, name='taowork-readonly-sync', daemon=True)
    worker.start()
    return worker


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--dashboard', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(sync(args.dashboard.resolve())))
