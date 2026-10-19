import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import unittest

path = Path(__file__).resolve().parents[2] / "config/zabbix/manifests/assets/service_qbittorrent.py"
spec = importlib.util.spec_from_file_location("qbit", path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

class Context:
    def __init__(self, connection="connected", queue=None, status=200, broken=None):
        self.calls = []
        self.responses = [b"v5.1.4", json.dumps({"connection_status": connection, "dl_info_speed": 0, "up_info_speed": 0}).encode(), json.dumps(queue or []).encode()]
        self.status, self.broken = status, broken
    def remaining(self):
        return 20
    def check(self, name, bad, detail, severity=3):
        return dict(name=name, status=int(bad), detail=detail, severity=severity)
    def http(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if isinstance(self.broken, Exception):
            raise self.broken
        body = self.responses.pop(0)
        return SimpleNamespace(status=self.status, body=self.broken if isinstance(self.broken, bytes) else body)

class Tests(unittest.TestCase):
    def run_check(self, ctx):
        return module.run(ctx, {"url": "http://qbittorrent.media.svc.cluster.local:8080"})
    def test_connected_and_firewalled(self):
        for connection in ("connected", "firewalled"):
            ctx = Context(connection)
            self.assertEqual([0, 0], [r["status"] for r in self.run_check(ctx)])
            self.assertEqual(2, len(ctx.calls))
            for _, kwargs in ctx.calls:
                self.assertLessEqual(kwargs["timeout"], 5)
                self.assertNotIn("data", kwargs)
    def test_idle_disconnected(self):
        self.assertEqual([0, 0], [r["status"] for r in self.run_check(Context("disconnected"))])
    def test_offline_download_and_redaction(self):
        ctx = Context("disconnected", [{"state": "stalledDL", "name": "PRIVATE", "hash": "SECRET"}])
        records = self.run_check(ctx)
        self.assertEqual([0, 1], [r["status"] for r in records])
        self.assertNotIn("PRIVATE", str(records))
        self.assertNotIn("SECRET", str(records))
    def test_bad_session(self):
        for ctx in (Context(status=403), Context(broken=b"<html>login</html>"), Context(broken=TimeoutError("PRIVATE"))):
            records = self.run_check(ctx)
            self.assertEqual([1, 1], [r["status"] for r in records])
            self.assertNotIn("PRIVATE", str(records))
    def test_malformed_transfer(self):
        for payload in (b"{}", b"[]", b"null", b"broken", b'{"connection_status":"connected","dl_info_speed":true,"up_info_speed":0}'):
            ctx = Context()
            ctx.responses[1] = payload
            self.assertEqual([0, 1], [r["status"] for r in self.run_check(ctx)])
    def test_malformed_queue(self):
        ctx = Context("disconnected")
        ctx.responses[2] = b"{}"
        self.assertEqual([0, 1], [r["status"] for r in self.run_check(ctx)])
    def test_expired_deadline(self):
        ctx = Context()
        ctx.remaining = lambda: 0
        self.assertEqual([1, 1], [r["status"] for r in self.run_check(ctx)])
        self.assertFalse(ctx.calls)
