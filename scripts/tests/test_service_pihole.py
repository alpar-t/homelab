import importlib.util
import json
from pathlib import Path
import socket
import struct
import unittest
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
ASSETS = ROOT / 'config/zabbix/manifests/assets'
spec = importlib.util.spec_from_file_location('pihole', ASSETS / 'service_pihole.py')
service = importlib.util.module_from_spec(spec)
spec.loader.exec_module(service)
CONFIG = json.loads((ASSETS / 'service_pihole.json').read_text())


def reply(ident=42, name='cloudflare.com', address='1.1.1.1', flags=0x8180):
    return (struct.pack('!6H', ident, flags, 1, 1, 0, 0) + service.question(name)
            + b'\xc0\x0c' + struct.pack('!HHIH', 1, 1, 60, 4)
            + socket.inet_aton(address))


class Context:
    def __init__(self):
        self.kube = SimpleNamespace(items=lambda path: [
            {'metadata': {'labels': {'app': 'pihole', 'instance': instance}},
             'status': {'podIP': ip}}
            for instance, ip in [('primary', '10.42.0.2'), ('secondary', '10.42.1.2')]])
    def remaining(self):
        return 30
    def check(self, name, bad, detail, severity=3):
        return dict(name=name, status=int(bad), detail=detail, severity=severity)


class FakeSocket:
    def __init__(self, data):
        self.data = data
        self.timeouts = []
    def __enter__(self):
        return self
    def __exit__(self, *args):
        pass
    def settimeout(self, timeout):
        self.timeouts.append(timeout)
    def connect(self, address):
        self.address = address
    def send(self, data):
        pass
    def sendall(self, data):
        self.sent = data
    def recv(self, size):
        # TCP reads may be fragmented down to a single byte.
        result, self.data = self.data[:min(size, 1)], self.data[min(size, 1):]
        return result


class PiHoleTests(unittest.TestCase):
    def test_answer_semantics(self):
        self.assertEqual(service.answers(reply(), 42, 'cloudflare.com'), ['1.1.1.1'])
        for data in [reply(ident=99), reply(name='unrelated.example'), reply(flags=0x8182),
                     reply(flags=0x0180), reply()[:-1], reply() + b'extra', b'short']:
            with self.subTest(data=data), self.assertRaises(ValueError):
                service.answers(data, 42, 'cloudflare.com')

    def test_compression_cycle_and_wrong_owner_rejected(self):
        data = reply()
        with self.assertRaises(ValueError):
            service.name_at(b'\xc0\x00', 0)
        offset = 12 + len(service.question('cloudflare.com'))
        data = data[:offset] + b'\x05wrong\x00' + data[offset + 2:]
        with self.assertRaises(ValueError):
            service.answers(data, 42, 'cloudflare.com')

    def test_cname_chain(self):
        name = 'cloudflare.com'
        alias = service.question('target.example')[:-4]
        data = (struct.pack('!6H', 42, 0x8180, 1, 2, 0, 0) + service.question(name)
                + b'\xc0\x0c' + struct.pack('!HHIH', 5, 1, 60, len(alias)) + alias
                + alias + struct.pack('!HHIH', 1, 1, 60, 4) + socket.inet_aton('1.1.1.1'))
        self.assertEqual(service.answers(data, 42, name), ['1.1.1.1'])

    def test_tcp_fragmented_frame_and_deadline(self):
        packet = reply()
        sock = FakeSocket(struct.pack('!H', len(packet)) + packet)
        with patch.object(service.socket, 'socket', return_value=sock), patch.object(service.secrets, 'randbits', return_value=42):
            self.assertEqual(service.query(Context(), '10.42.0.2', 'cloudflare.com', True), ['1.1.1.1'])
        self.assertTrue(all(0 < timeout <= 2 for timeout in sock.timeouts))
        ctx = Context()
        ctx.remaining = lambda: 0
        with patch.object(service.socket, 'socket') as factory, self.assertRaises(TimeoutError):
            service.query(ctx, '10.42.0.2', 'cloudflare.com')
        factory.assert_not_called()

    def test_udp_truncation_falls_back_to_tcp(self):
        truncated = reply(flags=0x8380)
        udp = FakeSocket(truncated)
        udp.recv = lambda size: truncated
        packet = reply()
        tcp = FakeSocket(struct.pack('!H', len(packet)) + packet)
        with patch.object(service.socket, 'socket', side_effect=[udp, tcp]), patch.object(service.secrets, 'randbits', return_value=42):
            self.assertEqual(service.query(Context(), '10.42.0.2', 'cloudflare.com'), ['1.1.1.1'])

    def test_both_instances_and_transports(self):
        def query(ctx, host, name, tcp=False):
            return ['1.1.1.1'] if name == CONFIG['upstream_name'] else [CONFIG['local_address']]
        with patch.object(service, 'query', side_effect=query) as probe:
            result = service.run(Context(), CONFIG)
        self.assertEqual([row['status'] for row in result], [0, 0])
        self.assertEqual(probe.call_count, 6)
        self.assertEqual({call.args[1] for call in probe.call_args_list}, {'10.42.0.2', '10.42.1.2'})

    def test_per_instance_timeout_and_redaction(self):
        def query(ctx, host, name, tcp=False):
            if host == '10.42.1.2':
                raise TimeoutError('private response')
            return ['1.1.1.1'] if name == CONFIG['upstream_name'] else [CONFIG['local_address']]
        with patch.object(service, 'query', side_effect=query):
            result = service.run(Context(), CONFIG)
        self.assertEqual([row['status'] for row in result], [0, 1])
        self.assertNotIn('private response', str(result))

    def test_wrong_local_and_tcp_failure(self):
        for broken_tcp in (False, True):
            def query(ctx, host, name, tcp=False):
                if name == CONFIG['upstream_name']:
                    return ['1.1.1.1']
                if broken_tcp and tcp:
                    raise ConnectionRefusedError()
                return [CONFIG['local_address']] if broken_tcp else ['192.168.1.201']
            with patch.object(service, 'query', side_effect=query):
                self.assertTrue(all(row['status'] for row in service.run(Context(), CONFIG)))

    def test_blocking_wrong_local_and_discovery_failure(self):
        for answer in ['0.0.0.0', '127.0.0.1', '192.168.1.3']:
            with patch.object(service, 'query', return_value=[answer]):
                self.assertTrue(all(row['status'] for row in service.run(Context(), CONFIG)))
        ctx = Context()
        ctx.kube.items = lambda path: []
        self.assertTrue(all(row['status'] for row in service.run(ctx, CONFIG)))
        ctx.kube.items = lambda path: (_ for _ in ()).throw(PermissionError('private data'))
        result = service.run(ctx, CONFIG)
        self.assertTrue(all(row['status'] for row in result))
        self.assertNotIn('private data', str(result))


if __name__ == '__main__':
    unittest.main()
