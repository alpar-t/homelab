import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'config/zabbix/manifests/assets'))
import service_tandoor


class Context:
    def __init__(self, page=None, status=200, missing=False):
        self.page = page
        self.status = status
        self.missing = missing
        self.calls = []
    def remaining(self): return 20
    def secret(self, key):
        if self.missing: raise ValueError('private secret')
        return 'private secret'
    def check(self, name, bad, detail, severity=3):
        return dict(name=name, status=int(bool(bad)), detail=detail)
    def http(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if 'server-settings' in url:
            data = dict(version='2.6.13', debug=False, disable_external_connectors=False)
            return SimpleNamespace(status=200, body=json.dumps(data).encode())
        if isinstance(self.page, Exception): raise self.page
        return SimpleNamespace(status=self.status, body=json.dumps(self.page).encode())


class Tests(unittest.TestCase):
    config = dict(base_url='http://example', token_key='tandoor_read_token')
    def test_empty_and_populated(self):
        for count, results in [(0, []), (3, [dict(id=1, name='private recipe')])]:
            ctx = Context(dict(count=count, results=results, next='http://example' if count else None, previous=None))
            rows = service_tandoor.run(ctx, self.config)
            self.assertEqual([r['status'] for r in rows], [0, 0])
            self.assertNotIn('private', str(rows))
            self.assertIn('page_size=1', ctx.calls[1][0])
            self.assertFalse(ctx.calls[1][1]['follow_redirects'])
            self.assertEqual(ctx.calls[1][1]['max_bytes'], 131072)
    def test_broken_backend_and_redaction(self):
        for page, status in [(dict(count=True, results=[]), 200), ([], 200), (dict(count=1, results=[]), 200), ('private recipe', 401), ('private recipe', 302), (TimeoutError('private secret'), 200)]:
            rows = service_tandoor.run(Context(page, status), self.config)
            self.assertEqual(rows[1]['status'], 1)
            self.assertNotIn('private', str(rows))
    def test_missing_credential_still_checks_public_config(self):
        ctx = Context(missing=True)
        rows = service_tandoor.run(ctx, self.config)
        self.assertEqual([r['status'] for r in rows], [0, 1])
        self.assertEqual(len(ctx.calls), 1)
        self.assertEqual(rows[1]["observation"], "deferred")
        self.assertEqual(rows[1]["notification"], "dashboard")
    def test_malformed_public_config(self):
        ctx = Context(dict(count=0, results=[], next=None, previous=None))
        original = ctx.http
        def http(url, **kwargs):
            if 'server-settings' in url: return SimpleNamespace(status=200, body=b'<html>login</html>')
            return original(url, **kwargs)
        ctx.http = http
        self.assertEqual(service_tandoor.run(ctx, self.config)[0]['status'], 1)
