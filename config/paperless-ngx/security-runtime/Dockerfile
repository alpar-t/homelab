# syntax=docker/dockerfile:1@sha256:4edf897a3ffa55b89f906fc8cc78afdb3f1834cc9c7083565e611a8a7d5fe99e
# Keep the Paperless 3.3.4 application and OS packages unchanged; replace the
# vulnerable Python Brotli decoder with its patched wheel.
FROM ghcr.io/paperless-ngx/paperless-ngx:3.3.4@sha256:9bc6e8248891bcfa6f52fffe8b81e4ea8cae75790c3ec1b9906961a7ba55c969

LABEL org.opencontainers.image.source="https://github.com/alpar-t/homelab" \
      org.opencontainers.image.description="Paperless-ngx 3.3.4 with patched Python Brotli decoder"

COPY requirements-overlay.txt /tmp/requirements-overlay.txt
RUN python -m pip install --disable-pip-version-check --no-cache-dir \
      --no-deps --only-binary=:all: --require-hashes \
      -r /tmp/requirements-overlay.txt \
    && python -m pip check \
    && python - <<'PY'
import importlib.metadata

import brotli
import httpx
from compression_middleware.br import brotli_compress

assert importlib.metadata.version("Brotli") == "1.2.1"
payload = b"paperless-brotli-runtime-probe" * 32
compressed = brotli_compress(payload)
assert brotli.Decompressor().process(compressed) == payload
with httpx.Client(transport=httpx.MockTransport(
    lambda request: httpx.Response(200, headers={"Content-Encoding": "br"}, content=compressed)
)) as client:
    assert client.get("https://example.invalid/probe").content == payload
PY
