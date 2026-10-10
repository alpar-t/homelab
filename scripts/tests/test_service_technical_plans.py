import copy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import unittest

SPEC = importlib.util.spec_from_file_location("service", Path(__file__).resolve().parents[2] / "config/zabbix/manifests/assets/service_technical_plans.py")
service = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(service)


def document():
    doc = {"openapi": "3.1.0", "info": {"title": "Newjoy Verified Artifact Preview"}, "paths": {}, "components": {"schemas": {}}}
    for path, model, fields in (("preview_opencloud_pdf", "PreviewPdf", ["path"]), ("preview_opencloud_image", "PreviewWebsiteImage", ["path"]), ("import_plan_attachment", "ImportAttachment", ["filename", "projectPath", "destinationKind"])):
        doc["paths"]["/" + path] = {"post": {"operationId": path, "responses": {"200": {}}, "requestBody": {"required": True, "content": {"application/json": {"schema": {"$ref": "#/components/schemas/" + model}}}}}}
        doc["components"]["schemas"][model] = {"type": "object", "additionalProperties": False, "required": fields, "properties": {f: {"type": "string"} for f in fields}}
    return doc


class Context:
    def __init__(self, responses):
        self.responses, self.calls = iter(responses), []
    def remaining(self): return 20
    def check(self, name, bad, detail): return {"name": name, "status": int(bad), "detail": detail}
    def http(self, url, **kwargs):
        self.calls.append((url, kwargs))
        value = next(self.responses)
        if isinstance(value, Exception): raise value
        return SimpleNamespace(status=value[0], body=value[1])


class Tests(unittest.TestCase):
    def run_check(self, first=None, second=None):
        ctx = Context([first or (200, json.dumps(document()).encode()), second or (401, b'{"detail":"Bearer authentication is required"}')])
        return service.run(ctx, {"url": "http://service:18809"}), ctx

    def test_healthy_and_bounded_without_credentials(self):
        rows, ctx = self.run_check()
        self.assertEqual([r["status"] for r in rows], [0, 0])
        for _, opts in ctx.calls:
            self.assertLessEqual(opts["timeout"], 8)
            self.assertLessEqual(opts["max_bytes"], 131072)
            self.assertNotIn("Authorization", opts.get("headers", {}))
        self.assertEqual(ctx.calls[1][1]["data"], b"{}")

    def test_incompatible_contracts(self):
        for mutation in (lambda d: d.update(openapi="2.0"), lambda d: d["paths"].pop("/import_plan_attachment"), lambda d: d["components"]["schemas"]["PreviewPdf"].update(additionalProperties=True), lambda d: d["components"]["schemas"]["PreviewPdf"].update(required=[])):
            doc = copy.deepcopy(document()); mutation(doc)
            rows, _ = self.run_check((200, json.dumps(doc).encode()))
            self.assertEqual(rows[0]["status"], 1)

    def test_missing_guard_and_wrong_service(self):
        for status, body in ((200, b'{}'), (404, b'{}'), (403, b'{}'), (401, b'{"detail":"different"}')):
            rows, _ = self.run_check(second=(status, body))
            self.assertEqual(rows[1]["status"], 1)

    def test_malformed_auth_http_timeout_are_redacted(self):
        for response in ((401, b'private'), (200, b'not-json'), TimeoutError("sensitive token")):
            rows, _ = self.run_check(response, TimeoutError("private path"))
            self.assertEqual([r["status"] for r in rows], [1, 1])
            self.assertNotIn("sensitive", str(rows))
            self.assertNotIn("private", str(rows))


if __name__ == "__main__": unittest.main()
