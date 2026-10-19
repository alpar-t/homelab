import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]
ASSET = ROOT / 'config/zabbix/manifests/assets/service_product_models.py'
spec = importlib.util.spec_from_file_location('security_product_models', ASSET)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
CONFIG = json.loads(ASSET.with_suffix('.json').read_text())
FIXTURES = {}


class Context:
    def __init__(self, fault=None, remaining=30):
        self.fault, self.budget, self.calls = fault, remaining, []
        self.kube = self
        self.secret_reads = []
    def remaining(self):
        return self.budget
    def secret(self, key):
        self.secret_reads.append(key)
        raise AssertionError('unsafe credential read attempted')
    def check(self, name, bad, detail, severity=3):
        return dict(name=name, status=int(bool(bad)), detail=detail, severity=severity)
    def http(self, url, **kwargs):
        if not 0 < kwargs['timeout'] <= self.remaining():
            raise TimeoutError('PRIVATE-CREDENTIAL')
        self.calls.append((url, kwargs))
        if (kwargs.get('headers') or {}).get('Authorization') or (kwargs.get('headers') or {}).get('X-Api-Key') or (kwargs.get('headers') or {}).get('X-Actual-Token'):
            raise AssertionError('unsafe authentication header')
        path = urlsplit(url).path
        if path not in FIXTURES:
            raise AssertionError('unexpected HTTP path: ' + path)
        status, value = FIXTURES[path]
        if self.fault == 'timeout':
            raise TimeoutError('PRIVATE-CREDENTIAL')
        if self.fault in (200, 302, 401, 403, 500):
            status, value = self.fault, {'error':'PRIVATE-CREDENTIAL'}
        if self.fault == 'malformed':
            value = 'PRIVATE-CREDENTIAL'
        body = value.encode() if isinstance(value, str) else json.dumps(value).encode()
        return SimpleNamespace(status=status, body=body, headers={'Content-Type':'text/html' if path == '/' else 'application/json'})
    def get(self, path):
        self.calls.append((path, {}))
        if self.fault == 'timeout':
            raise TimeoutError('PRIVATE-CREDENTIAL')
        if '/pods?' in path:
            assert path.startswith('/api/v1/namespaces/media/pods?')
            states = [dict(name='product_models',ready=self.fault != 'not-ready',state={'running':{}})]
            return {'items':[dict(metadata={'name':'unused'},status={'phase':'Running','containerStatuses':states})],
                    'metadata':{'continue':'private' if self.fault == 'truncated' else ''}}
        assert path == '/apis/apps/v1/namespaces/baloo/deployments?limit=100'
        names = ['pinchtab-web','pinchtab'] if 'product_models' == 'pinchtab' else ['product-model-api','product-model-renderer']
        items = [dict(metadata={'name':n,'generation':2},spec={'replicas':1},
                      status={'observedGeneration':1 if self.fault == 'stale-generation' else 2,
                              'availableReplicas':0 if self.fault == 'not-ready' else 1,'readyReplicas':1}) for n in names]
        return {'items':[] if self.fault == 'missing' else items,
                'metadata':{'continue':'private' if self.fault == 'truncated' else ''}}


class SecurityBaselineTests(unittest.TestCase):
    def test_useful_baseline_is_distinct_from_deferred_coverage(self):
        ctx = Context()
        rows = module.run(ctx, CONFIG)
        active = [r for r in rows if r['severity'] > 1]
        deferred = [r for r in rows if r['severity'] == 1]
        self.assertTrue(active)
        self.assertTrue(all(r['status'] == 0 for r in active), rows)
        self.assertTrue(deferred)
        self.assertTrue(all(r['status'] == 1 and r['observation'] == 'deferred' and r['notification'] == 'dashboard' and 'deferred' in r['detail'] for r in deferred), rows)
        self.assertTrue(ctx.calls)
        self.assertEqual([], ctx.secret_reads)
        for url, args in ctx.calls:
            self.assertNotIn('Authorization', (args.get('headers') or {}))
            self.assertNotIn('X-Api-Key', (args.get('headers') or {}))
            self.assertNotIn('X-Actual-Token', (args.get('headers') or {}))
            if url.startswith('http'):
                self.assertLessEqual(args['timeout'], 8)
                self.assertLessEqual(args['max_bytes'], 65536)
                if args.get('method') == 'POST':
                    self.assertEqual('actual_budget', 'product_models')
                    self.assertEqual('tools/list', json.loads(args['data'])['method'])
                else:
                    self.assertNotIn('method', args)
    def test_bad_baseline_never_claims_health_or_leaks_responses(self):
        faults = ['timeout','malformed',302,401,403,500] if FIXTURES else ['timeout','missing','not-ready','truncated','stale-generation']
        if 'product_models' in ('radarr','prowlarr'):
            faults = ['timeout','not-ready','truncated']
        for fault in faults:
            with self.subTest(fault=fault):
                rows = module.run(Context(fault), CONFIG)
                self.assertTrue(any(r['status'] for r in rows if r['severity'] > 1), rows)
                self.assertNotIn('PRIVATE-CREDENTIAL', json.dumps(rows))
    def test_legacy_credentials_cannot_reenable_privileged_access(self):
        legacy = dict(CONFIG,credential_key='admin',session_secret='admin',workspace_path='/dav/spaces/private/',
                      token_key='admin',api_url='http://renderer:18811',renderer_url='http://renderer:18811')
        rows = module.run(Context(), legacy)
        self.assertTrue(all(r['status'] == 1 for r in rows if r['severity'] == 1))
    def test_deadline_fails_without_authenticated_fallback(self):
        rows = module.run(Context(remaining=0), CONFIG)
        self.assertTrue(all(r['status'] == 1 for r in rows))


if __name__ == '__main__':
    unittest.main()
