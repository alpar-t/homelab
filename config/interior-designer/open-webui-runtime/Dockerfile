# syntax=docker/dockerfile:1@sha256:4edf897a3ffa55b89f906fc8cc78afdb3f1834cc9c7083565e611a8a7d5fe99e
# Keep Open WebUI 0.12.3 and its application dependencies intact. Replace only
# the Python packages with published security fixes. Their wheel hashes are
# pinned in requirements-overlay.txt so a rebuild cannot silently change them.
FROM ghcr.io/open-webui/open-webui:0.12.3@sha256:a537bbe1e6b428820f52ed4a029d7fff97062e24d5cf32c365fba36fd0542def

LABEL org.opencontainers.image.source="https://github.com/alpar-t/homelab" \
      org.opencontainers.image.description="Open WebUI 0.12.3 with patched Pillow, certifi and Brotli decoders"

USER root
COPY requirements-overlay.txt /tmp/requirements-overlay.txt
RUN python -m pip install --disable-pip-version-check --no-cache-dir \
      --no-deps --only-binary=:all: --require-hashes \
      -r /tmp/requirements-overlay.txt \
    && python -m pip check \
    && python - <<'PY'
import io
from importlib.metadata import version

import brotli
import brotlicffi
import certifi
from PIL import Image, ImageOps, features

assert version('Pillow') == '13.0.0'
assert version('certifi') == '2026.10.23'
assert version('Brotli') == '1.2.1'
assert version('brotlicffi') == '1.2.1.0'
assert 'emSign ECC Root CA - G3' not in open(certifi.where(), encoding='ascii').read()
for codec in (brotli, brotlicffi):
    source = b'open-webui-brotli-runtime-probe' * 32
    assert codec.decompress(codec.compress(source)) == source
assert features.version('libjpeg_turbo')
source = Image.new('RGB', (8, 8), (17, 34, 51))
data = io.BytesIO()
source.save(data, format='PNG')
with Image.open(io.BytesIO(data.getvalue())) as loaded:
    normalized = ImageOps.exif_transpose(loaded)
    normalized.thumbnail((4, 4))
    target = io.BytesIO()
    normalized.save(target, format='JPEG')
    assert Image.open(io.BytesIO(target.getvalue())).size == (4, 4)
PY

# Preserve the upstream runtime identity and inherited entrypoint.
USER 1000
