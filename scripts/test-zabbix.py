#!/usr/bin/env python3
import copy
import importlib.util
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('collector', ROOT / 'config/zabbix/manifests/assets/collector.py')
collector = importlib.util.module_from_spec(spec)
spec.loader.exec_module(collector)
NOW = 1780000000


class CollectorTests(unittest.TestCase):
    def setUp(self):
        self.data = {name: [] for name in collector.PATHS}
        self.policy = {'nodes': [], 'deployments': [], 'databases': [], 'probes': []}

    def checks(self):
        return {c['name']: c for c in collector.evaluate(self.data, self.policy, NOW)}

    def test_missing_expected_node_is_a_failure(self):
        self.policy['nodes'] = ['pufi']
        checks = self.checks()
        self.assertEqual(checks['Node pufi']['status'], 1)
        self.assertEqual(checks['Physical storage pufi']['status'], 1)
        self.assertEqual(checks['Node pufi memory']['status'], 1)

    def test_backup_freshness_requires_a_completed_backup(self):
        self.data['volumes'] = [{
            'metadata': {'name': 'v', 'labels': {'recurring-job-group.longhorn.io/critical': 'enabled'}},
            'status': {'state': 'attached', 'robustness': 'healthy', 'lastBackupAt': '2026-05-28T00:00:00Z',
                       'kubernetesStatus': {'namespace': 'mail', 'pvcName': 'blobs'}}}]
        self.assertEqual(self.checks()['Longhorn backup mail/blobs']['status'], 1)
        timestamp = collector.dt.datetime.fromtimestamp(NOW - 3600, collector.UTC).isoformat()
        self.data['longhorn_backups'] = [{'status': {'volumeName': 'v', 'state': 'Pending', 'backupCreatedAt': timestamp}}]
        self.assertEqual(self.checks()['Longhorn backup mail/blobs']['status'], 1)
        self.data['longhorn_backups'][0]['status']['state'] = 'Completed'
        self.assertEqual(self.checks()['Longhorn backup mail/blobs']['status'], 0)

    def test_excluded_volumes_are_not_reported_as_missing_backups(self):
        self.data['volumes'] = [{'metadata': {'name': 'media', 'labels': {
            'recurring-job-group.longhorn.io/excluded': 'enabled'}},
            'status': {'state': 'detached', 'robustness': 'unknown'}}]
        checks = self.checks()
        self.assertEqual(len(checks), 1)
        self.assertEqual(next(iter(checks.values()))['status'], 0)

    def test_excluded_marker_does_not_hide_an_active_backup_group(self):
        self.data['volumes'] = [{'metadata': {'name': 'media', 'labels': {
            'recurring-job-group.longhorn.io/excluded': 'enabled',
            'recurring-job-group.longhorn.io/default': 'enabled'}},
            'status': {'state': 'attached', 'robustness': 'healthy'}}]
        self.assertTrue(any('backup' in c and value['status'] == 1 for c, value in self.checks().items()))

    def test_cnpg_five_field_schedule_cannot_pass_as_healthy(self):
        self.data['scheduled_backups'] = [{'metadata': {'name': 'daily', 'namespace': 'db'},
                                          'spec': {'schedule': '15 3 * * *', 'cluster': {'name': 'pg'}}}]
        self.assertEqual(self.checks()['CNPG schedule db/daily']['status'], 1)
        self.data['scheduled_backups'][0]['spec']['schedule'] = '0 15 3 * * *'
        self.assertEqual(self.checks()['CNPG schedule db/daily']['status'], 0)

    def test_failed_or_missing_archive_condition_is_visible(self):
        self.policy['databases'] = [['db', 'pg']]
        self.data['clusters'] = [{'metadata': {'name': 'pg', 'namespace': 'db'}, 'spec': {'instances': 2},
                                 'status': {'readyInstances': 2, 'conditions': [{'type': 'Ready', 'status': 'True'}]}}]
        self.assertEqual(self.checks()['CNPG health db/pg']['status'], 0)
        self.assertEqual(self.checks()['CNPG ContinuousArchiving db/pg']['status'], 1)
        self.assertEqual(self.checks()['CNPG backup freshness db/pg']['status'], 1)

    def test_api_error_cannot_be_reported_as_an_all_clear(self):
        class BrokenKube:
            def items(self, path):
                raise PermissionError('forbidden')
        result = collector.collect(BrokenKube(), self.policy)
        errors = [c for c in result['checks'] if c['name'].startswith('Collector API')]
        self.assertEqual(len(errors), len(collector.PATHS))
        self.assertTrue(all(c['status'] == 1 for c in errors))

    def test_kubernetes_quantity_units(self):
        self.assertEqual(collector.quantity('16100Mi'), 16100 * 1024**2)
        self.assertEqual(collector.quantity('200000000n'), .2)


if __name__ == '__main__':
    unittest.main()
