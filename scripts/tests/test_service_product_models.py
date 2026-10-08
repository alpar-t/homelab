import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('product_models', ROOT / 'config/zabbix/manifests/assets/service_product_models.py')
SERVICE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SERVICE)
CONFIG = json.loads((ROOT / 'config/zabbix/manifests/assets/service_product_models.json').read_text())


class Context:
    def __init__(self, health=None, info=None, auth=401, error=None):
        self.health = {'ok': True} if health is None else health
        self.info = dict(schema=1, blenderAvailable=True, scratchWritable=True,
                         busy=False, activeSeconds=None, renderTimeoutSeconds=900) if info is None else info
        self.auth, self.error = auth, error
        self.requests = []

    def remaining(self):
        return 20

    def check(self, name, bad, detail, severity=3):
        return dict(name=name, status=int(bool(bad)), detail=detail, severity=severity)

    def http(self, url, **kwargs):
        self.requests.append((url, kwargs))
        if self.error:
            raise self.error
        status, payload = (200, self.info) if url.endswith('/capabilities') else ((200, self.health) if url.endswith('/health') else (self.auth, {'error': 'unauthorized'}))
        return SimpleNamespace(status=status, body=json.dumps(payload).encode())


class ProductModelsTests(unittest.TestCase):
    def test_idle_and_long_legitimate_render(self):
        ctx = Context()
        self.assertEqual([0, 0, 0], [r['status'] for r in SERVICE.run(ctx, CONFIG)])
        ctx.info.update(busy=True, activeSeconds=1150)
        self.assertEqual([0, 0, 0], [r['status'] for r in SERVICE.run(ctx, CONFIG)])
        self.assertTrue(all(k['max_bytes'] == 4096 and k['timeout'] <= 5 for _, k in ctx.requests))

    def test_stuck_render(self):
        ctx = Context()
        ctx.info.update(busy=True, activeSeconds=1201)
        self.assertEqual([0, 0, 1], [r['status'] for r in SERVICE.run(ctx, CONFIG)])

    def test_missing_dependencies_and_worker_failure(self):
        ctx = Context(health={'ok': False})
        ctx.info['blenderAvailable'] = False
        self.assertEqual([1, 1, 0], [r['status'] for r in SERVICE.run(ctx, CONFIG)])

    def test_broken_contracts_and_auth_bypass(self):
        for info in ({}, [], {'schema': True}, {'schema': 1, 'busy': True, 'activeSeconds': float('nan')}):
            with self.subTest(info=info):
                rows = SERVICE.run(Context(info=info, auth=200), CONFIG)
                self.assertEqual([1, 1, 1], [r['status'] for r in rows])

    def test_timeouts_redact(self):
        rows = SERVICE.run(Context(error=TimeoutError('private credentials')), CONFIG)
        self.assertEqual([1, 1, 1], [r['status'] for r in rows])
        self.assertNotIn('private', str(rows))

    def test_renderer_snapshot_handler(self):
        source = (ROOT / 'config/interior-designer/manifests/product-model-renderer.yaml').read_text().split('  server.py: |\n', 1)[1].split('\n---', 1)[0]
        source = '\n'.join(line[4:] for line in source.splitlines())
        source = source.rsplit('ThreadingHTTPServer(', 1)[0]
        namespace = {}
        exec(compile(source, '<renderer>', 'exec'), namespace)
        handler = object.__new__(namespace['Handler'])
        handler.path = '/capabilities'
        replies = []
        handler.send = lambda status, content, mime: replies.append((status, json.loads(content), mime))
        handler.do_GET()
        self.assertEqual(200, replies[0][0])
        self.assertEqual(False, replies[0][1]['busy'])
        namespace['active_since'] = namespace['time'].monotonic() - 100
        handler.do_GET()
        self.assertTrue(replies[-1][1]['busy'])
        self.assertGreaterEqual(replies[-1][1]['activeSeconds'], 100)


if __name__ == '__main__':
    unittest.main()
