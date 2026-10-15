import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from pokeradar.core import FixtureAdapter, LiveAdapter, PRODUCT, timestamp
from pokeradar.store import connect, ingest

BASE = json.loads(Path('fixtures/in_stock.json').read_text())
NOW = timestamp('2026-10-15T12:01:00Z')


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = Path(self.temp.name) / 'test.sqlite3'
        self.minute = 0

    def put(self, demo=True, raw=None, **changes):
        data = dict(BASE, checked_at=f'2026-10-15T12:{self.minute:02}:00Z')
        self.minute += 1
        data.update(changes)
        raw = json.dumps(data) if raw is None else raw
        now = timestamp('2026-10-15T12:10:00Z')
        with connect(self.db) as connection:
            return ingest(connection, raw, FixtureAdapter().read(raw, now), demo)

    def count(self, table):
        with connect(self.db) as connection:
            return connection.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]

    def test_stock_transitions_and_restart(self):
        # Every put opens a new connection: state must survive closing the process store.
        self.assertEqual(self.put()['action'], 'dry_run_alert')
        self.assertEqual(self.put()['action'], 'suppressed')
        self.put(availability='sold_out', purchasable=False)
        self.assertEqual(self.put()['action'], 'dry_run_alert')
        self.assertEqual(self.count('outbox'), 2)
        self.assertEqual(self.count('observations'), 4)
        self.assertEqual(self.count('decisions'), 4)

    def test_uncertain_states_never_rearm(self):
        self.put()
        for changes in ({'fetch_outcome': 'blocked'}, {'fetch_outcome': 'rate_limited'},
                        {'fetch_outcome': 'error'}, {'availability': 'unknown'},
                        {'availability': 'preorder'}, {'price_cents': None},
                        {'availability': 'sold_out', 'packs': 6},
                        {'availability': 'sold_out', 'checked_at': '2026-10-14T00:00:00Z'}):
            self.assertEqual(self.put(**changes)['action'], 'suppressed')
        self.assertEqual(self.put()['action'], 'suppressed')
        self.assertEqual(self.count('outbox'), 1)

    def test_negative_matrix(self):
        cases = [({'availability': 'sold_out'}, 'sold_out'),
                 ({'availability': 'preorder'}, 'preorder'),
                 ({'availability': 'unknown'}, 'unknown'),
                 ({'fetch_outcome': 'blocked'}, 'blocked'),
                 ({'fetch_outcome': 'rate_limited'}, 'rate_limited'),
                 ({'fetch_outcome': 'error'}, 'error'),
                 ({'sku': 'wrong'}, 'unknown'), ({'packs': 6}, 'unknown'),
                 ({'url': 'https://example.com'}, 'unknown'),
                 ({'source_id': 'other'}, 'unknown'),
                 ({'price_cents': None}, 'in_stock'),
                 ({'price_cents': True}, 'in_stock'),
                 ({'price_cents': 100.0}, 'in_stock'),
                 ({'price_cents': -1}, 'in_stock'),
                 ({'price_cents': 10001}, 'in_stock'),
                 ({'currency': 'CAD'}, 'in_stock'),
                 ({'purchasable': 'true'}, 'in_stock'),
                 ({'checked_at': '2026-10-15T11:00:00Z'}, 'stale'),
                 ({'checked_at': '2026-10-16T12:00:00Z'}, 'error')]
        for changes, expected in cases:
            with self.subTest(changes=changes):
                raw = json.dumps(dict(BASE, **changes))
                observation = FixtureAdapter().read(raw, NOW)
                with connect(self.db) as connection:
                    result = ingest(connection, raw, observation, True)
                self.assertEqual(result['status'], expected)
                self.assertEqual(result['action'], 'suppressed')
        self.assertEqual(self.count('outbox'), 0)

    def test_malformed(self):
        for raw in ('<html>captcha</html>', '{}', 'null', '[]', '{',
                    json.dumps(dict(BASE, checked_at='not-a-date')),
                    json.dumps(dict(BASE, checked_at='2026-10-15T12:00:00')),
                    json.dumps(dict(BASE, availability=[]))):
            with self.subTest(raw=raw):
                self.assertEqual(self.put(raw=raw)['status'], 'error')
        self.assertEqual(self.count('outbox'), 0)

    def test_unverified_price_rule(self):
        self.assertIsNone(PRODUCT.msrp_cents)
        self.assertEqual(self.put(demo=False)['action'], 'suppressed')
        self.assertEqual(self.count('outbox'), 0)
        self.assertEqual(self.put()['action'], 'dry_run_alert')

    def test_old_sold_out_cannot_rearm(self):
        self.put(checked_at='2026-10-15T12:05:00Z')
        self.put(availability='sold_out', checked_at='2026-10-15T12:04:00Z')
        self.assertEqual(self.put(checked_at='2026-10-15T12:06:00Z')['action'], 'suppressed')
        self.assertEqual(self.count('outbox'), 1)

    def test_freshness_boundary(self):
        for instant, status in [('2026-10-15T12:15:00Z', 'in_stock'),
                                ('2026-10-15T12:15:01Z', 'stale')]:
            self.assertEqual(FixtureAdapter().read(json.dumps(BASE), timestamp(instant))['status'], status)

    def test_append_only_and_atomic_rollback(self):
        self.put()
        with connect(self.db) as connection:
            for table in ('observations', 'decisions', 'outbox'):
                with self.assertRaises(sqlite3.IntegrityError):
                    connection.execute(f'DELETE FROM {table}')
                connection.rollback()
                with self.assertRaises(sqlite3.IntegrityError):
                    connection.execute(f'UPDATE {table} SET id=id')
                connection.rollback()
            with patch('pokeradar.store.eligible', side_effect=RuntimeError('test crash')):
                with self.assertRaises(RuntimeError):
                    ingest(connection, json.dumps(BASE), FixtureAdapter().read(json.dumps(BASE), NOW), True)
        self.assertEqual(self.count('observations'), 1)
        self.assertEqual(self.count('decisions'), 1)

    def test_live_adapter_has_no_network(self):
        with self.assertRaises(PermissionError):
            LiveAdapter().read('', NOW)

    def test_cli_process_restart(self):
        command = [sys.executable, '-m', 'pokeradar', '--db', str(self.db), 'import',
                   'fixtures/in_stock.json', '--demo-rule', '--now', '2026-10-15T12:01:00Z']
        first = subprocess.run(command, check=True, capture_output=True, text=True)
        second = subprocess.run(command, check=True, capture_output=True, text=True)
        self.assertEqual(json.loads(first.stdout)['action'], 'dry_run_alert')
        self.assertEqual(json.loads(second.stdout)['action'], 'suppressed')
        self.assertEqual(self.count('outbox'), 1)
        for name in ('history', 'decisions', 'alerts', 'registry'):
            result = subprocess.run(command[:5] + [name], check=True, capture_output=True, text=True)
            self.assertTrue(json.loads(result.stdout))
        result = subprocess.run(command[:5] + ['live'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn('not implemented', result.stderr)

    def test_concurrent_cli_imports(self):
        command = [sys.executable, '-m', 'pokeradar', '--db', str(self.db), 'import',
                   'fixtures/in_stock.json', '--demo-rule', '--now', '2026-10-15T12:01:00Z']
        processes = [subprocess.Popen(command, stdout=subprocess.PIPE,
                                      stderr=subprocess.PIPE, text=True) for _ in range(4)]
        results = []
        for process in processes:
            stdout, stderr = process.communicate(timeout=15)
            self.assertEqual(process.returncode, 0, stderr)
            results.append(json.loads(stdout)['action'])
        self.assertEqual(results.count('dry_run_alert'), 1)
        self.assertEqual(self.count('observations'), 4)
        self.assertEqual(self.count('outbox'), 1)


if __name__ == '__main__':
    unittest.main()
