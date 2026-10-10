import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import unittest

spec = importlib.util.spec_from_file_location("service", Path(__file__).resolve().parents[2] / "config/zabbix/manifests/assets/service_zabbix.py")
service = importlib.util.module_from_spec(spec)
spec.loader.exec_module(service)


def response(body, status=200, kind="text/html"):
    return SimpleNamespace(body=body, status=status, headers={"Content-Type": kind})


class Context:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    def remaining(self):
        return 25

    def http(self, url, **kwargs):
        self.calls.append((url, kwargs))
        result = next(self.responses)
        if isinstance(result, Exception):
            raise result
        return result

    def check(self, name, bad, detail):
        return dict(name=name, status=int(bad), detail=detail)


API = response(b'{"jsonrpc":"2.0","id":1,"result":"7.0.31"}', kind="application/json")
PAGE = response(b'<input name="name"><input name="password"><link rel="stylesheet" href="assets/styles/blue.css?123">')
CSS = response(b'body { color: black; }' * 10, kind="text/css; charset=UTF-8")
CONFIG = {"base_url": "http://zabbix-web/"}


class ZabbixTests(unittest.TestCase):
    def test_healthy_and_bounded_rpc(self):
        ctx = Context([API, PAGE, CSS])
        self.assertEqual([r["status"] for r in service.run(ctx, CONFIG)], [0, 0])
        self.assertEqual(json.loads(ctx.calls[0][1]["data"])["method"], "apiinfo.version")
        self.assertNotIn("Authorization", ctx.calls[0][1]["headers"])
        self.assertTrue(all(c[1]["timeout"] <= 6 for c in ctx.calls))

    def test_rpc_errors_and_malformed(self):
        for bad in [response(b'{}'), response(b'not json'), response(b'{"jsonrpc":"2.0","id":2,"result":"7.0.31"}'), response(b'{"jsonrpc":"2.0","id":1,"result":"7.0.31","error":{}}'), response(API.body, 401), TimeoutError("private secret")]:
            with self.subTest(bad=bad):
                rows = service.run(Context([bad, PAGE, CSS]), CONFIG)
                self.assertEqual([r["status"] for r in rows], [1, 0])
                self.assertNotIn("private secret", str(rows))

    def test_frontend_failures(self):
        for page, asset in [(response(b'<html>upgrade failed</html>'), CSS), (response(PAGE.body, 302), CSS), (PAGE, response(b'<html>login</html>', kind="text/css")), (PAGE, response(CSS.body, 404)), (PAGE, response(CSS.body, kind="text/html")), (PAGE, TimeoutError())]:
            with self.subTest(page=page, asset=asset):
                self.assertEqual(service.run(Context([API, page, asset]), CONFIG)[1]["status"], 1)

    def test_external_asset_not_fetched(self):
        ctx = Context([API, response(b'<input name="name"><input name="password"><link rel="stylesheet" href="https://external.example/style.css">')])
        self.assertEqual(service.run(ctx, CONFIG)[1]["status"], 1)
        self.assertEqual(len(ctx.calls), 2)
