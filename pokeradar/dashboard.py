"""Loopback-only, read-only dashboard. No retailer access or notification delivery."""

from contextlib import closing
from datetime import datetime, timedelta, timezone
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sqlite3

from .core import MAX_AGE, PRODUCT, SOURCE, FixtureAdapter, timestamp
from .store import connect, ingest

LIMIT = 100
FIELDS = {
    'observations': 'id,checked_at,status,payload',
    'decisions': 'id,observation_id,created_at,action,reason',
    'outbox': 'id,observation_id,payload',
}


def read_rows(connection):
    connection.row_factory = sqlite3.Row
    # One consistent read snapshot; never call the schema-initializing store connector here.
    connection.execute('BEGIN')
    try:
        return {table: [dict(row) for row in connection.execute(
            f'SELECT {FIELDS[table]} FROM {table} ORDER BY id DESC LIMIT ?', (LIMIT,))]
            for table in ('observations', 'decisions', 'outbox')}
    finally:
        connection.rollback()


def snapshot(path):
    empty = dict(observations=[], decisions=[], outbox=[], warning=None)
    try:
        if not Path(path).exists():
            return dict(empty, warning='No local database yet. Import a fixture with the CLI or launch --demo.')
        uri = Path(path).resolve().as_uri() + '?mode=ro'
        with closing(sqlite3.connect(uri, uri=True, timeout=2)) as connection:
            connection.execute('PRAGMA query_only=ON')
            data = read_rows(connection)
        return dict(data, warning=None)
    except (sqlite3.Error, OSError, ValueError):
        return dict(empty, warning='Local data could not be read. The database may be locked, malformed or incompatible. No changes were made.')


def demo_snapshot(now):
    """Generate disposable in-memory fixture history through the real pipeline."""
    with connect(':memory:') as connection:
        for minutes, state, outcome in ((25, 'sold_out', 'ok'), (10, 'in_stock', 'ok'),
                                         (8, 'in_stock', 'ok'), (2, 'unknown', 'blocked')):
            raw = json.dumps(dict(source_id=SOURCE.id, sku=PRODUCT.sku, url=PRODUCT.url,
                                  packs=36, checked_at=(now - timedelta(minutes=minutes)).isoformat(),
                                  fetch_outcome=outcome, availability=state,
                                  price_cents=10000, currency='USD', purchasable=state == 'in_stock'))
            ingest(connection, raw, FixtureAdapter().read(raw, now - timedelta(minutes=minutes)), True)
        return dict(read_rows(connection), warning=None)


def payload(row):
    try:
        value = json.loads(row.get('payload', ''))
        return value if isinstance(value, dict) else {}
    except (ValueError, TypeError, RecursionError):
        return {}


def text(value):
    value = str(value if value is not None else 'Unknown')
    # JSON can contain lone surrogates: replace invalid Unicode before HTML encoding.
    return escape(value.encode('utf-8', errors='replace').decode('utf-8'), quote=True)


def freshness(value, now):
    try:
        age = now - timestamp(value)
        if age < timedelta(0):
            return 'Invalid future time'
        return ('Fresh' if age <= MAX_AGE else 'Stale') + f' · {int(age.total_seconds() // 60)} min old'
    except (ValueError, TypeError, AttributeError, OverflowError):
        return 'Unknown · invalid timestamp'


def time_label(value):
    try:
        return timestamp(value).strftime('%Y-%m-%d %H:%M:%S UTC')
    except (ValueError, TypeError, AttributeError, OverflowError):
        return 'Unknown / invalid time'


def price(value, currency):
    if type(value) is not int or not 0 < value < 10**9 or currency != 'USD':
        return 'Unknown / unverified'
    return f'${value / 100:.2f} USD · fixture only'


def table(headers, rows, empty):
    if not rows:
        return f'<p class="empty">{text(empty)}</p>'
    return '<div class="table-wrap" tabindex="0"><table><thead><tr>' + ''.join(
        f'<th scope="col">{text(h)}</th>' for h in headers) + '</tr></thead><tbody>' + ''.join(
        '<tr>' + ''.join(f'<td>{text(cell)}</td>' for cell in row) + '</tr>' for row in rows
    ) + '</tbody></table></div>'


CSS = '''
:root{color-scheme:dark;font:16px/1.55 system-ui,sans-serif;background:#0b1220;color:#e2e8f0}
*{box-sizing:border-box}body{margin:0}main{max-width:1200px;margin:auto;padding:32px 24px 60px}
a{color:#67e8f9;text-underline-offset:4px}a:focus-visible,summary:focus-visible,.table-wrap:focus-visible{outline:3px solid #fbbf24;outline-offset:4px}
header{display:flex;justify-content:space-between;align-items:center;gap:24px}h1{font-size:2rem;letter-spacing:-.04em;margin:0}h2{font-size:1.15rem;margin:0 0 16px}p{margin:8px 0;color:#bac8dc}
nav{display:flex;gap:20px;flex-wrap:wrap;margin:24px 0}.tag{font-size:.8rem;letter-spacing:.06em;color:#fcd34d;font-weight:700}
.notice{background:#242237;border-left:4px solid #fbbf24;padding:16px 20px;margin:24px 0}.grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:16px}
.card,section{border:1px solid #29364b;border-radius:12px;background:#111c2e;padding:22px;min-width:0}section{margin-top:20px;scroll-margin-top:20px}.metric{font-size:1.3rem;color:#f8fafc;font-weight:650;overflow-wrap:anywhere}.label{font-size:.85rem;color:#a4b8d2}
.table-wrap{max-width:100%;overflow:auto}table{min-width:850px;width:100%;border-collapse:collapse;font-size:.88rem;text-align:left}th{color:#a4b8d2;font-size:.78rem;white-space:nowrap}th,td{padding:13px 12px;border-bottom:1px solid #29364b;vertical-align:top}td{min-width:90px;max-width:350px;overflow-wrap:anywhere}.empty{padding:16px;border:1px dashed #44536b;border-radius:8px}small{color:#a4b8d2}details{margin-top:12px}summary{cursor:pointer}footer{margin-top:24px;color:#a4b8d2;font-size:.85rem}
@media(max-width:700px){main{padding:20px 14px}.grid{grid-template-columns:1fr}header{align-items:flex-start}h1{font-size:1.7rem}.card,section{padding:16px}nav{gap:12px}td,th{padding:10px 8px}}
'''


def render(data, now, demo=False):
    observations, decisions, alerts = (data.get(key, []) for key in ('observations', 'decisions', 'outbox'))
    latest = observations[0] if observations else {}
    current = payload(latest)
    health = current.get('fetch_outcome', 'Unknown')
    if latest and not current:
        health = 'Malformed observation'
    fresh = freshness(latest.get('checked_at'), now) if latest else 'No observations'
    observation_rows = []
    for row in observations:
        item = payload(row)
        observation_rows.append((row.get('id'), time_label(row.get('checked_at')),
                                 row.get('status'), freshness(row.get('checked_at'), now),
                                 item.get('fetch_outcome', 'Malformed / unknown'),
                                 price(item.get('price_cents'), item.get('currency')),
                                 'Synthetic fixture' if item.get('mode') == 'fixture' else 'Unknown provenance'))
    decision_rows = [(row.get('observation_id'), time_label(row.get('created_at')), row.get('action'), row.get('reason'))
                     for row in decisions]
    alert_rows = []
    for row in alerts:
        item = payload(row)
        alert_rows.append((row.get('observation_id'), time_label(item.get('checked_at')),
                           price(item.get('price_cents'), item.get('currency')),
                           item.get('rule', 'Malformed / unknown'), 'Dry-run only · never delivered'))
    warning = f'<p class="notice">{text(data["warning"])}</p>' if data.get('warning') else ''
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>PokéRadar · Local dashboard</title><style>{CSS}</style></head>
<body><main><header><div><div class="tag">LOCAL · READ ONLY</div><h1>PokéRadar</h1></div><a href="/">Refresh view</a></header>
<div class="notice"><strong>{'SYNTHETIC DEMO · temporary in-memory data' if demo else 'OFFLINE FIXTURE HISTORY · no live inventory'}</strong><p>Not a purchase signal. Live retailer access and notifications are disabled.</p></div>
<nav aria-label="Dashboard sections"><a href="#product">Product</a><a href="#observations">Observations</a><a href="#decisions">Decisions</a><a href="#alerts">Dry-run alerts</a></nav>{warning}
<div class="grid"><div class="card"><div class="label">Latest recorded source outcome</div><div class="metric">{text(health)}</div><p>Fixture evidence only; not current retailer health.</p></div>
<div class="card"><div class="label">Freshness at page load</div><div class="metric">{text(fresh)}</div><p>Fresh means no older than 15 minutes.</p></div>
<div class="card"><div class="label">Current verified MSRP</div><div class="metric">Unknown</div><p>No authoritative price evidence recorded.</p></div></div>
<section id="product"><h2>Tracked product</h2><p class="metric">{text(PRODUCT.name)}</p><p>SKU {text(PRODUCT.sku)} · {text(SOURCE.id)} · 36 packs</p><a href="{text(PRODUCT.url)}" rel="noreferrer">Product reference</a><details><summary>Price provenance and access policy</summary><p>All displayed prices come from local fixtures, not a verified retailer feed. The demo rule uses a synthetic USD 100.00 ceiling. The historical $161.64 chat target is unverified and is not used.</p><p>{text(SOURCE.reason)}</p></details></section>
<section id="observations"><h2>Observation history</h2><p>Status is recorded at ingestion; freshness is recalculated when you load this page.</p>{table(['ID','Checked at (UTC)','Recorded status','Freshness now','Fetch outcome','Observed price','Provenance'], observation_rows, 'No observations yet. Use the CLI to import a local fixture.')}</section>
<section id="decisions"><h2>Alert decisions and suppression reasons</h2>{table(['Observation','Decided at (UTC)','Decision','Reason'], decision_rows, 'No decisions yet. Decisions are recorded by fixture imports, not this dashboard.')}</section>
<section id="alerts"><h2>Dry-run alert history</h2>{table(['Observation','Evidence time (UTC)','Fixture price','Rule','Delivery'], alert_rows, 'No dry-run alerts recorded. Nothing has been sent.')}</section>
<footer>Rendered {text(time_label(now.isoformat()))} · Newest {LIMIT} rows per history table · Manual refresh only. No polling, writes or scheduler.</footer></main></body></html>'''


def handler_for(path, demo=False):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            port = self.server.server_port
            hosts = self.headers.get_all('Host', [])
            if len(hosts) != 1 or hosts[0] not in {f'127.0.0.1:{port}', f'localhost:{port}'}:
                self.send_error(403, 'Loopback host required')
                return
            if self.path != '/':
                self.send_error(404, 'Not found')
                return
            now = datetime.now(timezone.utc)
            data = demo_snapshot(now) if demo else snapshot(path)
            body = render(data, now, demo).encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Content-Security-Policy', "default-src 'none'; style-src 'unsafe-inline'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format, *args):
            pass
    return Handler


def serve(path, port=8765, demo=False):
    if not 1 <= port <= 65535:
        raise ValueError('port must be between 1 and 65535')
    with ThreadingHTTPServer(('127.0.0.1', port), handler_for(path, demo)) as server:
        print(f'PokéRadar dashboard: http://127.0.0.1:{port} (read-only; Ctrl+C to stop)', flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
