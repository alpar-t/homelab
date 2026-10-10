import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[2]
ASSETS = ROOT / 'config/zabbix/manifests/assets'
spec = importlib.util.spec_from_file_location('service_searxng', ASSETS / 'service_searxng.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
CONFIG = json.loads((ASSETS / 'service_searxng.json').read_text())


def response(data, status=200, headers=None):
    return SimpleNamespace(status=status, body=json.dumps(data).encode(), headers=headers or {})


class Context:
    def __init__(self, search=None, tools=None):
        self.search = search or response({'query': 'Kubernetes', 'results': [{'title': 'Example', 'url': 'https://example.org/'}], 'unresponsive_engines': [['google', 'timeout']]})
        self.tools = tools or response({'jsonrpc': '2.0', 'id': 2, 'result': {'tools': [{'name': 'searxng_web_search', 'inputSchema': {'type': 'object'}}]}})
        self.calls = []
    def remaining(self):
        return 25
    def check(self, name, bad, detail, severity=3):
        return dict(name=name, status=int(bool(bad)), detail=detail, severity=severity)
    def http(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if '/search?' in url:
            if isinstance(self.search, Exception):
                raise self.search
            return self.search
        if kwargs['method'] == 'DELETE':
            return response({}, 200)
        method = json.loads(kwargs['data'])['method']
        if method == 'initialize':
            return response({'jsonrpc': '2.0', 'id': 1, 'result': {'protocolVersion': '2024-11-05', 'capabilities': {'tools': {}}}}, headers={'Mcp-Session-Id': 'test-session'})
        if method == 'notifications/initialized':
            return response({}, 202)
        return self.tools


class Tests(unittest.TestCase):
    def test_healthy_partial_engine_failure_and_session_cleanup(self):
        ctx = Context()
        self.assertEqual([r['status'] for r in module.run(ctx, CONFIG)], [0, 0])
        self.assertEqual(ctx.calls[-1][1]['method'], 'DELETE')
        self.assertTrue(all(c[1]['timeout'] <= 12 and c[1]['max_bytes'] <= 262144 for c in ctx.calls))
        self.assertEqual(ctx.calls[-2][1]['headers']['Mcp-Session-Id'], 'test-session')

    def test_search_empty_malformed_unauthorized_and_timeout(self):
        for search in [response({'query': 'Kubernetes', 'results': []}), response({'query': 'wrong', 'results': []}),
                       response([], 200), response({}, 401), TimeoutError('sensitive body'),
                       response({'query': 'Kubernetes', 'results': [{'title': 'X', 'url': 'javascript:alert(1)'}]})]:
            rows = module.run(Context(search=search), CONFIG)
            self.assertEqual([r['status'] for r in rows], [1, 0])
            self.assertNotIn('sensitive', str(rows))

    def test_mcp_missing_tool_error_and_bad_http(self):
        for tools in [response({'jsonrpc': '2.0', 'id': 2, 'result': {'tools': []}}),
                      response({'jsonrpc': '2.0', 'id': 2, 'error': {'message': 'sensitive'}}), response({}, 401)]:
            rows = module.run(Context(tools=tools), CONFIG)
            self.assertEqual([r['status'] for r in rows], [0, 1])
            self.assertNotIn('sensitive', str(rows))

    def test_sse_catalog(self):
        ctx = Context()
        ctx.tools.body = b'event: message\ndata: ' + ctx.tools.body + b'\n\n'
        self.assertEqual([r['status'] for r in module.run(ctx, CONFIG)], [0, 0])


if __name__ == '__main__':
    unittest.main()
