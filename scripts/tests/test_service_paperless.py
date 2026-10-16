import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

ASSETS = Path(__file__).resolve().parents[2] / "config/zabbix/manifests/assets"
spec = importlib.util.spec_from_file_location("paperless_check", ASSETS / "service_paperless.py")
service = importlib.util.module_from_spec(spec)
spec.loader.exec_module(service)
CONFIG = json.loads((ASSETS / "service_paperless.json").read_text())


class Context:
    def __init__(self, value=None, status=200):
        self.value = value if value is not None else {"count": 0, "results": []}
        self.status = status
        self.requests = []
    def remaining(self):
        return 25
    def secret(self, key):
        return "private-test-token"
    def http(self, url, **kwargs):
        self.requests.append((url, kwargs))
        return SimpleNamespace(status=self.status, body=json.dumps(self.value).encode())
    def check(self, name, bad, detail, severity=3):
        return dict(name=name, status=int(bool(bad)), detail=detail, severity=severity)


class PaperlessTests(unittest.TestCase):
    def test_document_coverage_is_deferred_without_credential_or_http_access(self):
        for legacy in ({}, {"token_key":"admin", "documents_url":"http://private/api/documents/"}):
            ctx = Context()
            ctx.secret = MagicMock(side_effect=AssertionError("unsafe credential read"))
            ctx.http = MagicMock(side_effect=AssertionError("unsafe document read"))
            result = service.documents(ctx, dict(CONFIG, **legacy))
            self.assertEqual(result["status"], 1)
            self.assertEqual(result["severity"], 1)
            self.assertEqual(result["observation"], "deferred")
            self.assertEqual(result["notification"], "dashboard")
            self.assertIn("ownerless", result["detail"])
            ctx.secret.assert_not_called()
            ctx.http.assert_not_called()
    def test_redis_fragmented_pong(self):
        conn = MagicMock()
        conn.__enter__.return_value = conn
        conn.recv.side_effect = [b"+PO", b"NG\r\n"]
        with patch.object(service.socket, "create_connection", return_value=conn):
            self.assertEqual(service.redis(Context(), CONFIG)["status"], 0)
        conn.sendall.assert_called_once_with(b"*1\r\n$4\r\nPING\r\n")
    def test_redis_error_eof_and_oversize(self):
        for replies in ([b"-NOAUTH\r\n"], [b""], [b"x" * 64]):
            conn = MagicMock()
            conn.__enter__.return_value = conn
            conn.recv.side_effect = replies
            with patch.object(service.socket, "create_connection", return_value=conn):
                self.assertEqual(service.redis(Context(), CONFIG)["status"], 1)
        with patch.object(service.socket, "create_connection", side_effect=TimeoutError("PRIVATE")):
            result = service.redis(Context(), CONFIG)
            self.assertEqual(result["status"], 1)
            self.assertNotIn("PRIVATE", result["detail"])
    def test_run_preserves_redis_when_credentials_missing(self):
        ctx = Context()
        ctx.secret = MagicMock(side_effect=OSError())
        with patch.object(service, "redis", return_value=ctx.check("Paperless Redis protocol", False, "okay")):
            records = service.run(ctx, CONFIG)
        self.assertEqual([row["status"] for row in records], [1, 0])
        self.assertEqual(records[0]["observation"], "deferred")
        self.assertEqual(records[0]["notification"], "dashboard")
        self.assertFalse(ctx.requests)


if __name__ == "__main__":
    unittest.main()
