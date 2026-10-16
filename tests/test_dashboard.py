from datetime import timedelta
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import sqlite3
import tempfile
from threading import Thread
import unittest

from pokeradar.core import timestamp
from pokeradar.dashboard import demo_snapshot, freshness, handler_for, render, snapshot

NOW = timestamp('2026-10-16T12:00:00Z')


class DashboardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'history.sqlite3'

    def test_missing_database_is_empty_and_not_created(self):
        html = render(snapshot(self.path), NOW)
        for phrase in ('No observations yet', 'No decisions yet', 'No dry-run alerts', 'Unknown'):
            self.assertIn(phrase, html)
        self.assertFalse(self.path.exists())

    def test_demo_pipeline_and_labels(self):
        data = demo_snapshot(NOW)
        self.assertEqual([len(data[k]) for k in ('observations', 'decisions', 'outbox')], [4, 4, 1])
        html = render(data, NOW, True)
        for phrase in ('SYNTHETIC DEMO', 'blocked', 'stock episode already alerted',
                       'Stale · 25 min old', '$100.00 USD · fixture only', 'never delivered'):
            self.assertIn(phrase, html)
        self.assertFalse(self.path.exists())

    def test_read_only_database_bytes_and_schema(self):
        # Create a real store via the existing import path, then close it before serving.
        from pokeradar.core import FixtureAdapter
        from pokeradar.store import connect, ingest
        raw = Path('fixtures/in_stock.json').read_text()
        with connect(self.path) as db:
            ingest(db, raw, FixtureAdapter().read(raw, NOW), True)
        before = self.path.read_bytes()
        names_before = list(Path(self.temp.name).iterdir())
        for _ in range(2):
            data = snapshot(self.path)
            self.assertIsNone(data['warning'])
            self.assertEqual(len(data['observations']), 1)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(list(Path(self.temp.name).iterdir()), names_before)

    def test_corrupt_and_incompatible_database(self):
        self.path.write_text('not sqlite')
        self.assertIn('could not be read', snapshot(self.path)['warning'])
        self.path.unlink()
        with sqlite3.connect(self.path) as db:
            db.execute('CREATE TABLE unrelated(value TEXT)')
        before = self.path.read_bytes()
        self.assertIn('could not be read', snapshot(self.path)['warning'])
        self.assertEqual(self.path.read_bytes(), before)

    def test_html_escaping_and_malformed_payloads(self):
        attack = '<script>alert("x")</script>'
        data = dict(observations=[dict(id=1, checked_at=attack, status=attack, payload='broken')],
                    decisions=[dict(observation_id=attack, reason=attack)],
                    outbox=[dict(observation_id=1, payload='[]')], warning=attack)
        html = render(data, NOW)
        self.assertNotIn('<script>', html)
        self.assertIn('&lt;script&gt;', html)
        self.assertIn('Malformed observation', html)
        self.assertIn('Unknown · invalid timestamp', html)
        self.assertIn('Unknown / unverified', html)
        data['observations'][0]['payload'] = json.dumps(dict(fetch_outcome=attack))
        self.assertNotIn('<script>', render(data, NOW))

    def test_invalid_unicode_and_deep_json_do_not_crash(self):
        data = dict(observations=[dict(id=1, payload='[' * 10000 + '0' + ']' * 10000)],
                    decisions=[dict(reason='bad\ud800text')],
                    outbox=[dict(payload=json.dumps(dict(rule='bad\udffftext')))])
        html = render(data, NOW)
        html.encode('utf-8')
        self.assertIn('Malformed observation', html)
        self.assertIn('bad?text', html)

    def test_incomplete_schema_shows_warning(self):
        with sqlite3.connect(self.path) as db:
            for name in ('observations', 'decisions', 'outbox'):
                db.execute(f'CREATE TABLE {name}(id INTEGER)')
        before = self.path.read_bytes()
        self.assertIn('could not be read', snapshot(self.path)['warning'])
        self.assertEqual(self.path.read_bytes(), before)

    def test_sqlite_uri_special_characters_and_bounded_rows(self):
        self.path = Path(self.temp.name) / 'history?#mode=rw.sqlite3'
        from pokeradar.store import connect
        with connect(self.path) as db:
            db.executemany('INSERT INTO observations(recorded_at,status,raw,payload) VALUES(?,?,?,?)',
                           [('now', 'unknown', '{}', '{}')] * 101)
            db.commit()
        before = self.path.read_bytes()
        data = snapshot(self.path)
        self.assertIsNone(data['warning'])
        self.assertEqual(len(data['observations']), 100)
        self.assertEqual(data['observations'][0]['id'], 101)
        self.assertEqual(self.path.read_bytes(), before)

    def test_fixture_urls_never_become_links(self):
        data = demo_snapshot(NOW)
        item = json.loads(data['observations'][0]['payload'])
        item['url'] = 'javascript:alert(1)'
        data['observations'][0]['payload'] = json.dumps(item)
        self.assertNotIn('javascript:', render(data, NOW))

    def test_freshness_boundaries_and_dynamic_aging(self):
        checked = NOW.isoformat()
        self.assertEqual(freshness(checked, NOW + timedelta(minutes=15)), 'Fresh · 15 min old')
        self.assertEqual(freshness(checked, NOW + timedelta(minutes=15, seconds=1)), 'Stale · 15 min old')
        self.assertEqual(freshness(checked, NOW - timedelta(seconds=1)), 'Invalid future time')
        for value in (None, {}, 'bad', '0001-01-01T00:00:00+01:00'):
            self.assertIn('Unknown', freshness(value, NOW))
        data = demo_snapshot(NOW)
        html = render(data, NOW + timedelta(hours=1), True)
        self.assertIn('Stale · 62 min old', html)
        self.assertIn('blocked', html)

    def test_http_routes_headers_methods_and_no_writes(self):
        server = ThreadingHTTPServer(('127.0.0.1', 0), handler_for(self.path))
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            for method, route, host, status in (
                ('GET', '/', None, 200), ('GET', '/missing', None, 404),
                ('GET', '/../../demo.sqlite3', None, 404), ('GET', '/?db=/tmp/x', None, 404),
                ('POST', '/', None, 501), ('GET', '/', 'evil.example', 403)):
                with self.subTest(method=method, route=route, host=host):
                    client = HTTPConnection('127.0.0.1', server.server_port)
                    try:
                        client.request(method, route, headers={'Host': host} if host else {})
                        response = client.getresponse()
                        self.assertEqual(response.status, status)
                        if status == 200:
                            self.assertEqual(response.getheader('Cache-Control'), 'no-store')
                            self.assertIn("frame-ancestors 'none'", response.getheader('Content-Security-Policy'))
                        response.read()
                    finally:
                        client.close()
            client = HTTPConnection('127.0.0.1', server.server_port)
            try:
                client.putrequest('GET', '/')  # Adds the legitimate Host header.
                client.putheader('Host', 'evil.example')
                client.endheaders()
                response = client.getresponse()
                self.assertEqual(response.status, 403)
                response.read()
            finally:
                client.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join()
        self.assertFalse(self.path.exists())


if __name__ == '__main__':
    unittest.main()
