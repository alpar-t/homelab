import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import unittest

spec = importlib.util.spec_from_file_location("opencloud", Path(__file__).resolve().parents[2] / "config/zabbix/manifests/assets/service_opencloud.py")
service = importlib.util.module_from_spec(spec)
spec.loader.exec_module(service)
PATH = "/dav/spaces/monitor/"
XML = b'<d:multistatus xmlns:d="DAV:"><d:response><d:href>/dav/spaces/monitor/</d:href><d:propstat><d:prop><d:resourcetype><d:collection/></d:resourcetype><d:getetag>test-etag</d:getetag></d:prop><d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response></d:multistatus>'
STATUS = {"installed": True, "maintenance": False, "version": "7.2", "productname": "OpenCloud"}

class Context:
    def __init__(self, responses, missing=False):
        self.responses, self.calls, self.missing = list(responses), [], missing
    def remaining(self):
        return 20
    def secret(self, key):
        if self.missing:
            raise RuntimeError("sensitive token")
        return "sensitive-token"
    def check(self, name, bad, detail, severity=3):
        return dict(name=name, status=int(bad), detail=detail, severity=severity)
    def http(self, url, **kwargs):
        self.calls.append((url, kwargs))
        result = self.responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

def response(status, body):
    return SimpleNamespace(status=status, body=body, headers={})

class OpenCloudTests(unittest.TestCase):
    def run_check(self, status=STATUS, dav=XML, code=207, missing=False, path=PATH):
        ctx = Context([response(200, json.dumps(status).encode()), response(code, dav)], missing)
        rows = service.run(ctx, {"base_url": "https://drive.newjoy.ro", "workspace_path": path})
        self.assertNotIn("sensitive", str(rows))
        self.assertNotIn("test-etag", str(rows))
        return rows, ctx
    def test_healthy_read_only_bounded(self):
        rows, ctx = self.run_check()
        self.assertEqual([r["status"] for r in rows], [0, 0])
        request = ctx.calls[1][1]
        self.assertEqual(request["method"], "PROPFIND")
        self.assertEqual(request["headers"]["Depth"], "0")
        self.assertLessEqual(request["timeout"], 8)
        self.assertEqual(request["max_bytes"], 32768)
        self.assertNotIn(b"displayname", request["data"])
    def test_status_maintenance_or_wrong_product(self):
        for change in ({"maintenance": True}, {"productname": "other"}, {"installed": "true"}, {"version": ""}):
            rows, _ = self.run_check(status=dict(STATUS, **change))
            self.assertEqual(rows[0]["status"], 1)
    def test_auth_redirect_missing_credentials_and_workspace(self):
        for code in (401, 403, 302, 404, 500):
            self.assertEqual(self.run_check(code=code)[0][1]["status"], 1)
        for options in ({"missing": True}, {"path": ""}, {"path": "/dav/spaces/../"}, {"path": PATH + "?token=secret"}):
            rows, ctx = self.run_check(**options)
            self.assertEqual(rows[1]["status"], 1)
            self.assertEqual(len(ctx.calls), 1)
    def test_multistatus_is_not_success_without_properties(self):
        for body in (b'<html/>', b'invalid', XML.replace(b'200 OK', b'403 Forbidden'), XML.replace(b'<d:collection/>', b''), XML.replace(b'test-etag', b''), XML.replace(b'/monitor/', b'/other/'), XML.replace(b'</d:multistatus>', XML[XML.index(b'<d:response>'):XML.index(b'</d:multistatus>')] + b'</d:multistatus>'), b'<!DOCTYPE foo>' + XML):
            self.assertEqual(self.run_check(dav=body)[0][1]["status"], 1)
    def test_network_errors_and_malformed_status_safe(self):
        for responses in ([TimeoutError("sensitive-token"), response(207, XML)], [response(200, b'<html>sensitive-token</html>'), TimeoutError("sensitive-token")]):
            ctx = Context(responses)
            rows = service.run(ctx, {"base_url": "https://drive.newjoy.ro", "workspace_path": PATH})
            self.assertEqual(rows[0]["status"], 1)
            self.assertNotIn("sensitive-token", str(rows))

if __name__ == "__main__":
    unittest.main()
