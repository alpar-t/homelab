import importlib.util
from pathlib import Path
from types import SimpleNamespace
import json
import unittest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("service", ROOT / "config/zabbix/manifests/assets/service_interior_designer.py")
service = importlib.util.module_from_spec(spec)
spec.loader.exec_module(service)

class Context:
    def __init__(self):
        self.calls = []
        self.responses = {
            "/api/version": {"version": "0.11.3"},
            "/api/config": {"status": True, "version": "0.11.3", "oauth": {"providers": {"oidc": "Pocket ID"}}, "features": {"auth": True, "enable_signup": False, "enable_login_form": False}},
            "/": b'<html><link href="/_app/immutable/entry/start.abc.js"><link href="/_app/immutable/entry/app.def.js"></html>',
            "/_app/immutable/entry/start.abc.js": b'export function start(){return "synthetic fixture entry module"}',
            "/_app/immutable/entry/app.def.js": b'import {start} from "./start.abc.js";export const app = start;',
        }
    def remaining(self): return 30
    def check(self, name, bad, detail, severity=3): return dict(name=name,status=int(bool(bad)),detail=detail,severity=severity)
    def http(self, url, **kwargs):
        self.calls.append((url, kwargs))
        path = url.removeprefix("http://webui")
        value = self.responses[path]
        if isinstance(value, Exception): raise value
        if isinstance(value, SimpleNamespace): return value
        return SimpleNamespace(status=200, headers={"Content-Type": "text/html" if path == "/" else "application/javascript"}, body=json.dumps(value).encode() if isinstance(value,dict) else value)

class Tests(unittest.TestCase):
    def run_check(self, ctx): return service.run(ctx, {"url":"http://webui"})
    def test_healthy_and_bounded_readonly(self):
        ctx=Context(); self.assertEqual([r["status"] for r in self.run_check(ctx)], [0,0])
        self.assertEqual(len(ctx.calls),5)
        self.assertTrue(all(k["timeout"] <= 5 and k["max_bytes"] <= 1048576 for _,k in ctx.calls))
    def test_config_invalid(self):
        for value in [b'<html>login</html>', {}, {"status": True}, SimpleNamespace(status=401,headers={},body=b'private'), TimeoutError("private")]:
            with self.subTest(value=type(value).__name__):
                ctx=Context();ctx.responses["/api/config"]=value
                rows=self.run_check(ctx);self.assertEqual(rows[0]["status"],1);self.assertNotIn("private",str(rows))
    def test_version_mismatch_and_onboarding(self):
        for key,value in [("version","0.11.4"),("onboarding",True)]:
            ctx=Context();ctx.responses["/api/config"][key]=value
            self.assertEqual(self.run_check(ctx)[0]["status"],1)
    def test_bad_assets(self):
        for value in [b'<html>fallback</html>',b'',TimeoutError(),SimpleNamespace(status=404,headers={},body=b'')]:
            ctx=Context();ctx.responses["/_app/immutable/entry/start.abc.js"]=value
            self.assertEqual(self.run_check(ctx)[1]["status"],1)
    def test_external_asset_not_fetched(self):
        ctx=Context();ctx.responses["/"]=b'<html><script src="https://external/entry/start.abc.js"></script></html>'
        self.assertEqual(self.run_check(ctx)[1]["status"],1)
        self.assertEqual(len(ctx.calls),3)
    def test_deadline(self):
        ctx=Context();ctx.remaining=lambda:0
        self.assertEqual([r["status"] for r in self.run_check(ctx)],[1,1]);self.assertFalse(ctx.calls)

if __name__ == "__main__": unittest.main()
