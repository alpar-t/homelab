#!/usr/bin/env python3
"""Offline HTTP framing, elapsed deadlines and Kubernetes inventory bounds."""
import http.client
import io
import json
from pathlib import Path
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'config/zabbix/manifests/assets'))
import collector
from functional import Context, SafeError, read_response


class Raw(io.RawIOBase):
    def __init__(self, body, clock=None):
        self.body = bytearray(body)
        self.clock = clock
        self.timeouts = []
        self._sock = self
    def readable(self): return True
    def settimeout(self, value): self.timeouts.append(value)
    def readinto(self, buffer):
        if not self.body: return 0
        if self.clock is not None:
            # One arriving byte consumes 0.04s; honour the socket's remaining
            # budget when the next byte would arrive too late.
            if self.timeouts and self.timeouts[-1] < .04:
                self.clock[0] += self.timeouts[-1]
                raise TimeoutError()
            self.clock[0] += .04
            amount = 1
        else:
            amount = min(len(buffer), len(self.body))
        buffer[:amount] = self.body[:amount]
        del self.body[:amount]
        return amount


def response(body, clock=None):
    class Socket:
        def makefile(self, *args):
            return io.BytesIO(b'HTTP/1.1 200 OK\r\nContent-Length: ' + str(len(body)).encode() + b'\r\n\r\n')
    value = http.client.HTTPResponse(Socket())
    value.begin()
    raw = Raw(body, clock)
    value.fp = io.BufferedReader(raw)
    value.code = 200
    return value, raw


class Transport(unittest.TestCase):
    def test_real_httpresponse_trickle_stops_at_elapsed_deadline(self):
        clock = [10.0]
        value, raw = response(b'x' * 20, clock)
        with patch('functional.time.monotonic', side_effect=lambda: clock[0]):
            with self.assertRaises((SafeError, TimeoutError)):
                read_response(value, 10.1, 30)
        self.assertLessEqual(clock[0], 10.100001)
        self.assertLess(raw.timeouts[-1], raw.timeouts[0])
        self.assertTrue(raw.body)  # Did not buffer the complete slow body.

    def test_chunked_size_line_trickle_is_bounded_below_framing(self):
        class Socket:
            def makefile(self, *args):
                return io.BytesIO(b'HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n')
        clock = [10.0]
        value = http.client.HTTPResponse(Socket())
        value.begin()
        raw = Raw(b'0' * 40 + b'1\r\nx\r\n0\r\n\r\n', clock)
        value.fp = io.BufferedReader(raw)
        with patch('functional.time.monotonic', side_effect=lambda: clock[0]):
            with self.assertRaises((SafeError, TimeoutError)):
                read_response(value, 10.1, 30)
        self.assertLessEqual(clock[0], 10.100001)
        self.assertTrue(raw.body)
        value.close()

    def test_chunked_http_error_framing_is_also_deadline_bound(self):
        class Socket:
            def makefile(self, *args):
                return io.BytesIO(b'HTTP/1.1 503 unavailable\r\nTransfer-Encoding: chunked\r\n\r\n')
        clock = [10.0]
        value = http.client.HTTPResponse(Socket())
        value.begin()
        raw = Raw(b'0' * 40 + b'1\r\nx\r\n0\r\n\r\n', clock)
        value.fp = io.BufferedReader(raw)
        error = collector.urllib.error.HTTPError('http://fixture.invalid', 503, 'unavailable', {}, value)
        with patch('functional.time.monotonic', side_effect=lambda: clock[0]):
            with self.assertRaises((SafeError, TimeoutError)):
                read_response(error, 10.1, 30)
        self.assertLessEqual(clock[0], 10.100001)
        error.close()

    def test_chunked_data_and_trailers_remain_compatible_and_capped(self):
        class Socket:
            def makefile(self, *args):
                return io.BytesIO(b'HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n')
        for cap, expected in [(4, b'abcd'), (3, None)]:
            value = http.client.HTTPResponse(Socket())
            value.begin()
            value.fp = io.BufferedReader(Raw(b'2\r\nab\r\n2\r\ncd\r\n0\r\nX-End: yes\r\n\r\n'))
            if expected is None:
                with self.assertRaises(SafeError): read_response(value, time.monotonic() + 1, cap)
            else:
                self.assertEqual(read_response(value, time.monotonic() + 1, cap), expected)
            value.close()

    def test_byte_cap_and_exact_limit(self):
        for size in (0, 10):
            value, _ = response(b'x' * size)
            self.assertEqual(read_response(value, time.monotonic() + 1, 10), b'x' * size)
        value, _ = response(b'x' * 11)
        with self.assertRaises(SafeError): read_response(value, time.monotonic() + 1, 10)

    def test_http_error_wrapper_socket_timeout(self):
        value, raw = response(b'error')
        wrapped = collector.urllib.error.HTTPError('http://fixture.invalid', 401, 'denied', {}, value)
        self.assertEqual(read_response(wrapped, time.monotonic() + 1, 10), b'error')
        self.assertTrue(raw.timeouts)
        wrapped.close()

    def test_context_request_budget_includes_open_time(self):
        clock = [1.0]
        value, raw = response(b'x' * 20, clock)
        def opened(*args, **kwargs):
            self.assertAlmostEqual(kwargs['timeout'], .1)
            clock[0] += .06
            return value
        ctx = Context(None, 2.0)
        with patch('functional.time.monotonic', side_effect=lambda: clock[0]), patch('functional.urllib.request.build_opener', return_value=SimpleNamespace(open=opened)):
            with self.assertRaises(SafeError): ctx.http('http://fixture.invalid', timeout=.1, max_bytes=30)
        self.assertLessEqual(clock[0], 1.100001)
        self.assertLessEqual(raw.timeouts[0], .040001)


class Kube(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.sa = Path(self.temp.name)
        (self.sa / 'token').write_text('fixture-token')
        self.kube = collector.Kubernetes.__new__(collector.Kubernetes)
        self.kube.context, self.kube.base = None, 'https://fixture.invalid'

    def test_json_caps_and_five_second_transport(self):
        value, _ = response(b'{"items":[]}')
        with patch('collector.SA', self.sa), patch('collector.urllib.request.urlopen', return_value=value) as opened:
            self.assertEqual(self.kube.get('/inventory'), {'items': []})
            self.assertLessEqual(opened.call_args.kwargs['timeout'], 5)
        value, _ = response(b'{"items":[]}')
        with patch('collector.SA', self.sa), patch('collector.urllib.request.urlopen', return_value=value):
            with self.assertRaises(SafeError): self.kube.get('/inventory', max_bytes=4)

    def test_items_page_item_and_time_bounds(self):
        paths = []
        def get(path, **kwargs):
            paths.append(path)
            self.assertEqual(kwargs['timeout'], 5)
            self.assertLessEqual(kwargs['deadline'] - time.monotonic(), 20)
            return {'items': [{}] * 500, 'metadata': {'continue': 'again'}}
        self.kube.get = get
        with self.assertRaises(SafeError): self.kube.items('/pods')
        self.assertEqual(len(paths), 4)
        self.kube.get = lambda *a, **k: {'items': [{}] * 2001}
        with self.assertRaises(SafeError): self.kube.items('/pods')
        self.kube.get = collector.Kubernetes.get.__get__(self.kube)
        with self.assertRaises(SafeError): self.kube.items('/pods', deadline=time.monotonic() - 1)

    def test_logs_preserve_historical_mail_cap_and_reject_truncation(self):
        value, _ = response(b'line\n')
        with patch('collector.SA', self.sa), patch('collector.urllib.request.urlopen', return_value=value) as opened:
            self.assertEqual(self.kube.logs('mail', 'pod', 'stalwart', limit_bytes=2097152, timestamps=True), 'line\n')
            self.assertLessEqual(opened.call_args.kwargs['timeout'], 5)
        value, _ = response(b'xxxx')
        with patch('collector.SA', self.sa), patch('collector.urllib.request.urlopen', return_value=value):
            with self.assertRaises(ValueError): self.kube.logs('mail', 'pod', 'stalwart', limit_bytes=4, timestamps=True)
        with self.assertRaises(SafeError): self.kube.logs('mail', 'pod', 'stalwart', limit_bytes=2097153)


if __name__ == '__main__': unittest.main()
