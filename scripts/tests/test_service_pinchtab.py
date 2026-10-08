import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[2]
ASSETS = ROOT / 'config/zabbix/manifests/assets'
spec = importlib.util.spec_from_file_location('pinchtab', ASSETS / 'service_pinchtab.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
CONFIG = json.loads((ASSETS / 'service_pinchtab.json').read_text())


class Context:
    def __init__(self, overrides=None, missing=False, remaining=30):
        self.overrides = overrides or {}
        self.missing, self.budget = missing, remaining
        self.calls = []

    def remaining(self):
        return self.budget

    def secret(self, key):
        if self.missing:
            raise RuntimeError('secret content must never appear')
        return 'private-token'

    def check(self, name, bad, detail, severity=3):
        return dict(name=name, status=int(bad), detail=detail, severity=severity)

    def http(self, url, **kwargs):
        self.calls.append((url, kwargs))
        path = '/' + url.rsplit('/', 1)[1]
        value = self.overrides.get(path, {
            '/health': {'status': 'ok', 'mode': 'dashboard', 'version': 'dev',
                        'instances': 0, 'authRequired': True, 'restartRequired': False},
            '/instances': [], '/sessions': []}[path])
        if isinstance(value, Exception):
            raise value
        if isinstance(value, SimpleNamespace):
            return value
        return SimpleNamespace(status=200, body=json.dumps(value).encode())


class PinchTabTests(unittest.TestCase):
    def test_idle_contract_and_get_only(self):
        ctx = Context()
        self.assertEqual([0, 0], [r['status'] for r in module.run(ctx, CONFIG)])
        self.assertEqual(5, len(ctx.calls))
        for url, args in ctx.calls:
            self.assertNotIn('method', args)
            self.assertNotIn('data', args)
            self.assertLessEqual(args['timeout'], 4)
            self.assertFalse(args['follow_redirects'])
            self.assertNotIn('/tabs', url)

    def test_running_and_stopped_are_normal(self):
        for state in ['running', 'stopped', 'starting', 'stopping']:
            with self.subTest(state=state):
                ctx = Context({'/instances': [{'id': 'private-id', 'status': state}]})
                result = module.run(ctx, CONFIG)
                self.assertEqual([0, 0], [r['status'] for r in result])
                self.assertNotIn('private-id', str(result))

    def test_error_instance_and_restart_required(self):
        ctx = Context({'/instances': [{'id': 'private-id', 'status': 'error', 'error': 'private-page'}]})
        result = module.run(ctx, CONFIG)
        self.assertEqual([1, 1], [r['status'] for r in result])
        self.assertNotIn('private-page', str(result))
        ctx = Context()
        health = json.loads(ctx.http('http://test/health').body)
        health['restartRequired'] = True
        self.assertTrue(all(r['status'] for r in module.run(Context({'/health': health}), CONFIG)))

    def test_contract_auth_transport_failures(self):
        for override in [None, [], {'status': 'ok'},
                         SimpleNamespace(status=401, body=b'private-token'),
                         SimpleNamespace(status=302, body=b'login'),
                         SimpleNamespace(status=200, body=b'not json'),
                         TimeoutError('private-token')]:
            with self.subTest(override=override):
                result = module.run(Context({'/health': override}), CONFIG)
                self.assertEqual([1, 1], [r['status'] for r in result])
                self.assertNotIn('private-token', str(result))
        for path in ['/instances', '/sessions']:
            result = module.run(Context({path: {}}), CONFIG)
            self.assertEqual(1, result[0]['status'])
        result = module.run(Context({'/instances': [{'id': 'x', 'status': 'invented'}]}), CONFIG)
        self.assertTrue(all(r['status'] for r in result))

    def test_missing_credentials_and_deadline(self):
        for ctx in [Context(missing=True), Context(remaining=0)]:
            self.assertEqual([1, 1], [r['status'] for r in module.run(ctx, CONFIG)])
            self.assertFalse(ctx.calls)


if __name__ == '__main__':
    unittest.main()
