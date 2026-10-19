import importlib.util
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
ASSETS = ROOT / 'config/zabbix/manifests/assets'
spec = importlib.util.spec_from_file_location('service_argocd', ASSETS / 'service_argocd.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
CONFIG = json.loads((ASSETS / 'service_argocd.json').read_text())


class Context:
    now = 1760000000
    def __init__(self, apps):
        self.apps = apps
        self.kube = self
        self.budget = 30
    def remaining(self):
        return self.budget
    def get(self, path):
        assert path.endswith('applications?limit=500')
        if isinstance(self.apps, Exception):
            raise self.apps
        return self.apps
    def check(self, name, bad, detail, severity=3, **kwargs):
        return dict(name=name, status=int(bool(bad)), detail=detail, **kwargs)


class Tests(unittest.TestCase):
    def setUp(self):
        module._since.clear()
        self.app = dict(metadata=dict(name='example', uid='id'),
                        spec=dict(syncPolicy=dict(automated={})),
                        status=dict(sync=dict(status='Synced'), health=dict(status='Healthy'),
                                    reconciledAt='2025-10-09T08:53:20Z'))
        self.ctx = Context(dict(items=[self.app]))

    def run_check(self, age=0):
        module.run(self.ctx, CONFIG)
        self.ctx.now += age
        # Refresh reconciliation normally while tracking continuous failure.
        from datetime import datetime, timezone
        self.app['status']['reconciledAt'] = datetime.fromtimestamp(self.ctx.now, timezone.utc).isoformat()
        return module.run(self.ctx, CONFIG)

    def test_healthy_and_obsolete_failed_operation(self):
        self.app['status']['operationState'] = dict(phase='Failed', message='private')
        self.assertEqual([0, 0, 0], [r['status'] for r in self.run_check(1801)])

    def test_recent_and_persistent_out_of_sync(self):
        self.app['status']['sync']['status'] = 'OutOfSync'
        self.assertEqual(0, self.run_check(100)[2]['status'])
        self.assertEqual(1, self.run_check(1801)[2]['status'])

    def test_error_redaction(self):
        self.app['status']['conditions'] = [dict(type='ComparisonError', message='secret private repo')]
        result = self.run_check(1801)
        self.assertEqual(1, result[1]['status'])
        self.assertNotIn('secret', str(result))

    def test_degraded_running_stalled(self):
        self.app['status']['health']['status'] = 'Degraded'
        self.app['status']['operationState'] = dict(phase='Running')
        self.assertEqual(1, self.run_check(1801)[2]['status'])

    def test_pause_variants(self):
        for kind in ('disabled', 'missing', 'skip', 'maintenance', 'delete'):
            with self.subTest(kind=kind):
                self.setUp()
                self.app['status']['sync']['status'] = 'OutOfSync'
                if kind == 'disabled':
                    self.app['spec']['syncPolicy']['automated']['enabled'] = False
                elif kind == 'missing':
                    self.app['spec']['syncPolicy'].pop('automated')
                elif kind == 'delete':
                    self.app['metadata']['deletionTimestamp'] = 'now'
                else:
                    key = 'argocd.argoproj.io/skip-reconcile' if kind == 'skip' else 'monitoring.homepbp.io/maintenance'
                    self.app['metadata']['annotations'] = {key: 'true'}
                self.assertEqual([0, 0, 0], [r['status'] for r in self.run_check(3600)])

    def test_stale_and_missing_reconciled(self):
        for value in ('2020-01-01T00:00:00Z', None):
            module._since.clear()
            self.app['status']['reconciledAt'] = value
            module.run(self.ctx, CONFIG)
            self.ctx.now += 1801
            self.assertEqual(1, module.run(self.ctx, CONFIG)[2]['status'])

    def test_unavailable_malformed_truncated_and_budget(self):
        for page in (PermissionError('secret'), TimeoutError('secret'), {}, dict(items=[]),
                     dict(items=[{}]), dict(items=[self.app], metadata={'continue': 'more'})):
            self.ctx.apps = page
            result = module.run(self.ctx, CONFIG)
            self.assertEqual(1, result[0]['status'])
            self.assertNotIn('secret', str(result))
        self.ctx.budget = 15
        self.assertEqual(1, module.run(self.ctx, CONFIG)[0]['status'])

    def test_restart_grace_and_paused_fault_are_unknown_not_recovery(self):
        self.app['status']['conditions'] = [dict(type='ComparisonError')]
        self.app['status']['sync']['status'] = 'OutOfSync'
        first = self.run_check(600)
        self.assertEqual([r['observation'] for r in first[1:]], ['unknown', 'unknown'])
        module._since.clear()  # Collector/source restart resets module grace.
        second = self.run_check(600)
        self.assertEqual([r['observation'] for r in second[1:]], ['unknown', 'unknown'])
        self.app['spec']['syncPolicy']['automated']['enabled'] = False
        paused = self.run_check(3600)
        self.assertEqual([r['observation'] for r in paused[1:]], ['unknown', 'unknown'])
        self.app['spec']['syncPolicy']['automated']['enabled'] = True
        self.app['status']['conditions'] = []
        self.app['status']['sync']['status'] = 'Synced'
        healthy = self.run_check()
        self.assertEqual([r['observation'] for r in healthy[1:]], ['known', 'known'])

    def test_recovery_resets_grace(self):
        self.app['status']['sync']['status'] = 'OutOfSync'
        self.assertEqual(1, self.run_check(1801)[2]['status'])
        self.app['status']['sync']['status'] = 'Synced'
        self.run_check()
        self.app['status']['sync']['status'] = 'OutOfSync'
        self.assertEqual(0, self.run_check()[2]['status'])


if __name__ == '__main__':
    unittest.main()
