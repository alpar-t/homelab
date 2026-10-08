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
    def test_empty_and_nonempty_database(self):
        for value in ({"count": 0, "results": []}, {"count": 25, "results": [{"id": 2}]}):
            ctx = Context(value)
            self.assertEqual(service.documents(ctx, CONFIG)["status"], 0)
            url, kwargs = ctx.requests[0]
            self.assertIn("fields=id", url)
            self.assertIn("page_size=1", url)
            self.assertEqual(kwargs["headers"]["Authorization"], "Token private-test-token")
            self.assertLessEqual(kwargs["timeout"], ctx.remaining())
    def test_broken_schema_and_unrequested_data(self):
        for value in ({}, [], {"count": True, "results": []}, {"count": 1, "results": []},
                      {"count": 1, "results": [{"id": 2, "title": "PRIVATE"}]},
                      {"count": 1, "results": [{"id": "2"}]}):
            result = service.documents(Context(value), CONFIG)
            self.assertEqual(result["status"], 1)
            self.assertNotIn("PRIVATE", result["detail"])
    def test_auth_rejection(self):
        for code in (401, 403, 302, 500):
            self.assertEqual(service.documents(Context(status=code), CONFIG)["status"], 1)
    def test_errors_redacted(self):
        for method in ("secret", "http"):
            ctx = Context()
            setattr(ctx, method, MagicMock(side_effect=TimeoutError("PRIVATE private-test-token")))
            result = service.documents(ctx, CONFIG)
            self.assertEqual(result["status"], 1)
            self.assertNotIn("PRIVATE", result["detail"])
            self.assertNotIn("private-test-token", result["detail"])
    def test_malformed_json(self):
        ctx = Context()
        ctx.http = MagicMock(return_value=SimpleNamespace(status=200, body=b"<html>login</html>"))
        self.assertEqual(service.documents(ctx, CONFIG)["status"], 1)
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


if __name__ == "__main__":
    unittest.main()
