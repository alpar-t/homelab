#!/usr/bin/env python3
"""Transcribe audio via the whisper HTTP bridge.

Usage: whisper-transcribe.py <audio-file>
"""
import io, os, sys, urllib.request

URL = os.environ.get('WHISPER_HTTP_URL', 'http://whisper.baloo.svc.cluster.local:10301/transcribe')
# Assume up to 20x real-time on iGPU for large-v3, with 60s minimum and 600s ceiling.
RTF = float(os.environ.get('WHISPER_RTF', '20'))


def audio_duration_seconds(path: str) -> float:
    try:
        import av
        with av.open(path) as container:
            stream = next(s for s in container.streams if s.type == 'audio')
            if stream.duration and stream.time_base:
                return float(stream.duration * stream.time_base)
            return container.duration / 1_000_000 if container.duration else 60.0
    except Exception:
        return 60.0


def main():
    if len(sys.argv) < 2:
        sys.exit('usage: whisper-transcribe.py <audio-file>')
    path = sys.argv[1]
    duration = audio_duration_seconds(path)
    timeout = max(60, min(int(duration * RTF) + 30, 600))
    with open(path, 'rb') as f:
        audio = f.read()
    req = urllib.request.Request(
        URL, data=audio, method='POST',
        headers={'Content-Type': 'application/octet-stream'},
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        print(r.read().decode())


main()
