import io
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ASSETS = Path(__file__).resolve().parents[2] / 'config/zabbix/manifests/assets'
sys.path.insert(0, str(ASSETS))
import service_roundcube as service


class Context:
    def remaining(self):
        return 20

    def check(self, name, bad, detail):
        return {'name': name, 'status': int(bad), 'detail': detail}

    def http(self, *args, **kwargs):
        return self.response


class Connection:
    def __init__(self, transcript):
        self.transcript = transcript
        self.sent = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def makefile(self, mode):
        return io.BytesIO(self.transcript)

    def settimeout(self, timeout):
        assert 0 < timeout <= 4

    def sendall(self, value):
        self.sent.append(value)


class Tests(unittest.TestCase):
    def setUp(self):
        self.config = json.loads((ASSETS / 'service_roundcube.json').read_text())
        self.ctx = Context()
        self.ctx.response = SimpleNamespace(status=302, body=b'', headers={
            'Set-Cookie': 'roundcube_sessid=anonymous-session; HttpOnly',
            'Location': self.config['authorize'] + '?response_type=code&client_id=monitor-client'
            '&scope=openid+email+profile&redirect_uri=https%3A%2F%2Fwebmail.newjoy.ro%2Findex.php%2Flogin%2Foauth'
            '&state=abcdefgh&nonce=ijklmnop&code_challenge_method=S256&code_challenge=' + 'a' * 43})

    def test_bootstrap_and_broken_contracts(self):
        self.assertTrue(service.bootstrap(self.ctx, self.config))
        healthy = dict(self.ctx.response.headers)
        for mutation in ({'Set-Cookie': ''}, {'Location': healthy['Location'].replace('auth.newjoy.ro', 'other.invalid')},
                         {'Location': healthy['Location'].replace('S256', 'plain')},
                         {'Location': healthy['Location'].replace('abcdefgh', '')},
                         {'Location': healthy['Location'].replace('webmail.newjoy.ro', 'other.invalid')}):
            self.ctx.response.headers = dict(healthy, **mutation)
            self.assertFalse(service.bootstrap(self.ctx, self.config))
        self.ctx.response.headers = healthy
        for status in (200, 401, 500):
            self.ctx.response.status = status
            self.assertFalse(service.bootstrap(self.ctx, self.config))

    def test_imap_actual_command_and_failures(self):
        for transcript, expected in (
            (b'* OK server\r\n* CAPABILITY IMAP4rev2 AUTH=OAUTHBEARER\r\nM1 OK CAPABILITY completed\r\n', True),
            (b'* OK server\r\n* CAPABILITY IMAP4rev1 AUTH=PLAIN\r\nM1 OK completed\r\n', False),
            (b'* OK server\r\n* CAPABILITY IMAP4rev1 AUTH=OAUTHBEARER\r\nM1 NO unavailable\r\n', False),
            (b'* BYE unavailable\r\n', False)):
            connection = Connection(transcript)
            with patch.object(service.socket, 'create_connection', return_value=connection):
                self.assertEqual(service.imap_capability(self.ctx, self.config), expected)
            self.assertTrue(all(value == b'M1 CAPABILITY\r\n' for value in connection.sent))

    def test_malformed_timeout_and_redaction(self):
        for transcript in (b'* OK x\r\n' + b'x' * 4097, b'* OK x\r\ntruncated'):
            with patch.object(service.socket, 'create_connection', return_value=Connection(transcript)):
                rows = service.run(self.ctx, self.config)
            self.assertEqual([row['status'] for row in rows], [0, 1])
        self.ctx.http = lambda *a, **k: (_ for _ in ()).throw(ValueError('private-secret'))
        with patch.object(service.socket, 'create_connection', side_effect=TimeoutError('private-secret')):
            rows = service.run(self.ctx, self.config)
        self.assertEqual([row['status'] for row in rows], [1, 1])
        self.assertNotIn('private-secret', str(rows))

    def test_deadline_and_work_bound(self):
        self.ctx.remaining = lambda: 0
        with patch.object(service.socket, 'create_connection') as connect:
            self.assertEqual(service.run(self.ctx, self.config)[1]['status'], 1)
            connect.assert_not_called()
        self.ctx.remaining = lambda: 20
        with patch.object(service.socket, 'create_connection', return_value=Connection(b'* OK x\r\n' + b'* ignored\r\n' * 12)):
            self.assertFalse(service.imap_capability(self.ctx, self.config))


if __name__ == '__main__':
    unittest.main()
