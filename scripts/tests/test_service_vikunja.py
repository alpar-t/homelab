import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('vikunja', ROOT / 'config/zabbix/manifests/assets/service_vikunja.py')
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
CONFIG = json.loads((ROOT / 'config/zabbix/manifests/assets/service_vikunja.json').read_text())
INFO = {'version': 'v2.5.0', 'frontend_url': CONFIG['frontend_url'], 'auth': {'openid_connect': {'enabled': True, 'providers': [{'key': 'pocketid'}]}}}
PAGE = {'items': [], 'page': 1, 'per_page': 1, 'total': 0, 'total_pages': 0}

class Context:
    def __init__(self, info=INFO, page=PAGE, secret=True):
        self.responses = [info, page]
        self.has_secret = secret
        self.calls = []
    def remaining(self):
        return 2
    def check(self, name, bad, detail, severity=3):
        return dict(name=name, status=int(bad), detail=detail, severity=severity)
    def secret(self, key):
        if not self.has_secret:
            raise RuntimeError('PRIVATE')
        return 'PRIVATE'
    def http(self, url, **kwargs):
        self.calls.append((url, kwargs))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        if isinstance(response, int):
            return SimpleNamespace(status=response, body=b'PRIVATE')
        return SimpleNamespace(status=200, body=json.dumps(response).encode())

class Tests(unittest.TestCase):
    def test_empty_and_populated(self):
        for page in (PAGE, dict(PAGE, items=None), dict(PAGE, items=[{'id': 7, 'title': 'PRIVATE'}], total=1, total_pages=1)):
            ctx = Context(page=page)
            rows = MODULE.run(ctx, CONFIG)
            self.assertEqual([0, 0], [r['status'] for r in rows])
            self.assertNotIn('PRIVATE', str(rows))
            self.assertTrue(all(c[1]['timeout'] == 2 and c[1]['max_bytes'] == 65536 for c in ctx.calls))
            self.assertEqual('Bearer PRIVATE', ctx.calls[1][1]['headers']['Authorization'])
    def test_bad_info(self):
        for info in ({}, dict(INFO, frontend_url='wrong'), 302, TimeoutError('PRIVATE'), ['wrong']):
            self.assertEqual(1, MODULE.run(Context(info=info), CONFIG)[0]['status'])
    def test_bad_project_response(self):
        for page in (401, 403, 500, [], {}, dict(PAGE, total=True), dict(PAGE, items=[{'id': '7'}]), TimeoutError('PRIVATE')):
            rows = MODULE.run(Context(page=page), CONFIG)
            self.assertEqual(1, rows[1]['status'])
            self.assertNotIn('PRIVATE', str(rows))
    def test_missing_token(self):
        ctx = Context(secret=False)
        rows = MODULE.run(ctx, CONFIG)
        self.assertEqual([0, 1], [r['status'] for r in rows])
        self.assertEqual(1, len(ctx.calls))
    def test_exhausted_deadline(self):
        ctx = Context()
        ctx.remaining = lambda: 0
        self.assertEqual([1, 1], [r['status'] for r in MODULE.run(ctx, CONFIG)])
        self.assertFalse(ctx.calls)
