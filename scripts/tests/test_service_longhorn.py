import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('service_longhorn', ROOT / 'config/zabbix/manifests/assets/service_longhorn.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class Reconciliation(unittest.TestCase):
    def probe(self, status=None, error=None, remaining=30, kind='BackupTarget'):
        def get(path):
            self.assertTrue(path.endswith('/backuptargets/default'))
            if error:
                raise error
            return {'kind': kind, 'status': status}
        ctx = SimpleNamespace(now=1800000000, remaining=lambda: remaining,
                              kube=SimpleNamespace(get=get),
                              check=lambda name, bad, detail: {'name': name, 'status': int(bad), 'detail': detail})
        return module.run(ctx, {'max_sync_age_seconds': 7200})[0]

    def status(self, age):
        from datetime import datetime, timezone
        return {'ownerID': 'controller', 'lastSyncedAt': datetime.fromtimestamp(1800000000-age, timezone.utc).isoformat()}

    def test_healthy_idle_store(self):
        self.assertEqual(self.probe(self.status(1800))['status'], 0)

    def test_stalled_despite_cached_available(self):
        status = self.status(7201)
        status['available'] = True
        self.assertEqual(self.probe(status)['status'], 1)

    def test_future_timestamp(self):
        self.assertEqual(self.probe(self.status(-301))['status'], 1)

    def test_missing_malformed_and_ownerless(self):
        for status in ({}, {'lastSyncedAt': 'broken'}, {'lastSyncedAt': '2026-01-01T00:00:00', 'ownerID': 'x'}, {**self.status(60), 'ownerID': ''}):
            with self.subTest(status=status):
                self.assertEqual(self.probe(status)['status'], 1)
        self.assertEqual(self.probe(self.status(60), kind='Status')['status'], 1)

    def test_api_failure_redacted(self):
        for error in (PermissionError('403 private-token'), TimeoutError('private-url'), OSError('404 private-path')):
            result = self.probe(error=error)
            self.assertEqual(result['status'], 1)
            self.assertNotIn('private', result['detail'])

    def test_insufficient_budget(self):
        self.assertEqual(self.probe(self.status(60), remaining=5)['status'], 1)
