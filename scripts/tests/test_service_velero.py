import copy
import importlib.util
import json
from pathlib import Path
import unittest
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[2]
ASSETS = ROOT / 'config/zabbix/manifests/assets'
spec = importlib.util.spec_from_file_location('service_velero', ASSETS / 'service_velero.py')
service = importlib.util.module_from_spec(spec)
spec.loader.exec_module(service)


def ts(value):
    return datetime.fromtimestamp(value, timezone.utc).isoformat()


class Context:
    now = service.timestamp('2026-10-08T12:00:00Z')
    def __init__(self, responses):
        self.responses = responses
        self.kube = self
        self.paths = []
    def remaining(self):
        return 30
    def get(self, path):
        self.paths.append(path)
        value = self.responses[path.split('/')[-1].split('?')[0]]
        if isinstance(value, Exception):
            raise value
        return value
    def check(self, name, bad, detail, severity=3, **kwargs):
        return dict(name=name, status=int(bad), detail=detail, severity=severity, **kwargs)


class VeleroTests(unittest.TestCase):
    def setUp(self):
        self.config = json.loads((ASSETS / 'service_velero.json').read_text())
        self.name = 'velero-daily-resources'
        self.schedule = {'metadata': {'name': self.name, 'creationTimestamp': '2025-01-01T00:00:00Z'},
                         'spec': {'schedule': '0 4 * * *'}, 'status': {'phase': 'Enabled'}}
        self.backup = {'metadata': {'creationTimestamp': '2026-10-08T04:00:58Z',
                                   'labels': {'velero.io/schedule-name': self.name}},
                       'status': {'phase': 'Completed', 'startTimestamp': '2026-10-08T04:00:58Z',
                                  'completionTimestamp': '2026-10-08T04:01:28Z'}}
        self.ctx = Context({'default': {'status': {'phase': 'Available', 'lastValidationTime': ts(Context.now - 60)}},
                            'schedules': {'items': [self.schedule]}, 'backups': {'items': [self.backup]}})
    def run_checks(self):
        return service.run(self.ctx, self.config)
    def test_paused_failed_schedule_does_not_prove_backup_recovery(self):
        self.backup['status']['phase'] = 'Failed'
        self.assertEqual(self.run_checks()[1]['status'], 1)
        self.schedule['spec']['paused'] = True
        row = self.run_checks()[1]
        self.assertEqual(row['observation'], 'unknown')
        self.assertEqual(row['status'], 0)
        self.schedule['spec']['paused'] = False
        self.backup['status']['phase'] = 'Completed'
        self.assertEqual(self.run_checks()[1]['observation'], 'known')

    def test_healthy(self):
        self.assertEqual([0, 0], [x['status'] for x in self.run_checks()])
        self.assertEqual(3, len(self.ctx.paths))
    def test_storage_unavailable_and_stale(self):
        for status in ({'phase': 'Unavailable'}, {'phase': 'Available', 'lastValidationTime': ts(Context.now - 901)}):
            self.ctx.responses['default']['status'] = status
            self.assertEqual(1, self.run_checks()[0]['status'])
    def test_failure_states(self):
        for phase in ('Failed', 'PartiallyFailed', 'FailedValidation', 'InProgress', 'Unknown'):
            self.backup['status']['phase'] = phase
            self.assertEqual(1, self.run_checks()[1]['status'])
    def test_previous_success_does_not_hide_failure(self):
        prior = copy.deepcopy(self.backup)
        prior['metadata']['creationTimestamp'] = '2026-10-07T04:00:00Z'
        self.backup['status']['phase'] = 'PartiallyFailed'
        self.ctx.responses['backups']['items'].append(prior)
        self.assertEqual(1, self.run_checks()[1]['status'])
    def test_daily_grace_boundary(self):
        self.ctx.now = service.timestamp('2026-10-08T05:59:59Z')
        self.backup['metadata']['creationTimestamp'] = '2026-10-07T04:00:00Z'
        self.backup['status'].update(startTimestamp='2026-10-07T04:00:00Z', completionTimestamp='2026-10-07T04:01:00Z')
        self.assertEqual(0, self.run_checks()[1]['status'])
        self.ctx.now += 1
        self.assertEqual(1, self.run_checks()[1]['status'])
    def test_old_backup_completing_today_not_fresh(self):
        self.backup['status']['startTimestamp'] = '2026-10-07T04:00:00Z'
        self.assertEqual(1, self.run_checks()[1]['status'])
    def test_paused_missing_and_intentionally_absent(self):
        self.schedule['spec']['paused'] = True
        self.ctx.responses['backups']['items'] = []
        self.assertEqual(0, self.run_checks()[1]['status'])
        self.ctx.responses['schedules']['items'] = []
        self.assertEqual(1, self.run_checks()[1]['status'])
        self.config['daily_schedules'] = {}
        self.assertEqual(0, self.run_checks()[1]['status'])
    def test_new_schedule_waits_until_first_due(self):
        self.schedule['metadata']['creationTimestamp'] = '2026-10-08T07:00:00Z'
        self.ctx.responses['backups']['items'] = []
        self.assertEqual(0, self.run_checks()[1]['status'])
    def test_cron_mismatch_and_validation_failure(self):
        self.schedule['spec']['schedule'] = '0 4 * * 0'
        self.assertEqual(1, self.run_checks()[1]['status'])
        self.schedule['spec']['schedule'] = '0 4 * * *'
        self.schedule['status']['phase'] = 'FailedValidation'
        self.assertEqual(1, self.run_checks()[1]['status'])
    def test_malformed_unauthorized_timeout_and_pagination_fail(self):
        for response in ({}, {'items': [], 'metadata': {'continue': 'more'}}, PermissionError('private'), TimeoutError('private')):
            self.ctx.responses['backups'] = response
            with self.assertRaises((ValueError, PermissionError, TimeoutError)):
                self.run_checks()
    def test_expired_future_and_missing_completion(self):
        self.backup['status']['expiration'] = ts(Context.now)
        self.assertEqual(1, self.run_checks()[1]['status'])
        del self.backup['status']['expiration']
        self.backup['status']['completionTimestamp'] = ts(Context.now + 301)
        self.assertEqual(1, self.run_checks()[1]['status'])
        del self.backup['status']['completionTimestamp']
        with self.assertRaises(KeyError):
            self.run_checks()
    def test_deadline_prevents_further_reads(self):
        self.ctx.remaining = lambda: 0
        with self.assertRaises(TimeoutError):
            self.run_checks()
        self.assertEqual([], self.ctx.paths)


if __name__ == '__main__':
    unittest.main()
