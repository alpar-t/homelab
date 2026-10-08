#!/usr/bin/env python3
import copy
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'config/zabbix/manifests/assets'))
spec = importlib.util.spec_from_file_location('collector', ROOT / 'config/zabbix/manifests/assets/collector.py')
collector = importlib.util.module_from_spec(spec)
spec.loader.exec_module(collector)
spec = importlib.util.spec_from_file_location('bootstrap', ROOT / 'scripts/bootstrap-zabbix.py')
bootstrap = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bootstrap)
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

    def test_healthy_pod_keeps_its_check_and_emits_recovery(self):
        pod = {'metadata': {'name': 'app-1', 'namespace': 'test',
                           'creationTimestamp': '2020-01-01T00:00:00Z'},
               'status': {'conditions': [{'type': 'Ready', 'status': 'False'}]}}
        self.data['pods'] = [pod]
        failed = self.checks()['Pod test/app-1']
        pod['status']['conditions'][0]['status'] = 'True'
        recovered = self.checks()['Pod test/app-1']
        self.assertEqual(failed['id'], recovered['id'])
        self.assertEqual((failed['status'], recovered['status']), (1, 0))

    def test_api_checks_emit_healthy_samples_after_failure(self):
        class Kube:
            broken = True

            def items(self, path):
                if self.broken:
                    raise PermissionError('forbidden')
                return []

        kube = Kube()
        before = collector.collect(kube, self.policy)
        kube.broken = False
        after = collector.collect(kube, self.policy)
        metric = lambda result: next(c for c in result['checks'] if c['name'] == 'Collector API metrics')
        self.assertEqual(metric(before)['id'], metric(after)['id'])
        self.assertEqual((metric(before)['status'], metric(after)['status']), (1, 0))

    def test_retired_pod_recovery_survives_restart_and_api_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'pods.json'
            lifecycle = collector.PodCheckLifecycle(path)
            failed = collector.check('Pod test/old', 'cluster', True, 'NotReady', 3)
            lifecycle.reconcile([failed], True, NOW)
            lifecycle = collector.PodCheckLifecycle(path)
            self.assertEqual(lifecycle.reconcile([], False, NOW + 60)[0]['status'], 1)
            retired = lifecycle.reconcile([], True, NOW + 120)[0]
            self.assertEqual(retired['status'], 0)
            self.assertIn('retired', retired['detail'])
            self.assertEqual(lifecycle.reconcile([], False, NOW + 150)[0]['status'], 0)
            for minute in range(3, 8):
                self.assertEqual(lifecycle.reconcile([], True, NOW + minute * 60)[0]['status'], 0)
            self.assertEqual(lifecycle.reconcile([], True, NOW + 86401), [])

    def test_notification_delays_preserve_urgent_node_and_disk_alerts(self):
        cases = [('Node pufi', 'node', 4, 'immediate'),
                 ('Physical storage pufi', 'storage', 4, 'immediate'),
                 ('Collector API pods', 'monitoring', 4, 'immediate'),
                 ('Node pufi memory', 'node', 3, '10m'),
                 ('Pod test/app', 'cluster', 3, '10m'),
                 ('Longhorn volume test/data', 'longhorn', 4, '10m'),
                 ('Application test/app', 'application', 4, '5m')]
        for name, family, severity, delay in cases:
            self.assertEqual(collector.check(name, family, True, '', severity)['notify_delay'], delay)
        self.assertEqual(collector.check('Node pufi', 'node', True, '')['failure_samples'], 5)
        self.assertEqual(collector.check('Application test/app', 'application', True, '')['failure_samples'], 3)
        self.assertEqual(collector.check('Longhorn volume test/data', 'longhorn', True,
                                        'state=detached; robustness=faulted')['notify_delay'], 'immediate')

    def test_reboot_grace_is_scoped_to_actual_workload_and_replica_nodes(self):
        self.data['nodes'] = [
            {'metadata': {'name': node}, 'status': {'conditions': [{'type': 'Ready', 'status': state}]}}
            for node, state in [('pufi', 'False'), ('buksi', 'True'), ('pamacs', 'True')]]
        self.data['pods'] = [
            {'metadata': {'name': app, 'namespace': 'test', 'labels': {'app': app}},
             'spec': {'nodeName': node}} for app, node in [('affected', 'pufi'), ('unrelated', 'buksi')]]
        self.data['deployments'] = [
            {'metadata': {'name': app, 'namespace': 'test'}, 'spec': {'selector': {'matchLabels': {'app': app}}}}
            for app in ('affected', 'unrelated')]
        self.data['volumes'] = [{'metadata': {'name': 'v'}, 'status': {
            'currentNodeID': 'buksi', 'kubernetesStatus': {'namespace': 'test', 'pvcName': 'data'}}}]
        self.data['replicas'] = [{'spec': {'volumeName': 'v', 'nodeID': 'pufi'}}]
        self.policy['probes'] = [{'name': 'Affected HTTP', 'workloads': [['test', 'affected']]}]
        raw = [collector.check(name, family, True, 'failed') for name, family in [
            ('Node pufi', 'node'), ('Application test/affected', 'application'),
            ('Application test/unrelated', 'application'), ('Affected HTTP', 'reachability'),
            ('Longhorn volume test/data', 'longhorn')]]
        checks = {c['name']: c for c in collector.add_reboot_dependencies(raw, self.data, self.policy)}
        self.assertEqual(checks['Node pufi']['parent_available'], 1)
        self.assertEqual(checks['Application test/affected']['parent_available'], 0)
        self.assertEqual(checks['Affected HTTP']['parent_available'], 0)
        self.assertEqual(checks['Application test/unrelated']['parent_available'], 1)
        self.assertEqual(checks['Longhorn volume test/data']['parent_available'], 0)
        self.assertEqual(checks['Application test/affected']['grace_samples'], 10)
        self.assertEqual(checks['Longhorn volume test/data']['grace_samples'], 30)
        self.assertTrue(all(c['status'] == 1 for c in checks.values()))
        self.data['nodes'][0]['status']['conditions'][0]['status'] = 'True'
        restored = collector.add_reboot_dependencies(raw, self.data, self.policy)
        self.assertTrue(all(c['parent_available'] == 1 for c in restored))

    def test_reboot_grace_survives_temporarily_empty_workload_placement(self):
        self.data['deployments'] = [{'metadata': {'name': 'app', 'namespace': 'test'},
                                    'spec': {'selector': {'matchLabels': {'app': 'app'}}}}]
        c = collector.check('Application test/app', 'application', True, 'available=0/1')
        result = collector.add_reboot_dependencies([c], self.data, self.policy)[0]
        self.assertEqual(result['grace_samples'], 10)


class TriggerTests(unittest.TestCase):
    def configuration(self):
        class API:
            def __init__(self):
                self.objects = []

            def ensure(self, kind, key, value, properties, *args, **kwargs):
                self.objects.append((kind, value, properties))
                return str(len(self.objects))
        api = API()
        bootstrap.configure_checks(api)
        return api

    def test_five_healthy_samples_are_required_and_flapping_stays_open(self):
        api = self.configuration()
        prototypes = [p for kind, name, p in api.objects if kind == 'triggerprototype']
        self.assertEqual(len(prototypes), 3)
        # Replay the boolean history predicates emitted to Zabbix, including
        # insufficient history and a one-sample recovery during replica rebuild.
        import re
        expression = prototypes[0]['recovery_expression']
        self.assertEqual(prototypes[0]['recovery_mode'], 1)
        samples = int(re.search(r'count\([^,]+,#(\d+)\)', expression)[1])
        required = int(re.search(r'\)=(\d+) and', expression)[1])
        maximum = int(re.search(r'max\([^,]+,#\d+\)=(\d+)', expression)[1])
        recovery = lambda history: len(history[-samples:]) == required and max(history[-samples:]) == maximum
        self.assertFalse(recovery([0]))
        self.assertFalse(recovery([1, 1, 1, 0, 1, 1, 1, 0, 0, 0, 0]))
        self.assertTrue(recovery([1, 1, 1, 0, 0, 0, 0, 0]))

    def test_actions_are_disjoint_and_only_notify_prior_recipients_on_recovery(self):
        api = self.configuration()
        bootstrap.configure_notification_actions(api, '22', {'operationtype': 0})
        actions = [p for kind, name, p in api.objects if kind == 'action']
        for delay in (None, 'immediate', '5m', '10m'):
            matched = []
            for action in actions:
                conditions = action['filter']['conditions'][1:]
                if all((delay == c['value']) if c['operator'] == 0 else (delay != c['value']) for c in conditions):
                    matched.append(action)
            self.assertEqual(len(matched), 1)
            action = matched[0]
            step = action['operations'][0]['esc_step_from']
            self.assertEqual(step, 2 if delay in ('5m', '10m') else 1)
            self.assertEqual(action['operations'][0]['esc_step_to'], step)
            self.assertEqual(action['recovery_operations'], [{'operationtype': 11}])
            self.assertEqual(action['notify_if_canceled'], 0)

    def test_parent_grace_blocks_new_incidents_without_clearing_existing_ones(self):
        api = self.configuration()
        prototype = next(p for kind, name, p in api.objects if kind == 'triggerprototype')
        self.assertIn('min(/HomePBP/homelab.parent_available[{#ID}],#{#GRACE_SAMPLES})=1', prototype['expression'])
        self.assertIn('count(/HomePBP/homelab.parent_available[{#ID}],#{#GRACE_SAMPLES})={#GRACE_SAMPLES}', prototype['expression'])
        self.assertNotIn('parent_available', prototype['recovery_expression'])
        def eligible(history, grace):
            return len(history[-grace:]) == grace and min(history[-grace:]) == 1
        self.assertFalse(eligible([1] * 30 + [0] * 3 + [1] * 9, 10))
        self.assertTrue(eligible([1] * 30 + [0] * 3 + [1] * 10, 10))
        self.assertFalse(eligible([0] * 3 + [1] * 29, 30))
        self.assertTrue(eligible([0] * 3 + [1] * 30, 30))


if __name__ == '__main__':
    unittest.main()
