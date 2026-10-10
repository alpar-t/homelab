import copy
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest

ASSETS = Path(__file__).resolve().parents[2] / 'config/zabbix/manifests/assets'
spec = importlib.util.spec_from_file_location('metrics_check', ASSETS / 'service_metrics_server.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
CONFIG = dict(max_age_seconds=180, future_skew_seconds=15, node_startup_grace_seconds=300)


class Checks(unittest.TestCase):
    def setUp(self):
        self.nodes = dict(kind='NodeList', items=[dict(metadata=dict(name='one',
            creationTimestamp='2026-10-08T00:00:00Z'), status=dict(conditions=[dict(
            type='Ready', status='True', lastTransitionTime='2026-10-08T00:00:00Z')]))])
        self.metrics = dict(kind='NodeMetricsList', items=[dict(metadata=dict(name='one'),
            timestamp='2026-10-08T01:00:00Z', window='15.003s',
            usage=dict(cpu='1000000n', memory='100Ki'))])
        self.now = module.timestamp('2026-10-08T01:00:30Z')
        self.calls = []

    def run_check(self, remaining=30):
        def get(path):
            self.calls.append(path)
            return self.metrics if 'metrics.k8s.io' in path else self.nodes
        ctx = SimpleNamespace(now=self.now, remaining=lambda: remaining,
            kube=SimpleNamespace(get=get), check=lambda name, bad, detail, **kwargs:
            dict(name=name, status=int(bad), detail=detail, **kwargs))
        return module.run(ctx, CONFIG)[0]

    def test_healthy(self):
        self.assertEqual(self.run_check()['status'], 0)
        self.assertEqual(len(self.calls), 2)

    def test_stale_and_future(self):
        for value in ('2026-10-08T00:00:00Z', '2026-10-08T02:00:00Z'):
            self.metrics['items'][0]['timestamp'] = value
            self.assertEqual(self.run_check()['status'], 1)

    def test_missing_and_grace(self):
        node = copy.deepcopy(self.nodes['items'][0])
        node['metadata']['name'] = 'two'
        self.nodes['items'].append(node)
        self.assertEqual(self.run_check()['status'], 1)
        node['status']['conditions'][0]['lastTransitionTime'] = '2026-10-08T01:00:00Z'
        self.assertEqual(self.run_check()['status'], 0)
        self.now += 301
        self.assertEqual(self.run_check()['status'], 1)

    def test_not_ready_node_missing_or_stale_metrics_is_excluded(self):
        other = copy.deepcopy(self.nodes['items'][0])
        other['metadata']['name'] = 'two'
        other['status']['conditions'][0]['status'] = 'False'
        self.nodes['items'].append(other)
        self.assertEqual(self.run_check()['status'], 0)
        sample = copy.deepcopy(self.metrics['items'][0])
        sample['metadata']['name'] = 'two'
        sample['timestamp'] = '2026-10-08T00:00:00Z'
        self.metrics['items'].append(sample)
        row = self.run_check()
        self.assertEqual(row['status'], 0)
        self.assertIn('not_ready_excluded=1', row['detail'])
        self.nodes['items'][1]['status']['conditions'][0]['status'] = 'True'
        self.assertEqual(self.run_check()['status'], 1)

    def test_no_ready_expected_nodes_preserves_unknown_observation(self):
        self.nodes['items'][0]['status']['conditions'][0]['status'] = 'Unknown'
        self.metrics['items'] = []
        self.assertEqual(self.run_check()['observation'], 'unknown')

    def test_stale_metrics_during_ready_startup_grace_are_excluded(self):
        self.nodes['items'][0]['status']['conditions'][0]['lastTransitionTime'] = '2026-10-08T01:00:00Z'
        self.metrics['items'][0]['timestamp'] = '2026-10-08T00:00:00Z'
        self.assertEqual(self.run_check()['observation'], 'unknown')
        self.now += 301
        self.assertEqual(self.run_check()['status'], 1)

    def test_malformed_metrics_are_rejected_even_for_not_ready_node(self):
        self.nodes['items'][0]['status']['conditions'][0]['status'] = 'False'
        self.metrics['items'][0]['usage'] = {}
        self.assertEqual(self.run_check()['status'], 1)

    def test_bad_schema(self):
        original = copy.deepcopy(self.metrics)
        for mutation in (lambda d: d.update(items=[]), lambda d: d.update(kind='Status'),
                         lambda d: d.update(metadata={'continue': 'next'}),
                         lambda d: d['items'].append(copy.deepcopy(d['items'][0])),
                         lambda d: d['items'][0].update(timestamp='2026-10-08T01:00:00'),
                         lambda d: d['items'][0].update(window='0s'),
                         lambda d: d['items'][0].update(usage={}),
                         lambda d: d['items'][0].update(timestamp=None)):
            self.metrics = copy.deepcopy(original)
            mutation(self.metrics)
            self.assertEqual(self.run_check()['status'], 1)

    def test_deadline(self):
        self.assertEqual(self.run_check(remaining=4)['status'], 1)
        self.assertEqual(self.calls, [])

    def test_unauthorized_timeout_redacted(self):
        for error in (PermissionError, TimeoutError):
            ctx = SimpleNamespace(now=self.now, remaining=lambda: 30,
                kube=SimpleNamespace(get=lambda path: (_ for _ in ()).throw(error('private'))),
                check=lambda name, bad, detail, **kwargs: dict(status=int(bad), detail=detail))
            record = module.run(ctx, CONFIG)[0]
            self.assertEqual(record['status'], 1)
            self.assertNotIn('private', record['detail'])


if __name__ == '__main__':
    unittest.main()
