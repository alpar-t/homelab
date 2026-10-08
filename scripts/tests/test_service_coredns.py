import importlib.util
from pathlib import Path
import socket
import struct
import unittest
from unittest.mock import Mock, patch

spec = importlib.util.spec_from_file_location('coredns', Path(__file__).resolve().parents[2] / 'config/zabbix/manifests/assets/service_coredns.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

class DNS(unittest.TestCase):
    def setUp(self):
        self.host = 'kubernetes.default.svc.cluster.local'
        self.question = b''.join(bytes([len(x)]) + x.encode() for x in self.host.split('.')) + b'\0\0\1\0\1'
        self.reply = struct.pack('!6H', 42, 0x8180, 1, 1, 0, 0) + self.question + b'\xc0\x0c' + struct.pack('!HHIH', 1, 1, 30, 4) + socket.inet_aton('10.43.0.1')
    def test_valid(self):
        m.validate(self.reply, 42, self.host, '10.43.0.1')
    def test_malformed(self):
        for data in (self.reply[:10], self.reply[:-1], self.reply + b'x', self.reply[:2] + b'\x83\x80' + self.reply[4:], self.reply[:2] + b'\x81\x83' + self.reply[4:]):
            with self.subTest(data=data), self.assertRaises(ValueError):
                m.validate(data, 42, self.host, '10.43.0.1')
    def test_wrong_transaction_question_address(self):
        for ident,host,ip in ((43,self.host,'10.43.0.1'),(42,'other.local','10.43.0.1'),(42,self.host,'10.43.0.2')):
            with self.assertRaises(ValueError): m.validate(self.reply,ident,host,ip)
    def test_pointer_loop(self):
        with self.assertRaises(ValueError): m.name_at(b'\xc0\0',0)
    def context(self):
        ctx = Mock()
        ctx.remaining.return_value = 30
        ctx.kube.get.side_effect = [{'spec':{'clusterIP':'10.43.0.1'}},{'spec':{'clusterIP':'10.43.0.10'}}]
        ctx.check.side_effect = lambda n,b,d: dict(name=n,status=int(b),detail=d)
        return ctx
    def config(self):
        return {'services':[{'namespace':'default','service':'kubernetes'},{'namespace':'kube-system','service':'kube-dns'}]}
    def test_run_healthy_and_timeout(self):
        with patch.object(m,'query') as probe:
            self.assertEqual([r['status'] for r in m.run(self.context(),self.config())],[0,0])
            self.assertEqual(probe.call_count,4)
        with patch.object(m,'query',side_effect=TimeoutError()):
            self.assertEqual([r['status'] for r in m.run(self.context(),self.config())],[1,1])
    def test_api_denied_or_budget(self):
        ctx = self.context()
        ctx.kube.get.side_effect = PermissionError('private')
        self.assertEqual(m.run(ctx,self.config())[0]['status'],1)
        ctx = self.context()
        ctx.remaining.return_value = 18
        self.assertEqual(m.run(ctx,self.config())[0]['status'],1)
        ctx.kube.get.assert_not_called()
    def test_tcp_short_and_udp_socket_failure(self):
        ctx=self.context()
        for tcp in (False,True):
            with patch.object(m.socket,'socket') as factory:
                factory.return_value.__enter__.return_value.recv.return_value=b''
                with self.assertRaises(ValueError): m.query(ctx,'10.43.0.10',self.host,'10.43.0.1',tcp)
        with patch.object(m.socket,'socket',side_effect=OSError()):
            with self.assertRaises(OSError): m.query(ctx,'10.43.0.10',self.host,'10.43.0.1',False)

if __name__=='__main__': unittest.main()
