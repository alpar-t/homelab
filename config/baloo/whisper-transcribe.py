#!/usr/bin/env python3
"""Wyoming STT client for OpenClaw audio transcription.

Converts an audio file to PCM via ffmpeg and sends it to a Wyoming-protocol
whisper server, printing the transcript to stdout.

Usage: whisper-transcribe.py <audio-file>
Env:   WYOMING_HOST (default: whisper.baloo.svc.cluster.local)
       WYOMING_PORT (default: 10300)
"""

import json
import os
import socket
import subprocess
import sys
import wave

WYOMING_HOST = os.environ.get("WYOMING_HOST", "whisper.baloo.svc.cluster.local")
WYOMING_PORT = int(os.environ.get("WYOMING_PORT", "10300"))
FFMPEG = os.environ.get("FFMPEG_BIN", "/tmp/ffmpeg")


def send_event(sock, type_, data=None, payload=b""):
    header = {"type": type_}
    if data:
        header["data"] = data
    if payload:
        header["data_length"] = len(payload)
    sock.sendall((json.dumps(header) + "\n").encode())
    if payload:
        sock.sendall(payload)


class WyomingReader:
    def __init__(self, sock):
        self._sock = sock
        self._buf = b""

    def recv(self):
        while b"\n" not in self._buf:
            chunk = self._sock.recv(65536)
            if not chunk:
                raise EOFError("connection closed")
            self._buf += chunk
        line, self._buf = self._buf.split(b"\n", 1)
        event = json.loads(line)
        need = event.get("data_length", 0)
        while len(self._buf) < need:
            chunk = self._sock.recv(65536)
            if not chunk:
                raise EOFError("connection closed mid-payload")
            self._buf += chunk
        payload, self._buf = self._buf[:need], self._buf[need:]
        return event, payload


def to_pcm16(path):
    """Return (pcm_bytes, rate, width=2, channels=1) via ffmpeg or wav fallback."""
    ffmpeg = FFMPEG if os.path.isfile(FFMPEG) else "ffmpeg"
    try:
        r = subprocess.run(
            [ffmpeg, "-hide_banner", "-loglevel", "error",
             "-i", path, "-ar", "16000", "-ac", "1", "-f", "s16le", "-"],
            capture_output=True, timeout=120,
        )
        if r.returncode == 0 and r.stdout:
            return r.stdout, 16000, 2, 1
        sys.stderr.write(f"ffmpeg error: {r.stderr.decode()}\n")
    except FileNotFoundError:
        sys.stderr.write("ffmpeg not found; falling back to wav\n")

    with wave.open(path) as w:
        return w.readframes(w.getnframes()), w.getframerate(), w.getsampwidth(), w.getnchannels()


def main():
    if len(sys.argv) < 2:
        sys.exit("usage: whisper-transcribe.py <audio-file>")

    pcm, rate, width, channels = to_pcm16(sys.argv[1])
    fmt = {"rate": rate, "width": width, "channels": channels}

    with socket.create_connection((WYOMING_HOST, WYOMING_PORT), timeout=10) as sock:
        sock.settimeout(120)
        reader = WyomingReader(sock)

        reader.recv()  # consume describe

        send_event(sock, "audio-start", fmt)
        for i in range(0, len(pcm), 8192):
            send_event(sock, "audio-chunk", fmt, pcm[i : i + 8192])
        send_event(sock, "audio-stop", {})

        while True:
            ev, _ = reader.recv()
            if ev["type"] == "transcript":
                print(ev.get("data", {}).get("text", ""))
                return
            if ev["type"] == "error":
                sys.exit(f"wyoming error: {ev.get('data')}")


main()
