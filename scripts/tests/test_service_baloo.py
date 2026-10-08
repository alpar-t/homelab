import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('baloo_check', ROOT / 'config/zabbix/manifests/assets/service_baloo.py')
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
CONFIG = json.loads((ROOT / 'config/zabbix/manifests/assets/service_baloo.json').read_text())


def reply(result, ident=1, sse=False, status=200, headers=None):
    body = json.dumps({'jsonrpc': '2.0', 'id': ident, 'result': result})
    if sse:
        body = 'event: message\r\ndata: ' + body + '\r\n\r\n'
    return SimpleNamespace(status=status, body=body.encode(), headers={
        'Content-Type': 'text/event-stream' if sse else 'application/json', **(headers or {})})


def healthy(sse=False, session=False):
    return [reply({'protocolVersion': MODULE.PROTOCOL, 'capabilities': {'tools': {}},
                   'serverInfo': {'name': 'kubernetes'}}, sse=sse,
                  headers={'Mcp-Session-Id': 'private-session'} if session else {}),
            SimpleNamespace(status=202, body=b'', headers={}),
            reply({'tools': [{'name': name, 'inputSchema': {'type': 'object'}}
                             for name in CONFIG['required_tools']]}, ident=2, sse=sse),
            reply({'content': [{'type': 'text', 'text': json.dumps({
                'apiVersion': 'v1', 'kind': 'Service',
                'metadata': {'name': 'kubernetes', 'namespace': 'default'},
                'spec': {'ports': [{'port': 443}]}})}]}, ident=3, sse=sse)]


class Context:
    def __init__(self, replies):
        self.replies = replies
        self.calls = []

    def http(self, url, **kwargs):
        self.calls.append(kwargs)
        response = self.replies.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    def check(self, name, bad, detail, severity=3):
        return dict(name=name, status=int(bad), detail=detail, severity=severity)


class BalooTests(unittest.TestCase):
    def test_json_and_sse_with_only_fixed_read_invocation(self):
        for sse in (False, True):
            ctx = Context(healthy(sse))
            self.assertEqual(MODULE.run(ctx, CONFIG)[0]['status'], 0)
            self.assertEqual([json.loads(c['data'])['method'] for c in ctx.calls],
                             ['initialize', 'notifications/initialized', 'tools/list', 'tools/call'])
            call = json.loads(ctx.calls[-1]['data'])['params']
            self.assertEqual(call, {'name': 'kubectl_get', 'arguments': {
                'resourceType': 'services', 'name': 'kubernetes',
                'namespace': 'default', 'output': 'json'}})
            self.assertTrue(all(c['timeout'] <= 5 and c['max_bytes'] <= 262144 for c in ctx.calls))

    def test_protocol_capabilities_and_identity_required(self):
        for result in ({}, {'protocolVersion': 'unexpected'},
                       {'protocolVersion': MODULE.PROTOCOL, 'capabilities': {'tools': {}},
                        'serverInfo': {'name': 'other'}}):
            self.assertEqual(MODULE.run(Context([reply(result)]), CONFIG)[0]['status'], 1)

    def test_broken_or_missing_catalog(self):
        for tools in ([], None, [{'name': 'kubectl_get', 'inputSchema': {}}],
                      [{'name': 'other', 'inputSchema': {'type': 'object'}}],
                      [{'name': 'same', 'inputSchema': {'type': 'object'}}] * 2):
            responses = healthy()
            responses[2] = reply({'tools': tools}, ident=2)
            self.assertEqual(MODULE.run(Context(responses), CONFIG)[0]['status'], 1)

    def test_unauthorized_malformed_error_and_timeout_are_redacted(self):
        failures = [reply({}, status=401), reply({}, ident=99),
                    SimpleNamespace(status=200, headers={'Content-Type': 'text/html'}, body=b'secret'),
                    SimpleNamespace(status=200, headers={'Content-Type': 'application/json'}, body=b'{secret'),
                    SimpleNamespace(status=200, headers={'Content-Type': 'application/json'},
                                    body=b'{"jsonrpc":"2.0","id":1,"error":{"message":"secret"}}'),
                    TimeoutError('secret')]
        for response in failures:
            result = MODULE.run(Context([response]), CONFIG)[0]
            self.assertEqual(result['status'], 1)
            self.assertNotIn('secret', result['detail'])

    def test_stateful_session_is_closed_even_when_catalog_fails(self):
        for broken in (False, True):
            responses = healthy(session=True)
            if broken:
                responses[-1] = TimeoutError('private-session')
            responses.append(SimpleNamespace(status=204, body=b'', headers={}))
            ctx = Context(responses)
            result = MODULE.run(ctx, CONFIG)[0]
            self.assertEqual(result['status'], int(broken))
            self.assertEqual(ctx.calls[-1]['method'], 'DELETE')
            self.assertNotIn('private-session', result['detail'])

    def test_session_cleanup_failure_and_unsupported_termination(self):
        for response, bad in [(TimeoutError('private-session'), 1),
                              (SimpleNamespace(status=403, body=b'', headers={}), 1),
                              (SimpleNamespace(status=405, body=b'', headers={}), 0)]:
            result = MODULE.run(Context(healthy(session=True) + [response]), CONFIG)[0]
            self.assertEqual(result['status'], bad)
            self.assertNotIn('private-session', result['detail'])

    def test_failed_or_wrong_fixed_service_read(self):
        for payload in ({'isError': True, 'content': []},
                        {'content': [{'type': 'text', 'text': 'secret'}]},
                        {'content': [{'type': 'text', 'text': '{"kind":"Pod"}'}]},
                        {'content': []}):
            responses = healthy()
            responses[-1] = reply(payload, ident=3)
            result = MODULE.run(Context(responses), CONFIG)[0]
            self.assertEqual(result['status'], 1)
            self.assertNotIn('secret', result['detail'])

    def test_notification_failure_is_not_healthy(self):
        responses = healthy()
        responses[1].status = 403
        self.assertEqual(MODULE.run(Context(responses), CONFIG)[0]['status'], 1)


if __name__ == '__main__':
    unittest.main()
