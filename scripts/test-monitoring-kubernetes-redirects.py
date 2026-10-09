#!/usr/bin/env python3
"""Offline ServiceAccount redirect canary; no sockets or cluster access."""
import importlib.util
import io
from email.message import Message
from pathlib import Path
import ssl
import sys
import tempfile
import unittest
from unittest.mock import patch
import urllib.error
import urllib.request
import urllib.response

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'config/zabbix/manifests/assets'))
spec = importlib.util.spec_from_file_location('redirect_collector', ROOT / 'config/zabbix/manifests/assets/collector.py')
collector = importlib.util.module_from_spec(spec)
spec.loader.exec_module(collector)
CANARY = 'PRIVATE-SERVICEACCOUNT-BEARER-CANARY'


class RedirectTransport(urllib.request.HTTPSHandler):
    handler_order = 100

    def __init__(self, status):
        super().__init__()
        self.status = status
        self.requests = []

    def https_open(self, req):
        self.requests.append((req.full_url, req.get_header('Authorization')))
        headers = Message()
        headers['Location'] = 'https://redirect-destination.invalid/steal'
        status = self.status if len(self.requests) == 1 else 200
        response = urllib.response.addinfourl(io.BytesIO(b'{}'), headers, req.full_url, status)
        response.msg = 'redirect' if status != 200 else 'OK'
        return response


class KubernetesRedirectTests(unittest.TestCase):
    def test_get_and_logs_refuse_all_redirects_without_forwarding_bearer(self):
        with tempfile.TemporaryDirectory() as directory:
            sa = Path(directory)
            (sa / 'token').write_text(CANARY)
            context = ssl.create_default_context()
            with patch.object(collector, 'SA', sa), patch.object(collector.ssl, 'create_default_context', return_value=context) as create:
                for operation in ('get', 'logs'):
                    for status in (301, 302, 303, 307, 308):
                        with self.subTest(operation=operation, status=status):
                            kube = collector.Kubernetes()
                            create.assert_called_with(cafile=str(sa / 'ca.crt'))
                            https = next(h for h in kube.opener.handlers if isinstance(h, urllib.request.HTTPSHandler))
                            self.assertIs(https._context, context)
                            transport = RedirectTransport(status)
                            kube.opener.add_handler(transport)
                            with self.assertRaises(urllib.error.HTTPError) as error:
                                if operation == 'get':
                                    kube.get('/apis/metrics.k8s.io/v1beta1/nodes')
                                else:
                                    kube.logs('test', 'pod', 'container')
                            self.assertEqual(error.exception.code, status)
                            self.assertEqual(len(transport.requests), 1)
                            self.assertEqual(transport.requests[0][1], 'Bearer ' + CANARY)
                            self.assertTrue(transport.requests[0][0].startswith(kube.base + '/'))
                            self.assertNotIn(CANARY, str(error.exception))
                            error.exception.close()


if __name__ == '__main__':
    unittest.main()
