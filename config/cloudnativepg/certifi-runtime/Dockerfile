# syntax=docker/dockerfile:1
# Overlay the fixed trust bundle without changing PostgreSQL or Barman.
# The workflow supplies one of the two exact CNPG system-image digests.
ARG POSTGRES_BASE
FROM ${POSTGRES_BASE}

LABEL org.opencontainers.image.source="https://github.com/alpar-t/homelab" \
      org.opencontainers.image.description="CloudNativePG system image with patched certifi"

USER root
COPY requirements-overlay.txt /tmp/requirements-overlay.txt
RUN python3 -m pip install --disable-pip-version-check --no-cache-dir \
      --no-deps --only-binary=:all: --require-hashes \
      -r /tmp/requirements-overlay.txt \
    && python3 -m pip check \
    && python3 - <<'PY'
from importlib.metadata import version
from pathlib import Path
import subprocess

import boto3
import certifi
from botocore.httpsession import get_cert_path

assert version('certifi') == '2026.10.23'
assert get_cert_path(True) == certifi.where()
assert 'emSign ECC Root CA - G3' not in Path(certifi.where()).read_text()
assert boto3.__version__
for command in ('barman-cloud-backup', 'barman-cloud-wal-archive'):
    subprocess.run((command, '--version'), check=True)
PY

# CloudNativePG upstream runs PostgreSQL as uid 26.
USER 26
