import importlib.util
from pathlib import Path
import socket
import ssl
import unittest
from unittest.mock import patch, Mock

ASSETS = Path(__file__).resolve().parents[2] / 'config/zabbix/manifests/assets'
spec = importlib.util.spec_from_file_location('mail_service', ASSETS / 'service_stalwart_mail.py')
mail = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mail)


class Context:
    def remaining(self): return 30
    def secret(self, key): return 'TEST TRUST ANCHOR'
    def check(self, name, bad, detail): return dict(name=name, status=int(bad), detail=detail)


class MailProtocolTests(unittest.TestCase):
    def endpoint(self, protocol='smtp', tls='none'):
        return dict(name='mail', host='internal', port=587, protocol=protocol,
                    tls=tls, server_name='mail.newjoy.ro', ca_key='stalwart_mail_ca')

    def probe(self, chunks, endpoint=None):
        sock = Mock()
        sock.recv.side_effect = chunks
        with patch.object(mail.socket, 'create_connection', return_value=sock):
            result = mail.run(Context(), {'endpoints': [endpoint or self.endpoint()]})[0]
        self.assertTrue(sock.close.called)
        return result, sock

    def test_smtp_transaction_is_only_ehlo_and_quit(self):
        result, sock = self.probe([b'220 ready\r\n', b'250-server\r\n250 SIZE 42\r\n', b'221 bye\r\n'])
        self.assertEqual(result['status'], 0)
        self.assertEqual([call.args[0] for call in sock.sendall.call_args_list], [b'EHLO monitor.invalid\r\n', b'QUIT\r\n'])

    def test_starttls_requires_advertisement(self):
        result, _ = self.probe([b'220 ready\r\n', b'250 server\r\n'], self.endpoint(tls='starttls'))
        self.assertEqual(result['status'], 1)

    def test_starttls_reissues_ehlo_and_validates_sni(self):
        sock = Mock()
        sock.recv.side_effect = [b'220 ready\r\n', b'250-server\r\n250 STARTTLS\r\n', b'220 TLS\r\n', b'250 server\r\n', b'221 bye\r\n']
        context = Mock()
        context.wrap_socket.return_value = sock
        with patch.object(mail.socket, 'create_connection', return_value=sock), patch.object(mail.ssl, 'create_default_context', return_value=context):
            result = mail.run(Context(), {'endpoints': [self.endpoint(tls='starttls')]})[0]
        self.assertEqual(result['status'], 0)
        context.load_verify_locations.assert_called_once_with(cadata='TEST TRUST ANCHOR')
        context.wrap_socket.assert_called_once_with(sock, server_hostname='mail.newjoy.ro')
        self.assertEqual(sum(c.args[0].startswith(b'EHLO') for c in sock.sendall.call_args_list), 2)

    def test_imap_requires_capability_and_tagged_success(self):
        for answer, expected in [(b'* CAPABILITY IMAP4rev1 AUTH=PLAIN\r\nM1 OK done\r\n', 0),
                                 (b'M1 OK done\r\n', 1),
                                 (b'* CAPABILITY IMAP4rev2\r\nM1 NO denied\r\n', 1),
                                 (b'* CAPABILITY SMTP\r\nM1 OK done\r\n', 1)]:
            with self.subTest(answer=answer):
                result, sock = self.probe([b'* OK ready\r\n', answer], self.endpoint(protocol='imap'))
                self.assertEqual(result['status'], expected)
                sock.sendall.assert_called_once_with(b'M1 CAPABILITY\r\n')

    def test_malformed_oversized_closed_and_timeout(self):
        for chunks in [[b'HTTP/1.1 200 OK\r\n'], [b'x'*4097], [b''], [socket.timeout('private response')]]:
            result, _ = self.probe(chunks)
            self.assertEqual(result['status'], 1)
            self.assertNotIn('private response', result['detail'])

    def test_untrusted_tls_is_failure_without_response_leak(self):
        context = Mock()
        context.wrap_socket.side_effect = ssl.SSLCertVerificationError('private certificate')
        with patch.object(mail.ssl, 'create_default_context', return_value=context):
            result, _ = self.probe([], self.endpoint(protocol='imap', tls='implicit'))
        self.assertEqual(result['status'], 1)
        self.assertNotIn('private certificate', result['detail'])

    def test_missing_trust_and_connection_failure_do_not_leak(self):
        ctx = Context()
        ctx.secret = Mock(side_effect=ValueError('private secret'))
        sock = Mock()
        with patch.object(mail.socket, 'create_connection', return_value=sock):
            result = mail.run(ctx, {'endpoints': [self.endpoint(protocol='imap', tls='implicit')]})[0]
        self.assertEqual(result['status'], 1)
        self.assertNotIn('private secret', result['detail'])
        with patch.object(mail.socket, 'create_connection', side_effect=OSError('private host')):
            result = mail.run(Context(), {'endpoints': [self.endpoint()]})[0]
        self.assertEqual(result['status'], 1)
        self.assertNotIn('private host', result['detail'])

    def test_expired_deadline_prevents_connect(self):
        ctx = Context()
        ctx.remaining = lambda: 0
        with patch.object(mail.socket, 'create_connection') as connect:
            self.assertEqual(mail.run(ctx, {'endpoints': [self.endpoint()]})[0]['status'], 1)
            connect.assert_not_called()


if __name__ == '__main__': unittest.main()
