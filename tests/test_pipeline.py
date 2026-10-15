import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

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
        cases = [({'availability': 'sold_out'}, 'sold_out', 'fixture normalized'),
                 ({'availability': 'preorder'}, 'preorder', 'fixture normalized'),
                 ({'availability': 'unknown'}, 'unknown', 'fixture normalized'),
                 *[({'fetch_outcome': state}, state, 'source access failure')
                   for state in ('blocked', 'rate_limited', 'error')],
                 *[(change, 'unknown', 'product identity mismatch') for change in
                   ({'sku': 'wrong'}, {'packs': 6}, {'url': 'https://example.com'},
                    {'source_id': 'other'})],
                 *[({'price_cents': price}, 'in_stock', 'price or currency uncertain')
                   for price in (None, True, 100.0, -1)],
                 ({'price_cents': 10001}, 'in_stock', 'above synthetic demo target'),
                 ({'currency': 'CAD'}, 'in_stock', 'price or currency uncertain'),
                 ({'purchasable': 'true'}, 'in_stock', 'positive purchasability evidence missing'),
                 ({'checked_at': '2026-10-15T11:00:00Z'}, 'stale', 'observation older than 15 minutes'),
                 ({'checked_at': '2026-10-16T12:00:00Z'}, 'error', 'future timestamp')]
        for changes, expected, reason in cases:
            with self.subTest(changes=changes), connect(':memory:') as connection:
                raw = json.dumps(dict(BASE, **changes))
                result = ingest(connection, raw, FixtureAdapter().read(raw, NOW), True)
                self.assertEqual(result['status'], expected)
                self.assertEqual(result['action'], 'suppressed')
                self.assertEqual(result['reason'], reason)
                self.assertEqual(connection.execute('SELECT COUNT(*) FROM outbox').fetchone()[0], 0)
        # Same timestamp and rule on another fresh store must pass when evidence is valid.
        with connect(':memory:') as connection:
            raw = json.dumps(BASE)
            result = ingest(connection, raw, FixtureAdapter().read(raw, NOW), True)
            self.assertEqual(result['action'], 'dry_run_alert')
            self.assertEqual(result['reason'], 'synthetic USD 100.00 fixture rule satisfied')
            self.assertEqual(connection.execute('SELECT COUNT(*) FROM outbox').fetchone()[0], 1)

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

    def test_append_only_audit_tables(self):
        self.put()
        with connect(self.db) as connection:
            for table in ('observations', 'decisions', 'outbox'):
                with self.assertRaises(sqlite3.IntegrityError):
                    connection.execute(f'DELETE FROM {table}')
                connection.rollback()
                with self.assertRaises(sqlite3.IntegrityError):
                    connection.execute(f'UPDATE {table} SET id=id')
                connection.rollback()

    def test_late_failure_rolls_back_all_tables_then_retry(self):
        self.put()
        self.put(availability='sold_out')
        tables = ('observations', 'decisions', 'monitor_state', 'outbox')
        raw = json.dumps(dict(BASE, checked_at='2026-10-15T12:02:00Z'))
        observation = FixtureAdapter().read(raw, timestamp('2026-10-15T12:03:00Z'))
        with connect(self.db) as connection:
            def snapshot():
                return {table: [tuple(row) for row in connection.execute(f'SELECT * FROM {table}')]
                        for table in tables}
            before = snapshot()
            # AFTER the final INSERT: observation, outbox and state writes have all run.
            connection.execute("""CREATE TEMP TRIGGER fail_last_write AFTER INSERT ON decisions
                BEGIN SELECT RAISE(ABORT, 'injected late failure'); END""")
            with self.assertRaisesRegex(sqlite3.IntegrityError, 'injected late failure'):
                ingest(connection, raw, observation, True)
            self.assertFalse(connection.in_transaction)
            self.assertEqual(snapshot(), before)
            connection.execute('DROP TRIGGER fail_last_write')
        # Retry through a new connection to prove persisted state was also restored.
        with connect(self.db) as connection:
            self.assertEqual(ingest(connection, raw, observation, True)['action'], 'dry_run_alert')
            self.assertEqual(ingest(connection, raw, observation, True)['action'], 'suppressed')
            state = connection.execute('SELECT armed,episode FROM monitor_state').fetchone()
            self.assertEqual(tuple(state), (0, 1))
            events = [json.loads(row[0]) for row in connection.execute('SELECT payload FROM outbox')]
            self.assertEqual([event['episode'] for event in events], [0, 1])
            self.assertEqual(connection.execute('SELECT COUNT(*) FROM observations').fetchone()[0], 4)
            self.assertEqual(connection.execute('SELECT COUNT(*) FROM decisions').fetchone()[0], 4)

    def test_timestamp_utc_overflow_is_validation_error(self):
        for value in ('0001-01-01T00:00:00+01:00', '9999-12-31T23:59:59-01:00'):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, 'supported UTC range'):
                    timestamp(value)
                raw = json.dumps(dict(BASE, checked_at=value))
                observation = FixtureAdapter().read(raw, NOW)
                self.assertEqual(observation['status'], 'error')
                self.assertEqual(observation['reason'], 'malformed fixture')
                self.assertIsNone(observation['checked_at'])
                fixture = Path(self.temp.name) / 'boundary.json'
                fixture.write_text(raw)
                command = [sys.executable, '-m', 'pokeradar', '--db', str(self.db),
                           'import', str(fixture), '--demo-rule']
                imported = subprocess.run(command, capture_output=True, text=True, check=True)
                self.assertEqual(json.loads(imported.stdout)['status'], 'error')
                result = subprocess.run(command + ['--now', value], capture_output=True, text=True)
                self.assertEqual(result.returncode, 2)
                self.assertIn('--now', result.stderr)
                self.assertNotIn('Traceback', result.stderr)
        self.assertEqual(self.count('observations'), 2)
        self.assertEqual(self.count('outbox'), 0)

    def test_newer_access_failure_blocks_older_stock(self):
        for outcome in ('blocked', 'error'):
            with self.subTest(outcome=outcome), connect(':memory:') as connection:
                def put(**changes):
                    raw = json.dumps(dict(BASE, **changes))
                    return ingest(connection, raw, FixtureAdapter().read(
                        raw, timestamp('2026-10-15T12:10:00Z')), True)
                put(fetch_outcome=outcome, checked_at='2026-10-15T12:05:00Z')
                older = put(checked_at='2026-10-15T12:04:00Z')
                self.assertEqual(older['action'], 'suppressed')
                self.assertEqual(older['reason'], 'duplicate or out-of-order timestamp')
                self.assertEqual(connection.execute('SELECT COUNT(*) FROM outbox').fetchone()[0], 0)
                self.assertEqual(put(checked_at='2026-10-15T12:06:00Z')['action'], 'dry_run_alert')

    def test_equivalent_timezone_timestamps_are_duplicates(self):
        self.put()
        result = self.put(availability='sold_out', checked_at='2026-10-15T14:00:00+02:00')
        self.assertEqual(result['reason'], 'duplicate or out-of-order timestamp')
        self.assertEqual(self.put()['reason'], 'stock episode already alerted')
        self.assertEqual(self.count('outbox'), 1)

    def test_fractional_seconds_ordering(self):
        self.put(checked_at='2026-10-15T12:00:00Z')
        self.put(availability='sold_out', checked_at='2026-10-15T12:00:00.000001Z')
        self.assertEqual(self.put(checked_at='2026-10-15T12:00:00.000002Z')['action'], 'dry_run_alert')
        old = self.put(availability='sold_out', checked_at='2026-10-15T12:00:00.000001Z')
        self.assertEqual(old['reason'], 'duplicate or out-of-order timestamp')
        self.assertEqual(self.put(checked_at='2026-10-15T12:00:00.1Z')['reason'], 'stock episode already alerted')
        same = self.put(availability='sold_out', checked_at='2026-10-15T12:00:00.100000Z')
        self.assertEqual(same['reason'], 'duplicate or out-of-order timestamp')
        self.assertEqual(self.count('outbox'), 2)

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

    def test_concurrent_restock_transitions(self):
        self.put()
        sold_out = Path(self.temp.name) / 'sold_out.json'
        restocked = Path(self.temp.name) / 'restocked.json'
        sold_out.write_text(json.dumps(dict(BASE, availability='sold_out',
                                            checked_at='2026-10-15T12:01:00Z')))
        restocked.write_text(json.dumps(dict(BASE, checked_at='2026-10-15T12:02:00Z')))

        def wave(fixtures):
            processes = [subprocess.Popen(
                [sys.executable, '-m', 'pokeradar', '--db', str(self.db), 'import',
                 str(fixture), '--demo-rule', '--now', '2026-10-15T12:03:00Z'],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for fixture in fixtures]
            actions = []
            for process in processes:
                stdout, stderr = process.communicate(timeout=15)
                self.assertEqual(process.returncode, 0, stderr)
                actions.append(json.loads(stdout)['action'])
            return actions

        # Duplicate sold-out reports must increment the episode exactly once.
        self.assertEqual(wave([sold_out] * 4), ['suppressed'] * 4)
        # Mix restock reports with late sold-out replays under competing processes.
        self.assertEqual(wave([restocked, sold_out] * 4).count('dry_run_alert'), 1)
        with connect(self.db) as connection:
            state = connection.execute('SELECT armed,episode FROM monitor_state').fetchone()
            self.assertEqual(tuple(state), (0, 1))
        self.assertEqual(self.count('outbox'), 2)
        self.assertEqual(self.count('observations'), 13)
        self.assertEqual(self.count('decisions'), 13)


if __name__ == '__main__':
    unittest.main()
