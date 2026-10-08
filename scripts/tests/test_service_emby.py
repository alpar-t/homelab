import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[2]
ASSETS = ROOT / "config/zabbix/manifests/assets"
spec = importlib.util.spec_from_file_location("emby", ASSETS / "service_emby.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
CONFIG = json.loads((ASSETS / "service_emby.json").read_text())

class Context:
    def __init__(self, public=None, library=None, status=200, missing=False, fail=False):
        self.public = public if public is not None else {"Version": "4.9.3.0", "Id": "server"}
        self.library = library if library is not None else {"Items": [], "TotalRecordCount": 0}
        self.status, self.missing, self.fail = status, missing, fail
        self.calls = []
    def remaining(self): return 10
    def check(self, name, bad, detail, severity=3):
        return dict(name=name, status=int(bool(bad)), detail=detail, severity=severity)
    def secret(self, key):
        if self.missing: raise RuntimeError("secret-private")
        return "a" * 32 if key.endswith("user_id") else "secret-private"
    def http(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if self.fail: raise TimeoutError("private-url-and-title")
        public = url.endswith("/Public")
        return SimpleNamespace(status=200 if public else self.status,
                               body=json.dumps(self.public if public else self.library).encode())

class EmbyTests(unittest.TestCase):
    def test_empty_and_one_item(self):
        for library in ({"Items": [], "TotalRecordCount": 0},
                        {"Items": [{"Id": "private-id", "Type": "Folder", "Name": "private-title"}], "TotalRecordCount": 2}):
            ctx = Context(library=library)
            result = module.run(ctx, CONFIG)
            self.assertEqual([r["status"] for r in result], [0, 0])
            self.assertNotIn("private", json.dumps(result))
            self.assertEqual(ctx.calls[1][1]["headers"], {"X-Emby-Token": "secret-private"})
            self.assertNotIn("secret-private", ctx.calls[1][0])
            self.assertLessEqual(ctx.calls[1][1]["timeout"], ctx.remaining())
    def test_public_contract(self):
        for public in ({}, {"Version": "html", "Id": "x"}, {"Version": "4.9.3.0", "Id": None}, []):
            self.assertEqual(module.run(Context(public=public), CONFIG)[0]["status"], 1)
    def test_library_malformed(self):
        for library in ({}, {"Items": [], "TotalRecordCount": 2}, {"Items": [], "TotalRecordCount": True}, {"Items": [{"Name": "private"}], "TotalRecordCount": 1}, {"Items": [], "TotalRecordCount": -1}):
            self.assertEqual(module.run(Context(library=library), CONFIG)[1]["status"], 1)
    def test_unauthorized_and_errors(self):
        for status in (401, 403, 500, 302):
            self.assertEqual(module.run(Context(status=status), CONFIG)[1]["status"], 1)
        for ctx in (Context(missing=True), Context(fail=True)):
            result = module.run(ctx, CONFIG)
            self.assertEqual(result[1]["status"], 1)
            self.assertNotIn("private", json.dumps(result))
        ctx = Context(missing=True)
        module.run(ctx, CONFIG)
        self.assertEqual(len(ctx.calls), 1)

if __name__ == "__main__": unittest.main()
