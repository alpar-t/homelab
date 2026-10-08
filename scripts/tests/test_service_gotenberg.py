import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('gotenberg', ROOT / 'config/zabbix/manifests/assets/service_gotenberg.py')
service = importlib.util.module_from_spec(spec)
spec.loader.exec_module(service)


class Context:
    def __init__(self, response=None, error=None, remaining=12):
        self.response, self.error, self.budget = response, error, remaining
        self.calls = []

    def remaining(self):
        return self.budget

    def http(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if self.error:
            raise self.error
        return self.response

    def check(self, name, bad, detail, severity=3):
        return dict(name=name, status=int(bad), detail=detail, severity=severity)


def response(status=200, body=None, headers=None):
    return SimpleNamespace(status=status,
                           body=body if body is not None else b'%PDF-1.7\n' + b'x' * 600 + b'\n%%EOF\n',
                           headers=headers if headers is not None else {'Content-Type': 'application/pdf'})


class GotenbergTests(unittest.TestCase):
    config = {'url': 'http://gotenberg:3000/forms/chromium/convert/html'}

    def test_conversion_and_bounded_self_contained_multipart(self):
        ctx = Context(response())
        self.assertEqual(service.run(ctx, self.config)[0]['status'], 0)
        url, request = ctx.calls[0]
        self.assertEqual(url, self.config['url'])
        self.assertEqual(request['method'], 'POST')
        self.assertEqual(request['timeout'], 12)
        self.assertEqual(request['max_bytes'], 262144)
        self.assertFalse(request['follow_redirects'])
        self.assertIn(b'name="files"; filename="index.html"', request['data'])
        self.assertIn(service.HTML, request['data'])
        self.assertNotIn(b'http', service.HTML)
        self.assertNotIn(b'<script', service.HTML)

    def test_broken_unauthorized_redirected(self):
        for status in (400, 401, 403, 302, 503):
            with self.subTest(status=status):
                result = service.run(Context(response(status=status)), self.config)[0]
                self.assertEqual(result['status'], 1)

    def test_malformed_or_truncated_pdf(self):
        cases = [response(body=b'<html>login</html>'), response(body=b'%PDF-1.7\n%%EOF'),
                 response(body=b'%PDF-1.7' + b'x' * 600),
                 response(body=b'%PDF-' + b'x' * 262144 + b'%%EOF'),
                 response(headers={'Content-Type': 'text/html'})]
        for item in cases:
            with self.subTest(size=len(item.body), headers=item.headers):
                self.assertEqual(service.run(Context(item), self.config)[0]['status'], 1)

    def test_header_case_and_parameters(self):
        ctx = Context(response(headers={'content-type': 'application/pdf; charset=binary'}))
        self.assertEqual(service.run(ctx, self.config)[0]['status'], 0)

    def test_errors_redacted_and_deadline(self):
        for error in (TimeoutError('secret body'), ValueError('private URL')):
            result = service.run(Context(error=error), self.config)[0]
            self.assertEqual(result['status'], 1)
            self.assertNotIn(str(error), result['detail'])
        ctx = Context(remaining=0)
        self.assertEqual(service.run(ctx, self.config)[0]['status'], 1)
        self.assertEqual(ctx.calls, [])


if __name__ == '__main__':
    unittest.main()
