import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
ASSETS = ROOT / 'config/zabbix/manifests/assets'
spec = importlib.util.spec_from_file_location('whisper', ASSETS / 'service_whisper.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
CONFIG = json.loads((ASSETS / 'service_whisper.json').read_text())
MODEL = {'name': 'whisper.cpp', 'installed': True, 'languages': ['hu', 'ro', 'en']}
CAPS = dict(schema=1, endpoint='/transcribe', method='POST', input='raw-audio',
            output='text/plain', rate=16000, width=2, channels=1, decoder_verified=True)


class Socket:
    def __init__(self, data): self.data = data
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def settimeout(self, value): assert 0 < value <= 5
    def sendall(self, data): assert data == b'{"type":"describe"}\n'
    def recv(self, size):
        data, self.data = self.data[:size], self.data[size:]
        return data


class Context:
    def remaining(self): return 20
    def check(self, name, bad, detail, severity=3):
        return dict(name=name, status=int(bad), detail=detail, severity=severity)
    def http(self, url, **kwargs):
        assert kwargs == dict(timeout=5, max_bytes=4096)
        return self.response


class WhisperTests(unittest.TestCase):
    def check(self, data=None, body=None, status=200, framed=False, wire=None, error=None):
        ctx = Context()
        ctx.response = SimpleNamespace(status=status, body=json.dumps(CAPS if body is None else body).encode())
        if data is None: data = {'asr': [{'installed': True, 'models': [MODEL]}]}
        encoded = json.dumps(data).encode()
        if wire is None:
            wire = ((json.dumps({'type': 'info', 'data_length': len(encoded)}).encode() + b'\n' + encoded)
                    if framed else json.dumps({'type': 'info', 'data': data}).encode() + b'\n')
        with patch.object(module.socket, 'create_connection', side_effect=error, return_value=Socket(wire)):
            return module.run(ctx, CONFIG)

    def test_healthy_inline_and_framed(self):
        for framed in (False, True):
            self.assertEqual([r['status'] for r in self.check(framed=framed)], [0, 0])

    def test_model_missing_not_installed_or_language_missing(self):
        for model in (dict(MODEL, installed=False), dict(MODEL, languages=['en'])):
            self.assertEqual(self.check(data={'asr': [{'installed': True, 'models': [model]}]})[0]['status'], 1)
        self.assertEqual(self.check(data={'asr': []})[0]['status'], 1)

    def test_bad_wire_and_bounds(self):
        for wire in (b'garbage\n', b'{"type":"error"}\n', b'{"type":"info","data_length":65537}\n',
                     b'{"type":"info","data_length":2}\n{', b'x' * 8193):
            self.assertEqual(self.check(wire=wire)[0]['status'], 1)

    def test_network_timeout_safe_and_bridge_independent(self):
        rows = self.check(error=TimeoutError('private transcript'))
        self.assertEqual([r['status'] for r in rows], [1, 0])
        self.assertNotIn('private', str(rows))

    def test_bridge_unauthorized_malformed_or_decoder_failure(self):
        for status, body in ((401, CAPS), (503, CAPS), (200, {}), (200, dict(CAPS, decoder_verified=False)),
                             (200, dict(CAPS, rate=True)), (200, ['invalid'])):
            self.assertEqual(self.check(status=status, body=body)[1]['status'], 1)

    def test_bridge_handler_contract_without_inference(self):
        # Extract embedded script without starting its HTTP server/importing runtime deps.
        source = (ROOT / 'config/baloo/manifests/whisper.yaml').read_text().split('  whisper-http.py: |\n', 1)[1].split('\n---', 1)[0]
        source = '\n'.join(line[4:] for line in source.splitlines())
        import ast, io, wave
        tree = ast.parse(source)
        handler = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'Handler')
        namespace = dict(BaseHTTPRequestHandler=object, io=io, wave=wave, json=json, RATE=16000,
                         to_pcm=lambda audio: b'\x00\x00' * 1600)
        exec(compile(ast.Module(body=[handler], type_ignores=[]), '<bridge>', 'exec'), namespace)
        h = namespace['Handler']()
        h.path, h.wfile = '/capabilities', io.BytesIO()
        statuses = []
        h.send_response = statuses.append
        h.send_header = lambda *args: None
        h.end_headers = lambda: None
        h.send_error = lambda status, *args: statuses.append(status)
        h.do_GET()
        self.assertEqual(statuses, [200])
        self.assertEqual(json.loads(h.wfile.getvalue()), CAPS)
        namespace['to_pcm'] = lambda audio: b'bad'
        h.do_GET()
        self.assertEqual(statuses[-1], 503)


if __name__ == '__main__': unittest.main()
