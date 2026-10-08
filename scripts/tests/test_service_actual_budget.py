import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'config/zabbix/manifests/assets'))
import service_actual_budget as service

CONFIG = json.loads((Path(__file__).resolve().parents[2] / 'config/zabbix/manifests/assets/service_actual_budget.json').read_text())

class Context:
    def __init__(self):
        self.responses = [(200, {'build': {'name': '@actual-app/sync-server', 'version': '26.8.0'}}), (200, {'status': 'ok', 'data': {'bootstrapped': True, 'availableLoginMethods': [{'method': 'password'}]}}), (200, {'status': 'ok', 'data': {'validated': True, 'permission': 'BASIC'}}), (200, {'status': 'ok', 'data': []}), (401, {'error': 'Unauthorized: Missing Authorization header'})]
        self.calls = []
    def remaining(self): return 20
    def secret(self, key): return 'sensitive-session'
    def check(self, name, bad, detail, severity=3): return dict(name=name, status=int(bool(bad)), detail=detail, severity=severity)
    def http(self, url, **kwargs):
        self.calls.append((url, kwargs))
        status, body = self.responses.pop(0)
        return SimpleNamespace(status=status, body=json.dumps(body).encode())

class Tests(unittest.TestCase):
    def test_healthy_empty_account_and_bounded_requests(self):
        ctx = Context()
        self.assertEqual([r['status'] for r in service.run(ctx, CONFIG)], [0, 0, 0])
        self.assertTrue(all(c[1]['timeout'] <= 5 and c[1]['max_bytes'] == 65536 for c in ctx.calls))
        self.assertTrue(all('/download' not in c[0] and '/login' not in c[0] for c in ctx.calls))
    def test_unbootstrapped_and_spa_fallback(self):
        for body in ({'status': 'ok', 'data': {'bootstrapped': False}}, {'html': 'SPA'}):
            ctx = Context(); ctx.responses[1] = (200, body)
            self.assertEqual(service.run(ctx, CONFIG)[0]['status'], 1)
    def test_budget_access_is_rejected_without_private_output(self):
        ctx = Context(); ctx.responses[3] = (200, {'status': 'ok', 'data': [{'name': 'private-budget'}]})
        rows = service.run(ctx, CONFIG)
        self.assertEqual(rows[1]['status'], 1)
        self.assertNotIn('private-budget', str(rows))
    def test_unauthorized_or_admin_account_does_not_list_budgets(self):
        for response in ((401, {'reason': 'token-expired'}), (200, {'status': 'ok', 'data': {'validated': True, 'permission': 'ADMIN'}})):
            ctx = Context(); ctx.responses[2] = response; ctx.responses.pop(3)
            rows = service.run(ctx, CONFIG)
            self.assertEqual(rows[1]['status'], 1)
            self.assertFalse(any('/list-user-files' in c[0] for c in ctx.calls))
    def test_missing_credential_is_failure(self):
        ctx = Context(); ctx.responses[2:4] = []
        def missing(key): raise FileNotFoundError('secret-value')
        ctx.secret = missing
        rows = service.run(ctx, CONFIG)
        self.assertEqual([r['status'] for r in rows], [0, 1, 0])
        self.assertNotIn('secret-value', str(rows))
    def test_mcp_open_or_malformed_rejection_fails(self):
        for response in ((200, {'result': {'tools': []}}), (401, {'error': 'other'})):
            ctx = Context(); ctx.responses[-1] = response
            self.assertEqual(service.run(ctx, CONFIG)[2]['status'], 1)
    def test_timeouts_and_malformed_json_do_not_leak(self):
        for exc in (TimeoutError('sensitive-session'), ValueError('private-body')):
            ctx = Context()
            def broken(*args, **kwargs): raise exc
            ctx.http = broken
            rows = service.run(ctx, CONFIG)
            self.assertEqual([r['status'] for r in rows], [1, 1, 1])
            self.assertNotIn(str(exc), str(rows))

if __name__ == '__main__': unittest.main()
