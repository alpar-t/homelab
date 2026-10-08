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
            kube=SimpleNamespace(get=get), check=lambda name, bad, detail:
            dict(name=name, status=int(bad), detail=detail))
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
        self.assertEqual(self.run_check(remaining=14)['status'], 1)
        self.assertEqual(self.calls, [])

    def test_unauthorized_timeout_redacted(self):
        for error in (PermissionError, TimeoutError):
            ctx = SimpleNamespace(now=self.now, remaining=lambda: 30,
                kube=SimpleNamespace(get=lambda path: (_ for _ in ()).throw(error('private'))),
                check=lambda name, bad, detail: dict(status=int(bad), detail=detail))
            record = module.run(ctx, CONFIG)[0]
            self.assertEqual(record['status'], 1)
            self.assertNotIn('private', record['detail'])


if __name__ == '__main__':
    unittest.main()
