"""Read-only Wyoming metadata and bridge decoder checks; never submits speech."""
import json
import socket
import time


def describe(ctx, config):
    deadline = time.monotonic() + min(5, ctx.remaining())
    def timeout():
        value = min(deadline - time.monotonic(), ctx.remaining())
        if value <= 0:
            raise TimeoutError()
        return value
    with socket.create_connection((config['host'], config['port']), timeout=timeout()) as sock:
        sock.settimeout(timeout())
        sock.sendall(b'{"type":"describe"}\n')
        def read(size):
            raw = bytearray()
            while len(raw) < size:
                sock.settimeout(timeout())
                chunk = sock.recv(size - len(raw))
                if not chunk:
                    raise ValueError()
                raw.extend(chunk)
            return bytes(raw)
        line = bytearray()
        while len(line) <= 8192:
            line.extend(read(1))
            if line.endswith(b'\n'):
                break
        if len(line) > 8192:
            raise ValueError()
        event = json.loads(line)
        if event.get('type') != 'info' or event.get('payload_length', 0) != 0:
            raise ValueError()
        size = event.get('data_length', 0)
        if type(size) is not int or not 0 <= size <= 65536:
            raise ValueError()
        data = event.get('data', {})
        if not isinstance(data, dict):
            raise ValueError()
        if size:
            data.update(json.loads(read(size)))
        programs = data.get('asr')
        if not isinstance(programs, list):
            raise ValueError()
        for program in programs:
            if not isinstance(program, dict) or program.get('installed') is not True:
                continue
            for model in program.get('models', []):
                if (isinstance(model, dict) and model.get('installed') is True
                        and isinstance(model.get('name'), str) and model['name']
                        and isinstance(model.get('languages'), list)
                        and set(config['languages']).issubset(model['languages'])):
                    return
        raise ValueError()


def run(ctx, config):
    rows = []
    try:
        describe(ctx, config)
        rows.append(ctx.check('Whisper ASR capabilities', False,
                              'installed ASR model advertises required languages; inference not exercised'))
    except Exception:
        rows.append(ctx.check('Whisper ASR capabilities', True,
                              'Wyoming unavailable or installed ASR capability invalid'))
    try:
        response = ctx.http(config['bridge_url'], timeout=5, max_bytes=4096)
        data = json.loads(response.body)
        expected = dict(schema=1, endpoint='/transcribe', method='POST', input='raw-audio',
                        output='text/plain', rate=16000, width=2, channels=1, decoder_verified=True)
        good = (response.status == 200 and
                all(type(data.get(k)) is type(v) and data.get(k) == v for k, v in expected.items()))
        rows.append(ctx.check('Whisper HTTP decoder contract', not good,
                              'bridge contract and in-memory WAV decoder verified; transcription not exercised'
                              if good else 'bridge contract or decoder self-check unavailable'))
    except Exception:
        rows.append(ctx.check('Whisper HTTP decoder contract', True,
                              'bridge contract or decoder self-check unavailable'))
    return rows
