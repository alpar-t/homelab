import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('arc', ROOT / 'config/zabbix/manifests/assets/service_github_runners.py')
arc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(arc)


class ARC(unittest.TestCase):
    def setUp(self):
        arc._since.clear()
        self.config = dict(runner_namespace='arc-runners', controller_namespace='arc-systems', sets=['test'], grace_seconds=900)
        self.data = dict(autoscalingrunnersets=[dict(metadata={'name': 'test'}, status={'phase': 'Running'})],
                         ephemeralrunnersets=[dict(metadata={'name': 'ers', 'ownerReferences': [{'kind': 'AutoscalingRunnerSet', 'name': 'test'}]}, spec={'replicas': 0}, status={'phase': 'Running', 'currentReplicas': 0})],
                         ephemeralrunners=[], autoscalinglisteners=[dict(spec={'autoscalingRunnerSetName': 'test', 'autoscalingRunnerSetNamespace': 'arc-runners', 'ephemeralRunnerSetName': 'ers'})])
        self.ctx = SimpleNamespace(now=2000, remaining=lambda: 30,
                                   check=lambda n,b,d: dict(name=n,status=int(bool(b)),detail=d),
                                   kube=SimpleNamespace(get=lambda p: {'items': self.data[p.split('/')[-1].split('?')[0]]}))

    def run_check(self):
        return arc.run(self.ctx, self.config)[0]['status']

    def test_idle_healthy(self):
        self.assertEqual(self.run_check(), 0)

    def test_missing_listener_grace_and_recovery(self):
        listeners = self.data['autoscalinglisteners']
        self.data['autoscalinglisteners'] = []
        self.assertEqual(self.run_check(), 0)
        self.ctx.now += 901
        self.assertEqual(self.run_check(), 1)
        self.data['autoscalinglisteners'] = listeners
        self.assertEqual(self.run_check(), 0)
        self.assertEqual(arc._since, {})

    def test_historical_failure_does_not_page(self):
        self.data['ephemeralrunners'] = [dict(metadata={'ownerReferences': [{'kind': 'EphemeralRunnerSet', 'name': 'ers'}]}, status={'phase': 'Failed', 'message': 'private'})]
        result = arc.run(self.ctx, self.config)[0]
        self.assertEqual(result['status'], 0)
        self.assertIn('historical_failed=1', result['detail'])
        self.assertNotIn('private', result['detail'])

    def test_stalled_registration_and_online(self):
        runner = dict(metadata={'creationTimestamp': '1970-01-01T00:00:00Z', 'ownerReferences': [{'kind': 'EphemeralRunnerSet', 'name': 'ers'}]}, status={'phase': 'Running', 'ready': False})
        self.data['ephemeralrunners'] = [runner]
        ers = self.data['ephemeralrunnersets'][0]
        ers['spec']['replicas'] = 1
        self.assertEqual(self.run_check(), 1)
        runner['status']['ready'] = True
        ers['status']['runningEphemeralRunners'] = 1
        self.assertEqual(self.run_check(), 0)

    def test_capacity_deficit_and_busy_queue(self):
        ers = self.data['ephemeralrunnersets'][0]
        ers['spec']['replicas'] = 1
        self.assertEqual(self.run_check(), 0)
        self.ctx.now += 901
        self.assertEqual(self.run_check(), 1)
        ers['status']['runningEphemeralRunners'] = 1
        self.assertEqual(self.run_check(), 0)

    def test_historical_sets_and_deleting_runners_are_ignored(self):
        old = dict(metadata={'name': 'retired', 'ownerReferences': [{'kind': 'AutoscalingRunnerSet', 'name': 'test'}]},
                   spec={'replicas': 10}, status={'phase': 'Failed', 'failedEphemeralRunners': 10})
        self.data['ephemeralrunnersets'].append(old)
        self.data['ephemeralrunners'] = [dict(metadata={'deletionTimestamp': 'now',
            'ownerReferences': [{'kind': 'EphemeralRunnerSet', 'name': 'ers'}]}, status={'phase': 'Running', 'ready': False})]
        self.assertEqual(self.run_check(), 0)
        self.ctx.now += 1000
        self.assertEqual(self.run_check(), 0)

    def test_replacement_capacity_recovers_with_retained_failures(self):
        ers = self.data['ephemeralrunnersets'][0]
        ers['spec']['replicas'] = 2
        ers['status'].update(runningEphemeralRunners=1, currentReplicas=2, failedEphemeralRunners=5)
        self.assertEqual(self.run_check(), 0)
        self.ctx.now += 901
        self.assertEqual(self.run_check(), 1)
        ers['status']['runningEphemeralRunners'] = 2
        self.assertEqual(self.run_check(), 0)
        self.assertEqual(arc._since, {})

    def test_malformed_counter(self):
        self.data['ephemeralrunnersets'][0]['spec']['replicas'] = '1'
        with self.assertRaises(ValueError):
            self.run_check()

    def test_unauthorized_and_deadline(self):
        self.ctx.kube.get = lambda p: (_ for _ in ()).throw(PermissionError('private'))
        with self.assertRaises(PermissionError):
            self.run_check()
        self.ctx.remaining = lambda: 0
        with self.assertRaises(ValueError):
            self.run_check()

    def test_truncated_inventory(self):
        self.ctx.kube.get = lambda p: {'items': [], 'metadata': {'continue': 'next'}}
        with self.assertRaises(ValueError):
            self.run_check()


if __name__ == '__main__':
    unittest.main()
