import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import unittest

spec = importlib.util.spec_from_file_location("radarr", Path(__file__).resolve().parents[2] / "config/zabbix/manifests/assets/service_radarr.py")
service = importlib.util.module_from_spec(spec)
spec.loader.exec_module(service)
CONFIG = {"base_url": "http://facade:8080", "credential_key": "radarr-monitor-token"}

class Context:
    def __init__(self, health=None, roots=None, status=200, error=False, missing=False):
        self.responses = [health if health is not None else [], roots if roots is not None else []]
        self.status, self.error, self.missing = status, error, missing
        self.calls = []
    def secret(self, key):
        if self.missing:
            raise RuntimeError("sensitive key")
        return "private-token"
    def remaining(self):
        return 10
    def check(self, name, bad, detail, severity=3):
        return dict(name=name, status=int(bad), detail=detail, severity=severity)
    def http(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if self.error:
            raise RuntimeError("private-token /private/movie")
        return SimpleNamespace(status=self.status, body=json.dumps(self.responses.pop(0)).encode())

class RadarrTests(unittest.TestCase):
    def test_empty_healthy(self):
        ctx = Context()
        self.assertEqual([r["status"] for r in service.run(ctx, CONFIG)], [0, 0])
        self.assertEqual(len(ctx.calls), 2)
        for url, kw in ctx.calls:
            self.assertTrue(url.endswith(("/health", "/rootfolder")))
            self.assertFalse(kw["follow_redirects"])
            self.assertLessEqual(kw["timeout"], 5)
            self.assertLessEqual(kw["max_bytes"], 131072)
    def test_native_dependency_and_storage_failures_redacted(self):
        rows = service.run(Context(health=[{"type":"error", "source":"DownloadClientCheck", "message":"private-title"}], roots=[{"accessible":False, "path":"/private/movie"}]), CONFIG)
        self.assertEqual([r["status"] for r in rows], [1, 1])
        self.assertNotIn("private", str(rows))
    def test_notice_and_accessible_root(self):
        rows = service.run(Context(health=[{"type":"notice", "source":"Check"}], roots=[{"accessible":True}]), CONFIG)
        self.assertEqual([r["status"] for r in rows], [0, 0])
    def test_bad_schema(self):
        for health, roots in [("html", {}), ([{"type":"unknown", "source":"x"}], [{"accessible":"false"}])]:
            self.assertEqual([r["status"] for r in service.run(Context(health, roots), CONFIG)], [1, 1])
    def test_http_and_transport_errors(self):
        for ctx in (Context(status=401), Context(status=302), Context(status=500), Context(error=True)):
            rows = service.run(ctx, CONFIG)
            self.assertEqual([r["status"] for r in rows], [1, 1])
            self.assertNotIn("private", str(rows))
    def test_missing_credentials(self):
        ctx = Context(missing=True)
        self.assertEqual([r["status"] for r in service.run(ctx, CONFIG)], [1, 1])
        self.assertEqual(ctx.calls, [])
    def test_deadline(self):
        ctx = Context()
        ctx.remaining = lambda: 0
        self.assertEqual([r["status"] for r in service.run(ctx, CONFIG)], [1, 1])
        self.assertEqual(ctx.calls, [])

if __name__ == "__main__":
    unittest.main()
