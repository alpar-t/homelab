import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("prowlarr", ROOT / "config/zabbix/manifests/assets/service_prowlarr.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
CONFIG = json.loads((ROOT / "config/zabbix/manifests/assets/service_prowlarr.json").read_text())


class Context:
    now = 1700000000
    def __init__(self, health=None, indexers=None, statuses=None):
        self.payloads = [health or [], indexers or [], statuses or []]
        self.calls = []
        self.code = 200
        self.missing = False
        self.error = False
    def remaining(self):
        return 20
    def secret(self, key):
        if self.missing:
            raise RuntimeError("secret-marker")
        return "secret-marker"
    def check(self, name, bad, detail, severity=3):
        return dict(name=name, status=int(bad), detail=detail, severity=severity)
    def http(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if self.error:
            raise TimeoutError("secret-marker private-url")
        return SimpleNamespace(status=self.code, body=json.dumps(self.payloads.pop(0)).encode())


class Checks(unittest.TestCase):
    def test_empty_and_fixed_gets(self):
        ctx = Context()
        self.assertEqual([r["status"] for r in module.run(ctx, CONFIG)], [0, 0])
        self.assertEqual([c[0].rsplit("/", 1)[-1] for c in ctx.calls], ["health", "indexer", "indexerstatus"])
        for _, kwargs in ctx.calls:
            self.assertNotIn("data", kwargs)
            self.assertNotIn("method", kwargs)
            self.assertFalse(kwargs["follow_redirects"])
            self.assertLessEqual(kwargs["timeout"], 6)
    def test_enabled_blocked_and_disabled(self):
        status = [{"indexerId": 1, "disabledTill": "2030-01-01T00:00:00Z"}]
        for enabled, expected in ((True, 1), (False, 0)):
            ctx = Context(indexers=[{"id": 1, "enable": enabled}], statuses=status)
            self.assertEqual(module.run(ctx, CONFIG)[1]["status"], expected)
    def test_expired_failure(self):
        ctx = Context(indexers=[{"id": 1, "enable": True}], statuses=[{"indexerId": 1, "disabledTill": "2000-01-01T00:00:00Z"}])
        self.assertEqual(module.run(ctx, CONFIG)[1]["status"], 0)
    def test_health_errors_and_empty_warning(self):
        ctx = Context(health=[{"source": "DatabaseCheck", "type": "error", "message": "secret-marker"}])
        result = module.run(ctx, CONFIG)
        self.assertEqual(result[0]["status"], 1)
        self.assertNotIn("secret-marker", str(result))
        ctx = Context(health=[{"source": "NoIndexerAvailableCheck", "type": "error"}])
        self.assertEqual(module.run(ctx, CONFIG)[0]["status"], 0)
    def test_schema_rejected(self):
        cases = [Context(indexers=[{"id": 1, "enable": "true"}]), Context(health=[{"source": "x", "type": "unknown"}]), Context(statuses=[{"indexerId": 1, "disabledTill": "invalid"}])]
        for ctx in cases:
            self.assertTrue(all(r["status"] for r in module.run(ctx, CONFIG)))
    def test_unavailable_auth_timeout_missing(self):
        for code in (401, 403, 302, 500):
            ctx = Context(); ctx.code = code
            self.assertTrue(all(r["status"] for r in module.run(ctx, CONFIG)))
        for flag in ("missing", "error"):
            ctx = Context(); setattr(ctx, flag, True)
            result = module.run(ctx, CONFIG)
            self.assertTrue(all(r["status"] for r in result))
            self.assertNotIn("secret-marker", str(result))
