import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import unittest

ASSETS = Path(__file__).resolve().parents[2] / 'config/zabbix/manifests/assets'
spec = importlib.util.spec_from_file_location('service_tika', ASSETS / 'service_tika.py')
tika = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tika)
CONFIG = json.loads((ASSETS / 'service_tika.json').read_text())


class Context:
    def __init__(self, responses):
        self.responses, self.calls = iter(responses), []

    def remaining(self):
        return 6

    def http(self, url, **kwargs):
        self.calls.append((url, kwargs))
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return response

    def check(self, name, bad, detail, severity=3):
        return dict(name=name, status=int(bad), detail=detail, severity=severity)


def response(status=200, body=tika.PAYLOAD, content_type='text/plain; charset=UTF-8'):
    return SimpleNamespace(status=status, headers={'Content-Type': content_type}, body=body)


class TikaTests(unittest.TestCase):
    def test_both_instances_and_bounds(self):
        ctx = Context([response(), response(body=b'\n' + tika.PAYLOAD + b'\n')])
        self.assertEqual([r['status'] for r in tika.run(ctx, CONFIG)], [0, 0])
        self.assertEqual(len(ctx.calls), 2)
        self.assertNotEqual(ctx.calls[0][0], ctx.calls[1][0])
        for _, call in ctx.calls:
            self.assertEqual(call['method'], 'PUT')
            self.assertEqual(call['data'], tika.PAYLOAD)
            self.assertEqual(call['timeout'], 5)
            self.assertEqual(call['max_bytes'], 4096)

    def test_broken_responses_are_independent(self):
        for broken in (response(status=401), response(status=422), response(status=500),
                       response(status=204, body=b''), response(body=b''),
                       response(body=b'wrong text'), response(body=b'\xff'),
                       response(content_type='text/html'),
                       TimeoutError('private-url-and-body'), ValueError('response exceeds limit')):
            with self.subTest(broken=broken):
                records = tika.run(Context([broken, response()]), CONFIG)
                self.assertEqual([r['status'] for r in records], [1, 0])
                self.assertNotIn('private-url', str(records))
                self.assertNotIn('wrong text', str(records))

    def test_header_case(self):
        reply = response()
        reply.headers = {'content-type': 'TEXT/PLAIN'}
        self.assertEqual(tika.run(Context([reply, reply]), CONFIG)[0]['status'], 0)


if __name__ == '__main__':
    unittest.main()
