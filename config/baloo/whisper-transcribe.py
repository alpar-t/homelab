#!/usr/bin/env python3
"""Transcribe audio via the whisper HTTP bridge.

Usage: whisper-transcribe.py <audio-file>
"""
import os, sys, urllib.request

URL = os.environ.get('WHISPER_HTTP_URL', 'http://whisper.baloo.svc.cluster.local:10301/transcribe')


def main():
    if len(sys.argv) < 2:
        sys.exit('usage: whisper-transcribe.py <audio-file>')
    with open(sys.argv[1], 'rb') as f:
        audio = f.read()
    req = urllib.request.Request(
        URL, data=audio, method='POST',
        headers={'Content-Type': 'application/octet-stream'},
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        print(r.read().decode())


main()
